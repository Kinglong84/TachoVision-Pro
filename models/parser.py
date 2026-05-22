"""
models/parser.py — Parser per file .DDD (Gen1, Gen2 v1/v2)

Il file .DDD (Digital Driver Data) è il formato standard EU per i dati
delle carte tachigrafo digitali. È definito nel Regolamento CE 3821/85
(Annex 1B, Gen1) e nel successivo 2016/799 (Annex 1C, Gen2).

STRUTTURA FILE: sequenza flat di record TLV (Tag-Length-Value)
  [tag:2][crypto_flag:1][length:2][data:length]

  TLV è un protocollo di serializzazione binaria: ogni blocco inizia con
  un identificatore (tag = numero di 2 byte che identifica il tipo di dato),
  seguito dalla lunghezza e poi dal payload con i dati veri.

  crypto_flag (cf) indica lo stato di firma del blocco:
    cf=0 → prima copia plaintext   (PREFERITA: è la copia "ufficiale")
    cf=1 → firma della prima copia (non ci interessa: è la firma digitale, non i dati)
    cf=2 → seconda copia plaintext (FALLBACK: copia di sicurezza duplicata)
    cf=3 → firma della seconda copia (skippata)

  Il protocollo prevede ridondanza: ogni dato critico è scritto DUE VOLTE.
  Noi scegliamo sempre cf=0 (prima copia), a parità di cf prendiamo quella più lunga.

ALGORITMO IN DUE PASSI:
  PASS 1 (_pass1): per ogni FID di interesse, scansiona il file raw cercando
    la sequenza di 2 byte del tag. Estrae il payload più valido trovato.
    Questo approccio è immune alla de-sincronizzazione causata da byte 0x00
    iniziali (es. EF_ICC = 0x0002 inizia con 0x00, che rompeva il vecchio
    scanner lineare che saltava i null byte).

  PASS 2 (parse_ddd): chiama i decoder semantici su ogni payload estratto.
    Ogni decoder conosce il formato specifico del proprio EF (Elementary File).
"""

from __future__ import annotations
import struct
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from models.card_data import (
    CardData, DriverInfo, DayActivity, ActivityChange,
    Vehicle, VehicleSession, GNSSRecord, Place,
    CardEvent, CardFault, SpecificCondition,
)

# ── FID completi (Annex 1B/1C) ────────────────────────────────────────────────
# FID = File Identifier, il "numero di targa" di ogni Elementary File nel DDD.
# Ogni tipo di dato nella carta ha il suo FID: attività, veicoli, luoghi, ecc.
# I valori 0x05xx sono definiti nella spec EU; 0xC1xx sono i certificati crittografici.
EF_ICC                        = 0x0002   # Integrated Circuit Card — serial number hardware
EF_IC                         = 0x0005   # Identification of the Card
EF_APPLICATION_IDENTIFICATION = 0x0501   # Versione applicazione tachigrafo
EF_EVENTS_DATA                = 0x0502   # Anomalie e violazioni registrate dall'apparecchio
EF_FAULTS_DATA                = 0x0503   # Guasti hardware/software
EF_DRIVER_ACTIVITY_DATA       = 0x0504   # Buffer attività Gen1 (ACI circolare)
EF_VEHICLES_USED              = 0x0505   # Elenco veicoli usati con date e odometro
EF_PLACES                     = 0x0506   # Luoghi di inizio/fine turno
EF_CURRENT_USAGE              = 0x0507   # Stato corrente della carta
EF_CONTROL_ACTIVITY_DATA      = 0x0508   # Dati dei controlli su strada
EF_CARD_DOWNLOAD              = 0x050E   # Data e ora dell'ultimo scarico carta
EF_IDENTIFICATION             = 0x0520   # Dati anagrafici del conducente
EF_DRIVING_LICENCE_INFO       = 0x0521   # Numero e autorità patente
EF_SPECIFIC_CONDITIONS        = 0x0522   # Condizioni speciali (traghetto, fuori ambito…)
EF_VEHICLEUNITS_USED          = 0x0523   # Gen2 v1: unità veicolo (VU) usate
EF_ACTIVITY_DATA_V2           = 0x0524   # Gen2 v1 — buffer attività (coppie UTC/locale)
EF_APPLICATION_ID_V2          = 0x0525   # Gen2 v2: discriminatore generazione
EF_PLACES_AUTHENTICATION      = 0x0526   # Autenticazione luoghi Gen2
EF_GNSS_PLACES_AUTH           = 0x0527   # Autenticazione waypoint GNSS
EF_BORDER_CROSSINGS           = 0x0528   # Attraversamenti di frontiera
EF_LOAD_UNLOAD_OPERATIONS     = 0x0529   # Operazioni carico/scarico merci
EF_LOAD_TYPE_ENTRIES          = 0x0530   # Tipi di carico
EF_CARD_CERTIFICATE           = 0xC100   # Certificato della carta (firma EU)
EF_CARDSIGN_CERTIFICATE       = 0xC101   # Certificato di firma carta
EF_CA_CERTIFICATE             = 0xC108   # Certificato dell'Autorità di Certificazione
EF_LINK_CERTIFICATE           = 0xC109   # Certificato di collegamento tra generazioni

FID_NAMES: Dict[int, str] = {
    EF_ICC:                        "ICC",
    EF_IC:                         "IC",
    EF_APPLICATION_IDENTIFICATION: "APP_ID",
    EF_EVENTS_DATA:                "EVENTS",
    EF_FAULTS_DATA:                "FAULTS",
    EF_DRIVER_ACTIVITY_DATA:       "ACTIVITY",
    EF_VEHICLES_USED:              "VEHICLES",
    EF_PLACES:                     "PLACES",
    EF_CURRENT_USAGE:              "CURRENT",
    EF_CONTROL_ACTIVITY_DATA:      "CONTROL",
    EF_CARD_DOWNLOAD:              "LAST_DL",
    EF_IDENTIFICATION:             "IDENTIFICATION",
    EF_DRIVING_LICENCE_INFO:       "LICENCE",
    EF_SPECIFIC_CONDITIONS:        "SPECIFIC",
    EF_VEHICLEUNITS_USED:          "VEHICLEUNITS",
    EF_ACTIVITY_DATA_V2:           "ACTIVITY_V2",
    EF_APPLICATION_ID_V2:          "APP_ID_V2",
    EF_PLACES_AUTHENTICATION:      "PLACES_AUTH",
    EF_GNSS_PLACES_AUTH:           "GNSS_PLACES_AUTH",
    EF_BORDER_CROSSINGS:           "BORDER",
    EF_LOAD_UNLOAD_OPERATIONS:     "LOAD_UNLOAD",
    EF_LOAD_TYPE_ENTRIES:          "LOAD_TYPE",
    EF_CARD_CERTIFICATE:           "CARD_CERT",
    EF_CARDSIGN_CERTIFICATE:       "CARDSIGN_CERT",
    EF_CA_CERTIFICATE:             "CA_CERT",
    EF_LINK_CERTIFICATE:           "LINK_CERT",
}

# frozenset: insieme immutabile — non può essere modificato accidentalmente dopo la definizione.
# Contiene solo i FID che ci interessano davvero: _pass1 salterà tutti gli altri,
# evitando di spendere memoria su certificati e metadati che non usiamo.
TARGET_FIDS = frozenset({
    EF_IDENTIFICATION, EF_CARD_DOWNLOAD, EF_DRIVING_LICENCE_INFO,
    EF_EVENTS_DATA, EF_FAULTS_DATA, EF_SPECIFIC_CONDITIONS,
    EF_DRIVER_ACTIVITY_DATA, EF_ACTIVITY_DATA_V2,
    EF_VEHICLES_USED, EF_VEHICLEUNITS_USED,
    EF_PLACES, EF_BORDER_CROSSINGS,
})

# I 4 codici attività tachigrafo (Reg. 3821/85, Annex 1B §2.1):
#   0 = Riposo (conducente fermo — riposo, pasto, sonno)
#   1 = Disponibilità (presente ma non alla guida — aiuto-conducente, attesa)
#   2 = Lavoro (attività non di guida: carico, scarico, manutenzione)
#   3 = Guida (veicolo in movimento con conducente attivo)
# Questi valori sono codificati su 2 bit (bit 12-11) nell'ACI a 16 bit.
ACTIVITY_MAP = {0: "Riposo", 1: "Disponibilità", 2: "Lavoro", 3: "Guida"}

# Tabella di conversione: codice numerico EU → codice ISO 3166-1 alpha-2 (sigla nazione).
# Definita nella spec EU Annex 1B §3.1 (NationNumeric). Valori 1-28 = stati UE storici;
# 56 e 57 = Svizzera e Norvegia (paesi SEE non-UE che hanno adottato il tachigrafo).
EU_NATIONS: Dict[int, str] = {
    1:"AT",2:"BE",3:"BG",4:"CY",5:"CZ",6:"DE",7:"DK",8:"EE",
    9:"ES",10:"FI",11:"FR",12:"GR",13:"HR",14:"HU",15:"IE",16:"IT",
    17:"LT",18:"LU",19:"LV",20:"MT",21:"NL",22:"PL",23:"PT",24:"RO",
    25:"SE",26:"SI",27:"SK",28:"GB",56:"CH",57:"NO",
}

# Range di validità per timestamp Unix (secondi dal 1970-01-01):
#   TS_MIN = 1072915200 → 2004-01-01 00:00:00 UTC (prima carta tachigrafo digitale EU)
#   TS_MAX = 2208988800 → 2040-01-01 00:00:00 UTC (limite futuro ragionevole)
# Qualsiasi timestamp fuori da questo range è sicuramente un falso positivo
# (es. un intero a 4 byte letto da un offset sbagliato del file binario).
TS_MIN, TS_MAX = 1072915200, 2208988800  # 2004..2040
YEAR_MIN, YEAR_MAX = 2004, 2040
# Massima differenza in secondi tra timestamp UTC e locale nella stessa coppia Gen2.
# UTC+14 (fuso orario della Polinesia Francese, il più avanti nel mondo) = 14*3600 = 50400s.
# Se la differenza UTC/locale supera questo valore, la coppia non è valida (falso positivo).
TZ_MAX_OFFSET = 50_400


# ─────────────────────────────────────────────────────────────────────────────
# PASS 1 — Ricerca diretta dei tag nel file raw
# ─────────────────────────────────────────────────────────────────────────────

# Eccezione alla regola "prendi il payload più lungo":
# Per i tag in questo set, il PRIMO match trovato nel file è quello corretto.
# Motivazione concreta: nel file MASOTTI, EF_DRIVING_LICENCE_INFO (0x0521) appare DUE VOLTE:
#   - Offset basso: 53 byte → payload REALE (dati patente corretti)
#   - Offset alto:  96 byte → FALSO POSITIVO (blocco directory che per caso inizia con 0x0521)
# Senza questa eccezione, la logica "più lungo vince" sceglierebbe il falso positivo
# e la patente mostrerebbe caratteri spazzatura come "$\`e·v%".
_PREFER_FIRST_MATCH = frozenset({
    EF_DRIVING_LICENCE_INFO,
})


def _pass1(data: bytes, max_depth: int = 6) -> Dict[int, bytes]:
    """
    Per ogni FID in TARGET_FIDS cerca il pattern [tag_hi, tag_lo] nel raw.
    Valida cf ∈ {0,2} (plaintext) e lunghezza plausibile.
    Preferisce cf=0 (prima copia).
    A parità di cf: per la maggior parte dei tag prende il payload più lungo;
    per i tag in _PREFER_FIRST_MATCH prende il primo trovato (offset minore).

    STRATEGIA A DUE PASSAGGI:
    1. Scansione strutturale: cammina il file come sequenza di blocchi TLV [tag(2)][cf(1)][ln(2)][payload(ln)].
       Immune ai falsi positivi dentro i payload di altri tag (es. timestamp GNSS che per caso
       formano la firma di un altro tag con lunghezza plausibile).
       Usata quando il file è ben formato (carte lette da USB, upload standard).
    2. Fallback fuzzy: scansione byte-per-byte se la struttura TLV non è valida.
       Gestisce file DDD legacy o con padding non standard.
    """
    dlen = len(data)

    # ── Tentativo 1: scansione strutturale ────────────────────────────────────
    struct_result: Dict[int, bytes] = {}
    struct_cf: Dict[int, int] = {}
    i, valid_struct = 0, True
    while i + 5 <= dlen:
        cf  = data[i + 2]
        ln  = (data[i + 3] << 8) | data[i + 4]
        tag = (data[i] << 8) | data[i + 1]
        # Struttura invalida: lunghezza che sfora il file
        if ln > 500_000 or i + 5 + ln > dlen:
            valid_struct = False
            break
        if cf in (0, 2) and tag in TARGET_FIDS and ln >= 2:
            prev_cf  = struct_cf.get(tag, 99)
            prev_ln  = len(struct_result[tag]) if tag in struct_result else 0
            prefer   = tag in _PREFER_FIRST_MATCH
            if tag not in struct_result or cf < prev_cf or (
                cf == prev_cf and not prefer and ln > prev_ln
            ):
                struct_result[tag] = data[i + 5 : i + 5 + ln]
                struct_cf[tag]     = cf
        i += 5 + ln   # salta al prossimo blocco TLV (ignora il payload corrente)

    # La scansione strutturale è valida se ha consumato esattamente tutti i byte
    # e ha trovato almeno un tag noto (altrimenti è un file vuoto o non-DDD).
    if valid_struct and i == dlen and struct_result:
        return struct_result

    # ── Fallback: scansione fuzzy byte-per-byte ────────────────────────────────
    # Usata per file DDD caricati con struttura non perfettamente allineata.
    result: Dict[int, bytes] = {}

    for tag in TARGET_FIDS:
        hi = (tag >> 8) & 0xFF
        lo = tag & 0xFF
        best: Optional[bytes] = None
        best_cf = 99
        best_ln = 0
        prefer_first = tag in _PREFER_FIRST_MATCH

        for i in range(dlen - 4):
            if data[i] != hi or data[i + 1] != lo:
                continue

            cf = data[i + 2]
            if cf not in (0, 2):
                continue

            ln = (data[i + 3] << 8) | data[i + 4]
            if ln < 2 or ln > 500_000 or i + 5 + ln > dlen:
                continue

            if best is None or cf < best_cf:
                best = data[i + 5 : i + 5 + ln]
                best_cf = cf
                best_ln = ln
            elif cf == best_cf and not prefer_first and ln > best_ln:
                best = data[i + 5 : i + 5 + ln]
                best_ln = ln

        if best is not None:
            result[tag] = best

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Utility — Funzioni di lettura binaria low-level
# ─────────────────────────────────────────────────────────────────────────────
# Queste funzioni leggono tipi di dato standard da sequenze di byte.
# Il prefisso ">" nel formato di struct indica big-endian (byte più significativo primo),
# che è il byte-order usato dal protocollo EU per i file DDD.

def _u16(d: bytes, o: int) -> int:
    """Legge un intero senza segno a 16 bit (2 byte, big-endian) all'offset o."""
    # struct.unpack_from: legge direttamente da bytes senza allocare memoria extra
    # ">H": big-endian unsigned short (16 bit = 2 byte)
    return struct.unpack_from(">H", d, o)[0]

def _u32(d: bytes, o: int) -> int:
    """Legge un intero senza segno a 32 bit (4 byte, big-endian) all'offset o."""
    # ">I": big-endian unsigned int (32 bit = 4 byte)
    return struct.unpack_from(">I", d, o)[0]

def _ts(d: bytes, o: int) -> Optional[datetime]:
    """
    Legge un timestamp Unix a 4 byte (big-endian) e lo converte in datetime UTC.
    Ritorna None se il timestamp è fuori dal range valido (falso positivo nel binario).

    I timestamp nei file DDD sono secondi dal 1970-01-01 (Unix epoch), come in tutti
    i sistemi POSIX. La spec EU usa questo formato per data/ora negli EF.
    """
    if o + 4 > len(d): return None
    v = _u32(d, o)
    # Sanity check: rifiuta timestamp fuori dal range storico atteso (2004-2040)
    if not (TS_MIN <= v <= TS_MAX): return None
    try:
        # timezone.utc: garantisce che il datetime abbia informazione di fuso (aware)
        # I timestamp DDD sono SEMPRE in UTC — la conversione locale avviene dopo
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except Exception:
        return None

def _str(b: bytes) -> str:
    """
    Decodifica bytes in stringa leggibile, ignorando null, 0xFF e non-stampabili.

    latin-1 (ISO-8859-1) è la codifica usata dai tachigrafi EU per i testi:
    copre tutti i caratteri europei occidentali in un singolo byte per carattere.
    I byte 0xFF sono usati come padding nei campi stringa a lunghezza fissa.
    isprintable() filtra caratteri di controllo (tab, newline, BEL, ecc.).
    """
    try:
        s = b.replace(b"\xff", b"").decode("latin-1")   # 0xFF = padding, rimuovi prima
        return "".join(c for c in s if c.isprintable()).strip()
    except Exception:
        return ""

def _bcd_date(b: bytes) -> str:
    """
    Decodifica 4 byte in formato BCD (Binary-Coded Decimal) YYYYMMDD → stringa gg/mm/aaaa.

    BCD è un formato dove ogni cifra decimale è codificata in 4 bit (un nibble):
      byte 0 = YY (decine e unità del millennio+secolo, es. 0x19 = 19)
      byte 1 = YY (decine e unità dell'anno, es. 0x84 = 84)  → 1984
      byte 2 = MM (es. 0x09 = settembre)
      byte 3 = DD (es. 0x29 = 29)

    Il trucco per leggere il BCD: format {:02x} stampa il byte in esadecimale,
    che coincide con la sua rappresentazione BCD (es. 0x84 → "84" → int("84") = 84).
    """
    if len(b) < 4: return ""
    try:
        year  = int(f"{b[0]:02x}{b[1]:02x}")   # due byte BCD → anno a 4 cifre
        month = int(f"{b[2]:02x}")               # un byte BCD → mese
        day   = int(f"{b[3]:02x}")               # un byte BCD → giorno
        if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
            return f"{day:02d}/{month:02d}/{year}"
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Tabelle di classificazione (EU Reg. 3821/85 Annex 1B + 2016/799 Annex 1C)
# ─────────────────────────────────────────────────────────────────────────────
# Queste tabelle mappano codici numerici (come li scrive il tachigrafo nel file)
# in descrizioni testuali italiane per l'interfaccia utente.

# EF_EVENTS_DATA: eventi anomali registrati dall'apparecchio di controllo.
# Un "evento" non è necessariamente una violazione del conducente — può essere
# un problema tecnico (es. perdita alimentazione) o un comportamento sospetto.
EVENT_TYPE_NAMES: Dict[int, str] = {
    0x01: "Carta non valida inserita",        # carta scaduta, di tipo sbagliato o contraffatta
    0x02: "Conflitto carta",                   # due carte dello stesso tipo (es. due conducenti)
    0x03: "Sovrapposizione oraria",            # attività registrate in periodi sovrapposti
    0x04: "Guida senza carta appropriata",     # veicolo in moto senza carta conducente
    0x05: "Carta inserita durante guida",      # carta inserita con veicolo già in movimento
    0x06: "Sessione non chiusa correttamente", # carta rimossa senza registrare la fine turno
    0x07: "Eccesso di velocità",               # superamento della velocità massima
    0x08: "Interruzione alimentazione",        # perdita di corrente all'apparecchio
    0x09: "Errore dati movimento",             # incoerenza nel segnale tachimetro
    0x0A: "Conflitto movimento veicolo",       # apparecchio di controllo segnala velocità diversa
    0x0B: "Conflitto orario (GNSS)",           # ora sistema non coincide con ora GPS
    0x0C: "Anomalia GNSS",                     # ricevitore GPS non disponibile o guasto
    0x0D: "Guasto comunicazione",              # errore nel bus di comunicazione (CAN, W-line)
}

# EF_FAULTS_DATA: guasti hardware/software dell'apparecchio o della carta.
# I guasti indicano malfunzionamenti dell'hardware, non violazioni del conducente.
FAULT_TYPE_NAMES: Dict[int, str] = {
    0x10: "Guasto hardware carta",    # chip carta danneggiato
    0x11: "Errore software carta",    # corruzione dati nella carta
    0x12: "Guasto sensore",           # sensore di movimento (tachimetro) non funzionante
    0x13: "Guasto ricevitore GNSS",   # GPS non disponibile per motivi hardware
    0x14: "Guasto comunicazione VU",  # Vehicle Unit (apparecchio tachigrafo) non risponde
    0x15: "Guasto interno VU",        # guasto interno all'apparecchio di controllo
}

# I record eventi e guasti sono organizzati in SLOT numerati (uno per tipo).
# Ogni slot contiene un array di record. Il numero di slot fissi nella spec:
#   Gen1: 6 slot eventi, 2 slot guasti
#   Gen2: 11 slot eventi, 2 slot guasti
# Il codice slot (index nella lista) corrisponde all'EventFaultType (EU spec §2.78).
_EVENT_SLOT_CODES = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B]
_FAULT_SLOT_CODES = [0x10, 0x11]

# EF_SPECIFIC_CONDITIONS: condizioni operative speciali che sospendono la registrazione normale.
# Es: traghetto o treno — il conducente non guida ma il veicolo si muove, i tempi non contano.
SPECIFIC_CONDITION_NAMES: Dict[int, str] = {
    0x00: "Normale",                        # condizione operativa standard
    0x01: "Fuori ambito (traghetto/treno)", # in transito su mezzo di trasporto
    0x02: "Inizio condizione speciale",     # inizio di un'attività fuori ambito
    0x03: "Fine condizione speciale",       # fine di un'attività fuori ambito
    0x04: "Inizio traghetto/treno",         # sinonimo specifico per mezzo di trasporto
    0x05: "Fine traghetto/treno",           # fine del transito
}


# ─────────────────────────────────────────────────────────────────────────────
# PASS 2 — Decoder semantici
# ─────────────────────────────────────────────────────────────────────────────

def _decode_identification(data: bytes) -> DriverInfo:
    """
    EF_IDENTIFICATION (0x0520): dati anagrafici del conducente.

    Layout (EU Annex 1B §4.5.5):
    [nation:1][cardNumber:16][authority:36][issueDate:4][validityBegin:4]
    [expiryDate:4][surname:36][firstname:36][birthDate:4 BCD][language:2]

    Ogni campo stringa ha una lunghezza fissa: i byte inutilizzati sono 0xFF (padding).
    I campi nome/cognome/autorità iniziano con 1 byte di "codepage" (charset),
    seguito dai caratteri veri: per questo leggiamo da [1:] ignorando il primo byte.
    Le date sono timestamp Unix a 4 byte (non BCD, tranne birthDate).
    """
    d = DriverInfo()
    if len(data) < 100: return d  # payload troppo corto: non è un EF_IDENTIFICATION valido
    o = 0

    # Helper locale: legge n byte dall'offset corrente e avanza il cursore.
    # nonlocal o: permette alla funzione interna di modificare la variabile locale
    # della funzione esterna (closure con modifica). Alternativa: usare una lista [0]
    # come workaround pre-Python-3, ma nonlocal è il modo idiomatico in Python 3.
    def rd(n):
        nonlocal o
        chunk = data[o:o+n] if o+n<=len(data) else b""
        o += n
        return chunk

    nation_b = rd(1)
    d.issuing_nation = EU_NATIONS.get(nation_b[0] if nation_b else 0, "")  # NationNumeric → ISO alpha-2
    d.card_number       = _str(rd(16))   # 16 byte: numero carta (es. "I100000333422003")
    auth                = rd(36)          # 36 byte: authority; byte[0] = codepage, [1:] = testo
    d.issuing_authority = _str(auth[1:]) if len(auth) > 1 else ""

    # Tre date consecutive a 4 byte ciascuna: emissione, inizio validità, scadenza.
    # setattr(d, attr, val) è equivalente a "d.attr = val" ma con nome dinamico,
    # utile per iterare su più attributi con lo stesso codice di parsing.
    for attr in ("issue_date", "validity_begin", "expiry_date"):
        ts = _ts(data, o); o += 4
        setattr(d, attr, ts.strftime("%d/%m/%Y") if ts else "")

    # Nome e cognome: 36 byte ciascuno, byte[0] = codepage (skippato), byte[1:] = testo
    sn = rd(36); d.surname   = _str(sn[1:]) if len(sn)>1 else _str(sn)
    fn = rd(36); d.firstname = _str(fn[1:]) if len(fn)>1 else _str(fn)
    d.birth_date = _bcd_date(rd(4))   # 4 byte BCD YYYYMMDD (vedi _bcd_date)
    d.language   = _str(rd(2))        # 2 caratteri ISO 639-1 (es. "IT", "DE")
    return d


def _decode_activities_gen1(data: bytes) -> List[DayActivity]:
    """
    Buffer circolare Gen1: [oldest:2][newest:2] + N × record giornaliero.

    STRUTTURA DEL BUFFER CIRCOLARE:
      I 4 byte iniziali sono il "direttorio" del buffer:
        [oldest:2] → offset del record più vecchio nel buffer
        [newest:2] → offset dove verranno scritti i prossimi dati
      Poi vengono i dati veri: un array di record giornalieri in ordine ciclico.

      "Circolare" significa che quando si riempie, sovrascrive dall'inizio.
      I pointer oldest/newest indicano dove si trova il "bordo" della sovrascrittura.
      Per linearizzare: se newest >= oldest, i dati sono contigui (no wrap-around);
      altrimenti sono spezzati e vanno concatenati: buf[oldest:] + buf[:newest].

    STRUTTURA RECORD GIORNALIERO:
      [prev:2]      → offset al record precedente (per navigazione backward)
      [rec:2]       → dimensione totale di questo record in byte
      [TimeReal:4]  → timestamp Unix del giorno (mezzanotte UTC)
      [presence:2]  → stato carta (bitmask, non usato qui)
      [dist:2]      → distanza percorsa in km (1 km/unit, non 0.1 come sembrebbe)
      [N × ACI:2]   → array di ActivityChangeInfo (ACI), uno per ogni cambio attività

    FIX storico: il limite rec > 2000 era troppo basso (max teorico: 12 + 1440×2 = 2892).
    FIX storico: range anni esteso a YEAR_MIN (2004) per coprire carte più vecchie.
    """
    if len(data) < 8: return []

    buf    = data[4:]    # il buffer vero inizia dopo i 4 byte di direttorio
    bsz    = len(buf)
    oldest = _u16(data, 0)   # puntatore al record più vecchio
    newest = _u16(data, 2)   # puntatore alla fine dei dati correnti

    if oldest >= bsz or newest > bsz:
        return []   # puntatori corrotti: file malformato

    # Linearizzazione del buffer circolare:
    # Se newest >= oldest: i dati sono nel segmento [oldest:newest] (caso normale).
    # Se newest < oldest: il buffer ha "wrappato" — i dati sono in due segmenti:
    #   buf[oldest:] (fine del buffer) + buf[:newest] (inizio del buffer).
    # newest == oldest e newest == 0: buffer pieno, prendi tutto.
    if newest >= oldest:
        linear = buf[oldest:newest] if newest > oldest else buf
    else:
        linear = buf[oldest:] + buf[:newest]

    records_raw: List[tuple] = []   # (dpc, DayActivity) per il trim DPC finale
    visited: set = set()           # previene duplicati per lo stesso giorno (calendario ISO)
    o = 0   # cursore di lettura nel buffer linearizzato

    while o + 12 <= len(linear):
        prev = _u16(linear, o)       # offset record precedente (backward nav, non usato)
        rec  = _u16(linear, o + 2)   # dimensione totale di questo record in byte

        # Sanity check sulla dimensione del record.
        # Massimo teorico: 12 byte header + 1440 ACI × 2 byte = 2892 byte.
        # Usare bsz come limite superiore accetta valori molto grandi (es. 3688) che
        # saltano i dati validi dopo il wrap del buffer circolare → record corrotto.
        # Il controllo su prev (stesso limite) esclude false positives nella zona di wrap.
        if rec < 12 or rec > 2892 or prev > 2892:
            o += 2   # non è un record valido: avanza di 2 byte e riprova (sliding window)
            continue
        if o + rec > len(linear):
            break   # record troncato: fine buffer

        ts = _ts(linear, o + 4)   # timestamp del giorno: 4 byte all'offset 4 del record
        if not ts or not (YEAR_MIN <= ts.year <= YEAR_MAX):
            o += rec   # data non valida: salta l'intero record
            continue

        dk = ts.strftime("%Y-%m-%d")   # chiave univoca giorno in formato ISO (ordinabile)
        if dk not in visited:
            visited.add(dk)
            dpc     = _u16(linear, o + 8)    # dailyPresenceCounter: contatore progressivo
            dist    = _u16(linear, o + 10)   # distanza a offset 10 del record (2 byte)
            # Distanza in km interi: valori > 2000 km/giorno non sono plausibili → 0
            dist_km = float(dist) if dist <= 2000 else 0.0

            # ── Decodifica ACI (ActivityChangeInfo) ─────────────────────────────
            # Gli ACI sono parole da 2 byte che codificano un cambio di attività.
            # Layout BIT dell'ACI (16 bit, big-endian):
            #   bit 15    → slot: 1 = co-conducente (codriver), skip
            #   bit 14    → inserimento manuale (1 = il conducente ha corretto manualmente)
            #   bit 13    → spare (riservato, non usato)
            #   bit 12-11 → activity code (0=Riposo, 1=Disponibilità, 2=Lavoro, 3=Guida)
            #   bit 10-0  → minuti dall'inizio della giornata (0-1440, 11 bit → max 2047)
            #
            # BUG STORICO: (aci >> 10) & 3 usava 10 bit invece di 11, misallineando
            # sia il codice attività che il tempo. Fix: >> 11 per activity, 0x7FF per tempo.
            changes: List[ActivityChange] = []
            ai = o + 12   # gli ACI iniziano subito dopo i 12 byte di header del record
            while ai + 2 <= o + rec:
                aci = _u16(linear, ai); ai += 2
                if (aci >> 15) & 1:
                    continue   # bit 15 = 1: co-conducente, ignora
                m = aci & 0x7FF         # bit 10-0: minuti dall'inizio giornata (11 bit)
                if m < 1440:            # 1440 = 24*60: scarta valori impossibili
                    changes.append(ActivityChange(
                        time=m,
                        activity=ACTIVITY_MAP[(aci >> 11) & 3],  # bit 12-11: tipo attività
                        manual=bool((aci >> 14) & 1)))            # bit 14: inserimento manuale

            if changes:
                records_raw.append((dpc, DayActivity(
                    date=dk,
                    date_display=ts.strftime("%d/%m/%Y"),
                    distance_km=dist_km,
                    changes=sorted(changes, key=lambda c: c.time))))   # ordina per minuto
        o += rec   # avanza al record successivo

    # ── Trim boundary orphans via DPC discontinuity ──────────────────────────
    # Il buffer circolare lascia talvolta alla posizione "oldest" uno o più record
    # appartenenti al ciclo precedente (non sovrascritti). Questi record hanno un
    # DPC (dailyPresenceCounter) molto più basso del primo record valido del ciclo
    # corrente: il salto improvviso identifica il confine.
    # Si controlla solo i primi 10 record per non scartare lacune legittime nel mezzo.
    start = 0
    for i in range(min(10, len(records_raw) - 1)):
        if records_raw[i + 1][0] - records_raw[i][0] > 50:
            start = i + 1
            break

    return [day for _, day in records_raw[start:]]


def _decode_activities_v2(data: bytes) -> List[DayActivity]:
    """
    Gen2 v1/v2: buffer con coppie timestamp UTC/locale per ogni giorno.

    DIFFERENZA CHIAVE rispetto a Gen1:
    Ogni record giornaliero inizia con DUE timestamp invece di uno:
      [ts_utc:4]   → mezzanotte in UTC
      [ts_local:4] → mezzanotte nel fuso locale del conducente

    Perché due timestamp? Gen1 registrava solo UTC, ma in Europa con UTC+1/+2
    la "mezzanotte locale" è alle 22:00 o 23:00 UTC del giorno precedente.
    Usando solo UTC, i giorni sembravano iniziare il giorno sbagliato.
    Gen2 registra anche il locale per eliminare questa ambiguità.

    ALGORITMO DI DISCOVERY (scan per coppie):
    Il buffer Gen2 non ha puntatori oldest/newest separati: scansiona tutto
    cercando coppie di timestamp plausibili (entrambi nel range 2004-2040,
    differenza ≤ 50400s = UTC+14). Questo è necessario perché il buffer
    Gen2 può avere una struttura variabile a seconda del firmware.

    Struttura record: [ts_utc:4][ts_local:4][presence:2][distance:2][ACI×N:2]

    FIX: usa timestamp LOCALE (d2) per la data: in Italia UTC+2, la mezzanotte
         locale = 22:00 UTC del giorno prima, quindi UTC sposterebbe tutte le
         date di un giorno indietro.
    FIX: distanza a offset 10 = km interi (1 km/unit), non 0.1 km.
    """
    if len(data) < 8: return []
    buf = data[4:]   # skip 4 byte di header (pointer Gen2)

    # Fase 1: discovery delle coppie UTC/locale nel buffer.
    # Scorriamo ogni posizione allineata a 2 byte e cerchiamo coppie plausibili.
    # pairs: lista di (posizione_in_buf, datetime_utc, datetime_locale)
    pairs: List[Tuple[int, datetime, datetime]] = []
    seen_pos: set = set()   # evita di riusare posizioni già assegnate

    for p in range(0, len(buf) - 8, 2):   # step 2: i timestamp sono allineati a 2 byte
        if p in seen_pos:
            continue   # questa posizione è già parte di una coppia trovata
        v1 = _u32(buf, p)
        if not (TS_MIN <= v1 <= TS_MAX):
            continue   # primo valore non è un timestamp plausibile
        d1 = datetime.fromtimestamp(v1, tz=timezone.utc)
        if not (YEAR_MIN <= d1.year <= YEAR_MAX):
            continue   # anno fuori range
        if p + 8 > len(buf):
            continue   # non c'è spazio per il secondo timestamp

        v2 = _u32(buf, p + 4)   # il secondo timestamp è 4 byte dopo il primo
        if not (TS_MIN <= v2 <= TS_MAX):
            continue
        d2 = datetime.fromtimestamp(v2, tz=timezone.utc)
        if not (YEAR_MIN <= d2.year <= YEAR_MAX):
            continue

        # Validazione coppia UTC/locale: la differenza deve essere ≤ UTC+14 (massimo fuso mondiale)
        if abs((d2 - d1).total_seconds()) <= TZ_MAX_OFFSET:
            pairs.append((p, d1, d2))
            seen_pos.add(p)
            seen_pos.add(p + 4)   # marca entrambe le posizioni come usate

    if not pairs:
        return []

    # Fase 2: per ogni coppia trovata, estrai header e ACI.
    days: List[DayActivity] = []
    visited: set = set()

    for idx, (p1, d_utc, d_local) in enumerate(pairs):
        # Delimita la regione degli ACI: dal byte 12 dopo la coppia fino all'inizio
        # della coppia successiva (meno 2 per evitare sovrapposizioni).
        # Per l'ultimo record, va fino alla fine del buffer.
        next_p = pairs[idx + 1][0] - 2 if idx + 1 < len(pairs) else len(buf)
        if p1 + 12 > len(buf):
            continue   # record senza spazio per l'header completo

        # Distanza giornaliera: 2 byte all'offset 10 dal primo timestamp della coppia
        dist_raw = _u16(buf, p1 + 10) if p1 + 12 <= len(buf) else 0
        dist_km  = float(dist_raw) if dist_raw <= 2000 else 0.0

        # Decodifica ACI (stessa logica di Gen1, vedi commenti sopra)
        changes: List[ActivityChange] = []
        o = p1 + 12   # gli ACI iniziano 12 byte dopo il primo timestamp
        while o + 2 <= next_p:
            aci = _u16(buf, o); o += 2
            if (aci >> 15) & 1:
                continue   # bit 15 = co-conducente: skip
            m = aci & 0x7FF        # bit 10-0: minuti dall'inizio giornata
            at = (aci >> 11) & 3   # bit 12-11: codice attività
            if m < 1440:
                # Ottimizzazione Gen2: salta duplicati consecutivi (stesso minuto, stessa attività)
                if not changes or m > changes[-1].time or ACTIVITY_MAP[at] != changes[-1].activity:
                    changes.append(ActivityChange(
                        time=m,
                        activity=ACTIVITY_MAP[at],
                        manual=bool((aci >> 14) & 1)))

        # Usa il timestamp LOCALE per la data (d_local, non d_utc):
        # in Italia (UTC+2 estate), mezzanotte locale = 22:00 UTC del giorno precedente.
        # Usare UTC sposterebbe il giorno a ieri → i dati apparirebbero nel giorno sbagliato.
        dk = d_local.strftime("%Y-%m-%d")
        if dk not in visited and changes:
            visited.add(dk)
            days.append(DayActivity(
                date=dk,
                date_display=d_local.strftime("%d/%m/%Y"),
                distance_km=dist_km,
                changes=sorted(changes, key=lambda c: c.time)))

    return days


def _decode_vehicles_tlv(data: bytes, prefer_gen2: bool = True) -> tuple:
    """
    Decodifica EF_VEHICLES_USED / EF_VEHICLEUNITS_USED dal payload TLV.

    STRUTTURA DEL PAYLOAD:
      [noOfVehicleUsed:2] → contatore, skippato (usiamo la dimensione totale)
      [record × N]        → array di record a dimensione fissa

    LAYOUT RECORD (identico per Gen1=31 byte e Gen2=48 byte):
      offset 0-2:  odo_begin (3 byte, big-endian, km)  → odometro all'inizio sessione
      offset 3-5:  odo_end   (3 byte, big-endian, km)  → odometro alla fine sessione
      offset 6-9:  first_use (4 byte, Unix UTC)         → prima accensione con questa carta
      offset 10-13: last_use (4 byte, Unix UTC)         → ultima accensione
      offset 14:   nation (1 byte)                      → nazione immatricolazione
      offset 15:   pad (1 byte)
      offset 16-28: VRN (13 byte, latin-1)              → targa (Vehicle Registration Number)
      [Gen2 aggiunge offset 29-47: VIN (17 byte, latin-1) → numero telaio]

    STRATEGIA DI AUTO-DETECTION:
    Prova prima Gen2 (48 byte/record), poi Gen1 (31 byte/record).
    Un record set è valido se len(payload) % rec_size == 0 E almeno 2 record validi.
    "2 record validi" è la soglia minima per distinguere dati reali da padding.

    DEDUPLICAZIONE VRN:
    La stessa targa può apparire più volte (più sessioni sullo stesso veicolo).
    Teniamo: min(first_use) e max(last_use) per costruire il range temporale complessivo.
    I km totali vengono accumulati solo per delta sensati (0 < delta ≤ 5000 km/sessione).

    Ritorna (List[Vehicle], List[VehicleSession]).
    """
    if len(data) < 4: return [], []
    payload = data[2:]  # skip i 2 byte header (noOfVehicleUsed)

    # Ordine formati: Gen2 (48 byte) o Gen1 (31 byte) per primo in base a prefer_gen2
    _formats = [
        (48, 16, 13,  6, 10),   # Gen2: VRN a offset 16, VIN extra a offset 29
        (31, 16, 13,  6, 10),   # Gen1: stesso layout, record termina a offset 31
    ]
    if not prefer_gen2:
        _formats = list(reversed(_formats))
    for rec_size, vrn_off, vrn_len, ts_f, ts_l in _formats:
        if len(payload) // rec_size < 2:
            continue   # neanche 2 record completi: impossibile validare
        # Non richiediamo len(payload) % rec_size == 0: il buffer può essere
        # troncato di pochi byte (stessa logica di _decode_gnss_accumulated).

        vrn_range: dict = {}   # vrn → (first_use_min, last_use_max)
        vrn_km: dict = {}      # vrn → km totali accumulati
        sessions: List[VehicleSession] = []
        valid = 0   # contatore record con dati plausibili

        for i in range(len(payload) // rec_size):
            o = i * rec_size   # offset di inizio record i-esimo
            if o + rec_size > len(payload):
                break
            vrn   = _str(payload[o + vrn_off : o + vrn_off + vrn_len]).strip()
            first = _ts(payload, o + ts_f)   # timestamp prima sessione
            last  = _ts(payload, o + ts_l)   # timestamp ultima sessione
            # int.from_bytes: converte 3 byte big-endian in intero (odometro in km)
            odo_b = int.from_bytes(payload[o:o+3], "big")
            odo_e = int.from_bytes(payload[o+3:o+6], "big")

            # Valida: VRN non vuota, almeno 2 caratteri, data sensata post-2000
            if vrn and len(vrn) >= 2 and first and 2000 <= first.year <= 2035:
                valid += 1
                if last and last < first:
                    last = first   # correggi last < first: impossibile, usa first

                fu_str = first.strftime("%d/%m/%Y")
                lu_str = (last or first).strftime("%d/%m/%Y")
                sessions.append(VehicleSession(
                    vrn=vrn, first_use=fu_str, last_use=lu_str,
                    odo_begin_km=odo_b, odo_end_km=odo_e,
                    first_use_utc=int(first.timestamp()),
                    last_use_utc=int((last or first).timestamp()),
                ))

                # Aggiorna range temporale per questo VRN (deduplicazione multi-sessione)
                prev = vrn_range.get(vrn)
                if prev is None:
                    vrn_range[vrn] = (first, last or first)
                else:
                    vrn_range[vrn] = (
                        min(prev[0], first),
                        max(prev[1], last or first),
                    )

                # Accumula km solo se il delta è fisicamente plausibile (0-5000 km/sessione)
                delta = odo_e - odo_b
                if 0 < delta <= 5000:
                    vrn_km[vrn] = vrn_km.get(vrn, 0) + delta

        if valid >= 2:
            # Costruisci il dizionario VIN (solo per Gen2, a offset 31 dal record)
            vin_map: dict = {}
            if rec_size == 48:
                for i in range(len(payload) // rec_size):
                    o = i * rec_size
                    vrn = _str(payload[o + vrn_off: o + vrn_off + vrn_len]).strip()
                    vin = _str(payload[o + 31: o + 48]).strip()   # VIN: 17 byte, offset 31
                    if vrn and vin and len(vin) >= 5:
                        vin_map[vrn] = vin

            # List comprehension: costruisce un Vehicle per ogni VRN unico nel range dict
            vehicles = [
                Vehicle(
                    vrn=vrn,
                    first_use=f.strftime("%d/%m/%Y"),
                    last_use=l.strftime("%d/%m/%Y"),
                    vin=vin_map.get(vrn, ""),
                    total_km=vrn_km.get(vrn, 0),
                )
                for vrn, (f, l) in vrn_range.items()
            ]
            return vehicles, sessions   # trovata struttura valida: ritorna subito

    return [], []   # nessuna struttura riconosciuta


_CARD_NUMBER_PATTERN = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

def _scan_vehicles_structured(raw: bytes) -> List[Vehicle]:
    """
    Fallback: scansione O(n) dell'intero file raw cercando record veicolo Gen1 da 28 byte.

    Usato quando _decode_vehicles_tlv() non trova abbastanza record (< 2 validi).
    Questo può accadere se il buffer EF_VEHICLES_USED ha un layout inatteso
    o se la carta ha scritto i veicoli in un formato non standard.

    STRATEGIA (pattern matching nel raw):
      "Ancora" (anchor): cerca un timestamp Unix plausibile all'offset 10.
      Se trovato, interpreta la struttura circostante come un record veicolo:
        p+0..9:  odometro e timestamp (già letti)
        p+10..13: last_use (l'ancora)
        p+14:    nation
        p+15..28: VRN (14 byte, ascii)

    FILTRI ANTI-FALSI-POSITIVI:
    Un timestamp Unix valido può apparire per caso in qualsiasi sequenza di 4 byte.
    Per ridurre i falsi positivi, il VRN estratto viene validato con criteri multipli:
      1. Lunghezza 4-13 caratteri (range tipico delle targhe europee)
      2. Primi 2 caratteri alfabetici (le targhe iniziano sempre con lettere)
      3. Solo caratteri alfanumerici, trattino, punto, spazio
      4. Non troppo lungo con solo alfanumerici (potrebbe essere testo/ID)
      5. Non tutto alfabetico corto (filtra cognomi del conducente: "MASOTTI", "PORTERO")
      6. Non "PAROLA PAROLA" con entrambe parti pure alpha (es. "RO AGUERLO" dal nome)
    """
    vehicles: dict = {}
    p = 0
    while p < len(raw) - 28:
        # Cerca il timestamp lastUse come anchor: è il punto più affidabile del record
        last = _ts(raw, p + 10)
        if last is None:
            p += 1
            continue   # nessun timestamp valido qui: avanza di 1 byte

        try:
            vrn = raw[p + 15 : p + 29].decode("ascii")   # 14 byte: solo ASCII
        except Exception:
            p += 1
            continue

        vrn = vrn.replace(chr(0), "").strip()   # rimuovi null byte e spazi iniziali/finali

        # ── Filtri anti-falsi-positivi ──────────────────────────────────────
        if not (4 <= len(vrn) <= 13):
            p += 1
            continue   # troppo corta (< 4) o troppo lunga (> 13): non è una targa
        if not any(c.isalpha() for c in vrn[:2]):
            p += 1
            continue   # i primi 2 caratteri devono contenere almeno una lettera
        if not all(c.isalnum() or c in "-. " for c in vrn):
            p += 1
            continue   # caratteri non validi in una targa: simboli speciali, accenti, ecc.
        if len(vrn) > 10 and vrn.replace(" ", "").isalnum():
            p += 1
            continue   # stringa alfanumerica > 10 caratteri: probabilmente un ID/seriale
        if vrn.isalpha() and vrn == vrn.upper() and len(vrn) <= 7:
            p += 1
            continue   # parola tutta maiuscola corta: potrebbe essere il cognome del conducente
        # Rigetta "PAROLA PAROLA": due (o più) parole tutte alfabetiche = frammento di nome
        parts = vrn.split()
        if len(parts) >= 2 and all(pt.isalpha() for pt in parts):
            p += 1
            continue

        # Record plausibile: leggi first_use e salva il veicolo
        first = _ts(raw, p + 6) or last   # first_use a offset 6, fallback su last
        if first > last:
            first = last   # impossibile first > last: correggi

        # Il primo record trovato per un VRN "vince" (in ordine di scan del file)
        if vrn not in vehicles:
            vehicles[vrn] = (first.strftime("%d/%m/%Y"), last.strftime("%d/%m/%Y"))

        p += 14   # avanza di 14 byte (lunghezza VRN) — heuristica per evitare duplicati ravvicinati

    # Dict comprehension per costruire i Vehicle dai dati raccolti
    return [Vehicle(vrn=vrn, first_use=f, last_use=l)
            for vrn, (f, l) in vehicles.items()]


def _decode_geocoord(b: bytes) -> Optional[float]:
    """
    Decodifica 3 byte GeoCoordinate (EU Annex 1B, formato EF_PLACES) in gradi decimali.

    FORMATO BINARIO:
    La spec EU usa un intero a 24 bit con segno (complemento a due) dove l'unità
    è 1/10 di minuto d'arco (non gradi decimali, non secondi d'arco).

    CONVERSIONE: decimal_degrees = value / 10 / 60 = value / 600
      Esempio: value = 27738 → 27738/600 = 46.23° (nord Italia)

    ESTENSIONE SEGNO A 32 BIT:
    Python non ha tipi a 24 bit. Per interpretare correttamente il segno (bit 23):
      - Se bit 7 del primo byte è 1 (numero negativo): riempi il byte alto con 0xFF
      - Altrimenti: riempi con 0x00
    Poi converti i 4 byte in int con signed=True.
    """
    if len(b) < 3:
        return None
    # Estensione segno: bit 7 del byte più significativo indica il segno
    fill = 0xFF if (b[0] & 0x80) else 0x00
    val = int.from_bytes(bytes([fill, b[0], b[1], b[2]]), "big", signed=True)
    if val == 0:
        return None   # coordinate 0,0 = dato mancante (in mezzo all'oceano)
    coord = round(val / 600.0, 6)   # 6 decimali = precisione ~0.11 metri al quatore
    if abs(coord) > 180:
        return None   # coordinata impossibile: falso positivo
    return coord


def _decode_gnss_coord(b: bytes) -> Optional[float]:
    """
    Decodifica 3 byte GnssCoordinate (EU Annex 1C, formato Gen2 GNSS) in gradi decimali.

    DIVERSO da _decode_geocoord: l'unità qui è milligradi (1/1000 di grado),
    NON decimi di minuto d'arco come in EF_PLACES.

    CONVERSIONE: decimal_degrees = value / 1000
      Esempio: value = 46230 → 46.230° (stesso punto del esempio sopra, formato diverso)

    La spec Gen2 ha scelto milligradi per semplificare la conversione: non serve
    la divisione per 60 come nel formato vecchio.
    Stessa tecnica di estensione segno a 32 bit di _decode_geocoord.
    """
    if len(b) < 3:
        return None
    fill = 0xFF if (b[0] & 0x80) else 0x00
    val = int.from_bytes(bytes([fill, b[0], b[1], b[2]]), "big", signed=True)
    if val == 0:
        return None
    coord = round(val / 1000.0, 6)
    if abs(coord) > 180:
        return None
    return coord


def _decode_gnss_accumulated(data: bytes) -> List[GNSSRecord]:
    """
    EF_GNSS_ACCUMULATED_DRIVING: waypoint GPS accumulati durante la guida (Gen2).

    Trovato nel payload del tag 0x0524 (EF_ACTIVITY_DATA_V2) nelle carte Gen2.
    I waypoint sono registrati automaticamente dall'apparecchio durante la guida
    per ricostruire il percorso del veicolo.

    STRUTTURA:
      [pointer:2] → header (skip, come altri buffer circolari)
      [record×N: 18 byte ciascuno]:
        offset 0-3:  gnss_ts (4 byte Unix UTC) → timestamp lettura GPS
        offset 4-7:  trip_ts (4 byte Unix UTC) → timestamp sessione (non usato)
        offset 8:    gnss_status (1 byte)       → 0 o 255 = posizione non disponibile
        offset 9-11: lat (3 byte, milligradi)   → latitudine (vedere _decode_gnss_coord)
        offset 12-14: lon (3 byte, milligradi)  → longitudine
        offset 15-17: odometer (3 byte, big-endian, km)

    VALIDAZIONE strutturale:
    Il buffer è valido solo se (len - 2) è esatto multiplo di 18.
    Il limite 1000 record previene false detections su buffer enormi.
    gnss_status ∈ {0, 255} indica "fix GPS non disponibile" → scarta il waypoint.
    """
    n = len(data)
    if n < 20:
        return []   # troppo corto per anche solo 1 record
    # Usa divisione intera: il buffer può avere una coda parziale (ultimo record
    # incompleto) se la carta è stata rimossa durante la scrittura.
    # Non richiediamo (n-2) % 18 == 0: i byte extra vengono ignorati.
    n_recs = (n - 2) // 18
    if n_recs == 0 or n_recs > 1000:
        return []   # 0 record o troppi: buffer non compatibile

    records: List[GNSSRecord] = []
    o = 2   # salta i 2 byte di header (pointer)

    for _ in range(n_recs):
        if o + 18 > n:
            break
        ts    = _ts(data, o)           # timestamp GPS
        acc   = data[o + 8]            # gnss_status (accuracy indicator)
        lat_b = data[o + 9:  o + 12]   # 3 byte latitudine
        lon_b = data[o + 12: o + 15]   # 3 byte longitudine
        odo   = int.from_bytes(data[o + 15: o + 18], "big")   # odometro in km
        o += 18

        if ts is None or not (YEAR_MIN <= ts.year <= YEAR_MAX):
            continue   # timestamp non valido
        if acc in (0, 255):
            continue   # GPS fix non disponibile: 0 = no signal, 255 = error
        lat = _decode_gnss_coord(lat_b)
        lon = _decode_gnss_coord(lon_b)
        if lat is None or lon is None:
            continue   # coordinate malformate o nulle

        records.append(GNSSRecord(
            timestamp=ts.strftime("%d/%m/%Y %H:%M"),
            date=ts.strftime("%Y-%m-%d"),
            lat=lat, lon=lon,
            accuracy_dm=acc,
            odometer_km=odo,
        ))

    # Ordina per data decrescente: i waypoint più recenti prima (come le altre liste)
    return sorted(records, key=lambda r: r.date, reverse=True)


def _decode_places(data: bytes, is_gen2: bool = False) -> List[Place]:
    """
    EF_PLACES (0x0506): luoghi di inizio e fine del periodo di lavoro.

    Un "luogo" viene registrato quando il conducente inserisce o rimuove la carta
    dal tachigrafo. Indica dove si trovava il veicolo in quel momento.
    Utile per ricostruire le città/nazioni visitate durante il periodo di lavoro.

    AUTO-DETECTION DEL FORMATO in base alla lunghezza del payload:
      Gen1: [pointer:1][record×N: 10 byte]  → (len-1) % 10 == 0
      Gen2: [pointer:2][record×N: 21 byte]  → (len-2) % 21 == 0 (solo se is_gen2=True)

    STRUTTURA RECORD GEN1 (10 byte):
      offset 0-3: ts (4 byte Unix UTC)    → data/ora di inserimento/rimozione carta
      offset 4:   entry_type (1 byte)     → 1 = INIZIO, 0 = FINE
      offset 5:   country (1 byte)        → codice nazione EU (tabella EU_NATIONS)
      offset 6:   region (1 byte)         → codice regione (mappa EU interna, non usato)
      offset 7-9: odometer (3 byte, km)   → lettura odometro al momento

    STRUTTURA RECORD GEN2 (21 byte = Gen1 + GNSSPlaceRecord):
      offset 10-13: gnss_ts (4 byte UTC)     → timestamp fix GPS (separato dal record)
      offset 14:    gnss_accuracy (1 byte)   → 0/255 = no fix
      offset 15-17: gnss_lat (3 byte, milligradi)
      offset 18-20: gnss_lon (3 byte, milligradi)

    NOTA: molte carte Gen2 v1 scrivono EF_PLACES in formato Gen1 per retrocompatibilità,
    quindi is_gen2=True non implica necessariamente il formato a 21 byte.
    """
    n = len(data)
    # Verifica se le due dimensioni fisse sono compatibili con la lunghezza del payload
    gen1_exact = n >= 11 and (n - 1) % 10 == 0   # Gen1: header 1 byte, record 10 byte
    gen2_exact = n >= 23 and (n - 2) % 21 == 0   # Gen2: header 2 byte, record 21 byte

    # Logica di selezione formato:
    if is_gen2 and gen2_exact and not gen1_exact:
        # Solo Gen2 è compatibile
        rec_size = 21
        hdr_size = 2
    elif is_gen2 and gen2_exact and gen1_exact:
        # Entrambi compatibili: scegli in base al numero di record.
        # Preferiamo Gen2 se produce un numero di record ≤ Gen1 (più credibile).
        n_gen2 = (n - 2) // 21
        n_gen1 = (n - 1) // 10
        rec_size = 21 if n_gen2 <= n_gen1 else 10
        hdr_size = 2 if rec_size == 21 else 1
    else:
        if n < 11:
            return []   # troppo corto per anche solo 1 record Gen1
        rec_size = 10   # default: formato Gen1
        hdr_size = 1

    o = hdr_size   # salta l'header (1 o 2 byte a seconda della generazione)
    max_records = (n - hdr_size) // rec_size   # numero massimo di record leggibili
    use_gnss = (rec_size == 21)   # True se il formato include i dati GNSS aggiuntivi

    places: List[Place] = []
    seen: set = set()   # deduplicazione: chiave (datetime_str, nat) per evitare duplicati

    for _ in range(max_records):
        if o + rec_size > n:
            break   # record troncato: fine dei dati

        ts     = _ts(data, o)           # timestamp: 4 byte Unix UTC
        et     = data[o + 4]            # entry_type: 1=Inizio, altro=Fine
        nat    = data[o + 5]            # codice nazione EU (1-57)
        region = data[o + 6]            # codice regione (non mappato in UI corrente)
        odo    = int.from_bytes(data[o + 7: o + 10], "big")   # odometro in km

        # Dati GNSS opzionali (solo record da 21 byte, formato Gen2)
        gnss_lat = gnss_lon = None
        gnss_acc = 0
        if use_gnss:
            gnss_acc = data[o + 14]   # accuracy: 0 o 255 = no fix GPS
            if gnss_acc not in (0, 255):
                # Coordinate nel formato EF_PLACES: decimi di minuto d'arco (non milligradi)
                gnss_lat = _decode_geocoord(data[o + 15: o + 18])
                gnss_lon = _decode_geocoord(data[o + 18: o + 21])

        o += rec_size   # avanza al record successivo

        if ts is None or not (YEAR_MIN <= ts.year <= YEAR_MAX):
            continue   # timestamp non valido: slot vuoto o padding
        # Chiave di deduplicazione: stesso minuto, stessa nazione = stesso evento
        key = (ts.strftime("%Y-%m-%d %H:%M"), nat)
        if key in seen:
            continue   # già visto: il buffer circolare può contenere copie sovrapposte
        seen.add(key)

        places.append(Place(
            datetime=ts.strftime("%d/%m/%Y %H:%M"),
            date=ts.strftime("%Y-%m-%d"),
            country=EU_NATIONS.get(nat, f"?{nat}"),   # "?57" se nazione sconosciuta
            entry_type="Inizio" if et == 1 else "Fine",
            odometer_km=odo,
            region=region,
            gnss_lat=gnss_lat,
            gnss_lon=gnss_lon,
            gnss_accuracy=gnss_acc,
        ))

    # Ordina per data decrescente: i luoghi più recenti prima
    return sorted(places, key=lambda p: p.date, reverse=True)


def _decode_events(data: bytes, is_gen2: bool = False) -> List[CardEvent]:
    """
    EF_EVENTS_DATA (0x0502): eventi anomali registrati dall'apparecchio di controllo.

    STRUTTURA A SLOT:
    Il buffer è organizzato in slot fissi, uno per tipo di evento.
    Ogni slot contiene un array di record; quando lo slot è pieno, il più vecchio
    viene sovrascritto (comportamento FIFO circolare per slot).

      Gen1: 6 slot (eventi base Reg. 3821/85)
      Gen2: 11 slot (aggiunge eventi GNSS, Annex 1C)

    Struttura di ogni slot:
      [NoOfEventsPerType: 1 byte] → quanti record validi ci sono in questo slot
      [CardEventRecord × N: 24 byte ciascuno]

    Struttura CardEventRecord (24 byte):
      offset 0:    event_type (1 byte) → tipo evento (spesso ridondante con lo slot_idx)
      offset 1-4:  begin (4 byte UTC) → inizio dell'evento
      offset 5-8:  end (4 byte UTC)   → fine dell'evento
      offset 9:    nation (1 byte)    → nazione
      offset 10:   codepage (1 byte)  → codifica VRN
      offset 11-23: vrn (13 byte)     → targa veicolo coinvolto
    """
    n_slots = 11 if is_gen2 else 6
    events: List[CardEvent] = []
    o = 0
    for slot_idx in range(n_slots):
        if o >= len(data):
            break
        n_recs = data[o]; o += 1   # conta record validi in questo slot

        # Il codice evento è determinato dall'indice dello slot, non dal campo interno
        code = _EVENT_SLOT_CODES[slot_idx] if slot_idx < len(_EVENT_SLOT_CODES) else 0xFF

        for _ in range(n_recs):
            if o + 24 > len(data):
                break   # record troncato
            ts_begin = _ts(data, o + 1)    # begin a offset 1 (non 0: il byte 0 è event_type)
            ts_end   = _ts(data, o + 5)    # end a offset 5
            vrn      = _str(data[o + 11: o + 24])   # VRN: 13 byte da offset 11
            o += 24   # avanza di 24 byte al prossimo record dello slot

            if ts_begin and YEAR_MIN <= ts_begin.year <= YEAR_MAX:
                events.append(CardEvent(
                    begin_time=ts_begin.strftime("%d/%m/%Y %H:%M"),
                    end_time=ts_end.strftime("%d/%m/%Y %H:%M") if ts_end else "",
                    event_type_code=code,
                    event_type=EVENT_TYPE_NAMES.get(code, f"Evento 0x{code:02X}"),
                    vehicle=vrn,
                ))
    return events


def _decode_faults(data: bytes, is_gen2: bool = False) -> List[CardFault]:
    """
    EF_FAULTS_DATA (0x0503): guasti hardware/software registrati dall'apparecchio.

    Struttura identica a EF_EVENTS_DATA ma con soli 2 slot (identico per Gen1 e Gen2):
      Slot 0: guasti hardware carta (codice 0x10)
      Slot 1: errori software carta (codice 0x11)

    Struttura slot:
      [NoOfFaultsPerType: 1 byte] → record validi in questo slot
      [CardFaultRecord × N: 24 byte] → stesso formato di CardEventRecord

    La differenza rispetto agli eventi è semantica: i guasti indicano problemi
    all'hardware o al firmware (carta o apparecchio), non al comportamento del conducente.
    """
    faults: List[CardFault] = []
    o = 0
    for slot_idx in range(2):   # sempre 2 slot, sia Gen1 che Gen2
        if o >= len(data):
            break
        n_recs = data[o]; o += 1   # record validi in questo slot

        code = _FAULT_SLOT_CODES[slot_idx] if slot_idx < len(_FAULT_SLOT_CODES) else 0xFF

        for _ in range(n_recs):
            if o + 24 > len(data):
                break
            ts_begin = _ts(data, o + 1)
            ts_end   = _ts(data, o + 5)
            vrn      = _str(data[o + 11: o + 24])
            o += 24
            if ts_begin and YEAR_MIN <= ts_begin.year <= YEAR_MAX:
                faults.append(CardFault(
                    begin_time=ts_begin.strftime("%d/%m/%Y %H:%M"),
                    end_time=ts_end.strftime("%d/%m/%Y %H:%M") if ts_end else "",
                    fault_type_code=code,
                    fault_type=FAULT_TYPE_NAMES.get(code, f"Fault 0x{code:02X}"),
                    vehicle=vrn,
                ))
    return faults


def _decode_specific_conditions(data: bytes, is_gen2: bool = False) -> List[SpecificCondition]:
    """
    EF_SPECIFIC_CONDITIONS (0x0522): periodi di attività in condizioni speciali.

    Le condizioni speciali sospendono il conteggio normale dei tempi di guida/riposo.
    Esempio tipico: il conducente è su un traghetto — il veicolo si muove, ma lui
    non sta guidando. Il tachigrafo registra inizio e fine di questa condizione.

    STRUTTURA DIVERSA TRA GEN1 E GEN2:
      Gen1: [pointer:1][record×56 max: 5 byte] → al massimo 56 record per spec
            - pointer: 1 byte (offset del record più vecchio, skippato)
            - count implicito: legge fino alla fine del payload o a 56 record

      Gen2: [pointer:2][count:2][record×N: 5 byte] → count esplicito
            - pointer: 2 byte
            - count: 2 byte (numero esatto di record validi presenti)

    STRUTTURA SpecificConditionRecord (5 byte):
      offset 0-3: entry_time (4 byte Unix UTC) → data/ora inizio/fine condizione
      offset 4:   condition_type (1 byte) → codice tipo (vedi SPECIFIC_CONDITION_NAMES)

    condition_type == 0x00 ("Normale") viene saltato: non è una condizione speciale.
    """
    conditions: List[SpecificCondition] = []
    if is_gen2:
        if len(data) < 4:
            return []
        count = _u16(data, 2)   # Gen2: count esplicito a offset 2
        o = 4   # inizio record dopo 4 byte header (pointer:2 + count:2)
    else:
        if len(data) < 1:
            return []
        count = 56   # Gen1: spec dice massimo 56 record, leggi fino alla fine
        o = 1        # inizio record dopo il pointer a 1 byte

    for _ in range(count):
        if o + 5 > len(data):
            break   # fine dati
        ts    = _ts(data, o)      # timestamp condizione: 4 byte Unix UTC
        ctype = data[o + 4]       # tipo condizione: 1 byte
        o += 5
        # Filtra: ctype == 0x00 è "Normale" (nessuna condizione speciale attiva)
        if ts and YEAR_MIN <= ts.year <= YEAR_MAX and ctype != 0x00:
            conditions.append(SpecificCondition(
                entry_time=ts.strftime("%d/%m/%Y %H:%M"),
                condition_type=SPECIFIC_CONDITION_NAMES.get(ctype, f"Tipo 0x{ctype:02X}"),
            ))
    return conditions


def _decode_licence(data: bytes, driver: DriverInfo) -> None:
    """
    EF_DRIVING_LICENCE_INFO (0x0521): numero e autorità emittente della patente.

    LAYOUT GEN1 (53 byte totali — Annex 1B):
      byte 0:     nation (1 byte) — nazione emittente patente (non usato qui)
      byte 1-35:  licence_authority (35 byte, latin-1) — autorità che ha emesso la patente
      byte 36:    separatore (skippato)
      byte 37-52: licence_number (16 byte, latin-1) — numero patente

    ATTENZIONE — falso positivo nel file MASOTTI:
    Il file contiene DUE occorrenze di questo tag:
      - Offset basso:  53 byte → dati REALI (catturato da _PREFER_FIRST_MATCH)
      - Offset alto:   96 byte → blocco directory che inizia per caso con 0x0521
    Questa funzione legge sempre il payload già selezionato da _pass1; non deve
    gestire la selezione (quella è compito di _PREFER_FIRST_MATCH).

    Modifica direttamente il driver DriverInfo passato per riferimento (in-place).
    In Python tutti gli oggetti mutabili sono passati per riferimento: la modifica
    dentro la funzione è visibile fuori (a differenza dei tipi primitivi come int/str).
    """
    if len(data) >= 36: driver.licence_authority = _str(data[1:36])   # byte 1..35 (skip nation a 0)
    if len(data) >= 53: driver.licence_number    = _str(data[37:53])  # byte 37..52 (skip separatore a 36)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def parse_ddd(raw: bytes) -> CardData:
    """
    Entry point principale: parsifica un file .DDD e ritorna un oggetto CardData.

    PIPELINE IN DUE PASSI:
      PASS 1 → _pass1(): scansiona il file raw e raccoglie i payload dei FID di interesse
      PASS 2 → decoder semantici: interpreta ogni payload nel suo formato specifico

    GESTIONE ERRORI:
    Ogni decoder è wrappato in try/except: se un blocco dati è malformato
    (es. carta vecchia o firmware non standard), l'errore viene registrato in
    cd.errors e il parsing continua con i dati parziali disponibili.
    Questo approccio "best effort" è essenziale: i file DDD reali non sono sempre
    perfettamente conformi alla spec, e meglio mostrare dati parziali che nulla.

    STRATEGIA ATTIVITÀ (dual-source):
    Le carte Gen2 v1 scrivono sia 0x0524 (buffer attività V2) che 0x0504 (buffer Gen1-compat).
    Entrambi vengono decodificati e viene scelto quello con più segmenti non-Riposo
    (= più informazioni reali). Il Riposo riempie automaticamente i giorni inattivi,
    quindi non è un indicatore di ricchezza del dato.

    STRATEGIA VEICOLI (fallback progressivo):
    1. Prova EF_VEHICLEUNITS_USED (Gen2, formato 48 byte/record)
    2. Prova EF_VEHICLES_USED (Gen1, formato 31 byte/record)
    3. Fallback: scan del raw intero con _scan_vehicles_structured()
    Il risultato con più veicoli vince.

    POST-PROCESSING (cutoff date):
    Rimuove record con date impossibilmente future. Il buffer circolare del tachigrafo
    può contenere slot vuoti con timestamp spazzatura che cadono nel 2036-2038.
    Cutoff = last_download + 30gg (se disponibile) o expiry_date + 365gg o oggi + 30gg.
    """
    cd = CardData()   # CardData è il contenitore principale di tutti i dati della carta

    # ── PASS 1: ricerca diretta dei tag nel file raw ───────────────────────────
    # S è un dizionario {FID → payload_bytes}: contiene i dati grezzi di ogni EF trovato
    S = _pass1(raw, max_depth=6)

    # ── PASS 2: decoder semantici ────────────────────────────────────────────────

    # Conducente — dati anagrafici (nome, carta, scadenza, …)
    if EF_IDENTIFICATION in S:
        try:
            cd.driver = _decode_identification(S[EF_IDENTIFICATION])
        except Exception as e:
            cd.errors.append(f"IDENT: {e}")

    # Patente — integra le info nel driver (già parzialmente riempito da IDENTIFICATION)
    if EF_DRIVING_LICENCE_INFO in S:
        try:
            _decode_licence(S[EF_DRIVING_LICENCE_INFO], cd.driver)
        except Exception as e:
            cd.errors.append(f"LICENCE: {e}")

    # Ultimo download — data/ora dell'ultima lettura della carta da parte di un'autorità
    if EF_CARD_DOWNLOAD in S:
        ts = _ts(S[EF_CARD_DOWNLOAD], 0)   # un solo timestamp da 4 byte
        if ts:
            cd.driver.last_download = ts.strftime("%d/%m/%Y %H:%M")

    # ── Attività: strategia dual-source ─────────────────────────────────────────
    # _act_score: conta i changeset non-Riposo — indicatore di "ricchezza" del dato
    # (Riposo è il valore di default quando non c'è guida, ha poco valore informativo)
    def _act_score(acts: list) -> int:
        return sum(1 for d in acts for c in d.changes if c.activity != "Riposo")

    acts_v2: List[DayActivity] = []   # da buffer Gen2 (0x0524)
    acts_g1: List[DayActivity] = []   # da buffer Gen1 (0x0504)

    if EF_ACTIVITY_DATA_V2 in S:
        try:
            acts_v2 = _decode_activities_v2(S[EF_ACTIVITY_DATA_V2])
        except Exception as e:
            cd.errors.append(f"ACTIVITY_V2: {e}")

    if EF_DRIVER_ACTIVITY_DATA in S and len(S[EF_DRIVER_ACTIVITY_DATA]) > 64:
        try:
            # Prova prima il decoder V2 (coppie UTC/locale): alcune carte Gen2 v1
            # scrivono anche 0x0504 in formato V2. Se non produce risultati,
            # usa il decoder Gen1 classico (buffer circolare con oldest/newest).
            acts_g1 = (_decode_activities_v2(S[EF_DRIVER_ACTIVITY_DATA]) or
                       _decode_activities_gen1(S[EF_DRIVER_ACTIVITY_DATA]))
        except Exception as e:
            cd.errors.append(f"ACTIVITY: {e}")

    # Selezione della sorgente attività migliore (maggiore score non-Riposo):
    score_v2, score_g1 = _act_score(acts_v2), _act_score(acts_g1)
    if score_v2 >= score_g1 and acts_v2:
        cd.activities = sorted(acts_v2, key=lambda d: d.date)   # ordina per data ISO
    elif acts_g1:
        cd.activities = sorted(acts_g1, key=lambda d: d.date)
    elif acts_v2:
        cd.activities = sorted(acts_v2, key=lambda d: d.date)   # fallback: usa V2 anche se score basso

    # ── Veicoli: strategia a cascata ────────────────────────────────────────────
    # Prova prima Gen2 (0x0523), poi Gen1 (0x0505): il migliore (più veicoli) vince
    for fid in (EF_VEHICLEUNITS_USED, EF_VEHICLES_USED):
        if fid in S:
            try:
                # 0x0523 = Gen2: prova 48-byte prima; 0x0505 = Gen1: prova 31-byte prima
                veh, sess = _decode_vehicles_tlv(S[fid], prefer_gen2=(fid == EF_VEHICLEUNITS_USED))
                if len(veh) > len(cd.vehicles):   # tieni il risultato più ricco
                    cd.vehicles = veh
                    cd.vehicle_sessions = sess
            except Exception as e:
                cd.errors.append(f"VEH({fid:#x}): {e}")

    # Fallback: scan del raw se TLV ha prodotto < 2 veicoli (dato insufficiente)
    if len(cd.vehicles) < 2:
        try:
            veh_fb = _scan_vehicles_structured(raw)
            if len(veh_fb) > len(cd.vehicles):
                cd.vehicles = veh_fb
        except Exception as e:
            cd.errors.append(f"VEH_FALLBACK: {e}")

    # ── Rilevamento generazione (Gen1 / Gen2 v1 / Gen2 v2) ─────────────────────
    # Discriminatori in ordine di affidabilità:
    #   1. EF_APPLICATION_ID_V2 (0x0525) → solo Gen2 v2
    #   2. EF_VEHICLEUNITS_USED (0x0523) con payload reale (≥ 98 byte) → Gen2 v1
    #      (falsi positivi da blocco directory hanno payload ~96 byte, sotto la soglia)
    #   3. Altrimenti → Gen1
    _VU_MIN = 98   # 2 header + 2 record × 48 byte = minimo plausibile per un EF_VEHICLEUNITS reale
    is_gen2 = False
    if EF_APPLICATION_ID_V2 in S:
        cd.driver.generation = "G2 (v2)"
        is_gen2 = True
    elif EF_VEHICLEUNITS_USED in S and len(S[EF_VEHICLEUNITS_USED]) >= _VU_MIN:
        cd.driver.generation = "G2 (v1)"
        is_gen2 = True
    else:
        cd.driver.generation = "G1"

    # Luoghi — is_gen2 influenza la scelta del formato record (10 vs 21 byte)
    if EF_PLACES in S:
        try:
            cd.places = _decode_places(S[EF_PLACES], is_gen2=is_gen2)
        except Exception as e:
            cd.errors.append(f"PLACES: {e}")

    # GNSS waypoint — prova a decodificare il buffer 0x0524 anche come GNSS.
    # Lo stesso payload può contenere sia le attività (coppie UTC/locale) che
    # i waypoint GPS: sono strutturalmente distinti e possono coesistere.
    # Non è critico: se il formato GNSS non corrisponde, ritorna [] e niente si rompe.
    if EF_ACTIVITY_DATA_V2 in S:
        try:
            gnss = _decode_gnss_accumulated(S[EF_ACTIVITY_DATA_V2])
            if gnss:
                cd.gnss_records = gnss
        except Exception:
            pass  # non critico: i waypoint GPS sono una feature opzionale

    # Eventi anomali (guida senza carta, eccesso velocità, ecc.)
    if EF_EVENTS_DATA in S:
        try:
            cd.events = _decode_events(S[EF_EVENTS_DATA], is_gen2=is_gen2)
        except Exception as e:
            cd.errors.append(f"EVENTS: {e}")

    # Guasti hardware/software dell'apparecchio
    if EF_FAULTS_DATA in S:
        try:
            cd.faults = _decode_faults(S[EF_FAULTS_DATA], is_gen2=is_gen2)
        except Exception as e:
            cd.errors.append(f"FAULTS: {e}")

    # Condizioni speciali (traghetto, fuori ambito, ecc.)
    if EF_SPECIFIC_CONDITIONS in S:
        try:
            cd.specific_conditions = _decode_specific_conditions(S[EF_SPECIFIC_CONDITIONS], is_gen2=is_gen2)
        except Exception as e:
            cd.errors.append(f"SPECIFIC_CONDITIONS: {e}")

    # Dimensione file originale in byte (utile per diagnostica e debug)
    cd.driver.file_size = str(len(raw))

    # ── POST-PROCESSING: filtro date future ──────────────────────────────────────
    # Il buffer circolare del tachigrafo contiene slot riservati ma vuoti.
    # Uno slot vuoto ha tutti i byte a 0x00 o 0xFF: il timestamp estratto può cadere
    # in anni futuri impossibili (es. 2036, 2038). Il cutoff li rimuove.
    #
    # LOGICA CUTOFF (in ordine di priorità):
    #   1. last_download + 30gg: il download è la data "fotografica" della carta.
    #   2. expiry_date + 365gg: se il download non è disponibile, usa la scadenza.
    #   3. oggi + 30gg: fallback generico.
    #
    # IMPORTANTE: il cutoff non deve mai essere inferiore a oggi + 1 giorno,
    # altrimenti taglia attività reali della giornata corrente (es. carta letta
    # oggi ma il download precedente era >30gg fa).
    try:
        from datetime import timedelta as _td, date as _date
        if cd.driver.last_download:
            ref = datetime.strptime(cd.driver.last_download, "%d/%m/%Y %H:%M").date()
            margin = _td(days=30)
        elif cd.driver.expiry_date:
            ref = datetime.strptime(cd.driver.expiry_date, "%d/%m/%Y").date()
            margin = _td(days=365)
        else:
            ref = _date.today()
            margin = _td(days=30)
        # Garantisce che attività di oggi non vengano mai filtrate
        cutoff = max(ref + margin, _date.today() + _td(days=1))

        # Helper: verifica che una data stringa non superi il cutoff.
        # Se il parsing fallisce (dato malformato), lascia passare (return True = valido).
        def _ok_iso(s: str) -> bool:
            try: return datetime.strptime(s, "%Y-%m-%d").date() <= cutoff
            except Exception: return True

        def _ok_dmy(s: str) -> bool:
            try: return datetime.strptime(s, "%d/%m/%Y").date() <= cutoff
            except Exception: return True

        # List comprehension con filtro: ricrea le liste senza i record fuori cutoff.
        # Per i veicoli serve che ENTRAMBE le date (prima e ultima sessione) siano valide.
        cd.activities = [a for a in cd.activities if _ok_iso(a.date)]
        cd.places     = [p for p in cd.places     if _ok_iso(p.date)]
        cd.vehicles   = [v for v in cd.vehicles
                         if _ok_dmy(v.first_use) and _ok_dmy(v.last_use)]
    except Exception:
        pass   # se il post-processing fallisce, usa i dati non filtrati (meglio parziale che niente)

    # Rimuove false positive da garbage nella zona di wrap del buffer circolare:
    # record con date impossibilmente vecchie rispetto all'attività più recente.
    # Limite: nessuna carta contiene dati oltre 2 anni prima dell'ultimo giorno.
    try:
        from datetime import timedelta as _td2
        if cd.activities:
            newest_act = datetime.strptime(cd.activities[-1].date, "%Y-%m-%d").date()
            floor_date = newest_act - _td2(days=730)
            cd.activities = [a for a in cd.activities
                             if datetime.strptime(a.date, "%Y-%m-%d").date() >= floor_date]
    except Exception:
        pass

    return cd

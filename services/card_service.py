"""
services/card_service.py
Lettura della carta conducente con un lettore USB (PC/SC) e scrittura della data
di scarico.

Protocollo: Reg. (UE) 2016/799, Appendice 2 (comandi) e Appendice 7 (formato del file).
Il file prodotto è quello di uno scarico completo, uguale a quello dei lettori
ufficiali:
  - MF: EF ICC (0002), EF IC (0005), EF DIR (2F00) — appendice 00, senza firma
  - applicazione Gen1 (AID FF 54 41 43 48 4F): certificati C100/C108 e tutti gli EF,
    ognuno seguito dalla sua firma (appendice 00 dati, 01 firma)
  - applicazione Gen2 (AID FF 53 4D 52 44 54), solo sulle carte di seconda
    generazione: certificati C100/C108/C101/C109 e gli EF Gen2 (appendice 02 dati,
    03 firma), compresi quelli della versione 2 (0525, 0528-0530) se presenti.

Ogni EF firmato si legge così (App. 2 §3.3.3):
  SELECT EF → PERFORM HASH OF FILE (80 2A 90 00) → READ BINARY → PSO: COMPUTE DIGITAL SIGNATURE

Le dimensioni degli EF si calcolano da EF Application_Identification (0501, e 0525
per la versione 2), come fanno i lettori ufficiali: così un EF letto a metà viene
riconosciuto e il file non si salva incompleto.
"""
from __future__ import annotations

import logging
import struct
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

try:
    from smartcard.System import readers as sc_readers
    from smartcard.Exceptions import (CardConnectionException, NoCardException,
                                      NoReadersException)
    from smartcard.util import toHexString
    PYSCARD_OK = True
except ImportError:
    PYSCARD_OK = False

    class CardConnectionException(Exception):   # segnaposto senza pyscard
        pass

# ── Applicazioni (App. 2 §3.5.1.1) ───────────────────────────────────────────────
AID_GEN1 = [0xFF, 0x54, 0x41, 0x43, 0x48, 0x4F]
AID_GEN2 = [0xFF, 0x53, 0x4D, 0x52, 0x44, 0x54]

EF_NAMES = {
    0x0002: "ICC", 0x0005: "IC", 0x2F00: "DIR",
    0x0501: "Application_Identification", 0x0502: "Events_Data", 0x0503: "Faults_Data",
    0x0504: "Driver_Activity_Data", 0x0505: "Vehicles_Used", 0x0506: "Places",
    0x0507: "Current_Usage", 0x0508: "Control_Activity_Data", 0x050E: "Card_Download",
    0x0520: "Identification", 0x0521: "Driving_Licence_Info", 0x0522: "Specific_Conditions",
    0x0523: "VehicleUnits_Used", 0x0524: "GNSS_Places", 0x0525: "Application_Identification_V2",
    0x0526: "Places_Authentication", 0x0527: "GNSS_Places_Authentication",
    0x0528: "Border_Crossings", 0x0529: "Load_Unload_Operations", 0x0530: "Load_Type_Entries",
    0xC100: "Card_Certificate", 0xC101: "CardSignCertificate", 0xC108: "CA_Certificate",
    0xC109: "Link_Certificate",
}

# Ordine degli EF nel file (come gli scarichi dei lettori ufficiali)
GEN1_ORDER = [0x0501, 0xC100, 0xC108, 0x0520, 0x050E, 0x0521, 0x0502, 0x0503, 0x0504,
              0x0505, 0x0506, 0x0507, 0x0508, 0x0522]
GEN2_ORDER = [0x0501, 0xC100, 0xC108, 0xC101, 0xC109, 0x0520, 0x050E, 0x0521, 0x0502,
              0x0503, 0x0504, 0x0505, 0x0506, 0x0507, 0x0508, 0x0522, 0x0523, 0x0524,
              0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x0530]
CERTIFICATES = {0xC100, 0xC101, 0xC108, 0xC109}          # non firmati

# EF senza i quali lo scarico non è valido (il file non viene salvato)
MANDATORY = {
    "G1": {0x0501, 0xC100, 0xC108, 0x0520, 0x0521, 0x0502, 0x0503, 0x0504, 0x0505,
           0x0506, 0x0507, 0x0508},
    "G2": {0x0501, 0xC100, 0xC108, 0xC101, 0x0520, 0x050E, 0x0521, 0x0502, 0x0503,
           0x0504, 0x0505, 0x0506, 0x0507, 0x0508, 0x0522, 0x0523, 0x0524},
}

CARD_TYPES = {1: "conducente", 2: "officina", 3: "controllo", 4: "azienda"}

CHUNK = 240          # byte per READ BINARY
# Data di questa versione: l'orologio del PC è plausibile se cade tra questa data e
# 5 anni dopo (come fanno i lettori ufficiali prima di scrivere la data di scarico).
BUILD_DATE = date(2026, 10, 18)


STAMP_OK = "Data di scarico scritta sulla carta."


class CardReadError(RuntimeError):
    """Lettura non riuscita o incompleta: il file non va salvato."""


# Esito dell'ultima lettura (data di scarico scritta, avvisi) per l'interfaccia
LAST_READ: Dict[str, object] = {}
# Avanzamento della lettura in corso, letto dall'interfaccia mentre la carta si legge
PROGRESS: Dict[str, object] = {"active": False, "step": 0, "total": 0, "text": ""}


# ── Dimensioni degli EF da Application_Identification ───────────────────────────

def sizes_gen1(app: bytes) -> Dict[int, int]:
    """EF Application_Identification Gen1 (10 byte):
    tipo(1) versione(2) eventi/tipo(1) guasti/tipo(1) lunghezza attività(2)
    record veicoli(2) record luoghi(1)."""
    ev, fa = app[3], app[4]
    act, veh = struct.unpack(">HH", app[5:9])
    places = app[9]
    return {0x0501: 10, 0x0520: 143, 0x050E: 4, 0x0521: 53, 0x0502: 6 * ev * 24,
            0x0503: 2 * fa * 24, 0x0504: 4 + act, 0x0505: 2 + veh * 31,
            0x0506: 1 + places * 10, 0x0507: 19, 0x0508: 46, 0x0522: 56 * 5,
            0xC100: 194, 0xC108: 194}


def sizes_gen2(app: bytes) -> Dict[int, int]:
    """EF Application_Identification Gen2 (17 byte): come la Gen1 con i luoghi su 2
    byte, più record GNSS(2), condizioni specifiche(2), unità veicolo(2)."""
    ev, fa = app[3], app[4]
    act, veh, places, gnss, cond, vu = struct.unpack(">HHHHHH", app[5:17])
    return {0x0501: 17, 0x0520: 143, 0x050E: 4, 0x0521: 53, 0x0502: 11 * ev * 24,
            0x0503: 2 * fa * 24, 0x0504: 4 + act, 0x0505: 2 + veh * 48,
            0x0506: 2 + places * 21, 0x0507: 19, 0x0508: 46, 0x0522: 2 + cond * 5,
            0x0523: 2 + vu * 10, 0x0524: 2 + gnss * 18}


def sizes_v2(app_v2: bytes) -> Dict[int, int]:
    """EF Application_Identification_V2 (0525): frontiere(2), carico/scarico(2),
    tipi di carico(2)."""
    if len(app_v2) < 6:
        return {}
    border, load, ltype = struct.unpack(">HHH", app_v2[:6])
    return {0x0528: 2 + border * 17, 0x0529: 2 + load * 20, 0x0530: 2 + ltype * 5}


def certificate_length(head: bytes) -> Optional[int]:
    """Lunghezza totale di un certificato Gen2 (BER-TLV, tag 7F21) dai primi byte."""
    if len(head) < 4 or head[0] != 0x7F:
        return None
    ln = head[2]
    if ln < 0x80:
        return 3 + ln
    if ln == 0x81:
        return 4 + head[3]
    if ln == 0x82 and len(head) >= 5:
        return 5 + (head[3] << 8 | head[4])
    return None


def tlv(fid: int, appendix: int, data: bytes) -> bytes:
    """Blocco del file: FID(2) appendice(1) lunghezza(2) dati (App. 7 §3.4.2)."""
    return bytes([fid >> 8, fid & 0xFF, appendix, len(data) >> 8, len(data) & 0xFF]) + data


def clock_plausible(now: datetime, previous: Optional[datetime] = None) -> bool:
    """Si scrive la data di scarico solo se l'orologio del PC è credibile."""
    today = now.date()
    if not (BUILD_DATE <= today <= BUILD_DATE + timedelta(days=1825)):
        return False
    return previous is None or now >= previous - timedelta(minutes=5)


# ── Comandi (APDU) ────────────────────────────────────────────────────────────────

class _Card:
    def __init__(self, conn):
        self.conn = conn

    def tx(self, apdu: List[int]) -> Tuple[bytes, int]:
        try:
            resp, sw1, sw2 = self.conn.transmit(apdu)
        except CardConnectionException as e:
            raise CardReadError("La carta è stata estratta durante la lettura.") from e
        if sw1 == 0x61:                                   # T=0: dati da recuperare
            more, sw1, sw2 = self.conn.transmit([0x00, 0xC0, 0x00, 0x00, sw2])
            resp = list(resp) + list(more)
        return bytes(resp), (sw1 << 8) | sw2

    def select_aid(self, aid) -> int:
        return self.tx([0x00, 0xA4, 0x04, 0x0C, len(aid)] + aid)[1]

    def select_ef(self, fid: int) -> int:
        return self.tx([0x00, 0xA4, 0x02, 0x0C, 0x02, fid >> 8, fid & 0xFF])[1]

    def read(self, offset: int, le: int) -> Tuple[bytes, int]:
        data, sw = self.tx([0x00, 0xB0, (offset >> 8) & 0x7F, offset & 0xFF, le])
        if sw >> 8 == 0x6C:                               # lunghezza giusta indicata
            data, sw = self.tx([0x00, 0xB0, (offset >> 8) & 0x7F, offset & 0xFF, sw & 0xFF])
        return data, sw

    def read_exact(self, fid: int, size: int) -> bytes:
        out = bytearray()
        while len(out) < size:
            le = min(CHUNK, size - len(out))
            data, sw = self.read(len(out), le)
            if sw not in (0x9000, 0x6282) or not data:
                raise CardReadError(f"EF {fid:04X} ({EF_NAMES.get(fid, '?')}): lettura "
                                    f"interrotta a {len(out)}/{size} byte, SW={sw:04X}")
            out += data
            if sw == 0x6282:
                break
        if len(out) < size:
            raise CardReadError(f"EF {fid:04X} ({EF_NAMES.get(fid, '?')}): {len(out)} "
                                f"byte invece di {size}")
        return bytes(out[:size])

    def read_to_end(self, fid: int, limit: int = 4096) -> bytes:
        """EF di lunghezza non calcolabile: legge fino alla fine del file. Se la carta
        rifiuta la lunghezza chiesta (6700) si ritenta con Le=00 ("quanto c'è")."""
        out = bytearray()
        while len(out) < limit:
            data, sw = self.read(len(out), CHUNK)
            if sw == 0x6700:
                data, sw = self.read(len(out), 0x00)
            if data:
                out += data
            if sw != 0x9000 or not data or len(data) < CHUNK:
                break
        return bytes(out)

    def hash_file(self) -> bool:
        return self.tx([0x80, 0x2A, 0x90, 0x00])[1] == 0x9000

    def signature(self, gen: str) -> Optional[bytes]:
        """PSO: COMPUTE DIGITAL SIGNATURE. Gen1: RSA 128 byte. Gen2: ECDSA, la carta
        vuole la lunghezza esatta (64/96/128 byte secondo la curva; Le=00 → 6700)."""
        for le in ((0x80,) if gen == "G1" else (0x40, 0x60, 0x80, 0x00)):
            data, sw = self.tx([0x00, 0x2A, 0x9E, 0x9A, le])
            if sw >> 8 == 0x6C:
                data, sw = self.tx([0x00, 0x2A, 0x9E, 0x9A, sw & 0xFF])
            if sw == 0x9000 and data:
                return data
            if sw != 0x6700:
                break
        return None

    def update(self, data: bytes) -> int:
        return self.tx([0x00, 0xD6, 0x00, 0x00, len(data)] + list(data))[1]


# ── Lettura ──────────────────────────────────────────────────────────────────────

def _identity(ef_0520: bytes) -> str:
    """ "COGNOME Nome · ****1234 · valida fino al gg/mm/aaaa" (numero carta mascherato)."""
    from models.parser import _decode_identification
    drv = _decode_identification(ef_0520)
    return (f"{drv.surname} {drv.firstname.title()} · ****{drv.card_number[-4:]} · "
            f"{drv.expiry_date}")


def _read_section(card: _Card, gen: str, appendix: int, progress) -> Tuple[List[bytes], Dict[int, bytes], List[str]]:
    """Legge gli EF di un'applicazione. Ritorna (blocchi, dati per FID, avvisi)."""
    order = GEN1_ORDER if gen == "G1" else GEN2_ORDER
    blocks: List[bytes] = []
    data: Dict[int, bytes] = {}
    warnings: List[str] = []
    sizes: Dict[int, int] = {}
    missing: List[str] = []

    for fid in order:
        name = EF_NAMES.get(fid, f"{fid:04X}")
        progress(f"{gen} · {name}")
        sw = card.select_ef(fid)
        if sw != 0x9000:
            if fid in MANDATORY[gen]:
                missing.append(f"{fid:04X} ({name}) SW={sw:04X}")
            continue
        signed = fid not in CERTIFICATES
        hashed = card.hash_file() if signed else False

        if fid == 0x0501:
            head = card.read_exact(fid, 10 if gen == "G1" else 17)
            card_type = head[0]
            if card_type != 1:
                kind = CARD_TYPES.get(card_type, f"tipo {card_type}")
                raise CardReadError(f"Questa non è una carta conducente (carta {kind}).")
            sizes = sizes_gen1(head) if gen == "G1" else sizes_gen2(head)
            ef = head
        elif fid in CERTIFICATES and gen == "G2":
            head, _ = card.read(0, 5)
            total = certificate_length(head)
            # intestazione illeggibile (es. certificato di collegamento vuoto, tutto a
            # zero): si copia l'EF com'è, come fanno i lettori ufficiali
            ef = card.read_exact(fid, total) if total else card.read_to_end(fid, 400)
        elif fid in sizes:
            ef = card.read_exact(fid, sizes[fid])
        else:
            ef = card.read_to_end(fid)
            if fid == 0x0525:
                sizes.update(sizes_v2(ef))
        if not ef:
            if fid in MANDATORY[gen]:
                missing.append(f"{fid:04X} ({name}) vuoto")
            continue

        data[fid] = ef
        blocks.append(tlv(fid, appendix, ef))
        if fid == 0x0520 and not PROGRESS.get("identity"):
            PROGRESS["identity"] = _identity(ef)
        if signed:
            sig = card.signature(gen) if hashed else None
            if sig:
                blocks.append(tlv(fid, appendix + 1, sig))
            else:
                warnings.append(f"firma non disponibile per {gen} {fid:04X}")

    if missing:
        raise CardReadError("Lettura incompleta, il file non è stato salvato. "
                            f"Mancano ({gen}): " + ", ".join(missing))
    return blocks, data, warnings


def _stamp_download(card: _Card, gens: List[str], previous: List[Optional[datetime]]) -> str:
    """Scrive l'ora attuale (UTC) in EF Card_Download di ogni applicazione."""
    now = datetime.now(timezone.utc)
    prev = max((p for p in previous if p), default=None)
    if not clock_plausible(now, prev):
        return ("Data di scarico NON scritta sulla carta: l'orologio del computer non "
                "sembra corretto.")
    stamp = struct.pack(">I", int(now.timestamp()))
    failed = []
    for gen in gens:
        sw = card.select_aid(AID_GEN1 if gen == "G1" else AID_GEN2)
        if sw == 0x9000:
            sw = card.select_ef(0x050E)
        if sw == 0x9000:
            sw = card.update(stamp)
        if sw != 0x9000:
            failed.append(f"{gen} SW={sw:04X}")
    if failed:
        return "Data di scarico non scritta sulla carta (" + ", ".join(failed) + ")."
    return STAMP_OK


def list_readers() -> List[str]:
    if not PYSCARD_OK:
        return []
    try:
        return [str(r) for r in sc_readers()]
    except Exception:
        return []


def get_status() -> dict:
    if not PYSCARD_OK:
        return {"available": False, "readers": [], "error": "pyscard non installato"}
    try:
        rds = sc_readers()
        out = {"available": len(rds) > 0, "readers": [], "error": None}
        for r in rds:
            conn = r.createConnection()
            try:
                conn.connect()
                atr = toHexString(conn.getATR())
                conn.disconnect()
                out["readers"].append({"name": str(r), "card": True, "atr": atr})
            except NoCardException:
                out["readers"].append({"name": str(r), "card": False})
            except Exception as e:
                out["readers"].append({"name": str(r), "card": False, "error": str(e)})
        return out
    except NoReadersException:
        return {"available": False, "readers": [], "error": "Nessun lettore collegato"}
    except Exception as e:
        return {"available": False, "readers": [], "error": str(e)}


def read_card(reader_name: str, progress_cb=None, timeout_s: int = 60,
              write_stamp: bool = False) -> bytes:
    """
    Scarica la carta conducente e ritorna il file .DDD (sequenza di blocchi TLV).

    write_stamp: dopo la lettura scrive la data di scarico sulla carta (impostazione
    "Timestamp della carta"); il file letto contiene ancora la data precedente.
    progress_cb(passo, totale, messaggio): avanzamento per l'interfaccia.
    Solleva CardReadError se la carta non è una carta conducente o se manca un EF
    obbligatorio: in quel caso non c'è nessun file da salvare.
    """
    if not PYSCARD_OK:
        raise RuntimeError("pyscard non installato. Esegui: pip install pyscard")

    reader = next((r for r in sc_readers() if str(r) == reader_name), None)
    if not reader:
        raise RuntimeError(f"Lettore non trovato: {reader_name}")
    conn = reader.createConnection()

    deadline = time.time() + timeout_s
    while True:
        try:
            conn.connect()
            break
        except NoCardException:
            if time.time() > deadline:
                raise RuntimeError("Nessuna carta inserita entro il timeout")
            time.sleep(0.5)

    card = _Card(conn)
    total = 3 + len(GEN1_ORDER) + len(GEN2_ORDER)
    step = [0]

    def progress(msg: str):
        step[0] += 1
        PROGRESS.update(step=min(step[0], total), total=total, text=msg)
        if progress_cb:
            progress_cb(min(step[0], total), total, msg)

    LAST_READ.clear()
    PROGRESS.update(active=True, step=0, total=total, text="", identity="")
    try:
        blocks: List[bytes] = []
        # ── MF: file non firmati ──────────────────────────────────────────────
        for fid, size in ((0x0002, 25), (0x0005, 8), (0x2F00, None)):
            progress(f"MF · {EF_NAMES[fid]}")
            if card.select_ef(fid) != 0x9000:
                if fid != 0x2F00:
                    raise CardReadError("Questa non sembra una carta tachigrafica "
                                        f"(EF {fid:04X} assente).")
                continue
            ef = card.read_exact(fid, size) if size else card.read_to_end(fid, 256)
            if ef:
                blocks.append(tlv(fid, 0, ef))

        # ── Applicazione Gen1 (sempre presente) ──────────────────────────────
        if card.select_aid(AID_GEN1) != 0x9000:
            raise CardReadError("Applicazione tachigrafica non trovata sulla carta.")
        b1, d1, warnings = _read_section(card, "G1", 0, progress)
        blocks += b1
        gens = ["G1"]
        downloads = [d1.get(0x050E)]

        # ── Applicazione Gen2 (carte di seconda generazione) ─────────────────
        if card.select_aid(AID_GEN2) == 0x9000:
            b2, d2, w2 = _read_section(card, "G2", 2, progress)
            blocks += b2
            warnings += w2
            gens.append("G2")
            downloads.append(d2.get(0x050E))
            ident = d2.get(0x0520) or d1.get(0x0520)
        else:
            ident = d1.get(0x0520)

        raw = b"".join(blocks)
        LAST_READ.update({"generation": gens[-1], "warnings": warnings, "size": len(raw)})
        if ident:
            LAST_READ["identity"] = _identity(ident)

        # ── Data di scarico sulla carta (dopo aver letto il file) ────────────
        if write_stamp:
            previous = []
            for d in downloads:
                ts = struct.unpack(">I", d)[0] if d and len(d) == 4 else 0
                previous.append(datetime.fromtimestamp(ts, timezone.utc) if ts else None)
            msg = _stamp_download(card, gens, previous)
            LAST_READ["stamp"] = msg
            LAST_READ["stamp_ok"] = msg == STAMP_OK
        return raw
    finally:
        PROGRESS["active"] = False
        try:
            conn.disconnect()
        except Exception:
            pass

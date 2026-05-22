"""
models/card_data.py
===================
Definisce le strutture dati (dataclass) del dominio TachoVision Pro.

Un "modello" (in senso MVC) rappresenta i dati dell'applicazione.
Questo file non conosce né la UI (Dash) né il database: contiene solo
la definizione di come sono fatti i dati e poche proprietà derivate.

Le "dataclass" Python sono classi speciali create con il decoratore @dataclass.
Generano automaticamente __init__, __repr__ e __eq__ dai campi dichiarati,
evitando di scrivere boilerplate ripetitivo.

Gerarchia delle strutture:
  CardData          ← radice: contiene tutto il contenuto della carta
    DriverInfo      ← informazioni sul conducente
    DayActivity     ← attività di un singolo giorno
      ActivityChange  ← singola variazione di attività (es. inizio Guida)
    VehicleSession  ← singolo inserimento carta in un veicolo
    Vehicle         ← veicolo unico (aggregato dalle sessioni)
    Place           ← luogo registrato (inizio/fine attività in un paese)
    GNSSRecord      ← waypoint GPS (solo carte Gen2)
    CardEvent       ← evento anomalo registrato dalla carta
    CardFault       ← malfunzionamento registrato dalla carta
    SpecificCondition ← condizione speciale (es. traghetto, ecc.)
    RestPeriod      ← periodo di riposo analizzato
    WeekSummary     ← riepilogo statistico di una settimana
    Violation       ← infrazione al Reg. CE 561/2006
"""

from __future__ import annotations
# Permette di usare le annotazioni di tipo come stringhe anche in Python 3.8

from dataclasses import dataclass, field
# @dataclass: decoratore che genera automaticamente i metodi __init__, __repr__, ecc.
# field(): usato per valori di default complessi (liste, dizionari) che non
#   possono essere scritti direttamente come default (es. changes=[] causerebbe
#   un bug classico in Python perché la lista sarebbe condivisa tra tutte le istanze).

from typing import List, Optional
# List[T]: tipo "lista di T" (es. List[ActivityChange] = lista di ActivityChange)
# Optional[T]: tipo "T oppure None" (campo che può non essere valorizzato)


@dataclass
class ActivityChange:
    """
    Rappresenta un singolo cambio di attività all'interno di un giorno.

    Nel file DDD, ogni giorno è registrato come una sequenza di "ACI"
    (ActivityChangeInfo): ogni ACI marca il momento in cui il conducente
    passa da un'attività all'altra (es. da Riposo a Guida).

    Campi:
        time:     minuti dalla mezzanotte UTC (0 = 00:00, 60 = 01:00, 1439 = 23:59)
        activity: tipo di attività (una delle 4 categorie EU)
        manual:   True se l'orario è stato inserito manualmente dal conducente
    """
    time: int           # minuti dalla mezzanotte (0-1439)
    activity: str       # "Guida" | "Lavoro" | "Disponibilità" | "Riposo"
    manual: bool = False  # False = registrazione automatica del tachigrafo


@dataclass
class DayActivity:
    """
    Record di attività per un singolo giorno.

    Contiene tutti i cambi di attività del giorno (lista 'changes')
    e alcuni dati aggregati (distanza percorsa, ecc.).

    Formato date:
        date         → "YYYY-MM-DD" (formato ISO 8601, usato per ordinamento e confronto)
        date_display → "DD/MM/YYYY" (formato italiano, usato per la visualizzazione)
    """
    date: str           # "YYYY-MM-DD" — per ordinamento e confronto
    date_display: str   # "DD/MM/YYYY" — per visualizzazione all'utente
    distance_km: float  # km percorsi nel giorno (dai byte ACI del buffer 0x0504)
    changes: List[ActivityChange] = field(default_factory=list)
    # field(default_factory=list) crea una nuova lista vuota per ogni istanza
    # (evita il bug Python dove tutti condividono la stessa lista)

    def segments(self) -> List[tuple]:
        """
        Calcola i segmenti temporali del giorno da una lista di cambi.

        Ogni "segmento" è un intervallo di tempo con una singola attività:
        (minuto_inizio, minuto_fine, nome_attività).

        Esempio:
            changes = [ActivityChange(0, "Riposo"), ActivityChange(360, "Guida"), ActivityChange(600, "Riposo")]
            → segments() = [(0, 360, "Riposo"), (360, 600, "Guida"), (600, 1440, "Riposo")]
        """
        # Ordina i cambi per orario crescente (sicurezza: nel DDD sono già ordinati)
        ch = sorted(self.changes, key=lambda c: c.time)
        segs = []
        for i, c in enumerate(ch):
            # Il segmento finisce quando inizia il segmento successivo,
            # oppure alla fine del giorno (1440 minuti = mezzanotte)
            t1 = ch[i + 1].time if i + 1 < len(ch) else 1440
            if t1 > c.time:   # scarta segmenti di durata zero o negativa
                segs.append((c.time, t1, c.activity))
        return segs

    def minutes_of(self, activity: str) -> int:
        """
        Restituisce il totale di minuti dedicati a una specifica attività nel giorno.

        Esempio:
            day.minutes_of("Guida")  →  480  (8 ore di guida)
        """
        # sum(...) somma le durate (e-s) di tutti i segmenti dell'attività richiesta
        return sum(e - s for s, e, a in self.segments() if a == activity)


@dataclass
class VehicleSession:
    """
    Rappresenta una singola sessione veicolo: un inserimento carta nel tachigrafo (VU).

    Una sessione inizia quando il conducente inserisce la carta nel VU
    (Vehicle Unit = unità tachigrafo a bordo del veicolo) e finisce quando
    la rimuove. Durante una sessione, il tachigrafo registra tutte le attività.

    Campi timestamp:
        first_use_utc / last_use_utc → timestamp Unix in secondi (precisione: 1 secondo)
        first_use / last_use         → stringhe "DD/MM/YYYY" (solo data, per display)
    """
    vrn: str            # targa del veicolo (Vehicle Registration Number, es. "GV824TP")
    first_use: str      # "DD/MM/YYYY" — data inserimento carta (visualizzazione)
    last_use: str       # "DD/MM/YYYY" — data rimozione carta (visualizzazione)
    odo_begin_km: int   # lettura odometro al momento dell'inserimento carta (km)
    odo_end_km: int     # lettura odometro al momento della rimozione carta (km)
    first_use_utc: int = 0   # Unix UTC timestamp inserimento carta (secondi da 1970)
    last_use_utc: int = 0    # Unix UTC timestamp disinserimento carta (secondi da 1970)

    @property
    def km(self) -> int:
        """
        Calcola i km percorsi nella sessione (differenza odometri).

        Ritorna 0 se la differenza è negativa (errore dati) o superiore a 5000 km
        (valore impossibile per una singola sessione = dato corrotto).
        """
        delta = self.odo_end_km - self.odo_begin_km
        # Sanity check: un autotrasportatore non percorre mai >5000 km in una sessione
        return delta if 0 <= delta <= 5000 else 0


@dataclass
class GNSSRecord:
    """
    Waypoint GPS registrato dal tachigrafo digitale Gen2.

    I tachigrafi di seconda generazione (Reg. 2016/799) possono memorizzare
    coordinate GPS periodiche nel file EF_GNSS_ACCUMULATED_DRIVING.

    Campi:
        accuracy_dm: precisione in decimetri (10 dm = 1 metro)
        odometer_km: lettura odometro al momento del waypoint
    """
    timestamp: str          # "DD/MM/YYYY HH:MM" — data e ora del waypoint
    date: str               # "YYYY-MM-DD" — solo data (per raggruppamento)
    lat: float              # latitudine in gradi decimali (positivo = Nord)
    lon: float              # longitudine in gradi decimali (positivo = Est)
    accuracy_dm: int        # precisione in decimetri (0 = non disponibile)
    odometer_km: int        # km odometro al momento del waypoint


@dataclass
class Vehicle:
    """
    Rappresenta un veicolo unico usato dal conducente.

    Viene derivato dall'aggregazione di più VehicleSession con la stessa targa:
    si prende la prima e l'ultima data d'uso tra tutte le sessioni.
    """
    vrn: str            # targa del veicolo
    first_use: str      # "DD/MM/YYYY" — prima volta che il conducente ha usato questo veicolo
    last_use: str       # "DD/MM/YYYY" — ultima volta
    vin: str = ""       # VIN = Vehicle Identification Number (disponibile solo in Gen2)
    total_km: int = 0   # km totali percorsi con questo veicolo (somma di tutte le sessioni)


@dataclass
class Place:
    """
    Luogo registrato dal tachigrafo (inizio o fine attività in un paese).

    Secondo il Reg. 561/2006, il tachigrafo deve registrare il paese
    in cui si trovava il conducente all'inizio e alla fine di ogni giornata.

    Campi:
        country:    codice ISO 3166-1 alpha-2 (es. "IT", "DE", "FR")
        entry_type: "Inizio" = prima attività del giorno, "Fine" = ultima attività
        region:     codice numerico della regione/nazione (byte RegionNumeric della spec EU)
        gnss_*:     coordinate GPS opzionali (solo se il tachigrafo ha GPS)
    """
    datetime: str           # "DD/MM/YYYY HH:MM" — data e ora del record
    date: str               # "YYYY-MM-DD" — solo data
    country: str            # codice ISO paese (es. "IT")
    entry_type: str         # "Inizio" | "Fine"
    odometer_km: int        # km odometro al momento del record
    region: int = 0         # RegionNumeric (0 = non disponibile)
    gnss_lat: Optional[float] = None   # latitudine GPS (None = non disponibile)
    gnss_lon: Optional[float] = None   # longitudine GPS
    gnss_accuracy: int = 0  # precisione GPS in decimetri (0 = N/D, 255 = non valido)


@dataclass
class CardEvent:
    """
    Evento anomalo registrato sulla carta tachigrafo (EF_EVENTS_DATA).

    Gli eventi includono situazioni come: guida senza carta inserita,
    conflitto dati, ecc. Ogni evento ha un tipo codificato e un intervallo temporale.
    """
    begin_time: str         # "DD/MM/YYYY HH:MM" — inizio evento
    end_time: str           # "DD/MM/YYYY HH:MM" — fine evento (vuoto se puntuale)
    event_type_code: int    # codice numerico del tipo evento (0x01-0x0D per la spec EU)
    event_type: str         # descrizione human-readable (es. "Guida senza carta")
    vehicle: str            # targa del veicolo coinvolto (vuoto se non applicabile)


@dataclass
class CardFault:
    """
    Malfunzionamento registrato sulla carta tachigrafo (EF_FAULTS_DATA).

    I fault rappresentano problemi hardware/software del tachigrafo o della carta
    (es. "Problema con il sensore di moto"). Distinti dagli eventi (comportamentali).
    """
    begin_time: str
    end_time: str
    fault_type_code: int    # codice numerico (0x10-0x15 per la spec EU)
    fault_type: str         # descrizione human-readable (es. "Fault strumento VU")
    vehicle: str            # targa del veicolo (se disponibile)


@dataclass
class SpecificCondition:
    """
    Condizione specifica registrata sulla carta (EF_SPECIFIC_CONDITIONS).

    Le "condizioni specifiche" sono circostanze particolari che il conducente
    può registrare manualmente (es. attraversamento in traghetto,
    guida fuori EU dove le regole sono diverse, ecc.).
    """
    entry_time: str         # "DD/MM/YYYY HH:MM" — momento della registrazione
    condition_type: str     # descrizione human-readable della condizione


@dataclass
class DriverInfo:
    """
    Informazioni identificative del conducente, lette dal tachigrafo.

    Queste informazioni vengono estratte dall'EF_IDENTIFICATION del file DDD.
    Alcuni campi possono essere vuoti se la carta è Gen1 (meno dati) o
    se il byte corrispondente non è stato ancora valorizzato.
    """
    surname: str = ""           # cognome
    firstname: str = ""         # nome
    birth_date: str = ""        # data di nascita "DD/MM/YYYY"
    language: str = ""          # lingua preferita (codice ISO 639-1, es. "it")
    card_number: str = ""       # numero carta tachigrafica (es. "I100000333422003")
    issuing_nation: str = ""    # codice nazione che ha rilasciato la carta (es. "IT")
    issuing_authority: str = "" # ente che ha rilasciato la carta (es. "CCIAA DI BARI")
    issue_date: str = ""        # data emissione carta "DD/MM/YYYY"
    validity_begin: str = ""    # data inizio validità "DD/MM/YYYY"
    expiry_date: str = ""       # data scadenza carta "DD/MM/YYYY"
    licence_number: str = ""    # numero patente di guida
    licence_authority: str = "" # autorità che ha rilasciato la patente
    generation: str = "G1"      # "G1" o "G2 (v1)" — generazione del tachigrafo
    renewal_index: str = "—"    # quante volte la carta è stata rinnovata
    replacement_index: str = "—" # quante volte la carta è stata sostituita
    last_download: str = ""     # data dell'ultimo scarico dati "DD/MM/YYYY HH:MM"
    prev_download: str = ""     # data del penultimo scarico
    file_size: str = ""         # dimensione del file DDD in byte
    filename: str = ""          # nome del file DDD caricato

    @property
    def full_name(self) -> str:
        """Restituisce nome completo "Nome Cognome", o "—" se entrambi vuoti."""
        return f"{self.firstname} {self.surname}".strip() or "—"


@dataclass
class RestPeriod:
    """
    Periodo di riposo analizzato (calcolato da analytics.py).

    I periodi di riposo vengono identificati esaminando i segmenti "Riposo"
    nelle attività giornaliere. Vengono classificati secondo il Reg. 561/2006:
    - Regolare: almeno 11 ore consecutive
    - Ridotto: almeno 9 ore (max 3 volte a settimana)
    - Settimanale: almeno 45 ore
    - Breve: pausa di 45 minuti (o 15+30) durante la guida
    """
    date: str           # "YYYY-MM-DD" — giorno in cui cade il riposo
    start: str          # "DD/MM/YYYY HH:MM" — inizio del periodo di riposo
    end: str            # "DD/MM/YYYY HH:MM" — fine del periodo di riposo
    duration_min: int   # durata in minuti
    duration_str: str   # "Xh YY" — durata in formato leggibile
    kind: str           # "Regolare" | "Ridotto" | "Settimanale" | "Breve"


@dataclass
class WeekSummary:
    """
    Riepilogo statistico di una settimana lavorativa.

    Contiene i totali di ciascuna attività (in minuti) per tutta la settimana,
    più flags che indicano se sono stati superati i limiti del Reg. 561/2006.
    """
    week_start: str     # "YYYY-MM-DD" — lunedì della settimana
    week_label: str     # "DD/MM/YYYY" — per visualizzazione
    days: int           # numero di giorni attivi nella settimana
    guida_min: int      # minuti totali di Guida
    lavoro_min: int     # minuti totali di Lavoro (non guida)
    disponibilita_min: int  # minuti di Disponibilità
    riposo_min: int     # minuti di Riposo
    km: float           # km totali della settimana

    def fmt(self, minutes: int) -> str:
        """Converte minuti in stringa "Xh YY" (es. 495 → "8h15")."""
        h, m = divmod(minutes, 60)   # divmod(495, 60) = (8, 15)
        return f"{h}h{m:02d}"        # :02d = almeno 2 cifre, con zero iniziale

    # Proprietà calcolate: si usano come attributi ma eseguono del calcolo
    @property
    def guida(self):        return self.fmt(self.guida_min)
    @property
    def lavoro(self):       return self.fmt(self.lavoro_min)
    @property
    def disponibilita(self):return self.fmt(self.disponibilita_min)
    @property
    def riposo(self):       return self.fmt(self.riposo_min)

    @property
    def totale_lavoro_min(self):
        """Totale lavoro = guida + lavoro + disponibilità (tutto tranne riposo)."""
        return self.guida_min + self.lavoro_min + self.disponibilita_min

    @property
    def totale_lavoro(self): return self.fmt(self.totale_lavoro_min)

    @property
    def over56h(self) -> bool:
        """True se la guida settimanale supera 56 ore (limite Reg. 561/2006 Art. 6)."""
        return self.guida_min > 3360   # 56 ore * 60 minuti = 3360 minuti

    @property
    def over48h_work(self) -> bool:
        """True se il totale lavoro supera 48 ore (Dir. 2002/15/CE)."""
        return self.totale_lavoro_min > 2880   # 48 * 60 = 2880


@dataclass
class Violation:
    """
    Infrazione al Regolamento CE 561/2006 o alla Direttiva 2002/15/CE.

    Le infrazioni vengono rilevate da models/violations.py analizzando
    le attività del conducente e confrontandole con i limiti normativi.

    Livelli di severità:
        Molto Grave → sanzione massima, sospensione attività
        Grave       → sanzione alta
        Lieve       → sanzione ridotta
    """
    date: str           # "YYYY-MM-DD"
    date_display: str   # "DD/MM/YYYY" — per visualizzazione
    code: str           # codice infrazione (es. "DayDriving", "ContinuousDriving")
    description: str    # titolo breve dell'infrazione
    detail: str         # descrizione estesa con articolo violato
    severity: str       # "Molto Grave" | "Grave" | "Lieve"
    value_min: int = 0  # valore rilevato (in minuti)
    limit_min: int = 0  # limite normativo (in minuti)
    excess_min: int = 0 # eccesso rispetto al limite (in minuti)

    def _fmt(self, m: int) -> str:
        """Formatta minuti in "Xh YY" o "Ymin" se inferiore a 1 ora."""
        h, mn = divmod(abs(m), 60)
        return f"{h}h{mn:02d}" if h else f"{mn}min"

    # Proprietà per la visualizzazione delle durate in formato leggibile
    @property
    def value_h(self):  return self._fmt(self.value_min)   # es. "10h30"
    @property
    def limit_h(self):  return self._fmt(self.limit_min)   # es. "9h00"
    @property
    def excess_h(self): return self._fmt(self.excess_min)  # es. "1h30"

    @property
    def icon(self) -> str:
        """Emoji corrispondente alla severità."""
        return {"Molto Grave": "🚨", "Grave": "🔴", "Lieve": "🟡"}.get(self.severity, "⚠️")

    @property
    def color(self) -> str:
        """Colore esadecimale corrispondente alla severità (per la UI)."""
        return {"Molto Grave": "#DC2626", "Grave": "#EF4444",
                "Lieve": "#F59E0B"}.get(self.severity, "#888")

    def to_dict(self) -> dict:
        """Serializza in dizionario (usato per passare dati alla UI e al PDF)."""
        return {k: getattr(self, k) for k in
                ("date","date_display","code","description","detail",
                 "severity","icon","color","value_h","limit_h","excess_h")}


@dataclass
class CardData:
    """
    Modello principale: rappresenta tutto il contenuto di una carta tachigrafica.

    È il "contenitore radice" che viene passato da un modulo all'altro.
    Dopo il parsing del file DDD, tutte le informazioni estratte vengono
    memorizzate qui. Poi viene serializzato in JSON per il dcc.Store di Dash.

    Ciclo di vita:
        1. parse_ddd(raw_bytes) → crea un CardData dal file binario
        2. enrich(cd) → aggiunge statistiche (rest_periods, weekly_summary, ecc.)
        3. cd.to_dict() → serializza per dcc.Store (JSON nel browser)
        4. CardData.from_dict(d) → deserializza dallo Store per i callback
    """
    driver: DriverInfo = field(default_factory=DriverInfo)
    activities: List[DayActivity] = field(default_factory=list)
    vehicles: List[Vehicle] = field(default_factory=list)
    vehicle_sessions: List[VehicleSession] = field(default_factory=list)
    places: List[Place] = field(default_factory=list)
    gnss_records: List[GNSSRecord] = field(default_factory=list)
    events: List[CardEvent] = field(default_factory=list)
    faults: List[CardFault] = field(default_factory=list)
    specific_conditions: List[SpecificCondition] = field(default_factory=list)
    rest_periods: List[RestPeriod] = field(default_factory=list)
    weekly_summary: List[WeekSummary] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)   # errori di parsing, mostrati all'utente
    demo: bool = False   # True se i dati sono sintetici (modalità demo)

    def to_dict(self) -> dict:
        """
        Serializza il CardData in un dizionario Python JSON-compatibile.

        Necessario per salvare i dati in dcc.Store (che usa JSON internamente).
        dcc.Store accetta solo tipi base: str, int, float, bool, list, dict.
        Le dataclass Python non sono JSON-serializzabili di default.

        Usa dataclasses.asdict() per la conversione ricorsiva:
        converte ogni dataclass in dict, ogni lista in lista, ecc.
        """
        import dataclasses

        def _conv(obj):
            # Se è una dataclass, converte ogni suo campo ricorsivamente
            if dataclasses.is_dataclass(obj):
                return {k: _conv(v) for k, v in dataclasses.asdict(obj).items()}
            # Se è una lista, converte ogni elemento ricorsivamente
            if isinstance(obj, list):
                return [_conv(i) for i in obj]
            # Altrimenti (str, int, float, bool, None) ritorna direttamente
            return obj

        return _conv(self)

    @staticmethod
    def from_dict(d: dict) -> "CardData":
        """
        Deserializza un CardData da un dizionario Python (da dcc.Store).

        Il metodo 'statico' (@staticmethod) può essere chiamato senza un'istanza:
        CardData.from_dict(raw_dict) invece di istanza.from_dict(raw_dict).

        Ricostruisce manualmente ogni oggetto della gerarchia perché il JSON
        non contiene informazioni sul tipo Python delle classi originali.
        """
        if not d:
            # Se il dizionario è vuoto o None, restituisce un CardData vuoto
            return CardData()

        # Ricostruisce DriverInfo: solo i campi riconosciuti vengono passati
        # (evita errori se il formato del dizionario cambia tra versioni)
        cd = CardData(
            driver=DriverInfo(**{k: v for k, v in d.get("driver", {}).items()
                                 if k in DriverInfo.__dataclass_fields__}),
            errors=d.get("errors", []),
            demo=d.get("demo", False),
        )

        # Ricostruisce la lista delle attività giornaliere
        for a in d.get("activities", []):
            # Prima ricostruisce ogni ActivityChange dal suo dict
            changes = [ActivityChange(**c) for c in a.get("changes", [])]
            cd.activities.append(DayActivity(
                date=a["date"], date_display=a["date_display"],
                distance_km=a["distance_km"], changes=changes,
            ))

        # Ricostruisce i veicoli (aggregati)
        for v in d.get("vehicles", []):
            cd.vehicles.append(Vehicle(
                vrn=v["vrn"], first_use=v["first_use"], last_use=v["last_use"],
                vin=v.get("vin", ""), total_km=v.get("total_km", 0),
            ))

        # Ricostruisce le sessioni veicolo (con **vs si passano tutti i campi del dict)
        for vs in d.get("vehicle_sessions", []):
            cd.vehicle_sessions.append(VehicleSession(**vs))

        # Ricostruisce i waypoint GNSS
        for g in d.get("gnss_records", []):
            cd.gnss_records.append(GNSSRecord(**g))

        # Ricostruisce i luoghi (con gestione dei campi opzionali via .get())
        for p in d.get("places", []):
            cd.places.append(Place(
                datetime=p["datetime"], date=p["date"],
                country=p["country"], entry_type=p["entry_type"],
                odometer_km=p["odometer_km"],
                region=p.get("region", 0),        # 0 se non presente nel dict
                gnss_lat=p.get("gnss_lat"),        # None se non presente
                gnss_lon=p.get("gnss_lon"),
                gnss_accuracy=p.get("gnss_accuracy", 0),
            ))

        # Ricostruisce eventi e fault
        for e in d.get("events", []):
            cd.events.append(CardEvent(**e))
        for f in d.get("faults", []):
            cd.faults.append(CardFault(**f))

        # Ricostruisce condizioni speciali
        for sc in d.get("specific_conditions", []):
            cd.specific_conditions.append(SpecificCondition(**sc))

        # Ricostruisce periodi di riposo e riepiloghi settimanali
        for r in d.get("rest_periods", []):
            cd.rest_periods.append(RestPeriod(**r))
        for w in d.get("weekly_summary", []):
            cd.weekly_summary.append(WeekSummary(**w))

        return cd

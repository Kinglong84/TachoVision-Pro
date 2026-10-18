"""
models/violations.py
=====================
Motore di rilevamento infrazioni al Reg. (CE) 561/2006 e alla Direttiva 2002/15/CE.

Regole e soglie del motore infrazioni
(Reg. CE 561/2006, Dir. 2002/15/CE):
  - codici infrazione e categoria AETR / WTD / TACHO / OTHER
  - gravità MI / SI / VSI / MSI con le soglie dell'Allegato I Reg. UE 2016/403
  - guida giornaliera calcolata tra due riposi (turno), non per giorno di calendario
  - orario di lavoro = Guida + Lavoro (+ pause < 15 min): la Disponibilità NON è lavoro
  - media 48h sul periodo di riferimento scelto nelle impostazioni
  - fascia notturna e opzioni delle impostazioni (models/settings.py)

Questo modulo è "pura logica di dominio": non dipende da Dash.

FLUSSO:
  detect_violations(activities, settings)
    Timeline (models/timeline.py) → riposi → turni
    → regole: guida continua, giornaliera, settimanale; riposi giornalieri e
      settimanali; orario settimanale, notturno, lavoro continuo
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from models.card_data import DayActivity, Violation
from models.settings import Settings, load_settings
from models.timeline import (_EPOCH, AVAIL, DRIVE, REST, SHORT_BREAK, WORK, Rest, Shift,
                             Timeline, build_shifts, classify_rests)

H = 60

# ── Gravità (Allegato I Reg. UE 2016/403) ────────────────────────────────────
MSI, VSI, SI, MI = "MSI", "VSI", "SI", "MI"
WARN = "W"
SEVERITIES = [MSI, VSI, SI, MI]

# Compatibilità con il codice esistente (stat-card e PDF)
SEV_VERY, SEV_HIGH, SEV_LOW = VSI, SI, MI

# Date normative (q10)
MOBILITY_PACKAGE = datetime(2020, 8, 20)      # Reg. UE 2020/1054
BUS_SPLIT_BREAK = datetime(2024, 5, 22)       # pause frazionate bus occasionali

# ── Testi delle infrazioni ───────────────────────────────────────────
DESCRIPTIONS = {
    "WeekDriving_one": "Superamento del periodo di guida settimanale",
    "WeekDriving_one_msi": "Superamento del 25% o più del periodo di guida settimanale",
    "WeekDriving_two": "Superamento del periodo di guida totale massimo durante 2 settimane consecutive",
    "WeekDriving_two_msi": "Superamento del 25% o più del periodo di guida totale massimo durante 2 settimane consecutive",
    "DayDriving_9": "Superamento del periodo di guida giornaliero di 9 ore in caso di mancata concessione dell'estensione a 10 ore",
    "DayDriving_9_msi": "Superamento del 50% o più del periodo di guida giornaliero di 9 ore, senza osservare una pausa o un periodo di riposo di almeno 4,5 ore",
    "DayDriving_10": "Superamento del periodo di guida giornaliero di 10 ore in caso di concessione dell'estensione",
    "DayDriving_10_msi": "Superamento del 50% o più del periodo di guida giornaliero di 10 ore, senza osservare una pausa o un periodo di riposo di almeno 4,5 ore",
    "ContinuousDriving": "Superamento di un periodo di guida ininterrotto di 4,5 ore prima di osservare una pausa",
    "NightDrivingBus": "Periodo di guida tra le 22:00 e le 6:00 superiore a 3 ore prima di osservare una pausa se vi siano più conducenti a bordo del veicolo",
    "Weekly_TooShort_45": "Periodo di riposo settimanale insufficiente poiché inferiore a 45 ore in caso di mancata concessione del periodo di riposo settimanale ridotto",
    "Weekly_TooShort_24": "Periodo di riposo settimanale ridotto insufficiente poiché inferiore a 24 ore",
    "Weekly_TooLate": "Superamento di sei periodi di 24 ore consecutivi successivamente al periodo di riposo settimanale",
    "Weekly_TooShort_Bus": "Periodo di riposo insufficiente settimanale usufruito dopo dodici periodi di 24 ore consecutivi",
    "Weekly_TooLate_Bus": "Superamento di dodici periodi di 24 ore consecutivi successivamente al periodo di riposo settimanale",
    "Rest_DailyNormal_Fine": "Periodo di riposo giornaliero insufficiente poiché inferiore a 11 ore in caso di mancata concessione del periodo di riposo giornaliero ridotto",
    "Rest_DailySplit_Fine": "Periodo di riposo giornaliero suddiviso insufficiente poiché inferiore a 3+9 ore",
    "Rest_DailyReduced_Fine": "Periodo di riposo giornaliero ridotto insufficiente poiché inferiore a 9 ore in caso di concessione della riduzione",
    "Rest_DailyStaff_Fine": "Periodo di riposo giornaliero insufficiente poiché inferiore a 9 ore in caso di multipresenza",
    "Mode_Incorrect_Use": "Uso scorretto del dispositivo di commutazione",
    "Missing_CountryCode": "Simbolo del paese non inserito nell'apparecchio di controllo",
    "Missing_CountryCode_Border": "Simbolo del paese non inserito nell'apparecchio di controllo (al valico di frontiera)",
    "Missing_ManualEntry": "Inserimento manuale mancante",
    "Rest45InVehicle": "Probabilmente ha trascorso in un veicolo un lungo periodo di riposo",
    "VehicleCheck": "Il veicolo non è stato ispezionato prima della partenza",
    "VirtualTravel": "Viaggio virtuale",
    "WeekWorking_48": "Superamento della durata massima settimanale della prestazione di lavoro fissata a 48 ore se è già stata sfruttata la possibilità di estenderla a 60 ore",
    "WeekWorking_60": "Superamento della durata massima settimanale della prestazione di lavoro fissata a 60 ore",
    "Working_IsNight_10": "Lavorare più di 10 ore al giorno, lavorando anche di notte.",
    "ContinuousWorking_6": "Riposo intermedio insufficiente per un periodo di lavoro compreso fra sei e nove ore",
    "ContinuousWorking_9": "Riposo intermedio insufficiente per un periodo di lavoro superiore a nove ore",
    "ContinuousWorking_6S": "Lavoro continuo per più di 6 ore",
    "Weekly_TooShort_International": "Mancato riposo compensativo per due periodi di riposo settimanale ridotti consecutivi",
    "FerryButtonInvalid": "Uso scorretto del commutatore traghetto/treno",
    "CardDownload_28": "La carta del conducente non è stata scaricata entro 28 giorni",
    "DataGap": "Dati mancanti tra i file scaricati",
}

# Gruppi della schermata "Filtro"
GROUPS = [
    ("Tempo Di Guida", ["DayDriving_9", "DayDriving_10", "ContinuousDriving",
                        "WeekDriving_one", "WeekDriving_two", "NightDrivingBus"]),
    ("Tempo di riposo", ["Rest_DailyNormal_Fine", "Rest_DailySplit_Fine",
                         "Rest_DailyReduced_Fine", "Rest_DailyStaff_Fine",
                         "Weekly_TooShort_45", "Weekly_TooShort_24",
                         "Weekly_TooShort_International", "Weekly_TooLate",
                         "Weekly_TooLate_Bus", "Weekly_TooShort_Bus", "Rest45InVehicle"]),
    ("Orario di lavoro", ["WeekWorking_48", "WeekWorking_60", "Working_IsNight_10",
                          "ContinuousWorking_6", "ContinuousWorking_9",
                          "ContinuousWorking_6S"]),
    ("Prefisso internazionale", ["Missing_CountryCode", "Missing_CountryCode_Border"]),
    ("Gestione del tachigrafo", ["Missing_ManualEntry", "VirtualTravel",
                                 "Mode_Incorrect_Use", "FerryButtonInvalid"]),
    ("Varie", ["VehicleCheck", "CardDownload_28"]),
]
ALL_CODES = [c for _, codes in GROUPS for c in codes]


def category(code: str) -> str:
    """AETR / WTD / TACHO / OTHER."""
    if code.startswith(("Week", "Day", "Continuous", "Night", "Weekly", "Rest_")):
        if code.startswith(("WeekWorking", "ContinuousWorking")):
            return "WTD"
        return "AETR"
    if code == "Working_IsNight_10":
        return "WTD"
    if code.startswith("Missing_CountryCode"):
        return "TACHO"
    return "OTHER"


def classify(code: str, value_min: int, no_msi: bool = False) -> Optional[str]:
    """
    Gravità di un'infrazione in base al valore misurato.
    value_min: minuti (per ContinuousWorking: minuti di pausa effettuati).
    Ritorna None se il valore non costituisce infrazione.
    """
    h = value_min / 60.0
    m = value_min

    def above(t_msi, t_vsi, t_si, t_mi):         # valore troppo alto
        if t_msi is not None and h >= t_msi:
            return MSI
        if h >= t_vsi:
            return VSI
        if h >= t_si:
            return SI
        if h > t_mi:
            return MI
        return None

    def below(t_vsi, t_si, t_mi):                 # valore troppo basso
        if h < t_vsi:
            return VSI
        if h < t_si:
            return SI
        if h < t_mi:
            return MI
        return None

    if code == "WeekDriving_one":
        return above(70, 65, 60, 56)
    if code == "WeekDriving_two":
        return above(112.5, 105, 100, 90)
    if code == "DayDriving_9":
        return above(None if no_msi else 13.5, 11, 10, 9)
    if code == "DayDriving_10":
        return above(None if no_msi else 15, 12, 11, 10)
    if code == "ContinuousDriving":
        return above(None, 6, 5, 4.5)
    if code == "NightDrivingBus":
        return VSI if h >= 4.5 else SI if h > 3 else None
    if code == "Weekly_TooShort_45":
        return below(36, 42, 45)
    if code == "Weekly_TooShort_24":
        return below(20, 22, 24)
    if code == "Weekly_TooLate":
        return above(None, 156, 147, 144)
    if code == "Weekly_TooShort_Bus":
        return below(65, 67, 69)
    if code == "Weekly_TooLate_Bus":
        return above(None, 300, 291, 288)
    if code == "Rest_DailyNormal_Fine":
        return below(8.5, 10, 11)
    if code in ("Rest_DailySplit_Fine", "Rest_DailyReduced_Fine", "Rest_DailyStaff_Fine"):
        return below(7, 8, 9)
    if code == "WeekWorking_48":
        return above(None, 60, 56, 48)
    if code == "WeekWorking_60":
        return above(None, 70, 65, 60)
    if code == "Working_IsNight_10":
        return above(None, 13, 11, 10)
    if code == "ContinuousWorking_6":
        return VSI if m <= 10 else SI if m <= 20 else MI if m < 30 else None
    if code == "ContinuousWorking_9":
        return VSI if m <= 20 else SI if m <= 30 else MI if m < 45 else None
    if code == "ContinuousWorking_6S":
        return SI
    return None


# Pesi di penalità (li.c) — usati per scegliere l'interpretazione migliore
PENALTY = {MI: 500, SI: 1000, VSI: 6000, MSI: 9000}


class _Ctx:
    """Contesto condiviso dalle regole: timeline, impostazioni, risultati."""

    def __init__(self, activities: List[DayActivity], settings: Settings, cd=None):
        self.s = settings
        self.cd = cd
        self.activities = activities
        # Regole nazionali (BASECOUNTRY 26 = Italia, 39 = Portogallo)
        self.italy = settings.basecountry == "IT"
        self.portugal = settings.basecountry == "PT"
        self.tl = Timeline(activities, settings.timezone)
        self.out: List[Violation] = []
        _mode_incorrect_use(self)          # va prima: riclassifica segmenti come riposo
        # riposi settimanali scelti a penalità minima (models/rest_optimizer.py)
        from models.rest_optimizer import rests_for
        self.rests: List[Rest] = rests_for(self.tl, settings)
        self.shifts: List[Shift] = build_shifts(self.tl, self.rests)

    def dur(self, m: int) -> str:
        """Durata nel formato scelto nelle impostazioni (oo:mm oppure oo.oo)."""
        m = max(0, int(round(m)))
        if self.s.intervalformat == "HHHH":
            return f"{m / 60:05.2f}"
        return f"{m // 60:02d}:{m % 60:02d}"

    def add(self, code: str, start: int, end: int, value: int, limit: int,
            detail_label: str, severity: Optional[str] = None, no_msi: bool = False,
            note: str = "", detail: str = None):
        sev = severity or classify(code, value, no_msi)
        if sev is None:
            return
        desc_key = f"{code}_msi" if sev == MSI and f"{code}_msi" in DESCRIPTIONS else code
        d = self.tl.local(start)
        self.out.append(Violation(
            date=d.date().isoformat(), date_display=d.strftime("%d/%m/%Y"),
            code=code, description=DESCRIPTIONS[desc_key],
            detail=detail or f"{detail_label} {self.dur(value)} ({self.dur(limit)})",
            severity=sev, value_min=int(value), limit_min=int(limit),
            excess_min=abs(int(value) - int(limit)),
            start=self.tl.fmt(start), end=self.tl.fmt(end),
            category=category(code), note=note,
        ))
        self.out[-1]._sort = start

    # ── utilità ──────────────────────────────────────────────────────────────
    def is_break(self, seg) -> bool:
        """Pausa: riposo, oppure disponibilità in equipaggio (Art. 7: pausa sul
        veicolo guidato da un altro conducente) o se l'impostazione
        "La disponibilità può essere considerata una interruzione" è attiva."""
        if seg.activity == REST:
            return True
        return seg.activity == AVAIL and (seg.crew or self.s.availibilityisbreak)

    def is_work(self, seg) -> bool:
        """Orario di lavoro (Dir. 2002/15): Guida + Lavoro; pause < 15 min
        contano come lavoro salvo impostazione."""
        if seg.activity in (DRIVE, WORK):
            return True
        return (seg.activity == REST and seg.length < SHORT_BREAK
                and not self.s.shortbreakisnotwork)

    def week_of(self, minute: int) -> int:
        return self.tl.week_start(minute, self.s.firstdayofweek)


# ── Regole ───────────────────────────────────────────────────────────────────

def _bus_derogation_periods(c: _Ctx) -> List[tuple]:
    """Periodi in cui un conducente di bus usa la deroga dei 12 giorni (Art. 8§6a):
    dalla fine di un riposo settimanale all'inizio del successivo, se tra i due
    passano più di 6 periodi di 24 ore."""
    if not c.s.isbus:
        return []
    weekly = [r for r in c.rests if r.weekly]
    return [(a.end, b.start) for a, b in zip(weekly, weekly[1:]) if b.start - a.end > 144 * H]


def _night_overlap(c: _Ctx, a: int, b: int) -> bool:
    """Il periodo tocca la fascia 22:00-06:00 (ora locale)."""
    d = c.tl.local(a).date() - timedelta(days=1)
    while True:
        start = c.tl.to_minute(datetime(d.year, d.month, d.day, 22, tzinfo=c.tl.tz))
        if start >= b:
            return False
        if min(b, start + 8 * H) > max(a, start):
            return True
        d += timedelta(days=1)


def _continuous_driving(c: _Ctx):
    """Art. 7 — guida ininterrotta > 4h30 senza pausa di 45 min (o 15 + 30).
    Le pause consecutive si sommano; un'infrazione per ogni blocco di guida.
    Bus in deroga 12 giorni (Art. 8§6a): guida da solo tra le 22 e le 6 oltre
    3 ore prima della pausa → NightDrivingBus (al posto della guida continua)."""
    derog = _bus_derogation_periods(c)

    def close(first, last, drive, solo):
        if derog and solo and drive > 180 and _night_overlap(c, first, last)                 and any(min(last, b) > max(first, a) for a, b in derog):
            c.add("NightDrivingBus", first, last, drive, 180,
                  "Tempo di guida notturno prima della pausa")
        elif drive > 270:
            c.add("ContinuousDriving", first, last, drive, 270, "Tempo di guida continuo")

    drive = 0
    solo = False
    first = last = None
    had15 = False
    big1 = big2 = 0                 # le due pause più lunghe (regola bus 2024)
    brk = 0
    segs = c.tl.segments
    for i, seg in enumerate(segs):
        if seg.activity == DRIVE:
            if drive == 0:
                first = seg.start
                solo = False
            drive += seg.length
            solo = solo or seg.solo
            last = seg.end
            brk = 0
            continue
        if not c.is_break(seg):
            brk = 0
            continue
        brk += seg.length
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        if nxt is not None and c.is_break(nxt):
            continue                # la pausa prosegue nel segmento successivo
        if drive > 0:
            if brk >= big1:
                big1, big2 = brk, big1
            elif brk > big2:
                big2 = brk
        bus_rule = (c.s.isbus and c.tl.local(seg.start).replace(tzinfo=None) >= BUS_SPLIT_BREAK
                    and big1 + big2 >= 45)
        if brk >= 45 or (brk >= 30 and had15) or bus_rule:
            if drive > 0:
                close(first, last, drive, solo)
            drive, had15, big1, big2 = 0, False, 0, 0
        elif brk >= 15 and drive > 0:
            had15 = True
    if drive > 0:
        close(first, last, drive, solo)


def _art12(c: _Ctx, r: Optional[Rest], need: int = 0) -> bool:
    """Art. 12 (dal 20/08/2020): il turno finisce con un riposo settimanale nel
    paese di base (rientro a casa) lungo più di `need` minuti → possibile deroga."""
    if r is None or not r.weekly or r.length <= need:
        return False
    limit = c.tl.to_minute(MOBILITY_PACKAGE.replace(tzinfo=c.tl.tz))
    return r.start > limit and _rest_country(c, r) in ("", c.s.basecountry)


def _day_driving(c: _Ctx):
    """Art. 6§1 — guida giornaliera tra due riposi: max 9h, 10h max 2 volte/settimana."""
    ext: Dict[int, int] = {}
    for sh in c.shifts:
        drive = sh.minutes(DRIVE)
        if drive <= 9 * H:
            continue
        wk = c.week_of(sh.start)
        ext[wk] = ext.get(wk, 0) + 1
        no_msi = any(s.length > 270 and (s.activity == REST or s.activity == AVAIL)
                     for s in sh.segments)
        first = next((s.start for s in sh.segments if s.activity == DRIVE), sh.start)
        last = max((s.end for s in sh.segments if s.activity == DRIVE), default=sh.end)
        if drive > 10 * H:
            code, lim = ("DayDriving_9", 9 * H) if ext[wk] > 2 else ("DayDriving_10", 10 * H)
        elif ext[wk] > 2:
            code, lim = "DayDriving_9", 9 * H
        else:
            continue
        # Art. 12: superamento per raggiungere casa per il riposo settimanale
        note = "overdrive" if drive <= 11 * H and _art12(c, sh.rest_after) else ""
        c.add(code, first, last, drive, lim, "Tempo di guida", no_msi=no_msi, note=note)


def _weekly_driving(c: _Ctx):
    """Art. 6§2-3 — guida settimanale > 56h, bisettimanale > 90h."""
    if not c.tl.segments:
        return
    weeks: Dict[int, int] = {}
    wk = c.week_of(c.tl.start)
    while wk < c.tl.end:
        nxt = c.week_of(wk + 8 * 24 * H)
        weeks[wk] = c.tl.minutes(wk, nxt, DRIVE)
        wk = nxt
    keys = sorted(weeks)
    for i, k in enumerate(keys):
        end = keys[i + 1] if i + 1 < len(keys) else c.week_of(k + 8 * 24 * H)
        if weeks[k] > 56 * H:
            limit = c.tl.to_minute(MOBILITY_PACKAGE.replace(tzinfo=c.tl.tz))
            note = "overdrive" if weeks[k] <= 58 * H and k > limit else ""
            c.add("WeekDriving_one", k, end - 1, weeks[k], 56 * H, "Tempo di guida", note=note)
        if i + 1 < len(keys):
            two = weeks[k] + weeks[keys[i + 1]]
            end2 = keys[i + 2] if i + 2 < len(keys) else c.week_of(keys[i + 1] + 8 * 24 * H)
            if two > 90 * H:
                c.add("WeekDriving_two", k, end2 - 1, two, 90 * H, "Tempo di guida")


def _daily_rest(c: _Ctx):
    """Art. 8§2 — riposo giornaliero: 11h (ridotto 9h max 3 volte, frazionato 3+9,
    multipresenza 9h in 30h) entro 24h dalla fine del riposo precedente."""
    reduced = 0
    for r in c.rests:
        if r.weekly:
            reduced = 0
            # riposo settimanale iniziato oltre la finestra delle 24h: il riposo
            # giornaliero è arrivato troppo tardi (Art. 12 se è il rientro a casa)
            if not r.truncated and r.start > c.tl.start and r.in_window < 11 * H:
                c.add("Rest_DailyNormal_Fine", r.start, r.end, r.in_window, 11 * H,
                      "Periodo di riposo avviato troppo tardi",
                      note="overrun" if _art12(c, r, 11 * H) else "")
            continue
        if r.truncated:
            continue
        if r.kind in ("DailyReduced",):
            reduced += 1
            continue
        if r.kind == "DailyNormal" and r.in_window < 11 * H:
            code, lim = "Rest_DailyNormal_Fine", 11 * H            # ridotti esauriti
        elif r.kind == "Insufficient":
            crew = any(s.crew for s in c.tl.between(r.start - 30 * H, r.start)
                       if s.activity == DRIVE)
            if crew:
                code, lim = "Rest_DailyStaff_Fine", 9 * H
            elif reduced < 3:
                code, lim = "Rest_DailyReduced_Fine", 9 * H
            else:
                code, lim = "Rest_DailyNormal_Fine", 11 * H
            reduced += 1
        else:
            continue
        late = r.length >= lim and r.in_window < lim
        label = "Periodo di riposo avviato troppo tardi" if late else "Periodo di riposo troppo breve"
        c.add(code, r.start, r.end if r.end > r.start else r.start, r.in_window, lim, label)


def _weekly_rest(c: _Ctx):
    """Art. 8§6 — riposo settimanale: entro 6×24h (12×24h bus) dal precedente;
    in 2 settimane consecutive 2 riposi, di cui almeno 1 regolare (45h)."""
    weekly = [r for r in c.rests if r.weekly]
    limit = (288 if c.s.isbus else 144) * H
    code_late = "Weekly_TooLate_Bus" if c.s.isbus else "Weekly_TooLate"
    # riposo settimanale ridotto sotto le 24h (può capitare con la scelta a
    # penalità minima, che accetta come settimanali i riposi da 20h)
    for r in weekly:
        if r.kind == "WeeklyReduced" and not r.truncated and r.length < 24 * H:
            c.add("Weekly_TooShort_24", r.start, r.end, r.length, 24 * H,
                  "Periodo di riposo settimanale troppo breve")
    prev = None
    for r in weekly:
        if prev is not None:
            gap = r.start - prev.end
            if gap > limit:
                c.add(code_late, prev.end, r.start, gap, limit,
                      "Periodo di riposo settimanale avviato troppo tardi")
            elif c.s.isbus and gap > 144 * H and r.length < 69 * H:
                c.add("Weekly_TooShort_Bus", r.start, r.end, r.length, 69 * H,
                      "Periodo di riposo settimanale troppo breve")
        prev = r
    # dall'ultimo riposo settimanale alla fine dell'ultima attività
    if prev is not None:
        last_work = max((s.end for s in c.tl.segments if s.activity != REST), default=0)
        if last_work - prev.end > limit:
            c.add(code_late, prev.end, last_work, last_work - prev.end, limit,
                  "Periodo di riposo settimanale avviato troppo tardi")

    # coppie di settimane consecutive (inizio settimana locale)
    if not c.tl.segments:
        return
    week = 7 * 24 * H
    p0 = c.week_of(c.tl.start)
    if p0 < c.tl.start:
        p0 = c.week_of(p0 + 8 * 24 * H)                   # prima settimana completa
    while True:
        p1 = c.week_of(c.week_of(p0 + 8 * 24 * H) + 8 * 24 * H)
        if p1 > c.tl.end:
            break
        found = []
        holiday = False
        for r in weekly:
            overlap = min(r.end, p1) - max(r.start, p0)
            if overlap >= 90 * H:
                holiday = True                            # riposo lunghissimo (ferie)
            if p0 <= r.start < p1 or overlap >= 24 * H:
                found.append(45 * H if r.truncated else r.length)
        regular = sum(1 for d in found if d >= 45 * H)
        # due ridotti consecutivi all'estero ammessi
        intl = {id(x) for pair in _international_pairs(c) for x in pair}
        in_pair = [w for w in weekly if (p0 <= w.start < p1 or
                                         min(w.end, p1) - max(w.start, p0) >= 24 * H)]
        if in_pair and all(id(w) in intl for w in in_pair if w.length < 45 * H):
            regular = max(regular, 1)
        if found and not holiday and regular < 1:
            best = max(found)
            r = max((w for w in weekly if (p0 <= w.start < p1)), key=lambda w: w.length,
                    default=None)
            s0, s1 = (r.start, r.end) if r else (p0, p1)
            c.add("Weekly_TooShort_45", s0, s1, best, 45 * H,
                  "Periodo di riposo settimanale ridotto non compensato")
        p0 = c.week_of(p0 + 8 * 24 * H)


def _weekly_working(c: _Ctx):
    """Dir. 2002/15 Art. 4 — orario settimanale: media ≤ 48h sul periodo di
    riferimento (impostazione "Cornice di lavoro"), massimo assoluto 60h."""
    if not c.tl.segments:
        return
    weeks: List[tuple] = []
    holidays = [d for h in (getattr(c.cd, "holidays", None) or []) for d in h.days()]
    wk = c.week_of(c.tl.start)
    while wk < c.tl.end:
        nxt = c.week_of(wk + 8 * 24 * H)
        work = sum(s.length for s in c.tl.between(wk, nxt) if c.is_work(s))
        # ogni giorno di ferie vale HOLIDAYHOURS ore di lavoro
        work += c.s.holidayhours * H * sum(
            1 for h in holidays if wk <= c.tl.day_start(h) < nxt)
        weeks.append((wk, nxt, work))
        wk = nxt
    n = c.s.reference_weeks
    for i, (ws, we, work) in enumerate(weeks):
        if i + 1 >= n:
            avg = sum(w for _, _, w in weeks[i + 1 - n:i + 1]) / n
            if avg > 48 * H:
                c.add("WeekWorking_48", ws, we - 1, work, 48 * H, "Orario di lavoro settimanale")
                continue
        c.add("WeekWorking_60", ws, we - 1, work, 60 * H, "Orario di lavoro settimanale")


def _night_and_continuous_work(c: _Ctx):
    """Dir. 2002/15 Art. 5 e 7, per turno:
      - lavoro > 6h → pause ≥ 30 min; > 9h → pause ≥ 45 min (pause da ≥ 15 min)
      - tratto di lavoro > 6h senza pausa ≥ 15 min
      - turno con lavoro notturno → orario max 10h (salvo impostazione)"""
    ns, ne = c.s.night_hours
    for sh in c.shifts:
        segs = sh.segments
        work_total = brk_total = stretch = longest = 0
        st_start = st_best = (sh.start, sh.start)
        cur_start = None
        for s in segs:
            if c.is_work(s):
                work_total += s.length
                if stretch == 0:
                    cur_start = s.start
                stretch += s.length
                if stretch > longest:
                    longest, st_best = stretch, (cur_start, s.end)
            elif s.length >= SHORT_BREAK and c.is_break(s):
                brk_total += s.length
                stretch = 0
        if c.italy:
            _continuous_work_italy(c, sh, work_total)
        elif work_total > 9 * H and classify("ContinuousWorking_9", brk_total):
            c.add("ContinuousWorking_9", sh.start, sh.end, brk_total, 45,
                  "Pausa")
        elif 6 * H < work_total <= 9 * H and classify("ContinuousWorking_6", brk_total):
            c.add("ContinuousWorking_6", sh.start, sh.end, brk_total, 30, "Pausa")
        elif longest > 6 * H:
            c.add("ContinuousWorking_6S", st_best[0], st_best[1], longest, 6 * H,
                  "Lavoro continuo", severity=SI)

        # ── lavoro notturno ──
        if c.s.dailyworkinglimitbynightwork:
            continue
        # In Italia la fascia notturna è 00:00-07:00 (D.Lgs. 234/2007) e basta
        # un qualsiasi lavoro in fascia; altrove soglia di 4h nella fascia scelta.
        n0, n1 = (0, 7) if c.italy else (ns, ne)
        d0 = c.tl.local(sh.start).date()
        window = None
        for d in (d0, d0 + timedelta(days=1)):
            w0 = c.tl.day_start(d) + n0 * H
            w1 = c.tl.day_start(d) + n1 * H
            if w0 < sh.end and w1 > sh.start:
                window = (w0, w1)
                break
        if not window:
            continue
        acc = best = 0
        for s in segs:
            if c.is_work(s):
                acc += max(0, min(s.end, window[1]) - max(s.start, window[0]))
                best = max(best, acc)
            elif s.length >= SHORT_BREAK:
                acc = 0
        needed = 1 if c.italy else min(4 * H, window[1] - window[0])
        if best < needed:
            continue
        # Italia e Portogallo: orario nelle 24h dall'inizio del turno
        span_end = sh.start + 24 * H if (c.italy or c.portugal) else sh.end
        work = sum(s.length for s in c.tl.between(sh.start, span_end) if c.is_work(s))
        c.add("Working_IsNight_10", sh.start, span_end if c.italy or c.portugal else sh.end,
              work, 10 * H, "Orario di lavoro")


def _continuous_work_italy(c: _Ctx, sh: Shift, total: int):
    """Ogni 6h di lavoro serve una pausa di
    30 min (45 min se il turno supera 9h), con pause da almeno 15 min."""
    if total <= 6 * H:
        return
    req = 45 if total > 9 * H else 30
    code = "ContinuousWorking_9" if total > 9 * H else "ContinuousWorking_6"
    start = sh.start
    work = brk = 0
    last_end = sh.start
    for s in sh.segments:
        if c.is_work(s):
            work += s.length
            last_end = s.end
        elif s.length >= SHORT_BREAK and c.is_break(s):
            brk += s.length
        if work > 6 * H:
            c.add(code, start, last_end, brk, req, "Pausa")
            start, work, brk = s.end, 0, 0
        if brk >= req:
            start, work, brk = s.end, 0, 0


def _mode_incorrect_use(c: _Ctx):
    """Lavoro ≥ 9h (o disponibilità ≥ 9h da solo) senza
    interruzioni: a fine giornata non è stato selezionato il riposo.
    Il periodo viene poi considerato riposo per gli altri controlli."""
    wrong = [s for s in c.tl.segments
             if s.length >= 9 * H and not (s.manual or s.unknown)
             and (s.activity == WORK or (s.activity == AVAIL and s.solo))]
    for s in wrong:
        c.add("Mode_Incorrect_Use", s.start, s.end, 0, 0, "", severity=MI,
              detail="Al termine della giornata lavorativa, non è stato indicato "
                     "alcun periodo di riposo")
    if wrong:
        c.tl.reclassify_as_rest(wrong)


def _missing_manual_entry(c: _Ctx):
    """Carta reinserita senza indicare l'attività svolta
    mentre era estratta: periodo "sconosciuto" che inizia durante la giornata.
    Gli ultimi 4 cambi del file non si giudicano (la carta può
    essere stata appena estratta per lo scarico)."""
    flat = []                                   # (minuto UTC, ActivityChange)
    for day in sorted(c.activities, key=lambda d: d.date):
        base = (date.fromisoformat(day.date) - _EPOCH).days * 1440
        flat += [(base + x.time, x) for x in sorted(day.changes, key=lambda x: x.time)]
    for i, (t, x) in enumerate(flat[:-4] if len(flat) > 4 else []):
        if x.card_inserted or x.manual or t % 1440 == 0:
            continue
        if any(u == t and (y.card_inserted or y.manual) for u, y in flat if y is not x):
            continue
        nxt = next((u for u, _ in flat[i + 1:] if u > t), t)
        c.add("Missing_ManualEntry", t, nxt, 0, 0, "", severity=MI,
              detail="Non è stato specificato il tipo di attività "
                     "precedente quando è stata inserita la scheda")


def _utc_minute(text: str) -> Optional[int]:
    """'DD/MM/YYYY HH:MM' (UTC, come nel parser) → minuti UTC dall'epoca."""
    try:
        return int(datetime.strptime(text, "%d/%m/%Y %H:%M")
                   .replace(tzinfo=timezone.utc).timestamp() // 60)
    except (TypeError, ValueError):
        return None


def _missing_country_code(c: _Ctx):
    """Simbolo del paese da inserire all'inizio e alla fine
    di ogni periodo di riposo (Reg. 165/2014 Art. 34§6f).
    Tolleranze: fine lavoro -3h/+4h dall'inizio del riposo,
    inizio lavoro -4h/+1h dalla fine del riposo."""
    places = [m for m in (_utc_minute(p.datetime) for p in (c.cd.places if c.cd else []))
              if m is not None]
    if not places:
        return
    out_of_scope = _condition_intervals(c)

    def has_place(a, b):
        return any(a <= m <= b for m in places)

    def covered(t):
        return any(a <= t <= b for a, b in out_of_scope)

    # Il buffer luoghi della carta è circolare: prima del luogo più vecchio
    # ancora presente non si può sapere se il paese era stato inserito.
    covered_from = min(places) - 4 * H
    # si controlla solo dentro gli intervalli
    # coperti dal registro luoghi di ciascun file unito
    ranges = getattr(c.cd, "place_ranges", None) or []
    in_scope = (lambda t: any(a <= t <= b for a, b in ranges)) if ranges else None
    rests = [r for r in c.rests if r.length > 0 and not r.truncated]
    for r in rests[:-1]:
        if in_scope is None and r.start < covered_from:
            continue
        check_start = in_scope is None or in_scope(r.start)
        check_end = in_scope is None or in_scope(r.end)
        before = c.tl.between(r.start - 1, r.start)
        after = c.tl.between(r.end, r.end + 1)
        manual_before = bool(before and before[0].manual)
        manual_after = bool(after and after[0].manual)
        if check_start and not has_place(r.start - 3 * H, r.start + 4 * H) and not manual_before \
                and not covered(r.start):
            c.add("Missing_CountryCode", r.start, r.start, 0, 0, "", severity=MI,
                  detail="Il simbolo del paese deve essere inserito all'inizio e "
                         "alla fine del periodo di riposo")
        if check_end and not has_place(r.end - 4 * H, r.end + H) and not manual_after \
                and not covered(r.end):
            c.add("Missing_CountryCode", r.end, r.end, 0, 0, "", severity=MI,
                  detail="Il simbolo del paese deve essere inserito all'inizio e "
                         "alla fine del periodo di riposo")


def _condition_intervals(c: _Ctx) -> List[tuple]:
    """Intervalli fuori ambito e traghetto/treno dalle condizioni specifiche
    (ogni tipo accoppiato col proprio inizio/fine."""
    out, begin = [], None
    conds = sorted((t, x.condition_type) for x in (c.cd.specific_conditions if c.cd else [])
                   if (t := _utc_minute(x.entry_time)) is not None)
    for t, kind in conds:
        if kind == "Inizio fuori ambito":
            begin = t
        elif kind == "Fine fuori ambito" and begin is not None:
            out.append((begin, t))
            begin = None
    out += [(b, e) for b, e in _ferry_pairs(c) if e is not None]
    return sorted(out)


def _vehicle_check(c: _Ctx):
    """Prima della
    prima guida del turno serve un periodo di lavoro (ispezione) di 5/10/15 min."""
    need = c.s.vehicle_check_min
    if not need:
        return
    for sh in c.shifts:
        work = 0
        for s in sh.segments:
            if s.activity == WORK:
                work += s.length
            elif s.activity == DRIVE:
                if work < need:
                    c.add("VehicleCheck", sh.start, s.start, work, need, "", severity=MI,
                          detail=f"Prima del primo periodo di guida, non c'era un periodo "
                                 f"di lavoro sufficiente {c.dur(work)} ({c.dur(need)})")
                break


def _rest45_in_vehicle(c: _Ctx):
    """Dal 20/08/2020 il riposo settimanale regolare non può
    essere trascorso nel veicolo (Art. 8§8): segnala i riposi ≥ 45h con meno di
    40h di carta fuori dal tachigrafo."""
    if not c.cd or not c.cd.vehicle_sessions:
        return
    sessions = [(v.first_use_utc // 60, v.last_use_utc // 60)
                for v in c.cd.vehicle_sessions if v.first_use_utc and v.last_use_utc]
    limit = c.tl.to_minute(MOBILITY_PACKAGE.replace(tzinfo=c.tl.tz))
    for r in c.rests:
        if not r.weekly or r.truncated or r.length < 45 * H or r.start <= limit:
            continue
        inside = sum(max(0, min(r.end, b) - max(r.start, a)) for a, b in sessions)
        if r.length - inside < 40 * H:
            c.add("Rest45InVehicle", r.start, r.end, r.length, 45 * H, "", severity=VSI,
                  detail="Durante il periodo di riposo la carta era nel tachigrafo")


def _rest_country(c: _Ctx, r: Rest) -> str:
    """Paese del riposo: luogo registrato più vicino all'inizio (o alla fine), entro 12h."""
    from models.rest_report import _country_of
    return _country_of(c.cd, r.start) or _country_of(c.cd, r.end)


def _international_pairs(c: _Ctx) -> List[tuple]:
    """
    due riposi settimanali
    ridotti consecutivi fuori dal paese di base (trasporto merci internazionale),
    ammessi se in 4 settimane consecutive ci sono almeno 4 riposi settimanali di
    cui 2 regolari. Ritorna le coppie (primo, secondo) che rispettano la condizione.
    """
    if hasattr(c, "_intl"):
        return c._intl
    c._intl = []
    if c.s.isbus or not c.cd:
        return c._intl
    base = c.s.basecountry
    weekly = [r for r in c.rests if r.weekly and not r.truncated]
    abroad = {id(r): (lambda k: bool(k) and k != base)(_rest_country(c, r)) for r in weekly}
    limit = c.tl.to_minute(MOBILITY_PACKAGE.replace(tzinfo=c.tl.tz))
    week = 7 * 24 * H
    for p, r in zip(weekly, weekly[1:]):
        if not (p.kind == r.kind == "WeeklyReduced" and abroad[id(p)] and abroad[id(r)]
                and p.start >= limit):
            continue
        w_first = c.week_of(r.start) - 3 * week
        ok = False
        for k in range(4):
            ws = w_first + k * week
            we = ws + 4 * week
            if not (ws <= c.week_of(p.start) and c.week_of(r.start) < we):
                continue
            inside = [x for x in weekly if ws <= c.week_of(x.start) < we]
            regular = sum(1 for x in inside if x.kind == "WeeklyNormal")
            total = len(inside)
            rem = we - c.tl.end
            if rem > 0:                      # settimane ancora da venire: caso migliore
                regular += rem // (45 * H) + 1
                total += rem // (24 * H) + 1
            if regular >= 2 and total >= 4:
                ok = True
                break
        if ok:
            c._intl.append((p, r))
    return c._intl


def _weekly_international(c: _Ctx):
    """le riduzioni dei due
    riposi settimanali ridotti consecutivi all'estero vanno compensate prima del
    riposo settimanale successivo (regolare, o ridotto nel paese di base)."""
    pairs = _international_pairs(c)
    if not pairs:
        return
    base = c.s.basecountry
    weekly = [r for r in c.rests if r.weekly and not r.truncated]
    rests = [r for r in c.rests if r.length > 0 and not r.truncated]
    surplus = {}
    for r in rests:
        if r.kind == "WeeklyNormal":
            surplus[id(r)] = max(0, r.length - 45 * H)
        elif r.kind.startswith("Daily") and r.length >= 9 * H:
            surplus[id(r)] = max(0, r.length - 11 * H)
    done = set()
    for p, r in pairs:
        nxt = next((w for w in weekly if w.start > r.start and
                    (w.kind == "WeeklyNormal" or _rest_country(c, w) in ("", base))), None)
        if nxt is None or id(nxt) in done:
            continue                                   # ancora in tempo per compensare
        missing = []
        for red in (p, r):
            deficit = 45 * H - red.length
            src = next((x for x in rests if red.end <= x.start <= nxt.start
                        and surplus.get(id(x), 0) >= deficit), None)
            if src is not None:
                surplus[id(src)] -= deficit
            else:
                missing.append(red)
        if missing:
            done.add(id(nxt))
            dates = ", ".join(c.tl.local(m.start).strftime("%d/%m/%y") for m in missing)
            c.add("Weekly_TooShort_International", nxt.start, nxt.end, nxt.length, 45 * H,
                  "", severity=VSI,
                  detail="Periodi di riposo settimanale ridotti all'estero non compensati "
                         f"prima di questo riposo settimanale: {dates}")


def _ferry_pairs(c: _Ctx) -> List[tuple]:
    """Periodi traghetto/treno (inizio, fine o None) dalle condizioni specifiche."""
    out, begin = [], None
    conds = sorted((t, x.condition_type) for x in (c.cd.specific_conditions if c.cd else [])
                   if (t := _utc_minute(x.entry_time)) is not None)
    for t, kind in conds:
        if kind == "Inizio traghetto/treno":
            if begin is not None:
                out.append((begin, None))
            begin = t
        elif kind == "Fine traghetto/treno" and begin is not None:
            out.append((begin, t))
            begin = None
    if begin is not None:
        out.append((begin, None))
    return out


def _ferry_button_invalid(c: _Ctx):
    """
    a ogni periodo
    traghetto/treno deve corrispondere un riposo (tra 2h30 e 48h): dentro il
    periodo se dura almeno 2h30, altrimenti nell'ora successiva all'inizio, con al
    massimo 30 minuti di guida tra l'inizio del periodo e il riposo.
    """
    pairs = _ferry_pairs(c)
    if not pairs:
        return
    segs = c.tl.segments
    rests = [s for s in segs if s.activity == REST]
    last = segs[-1] if segs else None
    changes = [s.start for s in segs if s.activity in (DRIVE, WORK)]

    def little_driving(begin, seg):           # [oi.l] guida ≤ 30 min prima del riposo
        if seg.start <= begin:
            return True
        drv = sum(max(0, min(s.end, seg.start) - max(s.start, begin))
                  for s in segs if s.activity == DRIVE and s.start < seg.start)
        return drv <= 30

    for i, (b, e) in enumerate(pairs):
        nxt = pairs[i + 1][0] if i + 1 < len(pairs) else None
        if e is not None:
            d = e - b
            if d < 3:
                continue
            # due pressioni brevi ravvicinate con guida/lavoro alla fine: ignorate
            if d <= 30 and nxt is not None and nxt >= e and nxt - e <= 30 \
                    and any(abs(t - e) <= 2 for t in changes):
                continue
        ranges = []
        if e is not None and e > b and e - b < 150:
            ranges = []
        elif e is not None and e > b and e - b <= 48 * 60:
            idx = [k for k, s in enumerate(rests)
                   if (ov := min(s.end, e) - max(s.start, b)) > 0 and ov * 2 >= s.length
                   and little_driving(b, s)]
            if idx:
                ranges.append((idx[0], idx[-1]))
        else:
            k = next((k for k, s in enumerate(rests) if s.end > b), None)
            if k is not None:
                s = rests[k]
                nk = k + 1 if k + 1 < len(rests) else None
                if nk is not None and not (rests[nk].start - s.end <= 60
                                           and little_driving(b, rests[nk])):
                    nk = None
                if s.start > b:
                    if s.start - b <= 60 and little_driving(b, s):
                        ranges.append((k, k))
                elif s.end - b < 30:
                    if nk is not None:
                        ranges.append((nk, nk))
                else:
                    ranges.append((k, k))
                    if nk is not None:
                        ranges.append((nk, nk))
        found, ongoing = False, False
        for a, z in ranges:
            best = max(rests[a:z + 1], key=lambda s: s.length)
            if 150 <= best.length <= 48 * 60:
                found = True
            elif best is last:
                ongoing = True
        if not found and not ongoing:
            c.add("FerryButtonInvalid", b, b, 0, 0, "", severity=WARN,
                  detail="Il tempo trascorso sul traghetto/in treno probabilmente non è "
                         "stato un riposo in una cabina (cuccetta)")


def _virtual_travel(c: _Ctx):
    """
    Viaggio virtuale (solo paese base Polonia, gravità minore): il paese a fine
    lavoro prima di un riposo (luogo tra -3h e +4h dall'inizio) e quello alla
    ripresa (tra -4h e +1h dalla fine) sono diversi senza guida registrata in
    mezzo, quindi il trasferimento non è stato registrato. Per i riposi di almeno
    6 giorni conta il rientro nel paese di base. Non si segnala se accanto al
    riposo c'è un inserimento manuale o se durante il riposo c'è un traghetto/treno.
    """
    base = c.s.basecountry
    if base != "PL" or not c.cd:
        return
    places = sorted((m, p.country) for p in c.cd.places
                    if (m := _utc_minute(p.datetime)) is not None and p.country)
    if not places:
        return
    ferries = [b for b, _ in _ferry_pairs(c)]

    def country_in(a, b):
        found = ""
        for m, k in places:
            if a <= m <= b:
                found = k
        return found

    def add(r, src, dst):
        c.add("VirtualTravel", r.start, r.end, 0, 0, "", severity=MI,
              detail="Probabilmente non hai inserito il periodo di pendolarismo nel "
                     f"tachigrafo (|{src}| >>> |{dst}|)")

    rests = [r for r in c.rests if r.length > 0 and not r.truncated]
    for r in rests[:-1]:
        before = c.tl.between(r.start - 1, r.start)
        after = c.tl.between(r.end, r.end + 1)
        manual_before = bool(before and before[0].manual)
        manual_after = bool(after and after[0].manual)
        end_c = country_in(r.start - 3 * H, r.start + 4 * H)
        start_c = country_in(r.end - 4 * H, r.end + H)
        if r.length >= 144 * H:
            if end_c and end_c != base and not manual_before:
                add(r, end_c, base)
            if start_c and start_c != base and not manual_after:
                add(r, base, start_c)
        elif end_c and start_c and end_c != start_c and                 ((not manual_before and end_c != base) or (not manual_after and start_c != base))                 and not any(r.start <= f <= r.end for f in ferries):
            add(r, end_c, start_c)


BORDER_RULE = datetime(2022, 2, 2)             # Reg. UE 165/2014 Art. 34§7


def _missing_country_code_border(c: _Ctx):
    """
    Simbolo del paese al valico di frontiera (dal 02/02/2022): nello stesso turno
    (dalla fine di un riposo all'inizio del successivo, ±1h) due luoghi consecutivi
    in paesi non confinanti né collegati da traghetto indicano che almeno un
    attraversamento non è stato registrato. Dettaglio "IT|/???/|DE".
    """
    if not c.cd:
        return
    from models.borders import NOT_CHECKED, neighbours
    places = sorted((m, p.country) for p in c.cd.places
                    if (m := _utc_minute(p.datetime)) is not None and p.country)
    if len(places) < 2:
        return
    since = int(BORDER_RULE.replace(tzinfo=timezone.utc).timestamp() // 60)
    rests = [r for r in c.rests if r.length > 0]
    for prev, nxt in zip(rests, rests[1:]):
        a, b = prev.end - H, nxt.start + H
        if a <= since:
            continue
        inside = [x for x in places if a <= x[0] <= b]
        for (m1, k1), (m2, k2) in zip(inside, inside[1:]):
            if not neighbours(k1, k2) and k1 not in NOT_CHECKED and k2 not in NOT_CHECKED:
                c.add("Missing_CountryCode_Border", prev.end, nxt.start, 0, 0, "",
                      severity=MI, detail=f"{k1}|/???/|{k2}")


def _data_gap(c: _Ctx):
    """buco tra due scarichi uniti nello storico:
    contato come riposo (models.history), segnalato come avvertenza."""
    for a, b in getattr(c.cd, "data_gaps", None) or []:
        c.add("DataGap", a, b, b - a, 0, "", severity=WARN,
              detail="Il periodo è stato conteggiato come riposo, la valutazione "
                     "circostante è incerta")


def _card_download_28(c: _Ctx):
    """più di 28 giorni tra due scarichi
    della carta (calcolato in models.history)."""
    for prev, cur, days in getattr(c.cd, "card_downloads", None) or []:
        # date di scarico in ora locale (come nell'archivio)
        a, b = (c.tl.to_minute(datetime.strptime(x, "%d/%m/%Y %H:%M").replace(tzinfo=c.tl.tz))
                for x in (prev, cur))
        word = "È trascorso" if days == 1 else "Sono trascorsi"
        unit = "giorno" if days == 1 else "giorni"
        c.add("CardDownload_28", a, b, days, 28, "", severity=MI,
              detail=f"{word} {days} {unit} dallo scarico precedente (28)")


RULES = [_continuous_driving, _day_driving, _weekly_driving, _daily_rest,
         _weekly_rest, _weekly_working, _night_and_continuous_work,
         _missing_manual_entry, _missing_country_code, _vehicle_check,
         _rest45_in_vehicle, _weekly_international, _ferry_button_invalid, _virtual_travel,
         _missing_country_code_border,
         _data_gap, _card_download_28]


# ── Entry point pubblico ─────────────────────────────────────────────────────

def detect_violations(activities: List[DayActivity],
                      settings: Settings = None, cd=None) -> List[Violation]:
    """
    Ritorna tutte le infrazioni, ordinate per inizio periodo.

    activities: cd.activities (dal parser)
    settings:   impostazioni (default: quelle salvate dall'utente)
    cd:         CardData completo, per le regole che usano luoghi, veicoli e
                condizioni specifiche (simbolo paese, riposo nel veicolo)
    """
    s = settings or load_settings()
    if not activities:
        return []
    c = _Ctx(activities, s, cd)
    for rule in RULES:
        rule(c)
    c.out.sort(key=lambda v: getattr(v, "_sort", 0))
    return c.out


def rest_penalty(tl: Timeline, settings: Settings, weekly: Dict[int, bool],
                 a: int, b: int) -> int:
    """Somma delle penalità (MI 500 … MSI 9000) delle infrazioni su riposi e guida
    giornaliera che iniziano tra a e b, con la scelta dei settimanali `weekly`."""
    c = object.__new__(_Ctx)
    c.s, c.cd, c.activities, c.tl, c.out = settings, None, None, tl, []
    c.italy = settings.basecountry == "IT"
    c.portugal = settings.basecountry == "PT"
    c.rests = classify_rests(tl, weekly=weekly)
    c.shifts = build_shifts(tl, c.rests)
    for rule in (_daily_rest, _weekly_rest, _day_driving):
        rule(c)
    return sum(PENALTY.get(v.severity, 0) for v in c.out if a <= getattr(v, "_sort", a) <= b)


def violation_summary(violations: List[Violation]) -> Dict[str, int]:
    """Conteggio per gravità: {"MSI": n, "VSI": n, "SI": n, "MI": n, "total": n}."""
    out = {sev: sum(1 for v in violations if v.severity == sev) for sev in SEVERITIES}
    out["total"] = len(violations)
    return out

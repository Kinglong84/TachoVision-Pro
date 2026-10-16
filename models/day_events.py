"""
models/day_events.py
====================
Righe giornaliere della schermata Attività, in ora locale.

Ogni giorno locale contiene, in ordine di orario:
  - attività: "HH:MM:SS", tipo, info (manuale / equipaggio / sconosciuta), ΔT=HH:MM
  - carta: "Card In (TARGA, 123456km)" / "Card Out (TARGA, 123456km)"
  - paese: "Italia" (inizio/fine periodo di lavoro, con odometro)
  - eventi e guasti della carta
  - condizioni specifiche (fuori ambito, traghetto/treno)
Filtri: Attività, Carta, Paese, Frontiera, Carico, Eventi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from models.settings import COUNTRY_OPTIONS, Settings, load_settings
from models.timeline import Timeline

_COUNTRY = dict(COUNTRY_OPTIONS)
_WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre"]


@dataclass
class Line:
    minute: int            # minuto UTC (per ordinamento)
    # carta inserita/estratta mostra anche i secondi: 04:29:38
    time: str              # "HH:MM:SS" locale
    kind: str              # activity | card | place | event | condition
    text: str
    activity: str = ""     # per kind=activity
    info: str = ""         # "manuale" | "equipaggio" | "sconosciuta"
    length: str = ""       # "ΔT=HH:MM"


@dataclass
class Day:
    date: date
    title: str             # "6 luglio 2024 (sabato)"
    start: int             # minuto UTC della mezzanotte locale
    segments: list = field(default_factory=list)   # (min_inizio_locale, min_fine, attività)
    lines: List[Line] = field(default_factory=list)
    drive: int = 0
    work: int = 0
    km: float = 0.0
    countries: List[str] = field(default_factory=list)


def _utc_min(text: str) -> Optional[int]:
    try:
        return int(datetime.strptime(text, "%d/%m/%Y %H:%M")
                   .replace(tzinfo=timezone.utc).timestamp() // 60)
    except (TypeError, ValueError):
        return None


def build_days(cd, settings: Settings = None, kinds=None,
               first: date = None, last: date = None) -> List[Day]:
    """
    Giorni locali con le righe richieste.
    kinds: insieme fra {"activity","card","place","event","note","holiday"} (None = tutti)
    """
    s = settings or load_settings()
    kinds = set(kinds) if kinds is not None else {"activity", "card", "place", "event",
                                                   "note", "holiday"}
    tl = Timeline(cd.activities, s.timezone)
    if not tl.segments:
        return []
    d = first or tl.local(tl.start).date()
    end_day = last or tl.local(tl.end - 1).date()
    km_by_day = {x.date: x.distance_km for x in cd.activities}

    extra: List[Line] = []
    if "card" in kinds:
        from models.vehicle_report import merged_sessions
        for v in merged_sessions(cd):
            if v.first_use_utc:
                extra.append(Line(v.first_use_utc // 60, str(v.first_use_utc % 60), "card",
                                  f"Card In ({v.vrn}, {v.odo_begin_km}km)"))
            if v.last_use_utc:
                extra.append(Line(v.last_use_utc // 60, str(v.last_use_utc % 60), "card",
                                  f"Card Out ({v.vrn}, {v.odo_end_km}km)"))
    if "place" in kinds:
        for p in cd.places:
            m = _utc_min(p.datetime)
            if m is not None:
                name = _COUNTRY.get(p.country, p.country)
                tag = "inizio" if p.entry_type == "Inizio" else "fine"
                extra.append(Line(m, "", "place", f"{name} ({tag}, {p.odometer_km}km)"))
    if "event" in kinds:
        for e in list(cd.events) + list(cd.faults):
            m = _utc_min(e.begin_time)
            if m is not None:
                txt = getattr(e, "event_type", None) or getattr(e, "fault_type", "")
                veh = f" ({e.vehicle})" if e.vehicle else ""
                extra.append(Line(m, "", "event", f"⚠ {txt}{veh}"))
        for c in cd.specific_conditions:
            m = _utc_min(c.entry_time)
            if m is not None:
                extra.append(Line(m, "", "condition", c.condition_type))

    if "note" in kinds:
        for n in getattr(cd, "notes", None) or []:
            val = f": {n.value}" if n.value else ""
            extra.append(Line(n.minute, "", "note", f"{n.group}{val}"))
    holiday_days = set()
    if "holiday" in kinds:
        holiday_days = {x for h in (getattr(cd, "holidays", None) or []) for x in h.days()}

    days: List[Day] = []
    while d <= end_day:
        a = tl.day_start(d)
        b = tl.day_start(d + timedelta(days=1))
        day = Day(date=d, title=f"{d.day} {_MONTHS[d.month - 1]} {d.year} ({_WEEKDAYS[d.weekday()]})",
                  start=a, km=km_by_day.get(d.isoformat(), 0.0))
        for x in tl.between(a, b):
            day.segments.append((x.start - a, x.end - a, x.activity))
            if x.activity == "Guida":
                day.drive += x.length
            elif x.activity == "Lavoro":
                day.work += x.length
            if "activity" in kinds:
                info = ("manuale" if x.manual else "equipaggio" if x.crew
                        else "sconosciuta" if x.unknown else "")
                day.lines.append(Line(x.start, tl.local(x.start).strftime("%H:%M:%S"),
                                      "activity", x.activity, x.activity, info,
                                      f"ΔT={x.length // 60:02d}:{x.length % 60:02d}"))
        for ln in extra:
            if a <= ln.minute < b:
                sec = int(ln.time) if ln.time.isdigit() else 0
                day.lines.append(Line(ln.minute, tl.local(ln.minute).strftime("%H:%M:")
                                      + f"{sec:02d}", ln.kind, ln.text))
                if ln.kind == "place":
                    name = ln.text.split(" (")[0]
                    if name not in day.countries:
                        day.countries.append(name)
        if d in holiday_days:
            day.lines.append(Line(a, "00:00:00", "holiday", "Ferie"))
        order = {"holiday": -1, "card": 0, "place": 1, "condition": 2, "event": 3,
                 "note": 4, "activity": 5}
        day.lines.sort(key=lambda l: (l.minute, order.get(l.kind, 9)))
        days.append(day)
        d += timedelta(days=1)
    return days

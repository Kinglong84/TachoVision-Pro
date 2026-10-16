"""
models/vehicle_report.py
========================
"Utilizzo del veicolo" e "Paesi visitati".

Per ogni sessione (inserimento → estrazione carta):
  "DD/MM/YY HH:MM - DD/MM/YY HH:MM (HH:MM)", targa, odometro inizio/fine, km,
  ore di guida nella sessione. Riepiloghi settimanali o mensili (ore guida, km).

Soggiorni per paese tra due luoghi registrati: entrata/uscita (inserimento o
rimozione carta), ore Guida/Lavoro/Disponibilità/Interruzione, distanza.
Se tutti i luoghi sono nel paese base: "L'autista non ha lavorato al di fuori
del paese di base".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from models.settings import COUNTRY_OPTIONS, Settings, load_settings
from models.timeline import AVAIL, DRIVE, REST, WORK, Timeline

H = 60
_COUNTRY = dict(COUNTRY_OPTIONS)
_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def _hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


@dataclass
class SessionRow:
    start: int
    period: str
    vrn: str
    odo_begin: int
    odo_end: int
    km: int
    drive: int
    gnss_date: str = ""          # data con posizioni GPS (per il pulsante mappa)
    end: int = 0                 # estrazione carta (minuti UTC)
    avail: int = 0               # disponibilità nella sessione (simbolo "◊" dell'Excel)


@dataclass
class VehiclePeriod:
    label: str
    start: int
    rows: List[SessionRow] = field(default_factory=list)
    drive: int = 0
    km: int = 0


@dataclass
class CountryStay:
    country: str
    name: str
    start: int
    end: int
    period: str
    entered: str                 # "Inserimento della carta" / "Entrata nel paese"
    left: str
    drive: int = 0
    work: int = 0
    avail: int = 0
    brk: int = 0
    distance: int = 0
    # veicolo e odometro all'entrata e all'uscita
    vrn_in: str = ""
    km_in: Optional[int] = None
    vrn_out: str = ""
    km_out: Optional[int] = None


def merged_sessions(cd) -> list:
    """
    Sessioni reali inserimento → estrazione carta.
    Il buffer della carta spezza l'uso dello stesso veicolo a mezzanotte UTC
    (Card Out 00:59:59 / Card In 01:00:00 con lo stesso odometro):
    i pezzi consecutivi dello stesso veicolo vengono uniti.
    """
    import copy
    out = []
    for v in sorted(cd.vehicle_sessions, key=lambda x: x.first_use_utc or 0):
        last = out[-1] if out else None
        if (last and last.vrn == v.vrn and v.first_use_utc and last.last_use_utc
                and 0 <= v.first_use_utc - last.last_use_utc <= 2
                and (not v.odo_begin_km or v.odo_begin_km == last.odo_end_km)):
            last.last_use_utc = v.last_use_utc
            last.last_use = v.last_use
            last.odo_end_km = v.odo_end_km
        else:
            out.append(copy.copy(v))
    return out


def vehicle_at(cd, minute: int, sessions=None) -> str:
    """Targa del veicolo in uso al minuto UTC indicato ("" se carta estratta)."""
    for v in sessions if sessions is not None else merged_sessions(cd):
        a = (v.first_use_utc or 0) // 60
        b = (v.last_use_utc or v.first_use_utc or 0) // 60
        if a <= minute <= b:
            return v.vrn
    return ""


def vehicle_periods(cd, settings: Settings = None, summary: str = "month",
                    order: str = "dec_inc") -> List[VehiclePeriod]:
    s = settings or load_settings()
    tl = Timeline(cd.activities, s.timezone)
    gnss_days = {g.date for g in (cd.gnss_records or [])}
    periods = {}
    for v in merged_sessions(cd):
        if not v.first_use_utc:
            continue
        a = v.first_use_utc // 60
        b = (v.last_use_utc or v.first_use_utc) // 60
        km = max(0, (v.odo_end_km or 0) - (v.odo_begin_km or 0))
        drive = tl.minutes(a, b, DRIVE) if tl.segments else 0
        avail = tl.minutes(a, b, AVAIL) if tl.segments else 0
        d0 = tl.local(a).date()
        gd = next((x.isoformat() for x in (d0 + timedelta(days=i)
                                         for i in range((tl.local(b).date() - d0).days + 1))
                   if x.isoformat() in gnss_days), "")
        row = SessionRow(a, f"{tl.fmt(a)} - {tl.fmt(b)} ({_hm(b - a)})", v.vrn,
                         v.odo_begin_km, v.odo_end_km, km, drive, gd, b, avail)
        if summary == "week":
            ps = tl.week_start(a, s.firstdayofweek)
            pe = tl.week_start(ps + 8 * 24 * H, s.firstdayofweek)
        else:
            n = s.firstdayofmonth
            first = d0.replace(day=n) if d0.day >= n else \
                ((d0.replace(day=1) - timedelta(days=1)).replace(day=n))
            nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=n)
            ps, pe = tl.day_start(first), tl.day_start(nxt)
        if ps not in periods:
            x, y = tl.local(ps).date(), tl.local(pe - 1).date()
            periods[ps] = VehiclePeriod(
                f"{x.day} {_MONTHS[x.month - 1]} {x.year} - {y.day} {_MONTHS[y.month - 1]} {y.year}",
                ps)
        p = periods[ps]
        p.rows.append(row)
        p.drive += drive
        p.km += km
    out = sorted(periods.values(), key=lambda p: p.start)
    for p in out:
        p.rows.sort(key=lambda r: r.start)
    if order in ("dec_dec", "dec_inc"):
        out.reverse()
    if order == "dec_dec":
        for p in out:
            p.rows.reverse()
    return out


def _utc_min(text: str) -> Optional[int]:
    try:
        return int(datetime.strptime(text, "%d/%m/%Y %H:%M")
                   .replace(tzinfo=timezone.utc).timestamp() // 60)
    except (TypeError, ValueError):
        return None


def country_stays(cd, settings: Settings = None):
    """
    Ritorna (stays, only_base): soggiorni per paese tra luoghi registrati e se
    il conducente ha lavorato solo nel paese base.
    """
    s = settings or load_settings()
    tl = Timeline(cd.activities, s.timezone)
    places = sorted(((m, p) for p in cd.places if (m := _utc_min(p.datetime)) is not None),
                    key=lambda x: x[0])
    if not places:
        return [], False
    only_base = all(p.country == s.basecountry for _, p in places)
    stays: List[CountryStay] = []
    sessions = merged_sessions(cd)
    for i, (m, p) in enumerate(places):
        if p.entry_type != "Inizio":
            continue
        end_m, end_p = next(((m2, p2) for m2, p2 in places[i + 1:]), (None, None))
        if end_m is None:
            continue
        st = CountryStay(
            country=p.country, name=_COUNTRY.get(p.country, p.country), start=m, end=end_m,
            period=f"{tl.fmt(m)} - {tl.fmt(end_m)} ({_hm(end_m - m)})",
            entered="Inserimento della carta",
            left="Rimozione della carta" if end_p.entry_type == "Fine" else "Uscita dal paese",
            distance=max(0, (end_p.odometer_km or 0) - (p.odometer_km or 0)),
            vrn_in=vehicle_at(cd, m, sessions), km_in=p.odometer_km,
            vrn_out=vehicle_at(cd, end_m, sessions), km_out=end_p.odometer_km)
        for x in tl.between(m, end_m):
            if x.activity == DRIVE:
                st.drive += x.length
            elif x.activity == WORK:
                st.work += x.length
            elif x.activity == AVAIL:
                st.avail += x.length
            elif x.activity == REST:
                st.brk += x.length
        stays.append(st)
    return stays, only_base


def country_totals(stays: List[CountryStay]):
    """Totali per paese (ore e distanza), dal più frequentato."""
    tot = {}
    for st in stays:
        t = tot.setdefault(st.country, CountryStay(st.country, st.name, 0, 0, "", "", ""))
        t.drive += st.drive
        t.work += st.work
        t.avail += st.avail
        t.brk += st.brk
        t.distance += st.distance
    return sorted(tot.values(), key=lambda t: -(t.drive + t.work))

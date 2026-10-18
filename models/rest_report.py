"""
models/rest_report.py
=====================
Elenco "Periodi di riposo".

Per ogni riposo giornaliero/settimanale:
  - periodo "DD/MM/YY HH:MM - DD/MM/YY HH:MM (HH:MM)"
  - tipo (regolare / ridotto / frazionato / multipresenza / settimanale …)
  - settimana di riferimento dei riposi settimanali "(→ settimana: 27-28)"
  - compensazione dei riposi settimanali ridotti (Art. 8§7)
  - paese del riposo (dal luogo registrato più vicino)
Dopo ogni riposo, il turno successivo con guida (e guida continua massima),
lavoro, disponibilità; a ogni cambio settimana il tempo di guida
settimanale e quindicinale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from models.settings import Settings, load_settings
from models.timeline import (AVAIL, DRIVE, REST, WORK, Rest, Timeline, build_shifts,
                             classify_rests)
from models.rest_optimizer import rests_for

H = 60

REST_TEXT = {
    "DailyNormal": "Periodo di riposo giornaliero regolare",
    "DailySplit": "Periodo di riposo giornaliero regolare (3h + 9h)",
    "DailyReduced": "Periodo di riposo giornaliero ridotto",
    "DailyStaff": "Periodo di riposo giornaliero in multipresenza",
    "WeeklyNormal": "Periodo di riposo settimanale regolare",
    "WeeklyReduced": "Periodo di riposo settimanale ridotto",
    "Insufficient": "Periodo di riposo troppo breve",
}


@dataclass
class RestEntry:
    kind: str
    period: str
    text: str
    start: int
    end: int
    weekly: bool
    truncated: bool
    country: str = ""
    weeks: str = ""                 # "(→ settimana: 27-28)"
    reduced: bool = False
    compensation: str = ""          # testo stato compensazione
    compensation_state: str = ""    # "done" | "required" | "missing"


@dataclass
class ShiftEntry:
    period: str
    drive: int
    drive_cont: int                 # guida continua massima
    work: int
    avail: int
    crew: bool
    split: bool
    start: int = 0


@dataclass
class WeekEntry:
    week: int                       # numero settimana ISO
    one_week: int                   # guida settimanale (min)
    two_week: int                   # guida quindicinale (min)
    start: int = 0


@dataclass
class RestReport:
    items: list = field(default_factory=list)   # RestEntry | ShiftEntry | WeekEntry


def _dur(m: int, fmt: str = "HHMM") -> str:
    m = max(0, int(m))
    return f"{m / 60:05.2f}" if fmt == "HHHH" else f"{m // 60:02d}:{m % 60:02d}"


def _country_of(cd, minute: int) -> str:
    """Paese del luogo registrato più vicino all'istante (entro 12h)."""
    best = None
    for p in (cd.places if cd else []):
        try:
            t = int(datetime.strptime(p.datetime, "%d/%m/%Y %H:%M")
                    .replace(tzinfo=timezone.utc).timestamp() // 60)
        except ValueError:
            continue
        d = abs(t - minute)
        if d <= 12 * H and (best is None or d < best[0]):
            best = (d, p.country)
    return best[1] if best else ""


def _compensations(tl: Timeline, rests: List[Rest], first_day: int) -> dict:
    """
    Art. 8§7: la riduzione di un riposo settimanale va compensata in blocco,
    attaccata a un altro riposo di almeno 9h, entro la fine della terza
    settimana successiva. Ritorna {id(rest): (stato, testo)}.
    """
    out = {}
    surplus = {}
    for r in rests:
        if r.kind == "WeeklyNormal":
            surplus[id(r)] = max(0, r.length - 45 * H)
        elif r.kind.startswith("Daily") and r.length >= 9 * H:
            surplus[id(r)] = max(0, r.length - 11 * H)
    for i, r in enumerate(rests):
        if r.kind != "WeeklyReduced" or r.truncated:
            continue
        deficit = 45 * H - r.length
        deadline = tl.week_start(r.start, first_day)
        for _ in range(4):
            deadline = tl.week_start(deadline + 8 * 24 * H, first_day)
        done = None
        for later in rests[i + 1:]:
            if later.start > deadline:
                break
            if surplus.get(id(later), 0) >= deficit:
                surplus[id(later)] -= deficit
                done = later
                break
        need = f"{_dur(deficit)} entro {tl.fmt(deadline)}"
        if done:
            out[id(r)] = ("done", f"Compensazione effettuata: {tl.fmt(done.start)} ({_dur(deficit)})")
        elif deadline > tl.end:
            out[id(r)] = ("required", f"Compensazione richiesta: {need}")
        else:
            out[id(r)] = ("missing", f"Nessuna compensazione effettuata ({_dur(deficit)})")
    return out


def build_report(activities, cd=None, settings: Settings = None) -> RestReport:
    s = settings or load_settings()
    tl = Timeline(activities, s.timezone)
    if not tl.segments:
        return RestReport()
    rests = [r for r in rests_for(tl, s) if r.length > 0]
    shifts = build_shifts(tl, rests)
    comp = _compensations(tl, rests, s.firstdayofweek)
    fmt = s.intervalformat

    items = []
    for r in rests:
        open_end = r.end >= tl.end
        period = (f"{tl.fmt(r.start)} - " if open_end
                  else f"{tl.fmt(r.start)} - {tl.fmt(r.end)} ({_dur(r.length, fmt)})")
        text = REST_TEXT.get(r.kind, "")
        if not r.weekly and r.kind != "Insufficient":
            text += f" ({_dur(r.in_window, fmt)})"
        weeks = ""
        if r.weekly:
            w1 = tl.local(r.start).isocalendar()[1]
            w2 = tl.local(max(r.start, r.end - 1)).isocalendar()[1]
            weeks = f"(→ settimana: {w1})" if w1 == w2 else f"(→ settimana: {w1}-{w2})"
        state, ctext = comp.get(id(r), ("", ""))
        items.append(RestEntry(
            kind=r.kind, period=period, text=text, start=r.start, end=r.end,
            weekly=r.weekly, truncated=r.truncated, country=_country_of(cd, r.start),
            weeks=weeks, reduced=r.kind in ("DailyReduced", "WeeklyReduced"),
            compensation=ctext, compensation_state=state))

    for sh in shifts:
        cont = best = 0
        for seg in sh.segments:                  # guida continua massima nel turno
            if seg.activity == DRIVE:
                cont += seg.length
                best = max(best, cont)
            elif seg.activity == REST and seg.length >= 45:
                cont = 0
        items.append(ShiftEntry(
            period=f"{tl.fmt(sh.start)} - {tl.fmt(sh.end)} ({_dur(sh.end - sh.start, fmt)})",
            drive=sh.minutes(DRIVE), drive_cont=best, work=sh.minutes(WORK),
            avail=sh.minutes(AVAIL), crew=sh.crew,
            split=bool(sh.rest_after and sh.rest_after.kind == "DailySplit"),
            start=sh.start))

    # Tempo di guida per settimana (settimanale e quindicinale)
    wk = tl.week_start(tl.start, s.firstdayofweek)
    prev = 0
    while wk < tl.end:
        nxt = tl.week_start(wk + 8 * 24 * H, s.firstdayofweek)
        one = tl.minutes(wk, nxt, DRIVE)
        items.append(WeekEntry(week=tl.local(wk).isocalendar()[1], one_week=one,
                               two_week=one + prev, start=nxt - 1))
        prev = one
        wk = nxt

    items.sort(key=lambda x: x.start)
    return RestReport(items)

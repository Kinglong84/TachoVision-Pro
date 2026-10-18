"""
models/planning.py
==================
Pianificazione: quanto si può ancora guidare/lavorare e quando riposare.

Calcolato all'istante di riferimento (fine dei dati = scarico), con la
"macchina del tempo" (Progetti futuri): si può simulare di lavorare
o riposare ancora per un certo tempo e vedere la situazione risultante.

Tab LAVORO
  - Tempo di guida: giornaliera (max 9h, 10h se restano estensioni), giorni
    estesi usati (max 2), settimanale (max 56h), quindicinale (max 90h),
    guida continua (max 4h30)
  - Orario di lavoro: settimanale (max 60h), media sul periodo di riferimento
    (max 48h), giornaliero (max 10h se lavoro notturno)
  - Prossimo riposo giornaliero: entro e non oltre, durata (regolare 11h /
    ridotto 9h / frazionato 3+9 / multipresenza 9h), ridotti usati (max 3)
  - Prossimo riposo settimanale: entro e non oltre, durata (45h / 24h)
Tab RIPOSO
  - riposo attuale (iniziato alle…) e possibili orari di fine
    (9h ridotto, 3+9 frazionato, multipresenza, 11h, 24h, 45h)
  - compensazioni ancora dovute
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import List, Optional

from models.settings import Settings, load_settings
from models.timeline import (AVAIL, DRIVE, REST, WORK, Segment, Timeline, build_shifts,
                             classify_rests)
from models.rest_optimizer import rests_for

H = 60


@dataclass
class Gauge:
    """Una riga "valore / massimo" della pianificazione."""
    label: str
    value: int
    limit: int
    note: str = ""

    @property
    def left(self) -> int:
        return max(0, self.limit - self.value)

    @property
    def over(self) -> bool:
        return self.value > self.limit


@dataclass
class EndOption:
    label: str
    end: str            # "DD/MM/YY HH:MM"
    available: bool = True


@dataclass
class Plan:
    reference: str                       # istante di riferimento
    in_rest: bool
    driving: List[Gauge] = field(default_factory=list)
    extended_used: int = 0               # giorni estesi (>9h) usati nella settimana
    working: List[Gauge] = field(default_factory=list)
    daily_rest_before: str = ""          # entro e non oltre (inizio riposo giornaliero)
    daily_rest_options: List[tuple] = field(default_factory=list)   # (testo, ore)
    reduced_used: int = 0                # riposi giornalieri ridotti usati (max 3)
    weekly_rest_before: str = ""
    weekly_rest_hours: int = 45
    weekly_regular_before: str = ""
    current_rest_start: str = ""
    current_rest_len: int = 0
    end_options: List[EndOption] = field(default_factory=list)
    compensations: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)


def _simulate(tl: Timeline, mode: Optional[str], minutes: int) -> Timeline:
    """Macchina del tempo: aggiunge in coda guida (lavoro) o riposo."""
    if not mode or minutes <= 0:
        return tl
    tl2 = copy.deepcopy(tl)
    act = REST if mode == "rest" else DRIVE
    last = tl2.segments[-1]
    if last.activity == act:
        last.end += minutes
    else:
        tl2.segments.append(Segment(tl2.end, tl2.end + minutes, act))
    tl2.end += minutes
    return tl2


def reference_minute(tl: Timeline, last_download: str) -> Optional[int]:
    """Istante dello scarico ("DD/MM/YYYY HH:MM" ora locale) in minuti UTC."""
    from datetime import datetime
    try:
        dt = datetime.strptime(last_download, "%d/%m/%Y %H:%M").replace(tzinfo=tl.tz)
    except (TypeError, ValueError):
        return None
    return tl.to_minute(dt)


def build_plan(activities, settings: Settings = None, mode: str = None,
               minutes: int = 0, last_download: str = "") -> Optional[Plan]:
    """last_download: data dello scarico; tra fine dati e scarico la carta era
    estratta e il tempo conta come riposo."""
    s = settings or load_settings()
    base = Timeline(activities, s.timezone)
    if not base.segments:
        return None
    ref = reference_minute(base, last_download)
    if ref and ref > base.end:
        base = _simulate(base, "rest", ref - base.end)
    tl = _simulate(base, mode, minutes)
    now = tl.end
    rests = [r for r in rests_for(tl, s) if r.length > 0]
    shifts = build_shifts(tl, rests)
    fmt = tl.fmt

    last = tl.segments[-1]
    in_rest = last.activity == REST
    plan = Plan(reference=fmt(now), in_rest=in_rest)

    # Turno corrente: dalla fine dell'ultimo riposo giornaliero/settimanale.
    # Se il riposo in corso basta già come riposo giornaliero (≥ 9h), il turno
    # nuovo inizia adesso ("Voglio ancora lavorare"): contatori giornalieri a zero.
    prev_rest = None
    for r in rests:
        if r.end < now:
            prev_rest = r
    rest_done = in_rest and last.length >= 9 * H
    if rest_done:
        shift_start = shift_end = now
    else:
        shift_start = prev_rest.end if prev_rest else tl.start
        shift_end = last.start if in_rest else now

    first_day = s.firstdayofweek
    week0 = tl.week_start(now, first_day)
    prev_week = tl.week_start(week0 - 1, first_day)

    # ── Tempo di guida ──────────────────────────────────────────────────────
    day_drive = tl.minutes(shift_start, shift_end, DRIVE)
    ext_used = sum(1 for sh in shifts
                   if week0 <= sh.start < now and sh.start < shift_start
                   and sh.minutes(DRIVE) > 9 * H)
    plan.extended_used = min(ext_used, 2)
    day_limit = 10 * H if ext_used < 2 else 9 * H
    week_drive = tl.minutes(week0, now, DRIVE)
    two_drive = week_drive + tl.minutes(prev_week, week0, DRIVE)

    cont = 0                                      # guida continua dall'ultima pausa
    brk = 0
    had15 = False
    for seg in tl.between(shift_start, now):
        if seg.activity == DRIVE:
            cont += seg.length
            brk = 0
        elif seg.activity == REST or (seg.activity == AVAIL and seg.crew):
            brk += seg.length
            if brk >= 45 or (brk >= 30 and had15):
                cont, had15 = 0, False
            elif brk >= 15 and cont > 0:
                had15 = True
        else:
            brk = 0

    plan.driving = [
        Gauge("Ogni giorno (massimo 10 ore)" if day_limit == 10 * H else "Ogni giorno (massimo 9 ore)",
              day_drive, day_limit),
        Gauge("Settimanale (max 56 ore)", week_drive, 56 * H),
        Gauge("Quindicinale (max 90 ore)", two_drive, 90 * H),
        Gauge("Continuo (max 4,5 ore)", cont, 270),
    ]

    # ── Orario di lavoro ────────────────────────────────────────────────────
    def work(a, b):
        return sum(x.length for x in tl.between(a, b)
                   if x.activity in (DRIVE, WORK)
                   or (x.activity == REST and x.length < 15 and not s.shortbreakisnotwork))

    week_work = work(week0, now)
    n = s.reference_weeks
    total, wk = 0, week0
    for _ in range(n):
        nxt = tl.week_start(wk + 8 * 24 * H, first_day)
        total += work(wk, nxt)
        wk = tl.week_start(wk - 1, first_day)
    avg = total // n
    day_work = work(shift_start, shift_end)
    ns, ne = (0, 7) if s.basecountry == "IT" else s.night_hours
    night = False
    for x in tl.between(shift_start, shift_end):
        if x.activity in (DRIVE, WORK):
            h0 = tl.local(x.start).hour
            h1 = tl.local(x.end - 1).hour
            if ns <= h0 < ne or ns <= h1 < ne:
                night = True
                break
    # lavoro continuo dall'ultima pausa di almeno 15 minuti (Dir. 2002/15 Art. 5)
    cont_work = 0
    for x in tl.between(shift_start, now):
        if x.activity in (DRIVE, WORK):
            cont_work += x.length
        elif x.length >= 15 and (x.activity == REST or
                                 (x.activity == AVAIL and (x.crew or s.availibilityisbreak))):
            cont_work = 0
    plan.working = [
        Gauge("Continuo (max 6 ore)", cont_work, 6 * H),
        Gauge(f"Settimanale (max 60:00)", week_work, 60 * H),
        Gauge(f"Media {n} settimane (massimo 48 ore)", avg, 48 * H),
        Gauge("Ogni giorno" + (" (massimo 10 ore)" if night and not s.dailyworkinglimitbynightwork else ""),
              day_work, 10 * H if night and not s.dailyworkinglimitbynightwork else 13 * H),
    ]

    # ── Prossimo riposo giornaliero ─────────────────────────────────────────
    since_weekly = [r for r in rests if r.weekly and r.end <= now]
    last_weekly = since_weekly[-1] if since_weekly else None
    plan.reduced_used = min(3, sum(1 for r in rests
                                   if r.kind == "DailyReduced"
                                   and (last_weekly is None or r.start > last_weekly.end)
                                   and r.end <= now))
    crew = any(x.crew for x in tl.between(shift_start, shift_end) if x.activity == DRIVE)
    window = 30 * H if crew else 24 * H
    can_reduce = plan.reduced_used < 3
    if crew:
        plan.daily_rest_options = [("Durata (multipresenza)", 9)]
        needed = 9 * H
    else:
        plan.daily_rest_options = [("Durata (regolare)", 11)]
        if can_reduce:
            plan.daily_rest_options.append(("Durata (ridotto possibile)", 9))
        had3h = any(x.activity == REST and x.length >= 3 * H
                    for x in tl.between(shift_start, shift_end))
        if had3h:
            plan.daily_rest_options.append(("Durata (frazionato 3+9)", 9))
        needed = 9 * H if (can_reduce or had3h) else 11 * H
    plan.daily_rest_before = fmt(shift_start + window - needed)

    # ── Prossimo riposo settimanale ─────────────────────────────────────────
    limit = (288 if s.isbus else 144) * H
    if last_weekly:
        plan.weekly_rest_before = fmt(last_weekly.end + limit)
        reduced_prev = last_weekly.kind == "WeeklyReduced"
        plan.weekly_rest_hours = 45 if reduced_prev else 24
        if reduced_prev:
            plan.weekly_regular_before = fmt(last_weekly.end + limit)
        else:
            plan.weekly_regular_before = fmt(last_weekly.end + 2 * limit + 24 * H)

    # ── Riposo attuale e possibili orari di fine ────────────────────────────
    if in_rest:
        start = last.start
        plan.current_rest_start = fmt(start)
        plan.current_rest_len = now - start
        opts = []
        if can_reduce and not crew:
            opts.append(EndOption("Giornaliero Ridotto (9 ore)", fmt(start + 9 * H)))
        if any(x.activity == REST and x.length >= 3 * H
               for x in tl.between(shift_start, start)):
            opts.append(EndOption("Giornaliero Regolare (9 ore, frazionato)", fmt(start + 9 * H)))
        if crew:
            opts.append(EndOption("Giornaliero Regolare (9 ore, multipresenza)", fmt(start + 9 * H)))
        opts.append(EndOption("Giornaliero Regolare (11 ore)", fmt(start + 11 * H)))
        opts.append(EndOption("Settimanale Ridotto (24 ore)", fmt(start + 24 * H)))
        opts.append(EndOption("Settimanale Regolare (45 ore)", fmt(start + 45 * H)))
        if s.isbus:
            opts.append(EndOption("Settimanale Ridotto bus (69 ore)", fmt(start + 69 * H)))
            opts.append(EndOption("Settimanale Regolare bus (90 ore)", fmt(start + 90 * H)))
        plan.end_options = opts

    # ── Compensazioni ancora dovute ─────────────────────────────────────────
    from models.rest_report import _compensations
    comp = _compensations(tl, rests, first_day)
    for r in rests:
        state, text = comp.get(id(r), ("", ""))
        if state == "required":
            plan.compensations.append(f"{fmt(r.start)}: {text}")

    # ── Messaggi ──────────────────────────────────────────────
    if any(g.over or g.left == 0 for g in plan.driving[:3]) or plan.driving[3].left == 0:
        plan.messages.append("Devi finire di lavorare!")
    if in_rest and plan.current_rest_len < 9 * H:
        plan.messages.append("Continua il periodo di riposo!")
    if not plan.messages:
        plan.messages.append("Puoi ancora lavorare")
    return plan

"""
models/worktime.py
==================
Riepilogo del tempo di lavoro (per giorno o per turno, settimanale o mensile).

Colonne: Guida, Lavoro, Disponibilità, Interruzione, km.
Riga di totale "G + L + D + P = totale" dove entrano solo le voci retribuite
secondo le impostazioni:
  - "Disponibilità a pagamento" (payedavailability)
  - "Interruzione pagata" (payedbreaktype): NO, ALL, ALL_EXCEPTREQUIRED,
    SHORTn (solo pause < n min), ALL_EXCEPTFIRSTn (ogni pausa meno i primi n min)
Periodi: settimana dal primo giorno scelto (lun/dom), mese dal giorno N al N-1.
Fascia salariale maggiorata (higherwageperiod): stesse colonne limitate alla fascia.
Contatori di periodo: giorni lavorati, turni con lavoro notturno, notti fuori
dal paese base, giorni di ferie (dati manuali, Fase 8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from models.settings import COUNTRY_OPTIONS, Settings, load_settings
from models.timeline import (AVAIL, DRIVE, REST, WORK, Segment, Timeline, build_shifts,
                             classify_rests)

H = 60


@dataclass
class Sums:
    drive: int = 0
    work: int = 0
    avail: int = 0
    brk: int = 0          # interruzione retribuita
    km: float = 0.0
    brk_all: int = 0      # tutte le interruzioni (colonna "INTERRUZIONE" dell'Excel per turno)

    def add(self, o: "Sums"):
        self.drive += o.drive
        self.work += o.work
        self.avail += o.avail
        self.brk += o.brk
        self.km += o.km
        self.brk_all += o.brk_all

    def total(self, s: Settings) -> int:
        """Tempo di lavoro retribuito = G + L (+ D) (+ P)."""
        return (self.drive + self.work + (self.avail if s.payedavailability else 0)
                + self.brk)


@dataclass
class Row:
    label: str            # "03 mer" oppure periodo del turno
    sums: Sums
    wage: Optional[Sums] = None     # stesse colonne nella fascia maggiorata
    kind: str = "day"     # "day" | "shift" | "rest"
    start: int = 0
    end: int = 0


@dataclass
class Period:
    label: str            # "1 luglio 2024 - 31 luglio 2024"
    rows: List[Row] = field(default_factory=list)
    sums: Sums = field(default_factory=Sums)
    wage: Optional[Sums] = None
    work_days: int = 0
    night_shifts: int = 0
    nights_abroad: int = 0
    holidays: int = 0
    start: int = 0
    end: int = 0


_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre"]
_DAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def _paid_break(seg_len: int, rule: str) -> int:
    """Minuti retribuiti di una singola pausa secondo l'impostazione."""
    if rule == "NO":
        return 0
    if rule in ("ALL", "ALL_EXCEPTREQUIRED"):
        return seg_len
    if rule.startswith("SHORT"):
        return seg_len if seg_len < int(rule[5:]) else 0
    if rule.startswith("ALL_EXCEPTFIRST"):
        return max(0, seg_len - int(rule[15:]))
    return 0


def _sums(tl: Timeline, segs: List[Segment], s: Settings, rest_marks) -> Sums:
    out = Sums()
    breaks = []
    for x in segs:
        if x.activity == DRIVE:
            out.drive += x.length
        elif x.activity == WORK:
            out.work += x.length
        elif x.activity == AVAIL:
            out.avail += x.length
        elif x.activity == REST and not rest_marks(x):
            breaks.append(x.length)
    out.brk = sum(_paid_break(b, s.payedbreaktype) for b in breaks)
    out.brk_all = sum(breaks)
    if s.payedbreaktype == "ALL_EXCEPTREQUIRED" and out.drive > 270:
        out.brk = max(0, out.brk - 45)          # la pausa obbligatoria non è pagata
    return out


def _clip(segs, a, b):
    return [Segment(max(x.start, a), min(x.end, b), x.activity, x.crew, x.manual, x.unknown)
            for x in segs if x.end > a and x.start < b]


def build_worktime(cd, view: str = "weekly_day", settings: Settings = None,
                   order: str = "inc_inc") -> List[Period]:
    """
    view: weekly_day | monthly_day | weekly_shift | monthly_shift
    order: inc_inc (dal più vecchio) | dec_dec | dec_inc  
    """
    s = settings or load_settings()
    tl = Timeline(cd.activities, s.timezone)
    if not tl.segments:
        return []
    rests = [r for r in classify_rests(tl) if r.length > 0]
    shifts = build_shifts(tl, rests)

    def is_daily_rest(x):                      # parte di un riposo giornaliero/settimanale
        return any(r.start <= x.start and x.end <= r.end for r in rests)

    wage = s.wage_period
    km_by_day: Dict[str, float] = {d.date: d.distance_km for d in cd.activities}
    base_country = s.basecountry

    # ── confini dei periodi ──
    def period_bounds(minute: int):
        d = tl.local(minute).date()
        if view.startswith("weekly"):
            ws = tl.week_start(minute, s.firstdayofweek)
            we = tl.week_start(ws + 8 * 24 * H, s.firstdayofweek)
            a, b = tl.local(ws).date(), tl.local(we - 1).date()
        else:
            n = s.firstdayofmonth
            first = d.replace(day=n) if d.day >= n else _prev_month(d).replace(day=n)
            nxt = _next_month(first).replace(day=n)
            ws, we = tl.day_start(first), tl.day_start(nxt)
            a, b = first, nxt - timedelta(days=1)
        label = f"{a.day} {_MONTHS[a.month - 1]} {a.year} - {b.day} {_MONTHS[b.month - 1]} {b.year}"
        return ws, we, label

    periods: Dict[int, Period] = {}

    def get_period(minute):
        ws, we, label = period_bounds(minute)
        if ws not in periods:
            periods[ws] = Period(label=label, start=ws, end=we,
                                 wage=Sums() if wage else None)
        return periods[ws]

    def wage_sums(segs, a, b):
        if not wage:
            return None
        out = Sums()
        d = tl.local(a).date() - timedelta(days=1)
        while tl.day_start(d) < b:
            w0 = tl.day_start(d) + wage[0] * H
            w1 = tl.day_start(d + timedelta(days=1 if wage[1] <= wage[0] else 0)) + wage[1] * H
            out.add(_sums(tl, _clip(segs, max(w0, a), min(w1, b)), s, is_daily_rest))
            d += timedelta(days=1)
        return out

    if view.endswith("_day"):
        d = tl.local(tl.start).date()
        last = tl.local(tl.end - 1).date()
        while d <= last:
            a, b = tl.day_start(d), tl.day_start(d + timedelta(days=1))
            segs = tl.between(a, b)
            sm = _sums(tl, segs, s, is_daily_rest)
            sm.km = km_by_day.get(d.isoformat(), 0.0)
            p = get_period(a)
            ws = wage_sums(segs, a, b)
            p.rows.append(Row(f"{d.day:02d} {_DAYS[d.weekday()]}", sm, ws, "day", a, b))
            p.sums.add(sm)
            if ws:
                p.wage.add(ws)
            if sm.drive + sm.work > 0:
                p.work_days += 1
            d += timedelta(days=1)
    else:
        for i, sh in enumerate(shifts):
            sm = _sums(tl, sh.segments, s, is_daily_rest)
            d0, d1 = tl.local(sh.start).date(), tl.local(sh.end - 1).date()
            sm.km = sum(km for k, km in km_by_day.items()
                        if d0.isoformat() <= k <= d1.isoformat()
                        and sh.minutes(DRIVE) > 0) if d0 == d1 else \
                sum(km_by_day.get(k.isoformat(), 0.0) for k in _days(d0, d1))
            p = get_period(sh.start)
            ws = wage_sums(sh.segments, sh.start, sh.end)
            p.rows.append(Row(f"{tl.fmt(sh.start)} - {tl.fmt(sh.end)} "
                              f"({_hm(sh.end - sh.start)})", sm, ws, "shift", sh.start,
                              sh.end))
            p.sums.add(sm)
            if ws:
                p.wage.add(ws)
            if sh.rest_after:
                r = sh.rest_after
                p.rows.append(Row(f"{tl.fmt(r.start)} - {tl.fmt(r.end)} "
                                  f"({_hm(r.length)})", Sums(), None, "rest", r.start + 1,
                                  r.end))
        work_days = {}
        for sh in shifts:
            work_days.setdefault(get_period(sh.start).start, set()).add(
                tl.local(sh.start).date())
        for k, v in work_days.items():
            periods[k].work_days = len(v)

    # turni con lavoro notturno e notti fuori dal paese base
    ns, ne = (0, 7) if base_country == "IT" else s.night_hours
    for sh in shifts:
        if any(x.activity in (DRIVE, WORK) and
               (ns <= tl.local(x.start).hour < ne or ns <= tl.local(x.end - 1).hour < ne)
               for x in sh.segments):
            get_period(sh.start).night_shifts += 1
    for r in rests:
        c = _country_at(cd, r.start)
        if c and base_country and c != base_country:
            get_period(r.start).nights_abroad += 1

    for h in getattr(cd, "holidays", None) or []:
        for d in h.days():
            m = tl.day_start(d)
            if tl.start <= m < tl.end + 24 * H:
                get_period(m).holidays += 1

    out = sorted(periods.values(), key=lambda p: p.start)
    for p in out:
        p.rows.sort(key=lambda r: r.start)
    if order in ("dec_dec", "dec_inc"):
        out.reverse()
    if order == "dec_dec":
        for p in out:
            p.rows.reverse()
    return out


def _country_at(cd, minute: int) -> str:
    from models.rest_report import _country_of
    return _country_of(cd, minute)


def _days(a: date, b: date):
    while a <= b:
        yield a
        a += timedelta(days=1)


def _prev_month(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def _next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"

"""
models/timeline.py
==================
Timeline continua delle attività e classificazione di riposi e turni.

È la base comune di infrazioni, periodi di riposo e pianificazione:
  - tempo assoluto in MINUTI UTC dall'epoca Unix (i giorni del DDD sono in UTC)
  - conversione nel fuso orario scelto nelle impostazioni solo dove serve
    (settimane di calendario, fascia notturna, date mostrate)
  - riposi giornalieri/settimanali e turni (periodi di lavoro tra due riposi)

Regole dei riposi (Reg. CE 561/2006, Art. 4 e 8):
  - riposo giornaliero regolare ≥ 11h, ridotto ≥ 9h (max 3 tra due settimanali),
    frazionato 3h + 9h, multipresenza ≥ 9h entro 30h
  - riposo settimanale regolare ≥ 45h, ridotto ≥ 24h
  - il riposo giornaliero va completato entro 24h dalla fine del precedente
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from models.card_data import DayActivity

DRIVE, WORK, AVAIL, REST = "Guida", "Lavoro", "Disponibilità", "Riposo"

H = 60                      # minuti in un'ora
DAILY_REGULAR = 11 * H
DAILY_REDUCED = 9 * H
SPLIT_FIRST = 3 * H
WEEKLY_REGULAR = 45 * H
WEEKLY_REDUCED = 24 * H
SHORT_BREAK = 15            # pause < 15 min contano come lavoro (Dir. 2002/15)

_EPOCH = date(1970, 1, 1)


@dataclass
class Segment:
    start: int              # minuti UTC dall'epoca
    end: int
    activity: str
    crew: bool = False      # guida in equipaggio
    manual: bool = False    # inserito a mano (carta non inserita)
    unknown: bool = False   # carta non inserita, attività sconosciuta

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def solo(self) -> bool:
        """Conducente solo con carta inserita."""
        return not (self.crew or self.manual or self.unknown)


@dataclass
class Rest:
    """Periodo di riposo usato come riposo giornaliero o settimanale."""
    start: int
    end: int
    kind: str               # WeeklyNormal | WeeklyReduced | DailyNormal | DailySplit
                            # | DailyReduced | DailyStaff | Insufficient
    in_window: int = 0      # durata utile entro la finestra di 24h/30h
    truncated: bool = False # tagliato dall'inizio/fine dei dati
    split_first: Optional[tuple] = None   # (inizio, fine) della prima parte (3h)

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def weekly(self) -> bool:
        return self.kind.startswith("Weekly")


@dataclass
class Shift:
    """Turno: periodo tra la fine di un riposo e l'inizio del successivo."""
    start: int
    end: int
    rest_before: Optional[Rest]
    rest_after: Optional[Rest]
    segments: List[Segment] = field(default_factory=list)
    crew: bool = False

    def minutes(self, *activities) -> int:
        return sum(s.length for s in self.segments if s.activity in activities)


class Timeline:
    """Timeline continua di tutte le attività del file."""

    def __init__(self, activities: List[DayActivity], tz: str = "Europe/Rome"):
        self.tz = ZoneInfo(tz) if tz else datetime.now().astimezone().tzinfo
        days = sorted(activities, key=lambda d: d.date)
        self.segments: List[Segment] = []
        self.start = self.end = 0
        if not days:
            return
        raw: List[Segment] = []
        prev = Segment(0, 0, REST)
        next_free = None
        for day in days:
            base = (date.fromisoformat(day.date) - _EPOCH).days * 1440
            if next_free is not None and base > next_free:
                # giorni assenti dal buffer → riposo; se la carta era estratta il
                # periodo resta "sconosciuto"/manuale come il segmento precedente
                raw.append(Segment(next_free, base, REST, False, prev.manual and prev.activity == REST,
                                   prev.unknown))
            ch = sorted(day.changes, key=lambda c: c.time)
            if not ch:
                raw.append(Segment(base, base + 1440, REST))
                prev = raw[-1]
            else:
                if ch[0].time > 0:
                    raw.append(Segment(base, base + ch[0].time, prev.activity,
                                       prev.crew, prev.manual, prev.unknown))
                for i, c in enumerate(ch):
                    t1 = ch[i + 1].time if i + 1 < len(ch) else 1440
                    if t1 > c.time:
                        raw.append(Segment(base + c.time, base + t1, c.activity, c.crew,
                                           c.manual,
                                           not c.card_inserted and not c.manual))
                prev = raw[-1]
            next_free = base + 1440
        self.segments = self._merge(raw)
        self.start = self.segments[0].start
        self.end = self.segments[-1].end

    @staticmethod
    def _merge(raw: List[Segment]) -> List[Segment]:
        """Fonde segmenti contigui con stessa attività e stessa modalità."""
        out: List[Segment] = []
        for s in raw:
            last = out[-1] if out else None
            if last and last.activity == s.activity and last.end >= s.start \
                    and (last.crew, last.manual, last.unknown) == (s.crew, s.manual, s.unknown):
                last.end = max(last.end, s.end)
            else:
                out.append(Segment(s.start, s.end, s.activity, s.crew, s.manual, s.unknown))
        return out

    def reclassify_as_rest(self, segs: List[Segment]):
        """Trasforma in riposo i segmenti indicati (uso scorretto del commutatore)."""
        ids = {(s.start, s.end) for s in segs}
        for s in self.segments:
            if (s.start, s.end) in ids:
                s.activity = REST
        self.segments = self._merge(self.segments)

    # ── Conversioni ora locale ────────────────────────────────────────────────
    def local(self, minute: int) -> datetime:
        return datetime.fromtimestamp(minute * 60, tz=timezone.utc).astimezone(self.tz)

    def to_minute(self, dt: datetime) -> int:
        return int(dt.timestamp() // 60)

    def fmt(self, minute: int) -> str:
        """Formato: DD/MM/YY HH:MM (ora locale)."""
        return self.local(minute).strftime("%d/%m/%y %H:%M")

    def local_date(self, minute: int) -> date:
        return self.local(minute).date()

    def week_start(self, minute: int, first_day: int = 1) -> int:
        """Inizio (minuto UTC) della settimana locale che contiene `minute`.
        first_day: 1 = lunedì 00:00, 0 = domenica 00:00 (impostazione app)."""
        d = self.local(minute)
        offset = d.weekday() if first_day == 1 else (d.weekday() + 1) % 7
        start = datetime(d.year, d.month, d.day, tzinfo=self.tz) - timedelta(days=offset)
        return self.to_minute(start)

    def day_start(self, d: date) -> int:
        return self.to_minute(datetime(d.year, d.month, d.day, tzinfo=self.tz))

    # ── Interrogazioni ────────────────────────────────────────────────────────
    def window(self, start: int, end: int) -> "Timeline":
        """Copia della timeline limitata a [start, end) (stessa zona oraria)."""
        tl = object.__new__(Timeline)
        tl.tz = self.tz
        tl.segments = self.between(max(start, self.start), min(end, self.end))
        tl.start = tl.segments[0].start if tl.segments else start
        tl.end = tl.segments[-1].end if tl.segments else start
        return tl

    def _ends(self) -> List[int]:
        """Fine di ogni segmento (ordinati, senza sovrapposizioni) per la ricerca
        binaria; ricalcolata se la lista cambia."""
        segs = self.segments
        key = (id(segs), len(segs), segs[-1].end if segs else 0)
        if getattr(self, "_ends_key", None) != key:
            self._ends_cache = [s.end for s in segs]
            self._ends_key = key
        return self._ends_cache

    def between(self, start: int, end: int) -> List[Segment]:
        """Segmenti tagliati all'intervallo [start, end)."""
        out = []
        segs = self.segments
        i = bisect_right(self._ends(), start)
        while i < len(segs) and segs[i].start < end:
            s = segs[i]
            if s.end > start:
                out.append(Segment(max(s.start, start), min(s.end, end), s.activity,
                                   s.crew, s.manual, s.unknown))
            i += 1
        return out

    def minutes(self, start: int, end: int, *activities) -> int:
        return sum(s.length for s in self.between(start, end) if s.activity in activities)

    def rests(self, min_len: int = 0) -> List[Segment]:
        return [s for s in self.segments if s.activity == REST and s.length >= min_len]


WEEKLY_CANDIDATE = 20 * H    # riposi che possono valere come settimanali ridotti


def classify_rests(tl: Timeline, max_reduced: int = 3,
                   weekly: Optional[dict] = None) -> List[Rest]:
    """
    Individua i riposi giornalieri e settimanali sulla timeline.

    Algoritmo (finestra di 24h dalla fine del riposo precedente, 30h in
    multipresenza):
      1. cerca il primo riposo con almeno 9h dentro la finestra
         (≥ 11h o preceduto da ≥ 3h → regolare/frazionato, altrimenti ridotto;
          in multipresenza ≥ 9h → DailyStaff)
      2. un riposo ≥ 24h è settimanale (≥ 45h regolare, altrimenti ridotto)
      3. se nella finestra non c'è un riposo di 9h, il riposo più lungo (≥ 3h)
         chiude comunque la giornata come "Insufficient"
      4. se la finestra va oltre la fine dei dati non si giudica

    I ridotti oltre il 3° tra due settimanali vengono valutati come normali
    (DailyNormal con durata < 11h → infrazione).

    weekly: scelta dei riposi settimanali {inizio del riposo: True/False} per i
    riposi da 20h in su (vedi models/rest_optimizer.py); senza scelta è
    settimanale ogni riposo di almeno 24h.
    """
    def is_weekly(r) -> bool:
        if weekly is not None and r.length >= WEEKLY_CANDIDATE and r.start in weekly:
            return weekly[r.start]
        return r.length >= WEEKLY_REDUCED

    rests_all = tl.rests(1)
    rest_ends = [r.end for r in rests_all]
    out: List[Rest] = []
    if not rests_all:
        return out

    first = rests_all[0]
    cursor = first.end
    # Il primo riposo apre il primo turno. Se inizia con i dati la sua durata reale
    # è sconosciuta: viene registrato come troncato e non giudicato.
    at_start = first.start <= tl.start
    if is_weekly(first):
        out.append(Rest(first.start, first.end,
                        "WeeklyNormal" if first.length >= WEEKLY_REGULAR or at_start
                        else "WeeklyReduced", first.length, truncated=at_start))
    elif at_start or first.length >= SPLIT_FIRST:
        out.append(Rest(first.start, first.end, "DailyNormal", first.length, truncated=True))
    reduced = 0
    while True:
        crew = any(s.crew for s in tl.between(cursor, cursor + 30 * H) if s.activity == DRIVE)
        window = 30 * H if crew else 24 * H
        w_end = cursor + window
        inside = []
        k = bisect_right(rest_ends, cursor)
        while k < len(rests_all) and rests_all[k].start < w_end:
            r = rests_all[k]
            inside.append((r, min(r.end, w_end) - max(r.start, cursor)))
            k += 1

        chosen = None
        split_part = None
        for r, dur in inside:
            if is_weekly(r):
                chosen = (r, dur, "weekly")
                break
            if dur >= DAILY_REDUCED:
                if crew:
                    kind = "DailyStaff"
                elif dur >= DAILY_REGULAR:
                    kind = "DailyNormal"
                elif split_part:
                    kind = "DailySplit"
                else:
                    kind = "DailyReduced"
                chosen = (r, dur, kind)
                break
            if dur >= SPLIT_FIRST and split_part is None:
                split_part = (r.start, r.end)

        if chosen is None and w_end > tl.end:
            # la finestra supera la fine dei dati: un eventuale riposo finale
            # (anche incompleto) viene registrato senza giudicarlo
            tail = next((r for r, _ in inside if r.end >= tl.end and r.length >= SPLIT_FIRST), None)
            if tail:
                out.append(Rest(tail.start, tail.end,
                                "WeeklyNormal" if is_weekly(tail) else "DailyNormal",
                                tail.length, truncated=True))
            break

        if chosen is not None:
            r, dur, kind = chosen
            if kind == "weekly":
                truncated = r.end >= tl.end
                kind = "WeeklyNormal" if r.length >= WEEKLY_REGULAR or truncated else "WeeklyReduced"
                out.append(Rest(r.start, r.end, kind, dur, truncated=truncated))
                reduced = 0
            else:
                if kind == "DailyReduced":
                    reduced += 1
                    if reduced > max_reduced:
                        kind = "DailyNormal"      # ridotti esauriti: serve un regolare
                out.append(Rest(r.start, r.end, kind, dur,
                                split_first=split_part if kind == "DailySplit" else None))
            cursor = r.end
            continue

        best = max(inside, key=lambda x: x[1], default=None)
        if best and best[1] >= SPLIT_FIRST:
            r, dur = best
            out.append(Rest(r.start, r.end, "Insufficient", dur))
            cursor = r.end
        else:
            out.append(Rest(cursor + window, cursor + window, "Insufficient", 0))
            nxt = next((r for r in rests_all if r.start >= w_end and r.length >= DAILY_REDUCED),
                       None)
            if nxt is None:
                break
            cursor = nxt.end
            out.append(Rest(nxt.start, nxt.end,
                            "DailyNormal" if not is_weekly(nxt) else
                            "WeeklyNormal" if nxt.length >= WEEKLY_REGULAR else "WeeklyReduced",
                            nxt.length))
    return out


def build_shifts(tl: Timeline, rests: List[Rest]) -> List[Shift]:
    """Turni = intervalli di attività tra due riposi giornalieri/settimanali."""
    shifts: List[Shift] = []
    marks = sorted((r for r in rests if r.length > 0), key=lambda r: r.start)
    prev: Optional[Rest] = None
    t = tl.start
    for r in marks + [None]:
        end = r.start if r else tl.end
        start = prev.end if prev else t
        if end > start:
            segs = tl.between(start, end)
            if any(s.activity != REST for s in segs):
                shifts.append(Shift(start, end, prev, r, segs,
                                    crew=any(s.crew for s in segs if s.activity == DRIVE)))
        if r:
            prev = r
    return shifts

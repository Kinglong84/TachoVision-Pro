"""
models/rest_optimizer.py
========================
Scelta dei riposi settimanali a penalità minima.

Un riposo lungo può essere letto in più modi: settimanale regolare (≥ 45h),
settimanale ridotto (≥ 20h, con infrazione graduata se < 24h) oppure semplice
riposo giornaliero. La lettura cambia le infrazioni sui riposi e sulla guida
giornaliera, quindi si prova ogni combinazione ammessa e si tiene quella con la
somma di penalità più bassa (MI 500, SI 1000, VSI 6000, MSI 9000).

Ricerca (con potatura):
  - candidati: riposi di almeno 20h; quelli di almeno 120h sono sempre
    settimanali e dividono la ricerca in segmenti indipendenti;
  - da un riposo settimanale si prova come successivo il primo e il secondo
    candidato; se il secondo è già oltre 6 giorni (12 per i bus) si provano anche
    i seguenti;
  - non più di 3 riposi settimanali negli ultimi 7 giorni;
  - se un segmento ha troppe combinazioni si fissa come settimanale il riposo
    più lungo e isolato e si risolvono le due metà.
A parità di penalità resta la lettura standard (settimanale da 24h in su).
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from models.timeline import (H, WEEKLY_CANDIDATE, WEEKLY_REDUCED, WEEKLY_REGULAR, Rest,
                             Timeline, classify_rests)

FORCED = 120 * H          # riposi così lunghi sono sempre settimanali
MAX_LEAVES = 400          # combinazioni oltre le quali il segmento viene diviso

_CACHE: Dict[tuple, Dict[int, bool]] = {}


def _key(tl: Timeline, settings) -> tuple:
    return (settings.isbus, settings.timezone, settings.firstdayofweek,
            tuple((s.start, s.end, s.activity, s.crew, s.manual, s.unknown)
                  for s in tl.segments))


def best_weekly(tl: Timeline, settings,
                penalty: Callable[[Dict[int, bool], int, int], int]) -> Dict[int, bool]:
    """Scelta {inizio riposo: settimanale?} per i riposi da 20h in su."""
    key = _key(tl, settings)
    if key in _CACHE:
        return _CACHE[key]
    cands = tl.rests(WEEKLY_CANDIDATE)
    choice = {c.start: c.length >= WEEKLY_REDUCED for c in cands}
    if not cands:
        _CACHE[key] = choice
        return choice
    window = (12 if settings.isbus else 6) * 24 * H

    # sempre settimanali: i riposi lunghissimi e quelli con cui iniziano o finiscono
    # i dati (come l'inizio e la fine della catena dei riposi)
    forced = [i for i, c in enumerate(cands)
              if c.length >= FORCED or c.start <= tl.start or c.end >= tl.end]
    for i in forced:
        choice[cands[i].start] = True
    bounds = [-1] + forced + [len(cands)]

    def t_end(i):                   # fine del settimanale i (-1 = inizio dati)
        return tl.start if i < 0 else cands[i].end

    def segment(a: int, b: int):
        """Sceglie i settimanali tra i candidati a+1 … b-1 (a e b sono fissi)."""
        free = list(range(a + 1, b))
        if not free:
            return
        lo = tl.start if a < 0 else cands[a].start
        hi = tl.end if b >= len(cands) else cands[b].end
        leaves: List[List[int]] = []

        def dfs(i: int, picked: List[int]):
            if len(leaves) > MAX_LEAVES:
                return
            explored = False
            for j in range(i + 1, b + 1):
                if j == b:
                    leaves.append(list(picked))
                    return
                near = sum(1 for p in picked if cands[p].end > cands[j].start - 7 * 24 * H)
                if near < 3:
                    dfs(j, picked + [j])
                if cands[j].start < t_end(i) + window and explored:
                    return
                explored = True

        dfs(a, [])
        if len(leaves) > MAX_LEAVES:
            # troppe combinazioni: fissa il riposo lungo più isolato e dividi
            best, gap = None, -1
            for j in free:
                if cands[j].length >= WEEKLY_REGULAR:
                    g = cands[j].start - t_end(j - 1 if j - 1 > a else a)
                    if g > gap:
                        best, gap = j, g
            if best is None:
                best = max(free, key=lambda j: cands[j].length)
            choice[cands[best].start] = True
            segment(a, best)
            segment(best, b)
            return

        base = dict(choice)
        best_pen = penalty(base, lo, hi)
        best_set = None
        for picked in leaves:
            trial = dict(choice)
            for j in free:
                trial[cands[j].start] = j in picked
            if trial == base:
                continue
            p = penalty(trial, lo, hi)
            if p < best_pen:
                best_pen, best_set = p, trial
        if best_set is not None:
            choice.update(best_set)

    for a, b in zip(bounds, bounds[1:]):
        segment(a, b)
    if len(_CACHE) > 50:
        _CACHE.clear()
    _CACHE[key] = choice
    return choice


MARGIN = 10 * 24 * H      # contesto attorno al segmento per valutare le penalità


def rests_for(tl: Timeline, settings) -> List[Rest]:
    """Riposi giornalieri e settimanali con la scelta a penalità minima."""
    from models.violations import rest_penalty
    windows: Dict[tuple, Timeline] = {}

    def penalty(w, a, b):
        # la scelta cambia solo il segmento: si valuta su una finestra locale
        if (a, b) not in windows:
            windows[(a, b)] = tl.window(a - MARGIN, b + MARGIN)
        return rest_penalty(windows[(a, b)], settings, w, a, b)

    choice = best_weekly(tl, settings, penalty)
    return classify_rests(tl, weekly=choice)

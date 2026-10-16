"""
models/history.py
=================
Storico unico del conducente: unione degli scarichi della stessa persona.

Infrazioni, Pianificazione e ottimizzazione dei riposi non guardano solo il file
aperto: si aggiungono i dati più vecchi presi dagli altri scarichi dello
stesso conducente in archivio.

Unione:
  - scarichi della stessa persona = stessi primi 14 caratteri della carta (carta
    rinnovata/sostituita) oppure stesso nome, cognome e data di nascita;
  - dal più recente al più vecchio, solo quelli scaricati prima del file aperto e
    da non più di 730 giorni; si salta uno scarico a meno di 4 giorni dall'ultimo
    unito (salvo cambio di carta);
  - il file vecchio deve finire prima della fine dei dati già uniti;
  - per ogni tipo (attività, inserimento/estrazione carta, luoghi, eventi, guasti,
    condizioni, posizioni GPS) si aggiungono solo i record precedenti al primo
    record dello stesso tipo già presente;
  - "Dati mancanti" (DataGap): se tra l'ultimo record del file vecchio e la prima
    attività/inserimento carta dei dati uniti passa più di 1 minuto, il buco è
    contato come riposo e segnalato come avvertenza;
  - alla fine si tengono solo gli ultimi 27 mesi.

Scarico entro 28 giorni (attivo con l'impostazione "Timestamp della
carta"): per ogni scarico della carta degli ultimi 1000 giorni si prende lo scarico
precedente = il più recente tra la data registrata nella carta (EF_CARD_DOWNLOAD,
dal 02/01/2017) e lo scarico precedente in archivio; se passano più di 28 giorni
(e al massimo 2190) è un'infrazione minore "CardDownload_28".

Copie dello stesso scarico salvate più volte in archivio (stessi dati) contano
una volta sola, con la data di scarico più vecchia.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

_EPOCH = date(1970, 1, 1)
MERGE_MAX_DAYS = 730  # scarichi più vecchi di 2 anni non si uniscono
MERGE_MIN_STEP = 4  # giorni minimi tra due scarichi uniti
KEEP_MONTHS = 27  # storico mantenuto
GAP_MIN_SECONDS = 60  # buco minimo per "Dati mancanti"
DL_LOOKBACK = 1000  # scarichi controllati per i 28 giorni
DL_MIN, DL_MAX = 28, 2190  # 28 < giorni <= 2190
CARD_STAMP_FROM = datetime(2017, 1, 2)


# ── utilità ─────────────────────────────────────────────────────────────────

def _dt(text: str) -> Optional[datetime]:
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime((text or "").strip(), fmt)
        except ValueError:
            pass
    return None


def _min(text: str) -> Optional[int]:
    """Testo "DD/MM/YYYY HH:MM" (UTC, come nel DDD) → minuti UTC dall'epoca."""
    d = _dt(text)
    return int(d.replace(tzinfo=timezone.utc).timestamp() // 60) if d else None


def _day_base(day) -> int:
    return (date.fromisoformat(day.date) - _EPOCH).days * 1440


def same_driver(a, b) -> bool:
    """stessa carta (primi 14 caratteri) o stessa persona."""
    ca, cb = (a.card_number or "").replace(" ", ""), (b.card_number or "").replace(" ", "")
    if ca and cb and ca[:14] == cb[:14]:
        return True
    norm = lambda s: (s or "").replace(" ", "").lower()
    names_a = {norm(a.firstname), norm(a.surname)}
    names_b = {norm(b.firstname), norm(b.surname)}
    return (bool(norm(a.surname)) and names_a == names_b
            and norm(a.birth_date) == norm(b.birth_date) != "")


# ── tempi per tipo di record (minuti UTC) ────────────────────────────────────

def _act_times(cd) -> List[int]:
    out = []
    for day in cd.activities:
        base = _day_base(day)
        out += [base + c.time for c in day.changes]
    return out


def _card_times(cd) -> List[int]:
    out = []
    for v in cd.vehicle_sessions:
        for t in (v.first_use_utc, v.last_use_utc):
            if t:
                out.append(t // 60)
    return out


def _place_time(p) -> Optional[int]:
    return p.ts_utc // 60 if p.ts_utc else _min(p.datetime)


_KINDS = {
    "places": _place_time,
    "events": lambda e: _min(e.begin_time),
    "faults": lambda e: _min(e.begin_time),
    "specific_conditions": lambda c: _min(c.entry_time),
    "gnss_records": lambda g: _min(g.timestamp),
}


def first_last(cd) -> Tuple[Optional[int], Optional[int]]:
    """Primo e ultimo record del file (qualsiasi tipo)."""
    times = _act_times(cd) + _card_times(cd)
    for attr, fn in _KINDS.items():
        times += [t for t in (fn(x) for x in getattr(cd, attr, []) or []) if t is not None]
    return (min(times), max(times)) if times else (None, None)


def _place_range(cd) -> Optional[Tuple[int, int]]:
    """Intervallo coperto dal registro luoghi (circolare) di un file."""
    ts = [t for t in (_place_time(p) for p in cd.places) if t is not None]
    return (min(ts), max(ts)) if ts else None


def _drop_after(cd, limit: datetime):
    """Toglie i record successivi allo scarico: in un file scaricato in quella data
    non possono esserci (falsi positivi del parser, es. luoghi datati un anno dopo
    lo scarico in un file di prova reale)."""
    lim = int(limit.replace(tzinfo=timezone.utc).timestamp() // 60)
    cd.activities = [d for d in cd.activities if _day_base(d) < lim]
    cd.vehicle_sessions = [v for v in cd.vehicle_sessions
                           if not v.first_use_utc or v.first_use_utc // 60 < lim]
    for attr, fn in _KINDS.items():
        setattr(cd, attr, [x for x in getattr(cd, attr, []) or []
                           if fn(x) is None or fn(x) < lim])


# ── scarichi in archivio ─────────────────────────────────────────────────────

_PARSED: dict = {}            # file d'archivio già letti (per sha256)
_HISTORY: dict = {}           # storici già calcolati

@dataclass
class Download:
    filename: str
    when: datetime              # data di scarico (ora locale come nell'archivio)
    cd: object                  # CardData (senza dati manuali)
    card_stamp: Optional[datetime] = None   # EF_CARD_DOWNLOAD registrato nella carta


def _signature(cd):
    days = sorted(d.date for d in cd.activities)
    return (days[0], days[-1], len(days),
            sum(len(d.changes) for d in cd.activities)) if days else None


def archive_downloads(driver, archive=None) -> List[Download]:
    """Scarichi in archivio della stessa persona, dal più recente al più vecchio."""
    from models.parser import parse_ddd
    from services.archive_service import get_archive
    arch = archive or get_archive()
    groups = {}
    for e in arch.list_entries():
        when = _dt(e.download_date)
        if when is None:
            continue
        raw = arch.get_bytes(e.filename)
        if not raw:
            continue
        key = e.sha256 or e.filename
        if key not in _PARSED:
            try:
                _PARSED[key] = parse_ddd(raw)
            except Exception as ex:      # un file rovinato non deve bloccare le infrazioni
                log.warning("Storico: %s non leggibile (%s)", e.filename, ex)
                _PARSED[key] = None
        if _PARSED[key] is None:
            continue
        cd = copy.deepcopy(_PARSED[key])
        if not same_driver(driver, cd.driver):
            continue
        sig = _signature(cd)
        if sig is None:
            continue
        stamp = _dt(cd.driver.last_download)
        if stamp is not None and stamp < CARD_STAMP_FROM:
            stamp = None
        _drop_after(cd, when + timedelta(days=1))
        dl = Download(e.filename, when, cd, stamp)
        # copie dello stesso scarico: conta quella con la data più vecchia
        if sig not in groups or when < groups[sig].when:
            groups[sig] = dl
    return sorted(groups.values(), key=lambda d: d.when, reverse=True)


# ── unione ──────────────────────────────────────────────────────────────────

def _to_rest_from(cd, start_min: int):
    """le attività interamente nel buco diventano riposo."""
    for day in cd.activities:
        base = _day_base(day)
        for c in day.changes:
            if base + c.time >= start_min:
                c.activity, c.manual, c.crew, c.card_inserted = "Riposo", False, False, True


def _merge_older(cur, old) -> Optional[Tuple[int, int]]:
    """Aggiunge a `cur` i record di `old` precedenti al primo dello stesso tipo.
    Ritorna il buco (inizio, fine) in minuti UTC se c'è."""
    old = copy.deepcopy(old)
    acts = _act_times(cur)
    cards = _card_times(cur)
    first_act = min(acts) if acts else None
    first_card = min(cards) if cards else None
    _, old_last = first_last(old)

    gap = None
    ends = [t for t in (first_act, first_card) if t is not None]
    if ends and old_last is not None and (min(ends) - old_last) * 60 > GAP_MIN_SECONDS:
        gap = (old_last, min(ends))
        _to_rest_from(old, old_last)

    # attività: giorni interi prima del primo giorno, e la parte iniziale dello stesso giorno
    if first_act is None:
        cur.activities = list(old.activities) + list(cur.activities)
    else:
        first_day = min(cur.activities, key=lambda d: d.date)
        add = []
        for day in old.activities:
            if day.date < first_day.date:
                add.append(day)
            elif day.date == first_day.date:
                lim = first_act - _day_base(first_day)
                first_day.changes = ([c for c in day.changes if c.time < lim]
                                     + first_day.changes)
        cur.activities = add + list(cur.activities)
    cur.activities.sort(key=lambda d: d.date)

    # inserimento/estrazione carta
    cur.vehicle_sessions = [v for v in old.vehicle_sessions
                            if first_card is None or (v.first_use_utc // 60) < first_card] \
        + list(cur.vehicle_sessions)
    have = {v.vrn for v in cur.vehicles}
    cur.vehicles += [v for v in old.vehicles if v.vrn not in have]

    for attr, fn in _KINDS.items():
        mine = getattr(cur, attr, []) or []
        times = [t for t in (fn(x) for x in mine) if t is not None]
        lim = min(times) if times else None
        older = [x for x in getattr(old, attr, []) or []
                 if lim is None or ((fn(x) is not None) and fn(x) < lim)]
        setattr(cur, attr, older + list(mine))
    return gap


def _trim(cd):
    """solo gli ultimi 27 mesi prima dell'ultimo record."""
    _, last = first_last(cd)
    if last is None:
        return
    d = (_EPOCH + timedelta(days=last // 1440))
    m = d.month - KEEP_MONTHS
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    limit_day = date(y, m, min(d.day, 28))
    limit = (limit_day - _EPOCH).days * 1440
    cd.activities = [x for x in cd.activities if x.date >= limit_day.isoformat()]
    cd.vehicle_sessions = [v for v in cd.vehicle_sessions
                           if not v.first_use_utc or v.first_use_utc // 60 >= limit]
    for attr, fn in _KINDS.items():
        setattr(cd, attr, [x for x in getattr(cd, attr, []) or []
                           if fn(x) is None or fn(x) >= limit])


def build_history(cd, archive=None, downloads: List[Download] = None):
    """
    Ritorna una copia di `cd` con lo storico unito dagli altri scarichi:
      cd.data_gaps       = [[inizio, fine], ...] minuti UTC (avvertenza DataGap)
      cd.history_files   = file uniti
      cd.card_downloads  = [[precedente, attuale, giorni], ...] scarichi oltre 28 giorni
    Il file aperto resta com'è; i dati manuali sono già in `cd`.
    """
    out = copy.deepcopy(cd)
    out.data_gaps, out.history_files, out.card_downloads = [], [], []
    out.place_ranges = []
    pr = _place_range(cd)
    if pr:
        # registro luoghi del file aperto, e dopo l'ultimo luogo
        out.place_ranges = [list(pr), [pr[1], 10 ** 12]]
    try:
        dls = downloads if downloads is not None else archive_downloads(cd.driver, archive)
    except Exception as ex:
        log.warning("Storico non disponibile: %s", ex)
        return out
    now = _dt(cd.driver.last_download)
    if now is None:
        last = max((d.date for d in cd.activities), default=None)
        now = datetime.fromisoformat(last) + timedelta(days=1) if last else datetime.now()

    # ── unione ──
    _, cur_last = first_last(out)
    step_ref = now
    card = (cd.driver.card_number or "").replace(" ", "")
    for dl in dls:
        if dl.when >= now:
            continue
        if (now - dl.when).days >= MERGE_MAX_DAYS:
            break
        other = (dl.cd.driver.card_number or "").replace(" ", "")
        changed = other != card
        if (step_ref - dl.when).days < MERGE_MIN_STEP and not changed:
            continue
        _, old_last = first_last(dl.cd)
        if old_last is None or cur_last is None or not cur_last > old_last:
            continue
        pr = _place_range(dl.cd)
        if pr:
            out.place_ranges.append(list(pr))
        gap = _merge_older(out, dl.cd)
        if gap:
            out.data_gaps.append(list(gap))
        out.history_files.append(dl.filename)
        step_ref, card = dl.when, other
    _trim(out)
    out.data_gaps.sort()
    out.card_downloads = card_download_checks(cd, dls, now)
    return out


def card_download_checks(cd, dls: List[Download], now: datetime) -> List[list]:
    """scarichi della carta a più di 28 giorni dal precedente."""
    from models.settings import load_settings
    if not load_settings().cardstamping:
        return []
    # il file aperto: la data registrata nella carta è quella della sua copia in archivio
    sig = _signature(cd)
    twin = next((d for d in dls if _signature(d.cd) == sig), None)
    here = Download(cd.driver.filename or "", now, cd, twin.card_stamp if twin else None)
    items = sorted([here] + [d for d in dls if d.when < now and d is not twin],
                   key=lambda d: d.when, reverse=True)
    out, seen = [], set()
    for i, dl in enumerate(items):
        if (now - dl.when).days > DL_LOOKBACK:
            break
        prev = dl.card_stamp
        older = next((x.when for x in items[i + 1:] if x.when < dl.when), None)
        if older is not None and (prev is None or older > prev):
            prev = older
        if prev is None:
            continue
        # data registrata uguale o successiva allo scarico (carta timbrata ora): ok
        days = (dl.when.date() - prev.date()).days
        if DL_MIN < days <= DL_MAX:
            key = (prev.strftime("%Y%m%d%H%M"), dl.when.strftime("%Y%m%d%H%M"))
            if key not in seen:
                seen.add(key)
                out.append([prev.strftime("%d/%m/%Y %H:%M"), dl.when.strftime("%d/%m/%Y %H:%M"),
                            days])
    return out


def history_for(cd, archive=None):
    """build_history con cache: stesso file e stesso archivio → stesso risultato."""
    try:
        dls = archive_downloads(cd.driver, archive)
    except Exception as ex:
        log.warning("Storico non disponibile: %s", ex)
        dls = []
    from models.settings import load_settings
    key = (_signature(cd), cd.driver.card_number, cd.driver.last_download,
           len(getattr(cd, "notes", []) or []), len(getattr(cd, "holidays", []) or []),
           load_settings().cardstamping,
           tuple((d.filename, d.when) for d in dls))
    if key not in _HISTORY:
        if len(_HISTORY) > 20:
            _HISTORY.clear()
        _HISTORY[key] = build_history(cd, archive, dls)
    return _HISTORY[key]


def violations_with_history(cd, settings=None):
    """infrazioni calcolate sullo storico unito del conducente."""
    from models.violations import detect_violations
    h = history_for(cd) if cd is not None and not getattr(cd, "demo", False) else cd
    return detect_violations(h.activities, settings, h)

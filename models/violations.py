"""
models/violations.py
=====================
Motore di rilevamento infrazioni al Reg. (CE) 561/2006 e alla Direttiva 2002/15/CE.

Questo modulo è "pura logica di dominio":
  - Riceve una lista di DayActivity (dal parser)
  - Applica le regole normative EU
  - Restituisce una lista di Violation (da mostrare nella tab Infrazioni)

NON dipende da Dash, Plotly o altri moduli di presentazione.
È riutilizzabile in contesti diversi (test, CLI, API futura).

NORMATIVA DI RIFERIMENTO:
  Reg. CE 561/2006 — tempi di guida, pause e riposi (autisti professionali EU)
  Dir. 2002/15/CE  — orario di lavoro totale degli autotrasportatori

FLUSSO DI CALCOLO:
  detect_violations(activities)
    ↓ per ogni giorno
    _check_day_driving()          Art. 6§1 — guida giornaliera
    _check_night_work()           Dir. Art. 7 — turno notturno
    ↓ su tutti i giorni insieme
    _check_weekly_driving()       Art. 6§2-3 — guida settimanale/bisettimanale
    _check_weekly_work()          Dir. Art. 4 — ore lavoro settimanali
    _check_continuous_driving()   Art. 7 — guida continua (timeline continua)
    _check_continuous_work()      Dir. Art. 5 — lavoro continuo (timeline continua)
    _check_daily_rest()           Art. 8§2 — riposo giornaliero (timeline continua)
    _check_weekly_rest()          Art. 8§6 — riposo settimanale (timeline continua)
"""

from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional

from models.card_data import DayActivity, Violation


# ── Costanti normative (tutte in minuti salvo indicazione) ───────────────────
# Reg. CE 561/2006:
LIM_CONT_DRIVE    = 270   # Art. 7 – guida continua massima senza pausa: 4h30 = 270 min
LIM_DAY_DRIVE     = 540   # Art. 6§1 – guida giornaliera normale: 9h = 540 min
LIM_DAY_DRIVE_EXT = 600   # Art. 6§1 – guida giornaliera estesa: 10h = 600 min (max 2×/sett.)
LIM_WEEK_DRIVE    = 3360  # Art. 6§2 – guida settimanale massima: 56h = 3360 min
LIM_BIWEEK_DRIVE  = 5400  # Art. 6§3 – guida bisettimanale massima: 90h = 5400 min
LIM_DAILY_REST    = 660   # Art. 8§1 – riposo giornaliero regolare: 11h = 660 min
LIM_DAILY_REST_R  = 540   # Art. 8§1 – riposo giornaliero ridotto: 9h = 540 min (max 3×/sett.)
LIM_WEEKLY_REST   = 2700  # Art. 8§6 – riposo settimanale regolare: 45h = 2700 min
LIM_WEEKLY_REST_R = 1440  # Art. 8§6 – riposo settimanale ridotto: 24h = 1440 min
LIM_WEEKLY_WIN    = 8640  # Art. 8§6 – finestra massima tra riposi settimanali: 6×24h = 8640 min

# Dir. 2002/15/CE — Orario di lavoro autotrasportatori:
LIM_WEEK_WORK     = 2880  # Art. 4 – ore lavoro settimanali media: 48h = 2880 min
LIM_WEEK_WORK_MAX = 3600  # Art. 4 – ore lavoro settimanali massimo assoluto: 60h = 3600 min
LIM_CONT_WORK     = 360   # Art. 5 – lavoro continuo massimo senza pausa: 6h = 360 min
LIM_NIGHT_WORK    = 600   # Art. 7 – turno notturno: lavoro totale max 10h = 600 min

# Costanti di severità (usate anche in views/tabs/infrazioni.py per i colori)
SEV_VERY = "Molto Grave"   # rosso: infrazione grave (es. > 10h guida)
SEV_HIGH = "Grave"         # arancione: infrazione rilevante
SEV_LOW  = "Lieve"         # giallo: infrazione minore


# ── Funzioni helper (private: prefisso _) ────────────────────────────────────

def _week_monday(d: date) -> date:
    """
    Ritorna il lunedì della settimana a cui appartiene la data `d`.
    Usata per raggruppare i giorni per settimana ISO.
    Esempio: 2024-05-15 (mercoledì) → 2024-05-13 (lunedì)
    d.weekday() = 0 (lunedì) ... 6 (domenica)
    """
    return d - timedelta(days=d.weekday())


def _date(s: str) -> date:
    """Converte stringa 'YYYY-MM-DD' in oggetto date Python."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def _exists(violations: List[Violation], d: str, code: str) -> bool:
    """
    Verifica se un'infrazione con quel codice esiste già per quella data.
    Evita i duplicati: alcune infrazioni vengono verificate in loop
    e potrebbero essere aggiunte più volte senza questo controllo.
    """
    return any(v.date == d and v.code == code for v in violations)


def _violation(day: DayActivity, code: str, desc: str, detail: str,
               sev: str, val: int, lim: int) -> Violation:
    """
    Factory function: crea un oggetto Violation con tutti i campi richiesti.
    excess_min = quanti minuti in eccesso rispetto al limite.
    abs() gestisce il caso in cui val < lim (es. riposo insufficiente).
    """
    return Violation(
        date=day.date, date_display=day.date_display,
        code=code, description=desc, detail=detail,
        severity=sev, value_min=val, limit_min=lim,
        excess_min=abs(val - lim),   # eccesso in minuti assoluti
    )


# ── Regole su attività consecutive ────────────────────────────────────────────
# guida/lavoro continuo usano la timeline continua (vedi _timeline più sotto)

def _check_continuous_driving(all_days: List[DayActivity], viols: List[Violation]):
    """
    Art. 7 Reg. 561/2006 — Guida continua eccessiva.

    Regola: il conducente non può guidare più di 4h30 (270 min) senza
    una pausa di almeno 45 minuti (oppure due pause da 15+30 min).

    Algoritmo:
      - `cont` accumula i minuti di guida consecutivi
      - Una pausa ≥ 45 min azzera il contatore (guida continua OK)
      - Una pausa ≥ 15 min avvia la "split rest" (2 pause: 15 poi 30)
      - Se cont supera 270 min senza pausa adeguata → infrazione Grave

    Lavora sulla timeline continua: una guida 22:00→03:00 è un unico
    periodo di 5h, non 2h + 3h spezzate a mezzanotte.
    """
    d0, tl, _ = _timeline(all_days)
    cont = pause_bank = 0   # minuti di guida accumulati, "conto corrente" pausa split
    split_started = False   # True se la prima pausa da 15 min è già stata registrata

    for s, e, a in tl:
        dur = e - s   # durata del segmento in minuti
        if a == "Guida":
            cont += dur
            day = _day_at(d0, s)
            # Se supera il limite e non è già stata segnalata per questo giorno
            if cont > LIM_CONT_DRIVE and not _exists(viols, day.date, "ContinuousDriving"):
                viols.append(_violation(
                    day, "ContinuousDriving",
                    "Guida continua eccessiva",
                    f"Guida continua: {cont//60}h{cont%60:02d} senza pausa adeguata (limite 4h30)",
                    SEV_HIGH, cont, LIM_CONT_DRIVE,
                ))
        elif a == "Riposo":
            if dur >= 45:
                # Pausa piena ≥ 45 min: azzera tutto
                cont = pause_bank = 0
                split_started = False
            elif dur >= 15 and not split_started:
                # Prima parte della pausa split (≥15 min)
                split_started = True
            elif dur >= 30 and split_started:
                # Seconda parte della pausa split (≥30 min): pausa split completata
                cont = pause_bank = 0
                split_started = False


def _check_day_driving(day: DayActivity, all_days: List[DayActivity],
                       viols: List[Violation]):
    """
    Art. 6§1 — Guida giornaliera eccessiva.

    Regola:
      - Guida normale: massimo 9h (540 min)
      - Il conducente può estendere a 10h (600 min) ma solo 2 volte a settimana
      - Se supera 10h: MOLTO GRAVE (massimo assoluto violato)
      - Se supera 9h per la 3ª volta in una settimana: GRAVE (estensione esaurita)

    Il conteggio delle estensioni già usate nella settimana corrente
    viene fatto cercando i giorni precedenti nella stessa settimana ISO
    con guida > 9h.
    """
    guida = day.minutes_of("Guida")
    if guida <= LIM_DAY_DRIVE:
        return   # nessun problema, guida ≤ 9h

    # Trova il lunedì della settimana corrente
    wk = _week_monday(_date(day.date))

    # Conta quante estensioni (>9h) sono già state usate in questa settimana
    # (solo giorni PRIMA di quello corrente per non contare il giorno stesso)
    ext_used = sum(
        1 for d in all_days
        if _week_monday(_date(d.date)) == wk    # stessa settimana
        and d.date < day.date                    # solo giorni precedenti
        and d.minutes_of("Guida") > LIM_DAY_DRIVE
    )

    if guida > LIM_DAY_DRIVE_EXT:
        # Supera il massimo assoluto di 10h → MOLTO GRAVE
        code, desc, sev, lim = (
            "DayDriving_10",
            "Guida giornaliera > 10h (massimo assoluto)",
            SEV_VERY, LIM_DAY_DRIVE_EXT,
        )
    elif ext_used >= 2:
        # Ha già usato 2 estensioni questa settimana → 3ª estensione non consentita
        code, desc, sev, lim = (
            "DayDriving_9",
            "Guida giornaliera > 9h (3ª estensione, max 2/settimana)",
            SEV_HIGH, LIM_DAY_DRIVE,
        )
    else:
        return   # estensione consentita (1ª o 2ª della settimana)

    if not _exists(viols, day.date, code):
        viols.append(_violation(
            day, code, desc,
            f"Guida: {guida//60}h{guida%60:02d} (limite {lim//60}h)",
            sev, guida, lim,
        ))


# ── Timeline continua (riposi a cavallo della mezzanotte e di più giorni) ────
# Issue GitHub #2/#3: i riposi NON vanno valutati giorno per giorno. Un riposo
# notturno 18:00→08:00 è un unico riposo di 14h, e 10 giorni di ferie sono un
# unico riposo di 240h, non 10 riposi settimanali da 24h.

def _timeline(all_days: List[DayActivity]):
    """
    Unisce tutti i giorni in un'unica timeline in minuti assoluti dalla
    mezzanotte del primo giorno. Ritorna (d0, segmenti, fine_timeline) dove
    segmenti = [(inizio, fine, attività)] con attività uguali consecutive fuse.

    - Giorni mancanti nel buffer (carta non inserita) → Riposo
    - Parte del giorno prima del primo cambio → prosegue l'attività del giorno prima
    """
    days = sorted(all_days, key=lambda d: d.date)
    if not days:
        return None, [], 0
    d0 = _date(days[0].date)
    raw = []
    prev_act = "Riposo"
    next_free = 0   # primo minuto non ancora coperto
    for day in days:
        base = (_date(day.date) - d0).days * 1440
        if base > next_free:
            raw.append((next_free, base, "Riposo"))   # giorni assenti nel buffer
        segs = day.segments()
        if not segs:
            raw.append((base, base + 1440, "Riposo"))
            prev_act = "Riposo"
        else:
            if segs[0][0] > 0:
                raw.append((base, base + segs[0][0], prev_act))
            raw.extend((base + s, base + e, a) for s, e, a in segs)
            prev_act = segs[-1][2]
        next_free = base + 1440

    merged: List[list] = []
    for s, e, a in raw:
        if merged and merged[-1][2] == a and merged[-1][1] >= s:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e, a])
    return d0, [tuple(m) for m in merged], next_free


def _day_at(d0: date, minute: int) -> DayActivity:
    """DayActivity vuoto per il giorno che contiene il minuto assoluto `minute`."""
    d = d0 + timedelta(days=minute // 1440)
    return DayActivity(d.isoformat(), d.strftime("%d/%m/%Y"), 0)


def _check_daily_rest(all_days: List[DayActivity], viols: List[Violation]):
    """
    Art. 8§2 — Riposo giornaliero insufficiente.

    Regola: entro 24h dalla fine del riposo precedente (giornaliero o
    settimanale) il conducente deve aver effettuato un nuovo riposo giornaliero:
      - Regolare: ≥ 11h (660 min) entro la finestra di 24h
      - Frazionato: ≥ 3h seguito da ≥ 9h → equivale a regolare
      - Ridotto: ≥ 9h (540 min) — ammesso max 3 volte tra due riposi settimanali

    Algoritmo (su timeline continua, i riposi attraversano la mezzanotte):
      1. Parte dalla fine del primo riposo della timeline
      2. Finestra [cursore, cursore+24h]: cerca il primo riposo con almeno 9h
         dentro la finestra (conta solo la parte che cade nella finestra)
      3. ≥ 11h o frazionato → OK; 9-11h → ridotto (dal 4° in poi: Lieve)
      4. Nessun riposo ≥ 9h → Grave, con il riposo più lungo trovato
      5. Il cursore riparte dalla fine del riposo usato
      6. Se la finestra supera la fine dei dati non si giudica (scarico in corso)
    """
    d0, tl, t_end = _timeline(all_days)
    rests = [(s, e) for s, e, a in tl if a == "Riposo"]
    if not rests:
        return

    cursor = rests[0][1]   # fine del primo riposo
    reduced = 0            # riposi ridotti dall'ultimo riposo settimanale
    while True:
        w_end = cursor + 1440
        # riposi nella finestra con la durata della sola parte interna
        inside = [(s, e, min(e, w_end) - max(s, cursor))
                  for s, e in rests if e > cursor and s < w_end]

        chosen = None   # (s, e, durata_in_finestra, regolare?)
        had_3h = False  # prima parte di un riposo frazionato
        for s, e, dur in inside:
            if dur >= LIM_DAILY_REST_R:
                chosen = (s, e, dur, dur >= LIM_DAILY_REST or had_3h)
                break
            if dur >= 180:
                had_3h = True

        if chosen is None and w_end > t_end:
            break   # i dati finiscono prima della fine della finestra

        if chosen is not None:
            s, e, dur, regular = chosen
            weekly = (e - s) >= LIM_WEEKLY_REST_R
            if not regular and not weekly:
                reduced += 1
                if reduced > 3:
                    day = _day_at(d0, s)
                    if not _exists(viols, day.date, "Daily_TooShort_Reduced"):
                        viols.append(_violation(
                            day, "Daily_TooShort_Reduced",
                            "Riposo giornaliero ridotto oltre il limite",
                            f"Riposo: {dur//60}h{dur%60:02d} — {reduced}° ridotto "
                            f"(max 3 tra due riposi settimanali)",
                            SEV_LOW, dur, LIM_DAILY_REST,
                        ))
            if weekly:
                reduced = 0
            cursor = e
            continue

        # Nessun riposo ≥ 9h entro 24h: infrazione Grave
        best = max(inside, key=lambda r: r[2], default=None)
        day = _day_at(d0, cursor)
        val = best[2] if best else 0
        if not _exists(viols, day.date, "Daily_TooShort"):
            viols.append(_violation(
                day, "Daily_TooShort",
                "Riposo giornaliero insufficiente",
                f"Riposo massimo: {val//60}h{val%60:02d} (minimo 9h)",
                SEV_HIGH, val, LIM_DAILY_REST_R,
            ))
        if best and best[2] >= 180:
            cursor = best[1]   # il riposo insufficiente chiude comunque la giornata
        else:
            nxt = next((e for s, e in rests if s >= w_end and e - s >= LIM_DAILY_REST_R), None)
            if nxt is None:
                break
            cursor = nxt


def _check_continuous_work(all_days: List[DayActivity], viols: List[Violation]):
    """
    Dir. 2002/15/CE Art. 5 — Lavoro continuo eccessivo.

    Regola: non si può lavorare più di 6h (360 min) consecutivamente
    senza una pausa di almeno 30 minuti.

    "Lavoro" include: Guida, Lavoro, Disponibilità (tutte le attività non-Riposo).
    Una pausa è un periodo di Riposo ≥ 30 min.

    Differenza da Art. 7 (guida continua):
      - Art. 7: solo guida, pausa ≥ 45 min, limite 4h30
      - Dir. Art. 5: tutto il lavoro, pausa ≥ 30 min, limite 6h

    Lavora sulla timeline continua (il lavoro notturno non si spezza a mezzanotte).
    """
    d0, tl, _ = _timeline(all_days)
    cont = 0   # minuti di lavoro continuo accumulati

    for s, e, a in tl:
        if a in ("Guida", "Lavoro", "Disponibilità"):
            cont += e - s   # accumula minuti di lavoro
            day = _day_at(d0, s)
            if cont > LIM_CONT_WORK and not _exists(viols, day.date, "ContinuousWorking_6"):
                viols.append(_violation(
                    day, "ContinuousWorking_6",
                    "Lavoro continuo > 6h",
                    f"Lavoro continuo: {cont//60}h{cont%60:02d} senza pausa ≥30min",
                    SEV_LOW, cont, LIM_CONT_WORK,
                ))
        elif a == "Riposo" and (e - s) >= 30:
            # Pausa ≥ 30 min: azzera il contatore del lavoro continuo
            cont = 0


def _check_night_work(day: DayActivity, viols: List[Violation]):
    """
    Dir. 2002/15/CE Art. 7 — Turno notturno eccessivo.

    Regola: se il conducente ha lavorato almeno 4h nel periodo notturno
    (definito come 00:00-07:00, ovvero min 0-420), allora il lavoro
    totale nella giornata non può superare 10h (600 min).

    Algoritmo:
      1. Calcola i minuti di lavoro nel periodo notturno (0-420 min dal mezzanotte)
         usando min/max per intersecare il segmento con la finestra 00-07
      2. Se il lavoro notturno ≥ 4h (240 min): applica il limite di 10h totali
      3. Calcola il totale lavoro del giorno (Guida + Lavoro + Disponibilità)
      4. Se totale > 10h: infrazione Grave
    """
    # Intersezione di ogni segmento lavorativo con la fascia 00:00-07:00
    # min(e, 420): il segmento finisce al max alle 7:00 (420 min)
    # max(s, 0):   il segmento inizia al minimo a mezzanotte
    night = sum(min(e, 420) - max(s, 0)
                for s, e, a in day.segments()
                if a in ("Guida", "Lavoro") and s < 420 and e > 0)

    # Solo se il lavoro notturno è significativo (≥ 4h = 240 min)
    if night < 240:
        return

    # Calcola il lavoro totale del giorno
    total = sum(e - s for s, e, a in day.segments()
                if a in ("Guida", "Lavoro", "Disponibilità"))

    if total > LIM_NIGHT_WORK and not _exists(viols, day.date, "Working_IsNight_10"):
        viols.append(_violation(
            day, "Working_IsNight_10",
            "Superamento ore lavoro con turno notturno",
            f"Lavoro totale: {total//60}h{total%60:02d} (limite 10h con turno notturno)",
            SEV_HIGH, total, LIM_NIGHT_WORK,
        ))


# ── Regole settimanali (richiedono tutti i giorni insieme) ───────────────────

def _check_weekly_driving(all_days: List[DayActivity], viols: List[Violation]):
    """
    Art. 6§2 — Guida settimanale > 56h
    Art. 6§3 — Guida bisettimanale > 90h

    Algoritmo:
      1. Raggruppa i giorni per settimana ISO (usando _week_monday)
      2. Per ogni settimana: somma i minuti di guida
         → se > 56h: infrazione MOLTO GRAVE (attribuita all'ultimo giorno della settimana)
      3. Per ogni coppia di settimane consecutive: somma i minuti bisettimanali
         → se > 90h: infrazione MOLTO GRAVE

    La violazione viene attribuita all'ULTIMO giorno della settimana (o biweek)
    perché quello è il momento in cui il limite viene definitivamente superato.
    """
    # Dizionario: lunedì → lista dei giorni di quella settimana
    by_week: Dict[date, List[DayActivity]] = {}
    for d in all_days:
        wk = _week_monday(_date(d.date))
        by_week.setdefault(wk, []).append(d)

    weeks = sorted(by_week)   # lista dei lunedì in ordine cronologico

    for idx, wk in enumerate(weeks):
        days  = by_week[wk]
        total = sum(d.minutes_of("Guida") for d in days)   # ore guida della settimana
        last  = max(days, key=lambda d: d.date)             # ultimo giorno della settimana

        # Verifica guida settimanale > 56h
        if total > LIM_WEEK_DRIVE and not _exists(viols, last.date, "WeekDriving_one"):
            viols.append(_violation(
                last, "WeekDriving_one",
                f"Guida settimanale > 56h (sett. {wk.strftime('%d/%m/%Y')})",
                f"Guida: {total//60}h{total%60:02d} (limite 56h)",
                SEV_VERY, total, LIM_WEEK_DRIVE,
            ))

        # Verifica guida bisettimanale > 90h (questa settimana + la successiva)
        if idx + 1 < len(weeks):
            nw   = weeks[idx + 1]   # lunedì della settimana successiva
            # Somma guida bisettimanale (settimana corrente + successiva)
            biw  = total + sum(d.minutes_of("Guida") for d in by_week[nw])
            last2 = max(by_week[nw], key=lambda d: d.date)   # ultimo giorno del periodo bisettimanale
            if biw > LIM_BIWEEK_DRIVE and not _exists(viols, last2.date, "WeekDriving_two"):
                viols.append(_violation(
                    last2, "WeekDriving_two",
                    f"Guida bisettimanale > 90h ({wk.strftime('%d/%m')}+{nw.strftime('%d/%m')})",
                    f"Guida 2 settimane: {biw//60}h{biw%60:02d} (limite 90h)",
                    SEV_VERY, biw, LIM_BIWEEK_DRIVE,
                ))


def _check_weekly_work(all_days: List[DayActivity], viols: List[Violation]):
    """
    Dir. 2002/15/CE Art. 4 — Ore lavoro settimanali eccessive.

    Regola:
      - Media su 4 mesi: max 48h/settimana (LIM_WEEK_WORK = 2880 min)
      - Massimo assoluto: 60h/settimana (LIM_WEEK_WORK_MAX = 3600 min)

    "Ore lavoro" = Guida + Lavoro + Disponibilità (tutte le attività non-Riposo).

    L'infrazione "WeekWorking_60" (> 60h) è MOLTO GRAVE (massimo assoluto violato).
    L'infrazione "WeekWorking_48" (> 48h) è GRAVE (media settimanale > 48h).
    Non si registrano entrambe per la stessa settimana: prima si verifica la più grave.
    """
    # Raggruppa i giorni per settimana ISO
    by_week: Dict[date, List[DayActivity]] = {}
    for d in all_days:
        by_week.setdefault(_week_monday(_date(d.date)), []).append(d)

    for wk, days in sorted(by_week.items()):
        # Somma Guida + Lavoro + Disponibilità per ogni giorno della settimana
        total = sum(
            d.minutes_of("Guida") + d.minutes_of("Lavoro") + d.minutes_of("Disponibilità")
            for d in days
        )
        last = max(days, key=lambda d: d.date)   # infrazione attribuita all'ultimo giorno

        if total > LIM_WEEK_WORK_MAX and not _exists(viols, last.date, "WeekWorking_60"):
            viols.append(_violation(
                last, "WeekWorking_60",
                f"Ore lavoro > 60h (sett. {wk.strftime('%d/%m/%Y')})",
                f"Ore lavoro: {total//60}h{total%60:02d} (max 60h)",
                SEV_VERY, total, LIM_WEEK_WORK_MAX,
            ))
        elif total > LIM_WEEK_WORK and not _exists(viols, last.date, "WeekWorking_48"):
            viols.append(_violation(
                last, "WeekWorking_48",
                f"Ore lavoro > 48h (sett. {wk.strftime('%d/%m/%Y')})",
                f"Ore lavoro: {total//60}h{total%60:02d} (media max 48h)",
                SEV_HIGH, total, LIM_WEEK_WORK,
            ))


def _check_weekly_rest(all_days: List[DayActivity], viols: List[Violation]):
    """
    Art. 8§6 — Riposo settimanale insufficiente o in ritardo.

    RIPOSO SETTIMANALE: il conducente deve fare almeno 45h di riposo consecutivo
    ogni 6 giorni di lavoro (finestra di 144h = 6×24h).

    Regola 1 — TooLate: se tra un riposo settimanale e il precedente
      passa più di 144h (6 giorni), il riposo arriva troppo tardi → MOLTO GRAVE.

    Regola 2 — TooShort (Art. 8§6): in due settimane consecutive servono
      almeno due riposi settimanali regolari (≥ 45h), oppure uno regolare
      e uno ridotto (≥ 24h). Un singolo riposo ridotto NON è un'infrazione.

    Algoritmo (su timeline continua, issue GitHub #2/#3):
      1. Unisce i giorni in una timeline: i riposi attraversano la mezzanotte
         e più giorni (ferie = un unico riposo lungo, non N riposi da 24h)
      2. Considera solo i riposi ≥ 24h (LIM_WEEKLY_REST_R): quelli più corti
         non possono essere "riposi settimanali" per definizione
      3. Se tra la fine di un riposo settimanale e l'inizio del successivo
         passano più di 144h → infrazione TooLate
      4. Per ogni coppia di settimane (lun-dom) interamente nei dati conta i
         riposi settimanali (che vi iniziano o vi cadono per ≥ 24h): se non
         ci sono 2 riposi di cui almeno 1 regolare → infrazione TooShort.
         Un riposo tagliato dall'inizio/fine dei dati conta come regolare
         (durata reale sconosciuta); un riposo ≥ 90h nella coppia (ferie)
         la soddisfa da solo.
    """
    d0, tl, t_end = _timeline(all_days)
    weekly = [(s, e) for s, e, a in tl if a == "Riposo" and e - s >= LIM_WEEKLY_REST_R]

    last_rest_end: Optional[int] = None   # fine dell'ultimo riposo settimanale (minuti)
    for s, e in weekly:
        day = _day_at(d0, s)

        # Regola 1: verifica il gap dall'ultimo riposo settimanale
        if last_rest_end is not None:
            gap = s - last_rest_end
            if gap > LIM_WEEKLY_WIN and not _exists(viols, day.date, "Weekly_TooLate"):
                viols.append(_violation(
                    day, "Weekly_TooLate",
                    "Ritardo inizio riposo settimanale",
                    f"Attesa: {gap//60}h{gap%60:02d} (max 144h)",
                    SEV_VERY, gap, LIM_WEEKLY_WIN,
                ))

        last_rest_end = e

    # Regola 2: coppie di settimane consecutive (lunedì 00:00 → lunedì+14gg)
    if d0 is None:
        return
    week = 7 * 1440
    p0 = ((7 - d0.weekday()) % 7) * 1440   # primo lunedì nei dati
    while p0 + 2 * week <= t_end:
        p1 = p0 + 2 * week
        found = []   # durate dei riposi settimanali della coppia
        holiday = False
        for s, e in weekly:
            overlap = min(e, p1) - max(s, p0)
            if overlap >= 2 * LIM_WEEKLY_REST:
                holiday = True   # riposo ≥ 90h nella coppia (es. ferie)
            if p0 <= s < p1 or overlap >= LIM_WEEKLY_REST_R:
                truncated = s == 0 or e >= t_end
                found.append(LIM_WEEKLY_REST if truncated else e - s)
        regular = sum(1 for d in found if d >= LIM_WEEKLY_REST)

        if not holiday and (len(found) < 2 or regular < 1):
            day = _day_at(d0, p1 - 1)   # domenica della seconda settimana
            best = max(found, default=0)
            mon = d0 + timedelta(minutes=p0)
            sun = d0 + timedelta(minutes=p1 - 1)
            if not _exists(viols, day.date, "Weekly_TooShort"):
                viols.append(_violation(
                    day, "Weekly_TooShort",
                    "Riposo settimanale insufficiente in 2 settimane",
                    f"Sett. {mon.strftime('%d/%m')}–{sun.strftime('%d/%m')}: "
                    f"{len(found)} riposi settimanali, {regular} regolari "
                    f"(servono 2 regolari, o 1 regolare + 1 ridotto ≥24h)",
                    SEV_HIGH if len(found) < 2 else SEV_LOW, best, LIM_WEEKLY_REST,
                ))
        p0 += week


# ── Entry point pubblico ─────────────────────────────────────────────────────

def detect_violations(activities: List[DayActivity]) -> List[Violation]:
    """
    Funzione principale: riceve la lista DayActivity e ritorna tutte le infrazioni.

    1. Ordina i giorni cronologicamente (necessario per le regole settimanali)
    2. Applica le regole giornaliere su ogni singolo giorno
    3. Applica le regole settimanali su tutti i giorni insieme
    4. Ordina le infrazioni per data (per la visualizzazione nella tab)

    Parametro: activities = cd.activities (da CardData)
    Ritorna:   lista di Violation, ordinata per data crescente
    """
    days = sorted(activities, key=lambda d: d.date)   # ordine cronologico
    viols: List[Violation] = []

    # Regole giornaliere: eseguite su ogni giorno singolarmente
    for day in days:
        _check_day_driving(day, days, viols)     # Art. 6§1 — guida giornaliera
        _check_night_work(day, viols)            # Dir. Art. 7 — turno notturno

    # Regole su più giorni insieme (timeline continua / settimane)
    _check_weekly_driving(days, viols)   # Art. 6§2-3 — guida settimanale/bisettimanale
    _check_weekly_work(days, viols)      # Dir. Art. 4 — ore lavoro settimanali
    _check_continuous_driving(days, viols)  # Art. 7 — guida continua (timeline continua)
    _check_continuous_work(days, viols)     # Dir. Art. 5 — lavoro continuo (timeline continua)
    _check_daily_rest(days, viols)       # Art. 8§2 — riposo giornaliero (timeline continua)
    _check_weekly_rest(days, viols)      # Art. 8§6 — riposo settimanale

    # Ordina per data crescente (dalla più vecchia alla più recente)
    return sorted(viols, key=lambda v: v.date)


def violation_summary(violations: List[Violation]) -> Dict[str, int]:
    """
    Calcola il riepilogo delle infrazioni per severità.

    Ritorna un dizionario con il conteggio per ogni livello di gravità
    e il totale. Usato dalle stat-card nella tab Infrazioni.

    Esempio di output: {"Molto Grave": 2, "Grave": 5, "Lieve": 3, "total": 10}
    """
    return {
        SEV_VERY: sum(1 for v in violations if v.severity == SEV_VERY),
        SEV_HIGH: sum(1 for v in violations if v.severity == SEV_HIGH),
        SEV_LOW:  sum(1 for v in violations if v.severity == SEV_LOW),
        "total":  len(violations),
    }

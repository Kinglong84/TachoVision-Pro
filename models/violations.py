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
    _check_continuous_driving()   Art. 7 — guida continua
    _check_day_driving()          Art. 6§1 — guida giornaliera
    _check_daily_rest()           Art. 8§1 — riposo giornaliero
    _check_continuous_work()      Dir. Art. 5 — lavoro continuo
    _check_night_work()           Dir. Art. 7 — turno notturno
    ↓ su tutte le settimane insieme
    _check_weekly_driving()       Art. 6§2-3 — guida settimanale/bisettimanale
    _check_weekly_work()          Dir. Art. 4 — ore lavoro settimanali
    _check_weekly_rest()          Art. 8§6 — riposo settimanale
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


# ── Regole giornaliere (applicate su un singolo DayActivity) ─────────────────

def _check_continuous_driving(day: DayActivity, viols: List[Violation]):
    """
    Art. 7 Reg. 561/2006 — Guida continua eccessiva.

    Regola: il conducente non può guidare più di 4h30 (270 min) senza
    una pausa di almeno 45 minuti (oppure due pause da 15+30 min).

    Algoritmo:
      - `cont` accumula i minuti di guida consecutivi
      - Una pausa ≥ 45 min azzera il contatore (guida continua OK)
      - Una pausa ≥ 15 min avvia la "split rest" (2 pause: 15 poi 30)
      - Se cont supera 270 min senza pausa adeguata → infrazione Grave

    day.segments() restituisce [(start_min, end_min, activity), ...]:
      ogni tupla rappresenta un periodo di attività consecutiva nel giorno.
    """
    cont = pause_bank = 0   # minuti di guida accumulati, "conto corrente" pausa split
    split_started = False   # True se la prima pausa da 15 min è già stata registrata

    for s, e, a in day.segments():
        dur = e - s   # durata del segmento in minuti
        if a == "Guida":
            cont += dur
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


def _check_daily_rest(day: DayActivity, viols: List[Violation]):
    """
    Art. 8§1 — Riposo giornaliero insufficiente.

    Regola:
      - Riposo regolare: ≥ 11h consecutive (660 min)
      - Riposo ridotto:  ≥ 9h consecutive (540 min) — tollerato (non più di 3×/sett.)
      - Split rest:      ≥ 3h + ≥ 9h (totale ≥ 12h, ma in due blocchi)

    Algoritmo:
      1. Trova tutti i periodi di Riposo nel giorno, ordinati dal più lungo
      2. Se il periodo più lungo ≥ 11h: OK
      3. Se split rest valido (≥9h + ≥3h): OK
      4. Se ≥ 9h ma < 11h: infrazione Lieve (riposo ridotto, norma solo parzialmente rispettata)
      5. Se < 9h: infrazione Grave (riposo ridotto non rispettato)
    """
    # Lista durate dei periodi di Riposo, dalla più lunga alla più breve
    rests = sorted([e - s for s, e, a in day.segments() if a == "Riposo"], reverse=True)
    if not rests:
        return   # nessun riposo registrato (giorno di lavoro continuo?)

    best = rests[0]   # periodo di riposo più lungo del giorno

    # Verifica split rest: almeno due pause, la maggiore ≥ 9h e la seconda ≥ 3h
    split_ok = len(rests) >= 2 and rests[0] >= LIM_DAILY_REST_R and rests[1] >= 180

    if best >= LIM_DAILY_REST or split_ok:
        return   # riposo sufficiente, nessuna infrazione

    if best >= LIM_DAILY_REST_R:
        # Riposo tra 9h e 11h: lieve (è ridotto ma almeno ≥ 9h)
        code, sev, lim = "Daily_TooShort_Reduced", SEV_LOW, LIM_DAILY_REST
    else:
        # Riposo < 9h: grave (non rispetta neanche il minimo ridotto)
        code, sev, lim = "Daily_TooShort", SEV_HIGH, LIM_DAILY_REST_R

    if not _exists(viols, day.date, code):
        viols.append(_violation(
            day, code,
            "Riposo giornaliero insufficiente",
            f"Riposo massimo: {best//60}h{best%60:02d} (minimo {lim//60}h)",
            sev, best, lim,
        ))


def _check_continuous_work(day: DayActivity, viols: List[Violation]):
    """
    Dir. 2002/15/CE Art. 5 — Lavoro continuo eccessivo.

    Regola: non si può lavorare più di 6h (360 min) consecutivamente
    senza una pausa di almeno 30 minuti.

    "Lavoro" include: Guida, Lavoro, Disponibilità (tutte le attività non-Riposo).
    Una pausa è un periodo di Riposo ≥ 30 min.

    Differenza da Art. 7 (guida continua):
      - Art. 7: solo guida, pausa ≥ 45 min, limite 4h30
      - Dir. Art. 5: tutto il lavoro, pausa ≥ 30 min, limite 6h
    """
    cont = 0   # minuti di lavoro continuo accumulati

    for s, e, a in day.segments():
        if a in ("Guida", "Lavoro", "Disponibilità"):
            cont += e - s   # accumula minuti di lavoro
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

    Regola 2 — TooShort: se il riposo è tra 24h e 45h → è ridotto.
      Un riposo ridotto deve essere compensato nella settimana successiva → LIEVE.

    Algoritmo:
      1. Scorre tutti i segmenti di Riposo in ordine cronologico
      2. Considera solo i segmenti ≥ 24h (LIM_WEEKLY_REST_R): quelli più corti
         non possono essere "riposi settimanali" per definizione
      3. Confronta l'inizio del riposo corrente con la fine del precedente
      4. Se il gap supera 144h → infrazione TooLate
      5. Se il riposo è < 45h → infrazione TooShort

    NOTA: usa `__import__("datetime").timedelta(...)` invece di `timedelta(...)` direttamente
    per evitare un possibile conflitto di nome (bug noto nell'implementazione originale).
    """
    last_rest_end: Optional[datetime] = None   # fine dell'ultimo riposo settimanale trovato

    # Itera i giorni in ordine cronologico
    for day in sorted(all_days, key=lambda d: d.date):
        # Base temporale del giorno corrente: mezzanotte del giorno
        base = datetime.strptime(day.date, "%Y-%m-%d")

        for s, e, a in day.segments():
            if a != "Riposo":
                continue
            dur = e - s   # durata del periodo di Riposo in minuti

            # Considera solo i periodi abbastanza lunghi da essere "settimanali"
            if dur < LIM_WEEKLY_REST_R:
                continue

            # Calcola inizio e fine assoluti del riposo come datetime
            rest_start = base + __import__("datetime").timedelta(minutes=s)
            rest_end   = base + __import__("datetime").timedelta(minutes=e)

            # Regola 1: verifica il gap dall'ultimo riposo settimanale
            if last_rest_end is not None:
                gap = int((rest_start - last_rest_end).total_seconds() / 60)
                if gap > LIM_WEEKLY_WIN and not _exists(viols, day.date, "Weekly_TooLate"):
                    # Il conducente ha aspettato troppo prima del riposo settimanale
                    viols.append(_violation(
                        DayActivity(day.date, day.date_display, 0),
                        "Weekly_TooLate",
                        "Ritardo inizio riposo settimanale",
                        f"Attesa: {gap//60}h{gap%60:02d} (max 144h)",
                        SEV_VERY, gap, LIM_WEEKLY_WIN,
                    ))

            # Regola 2: verifica la durata del riposo settimanale
            if dur < LIM_WEEKLY_REST and not _exists(viols, day.date, "Weekly_TooShort"):
                # Il riposo è ridotto (tra 24h e 45h)
                viols.append(_violation(
                    DayActivity(day.date, day.date_display, 0),
                    "Weekly_TooShort",
                    "Riposo settimanale ridotto",
                    f"Riposo: {dur//60}h{dur%60:02d} (regolare ≥45h)",
                    SEV_LOW, dur, LIM_WEEKLY_REST,
                ))

            # Aggiorna la fine dell'ultimo riposo settimanale trovato
            last_rest_end = rest_end


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
        _check_continuous_driving(day, viols)   # Art. 7 — guida continua
        _check_day_driving(day, days, viols)     # Art. 6§1 — guida giornaliera
        _check_daily_rest(day, viols)            # Art. 8§1 — riposo giornaliero
        _check_continuous_work(day, viols)       # Dir. Art. 5 — lavoro continuo
        _check_night_work(day, viols)            # Dir. Art. 7 — turno notturno

    # Regole settimanali: richiedono la visione di più giorni insieme
    _check_weekly_driving(days, viols)   # Art. 6§2-3 — guida settimanale/bisettimanale
    _check_weekly_work(days, viols)      # Dir. Art. 4 — ore lavoro settimanali
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

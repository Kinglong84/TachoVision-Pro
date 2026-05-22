"""
models/analytics.py
====================
Calcoli analitici sui dati della carta tachigrafica.

Questo modulo elabora i dati grezzi del CardData per produrre:
  - KPI (Key Performance Indicators) per la Panoramica
  - Riepilogo settimanale (ore/km per settimana)
  - Periodi di riposo identificati e classificati

NON dipende dalla UI (Dash) né dal parser. Riceve CardData e restituisce
strutture dati calcolate (dict, liste di dataclass).

Flusso:
    parser.py → parse_ddd() → CardData grezzo
    analytics.py → enrich() → aggiunge rest_periods e weekly_summary
    controller → serializza in Store → view legge dallo Store
"""

from __future__ import annotations
from collections import defaultdict
# defaultdict: come dict, ma con un valore di default per le chiavi mancanti.
# defaultdict(lambda: {"g": 0, "l": 0}) → accedere a una chiave inesistente
# crea automaticamente il dizionario {"g": 0, "l": 0} invece di sollevare KeyError.

from datetime import datetime, timedelta
# timedelta: rappresenta una differenza di tempo (es. timedelta(days=7) = una settimana)

from typing import List, Dict

from models.card_data import CardData, DayActivity, RestPeriod, WeekSummary


def compute_stats(cd: CardData) -> Dict:
    """
    Calcola i KPI (indicatori chiave) di alto livello per la schermata Panoramica.

    Itera su tutte le attività e somma le ore per tipo,
    conta i giorni di guida e i km totali.

    Ritorna un dizionario con:
        days:         numero totale di giorni nel periodo
        driving_days: giorni in cui c'è stata almeno una sessione di guida
        total_km:     km totali percorsi nel periodo
        driving_h:    ore totali di guida (float, arrotondato a 1 decimale)
        work_h:       ore totali di lavoro
        vehicles:     numero di veicoli distinti usati
        hours:        dizionario {attività: ore} per il grafico donut
    """
    if not cd.activities:
        return {}   # nessun dato disponibile

    # Somma i km di tutti i giorni
    total_km = sum(d.distance_km for d in cd.activities)

    # Conta i giorni con almeno un segmento di guida
    driving_days = sum(1 for d in cd.activities
                       if any(c.activity == "Guida" for c in d.changes))

    # Inizializza il dizionario delle ore per tipo di attività
    hours: Dict[str, float] = {"Guida": 0, "Lavoro": 0, "Disponibilità": 0, "Riposo": 0}

    # Per ogni giorno, somma la durata di ogni segmento nel bucket corretto
    for day in cd.activities:
        for s, e, a in day.segments():
            if a in hours:
                # (e - s) = durata in minuti → / 60 = ore decimali
                hours[a] += max(0, e - s) / 60   # max(0,...) evita durate negative

    return {
        "days":         len(cd.activities),
        "driving_days": driving_days,
        "total_km":     total_km,
        "driving_h":    round(hours["Guida"], 1),    # arrotondato a 1 decimale
        "work_h":       round(hours["Lavoro"], 1),
        "vehicles":     len(cd.vehicles),
        "hours":        hours,   # usato dal grafico donut nella Panoramica
    }


def _week_monday(d: datetime) -> str:
    """
    Dato un giorno, restituisce la data del lunedì della stessa settimana.

    Usata per raggruppare i giorni per settimana ISO (lunedì-domenica).

    datetime.weekday() restituisce:
        0 = lunedì, 1 = martedì, ..., 6 = domenica

    Sottraendo weekday() giorni, torniamo sempre al lunedì.

    Esempio:
        _week_monday(datetime(2026, 5, 14))  # giovedì → lunedì 11/05/2026
        → "2026-05-11"
    """
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def compute_weekly_summary(activities: List[DayActivity]) -> List[WeekSummary]:
    """
    Raggruppa le attività per settimana ISO e calcola i totali per settimana.

    Algoritmo:
    1. Per ogni giorno, trova il lunedì della settimana (chiave del dizionario)
    2. Accumula ore e km in quel bucket settimanale
    3. Converte ogni bucket in un oggetto WeekSummary
    4. Ritorna la lista ordinata (settimana più recente prima)

    Il Reg. 561/2006 usa la settimana ISO (lunedì–domenica), quindi
    il raggruppamento deve rispettare questo confine.

    Ritorna: lista di WeekSummary, dalla più recente alla più vecchia.
    """
    # defaultdict: ogni chiave (lunedì della settimana) crea automaticamente
    # un dizionario con le somme inizializzate a zero
    weeks: Dict[str, Dict] = defaultdict(lambda: {
        "g": 0,    # minuti Guida
        "l": 0,    # minuti Lavoro
        "d": 0,    # minuti Disponibilità
        "r": 0,    # minuti Riposo
        "km": 0.0, # km
        "days": 0  # giorni attivi
    })

    for day in activities:
        # Converte la stringa "YYYY-MM-DD" in oggetto datetime per calcolare il lunedì
        dt = datetime.strptime(day.date, "%Y-%m-%d")
        wk = _week_monday(dt)   # chiave: "YYYY-MM-DD" del lunedì

        # Accumula le durate nei bucket per tipo di attività
        for s, e, a in day.segments():
            dur = max(0, e - s)   # durata in minuti
            if   a == "Guida":         weeks[wk]["g"] += dur
            elif a == "Lavoro":        weeks[wk]["l"] += dur
            elif a == "Disponibilità": weeks[wk]["d"] += dur
            elif a == "Riposo":        weeks[wk]["r"] += dur

        weeks[wk]["km"]   += day.distance_km   # somma km giornalieri
        weeks[wk]["days"] += 1                  # conta i giorni attivi

    # Converte i bucket in oggetti WeekSummary
    result = []
    for wk, w in sorted(weeks.items(), reverse=True):   # dalla settimana più recente
        result.append(WeekSummary(
            week_start=wk,
            # Converte "YYYY-MM-DD" in "DD/MM/YYYY" per la visualizzazione
            week_label=datetime.strptime(wk, "%Y-%m-%d").strftime("%d/%m/%Y"),
            days=w["days"],
            guida_min=w["g"],
            lavoro_min=w["l"],
            disponibilita_min=w["d"],
            riposo_min=w["r"],
            km=round(w["km"], 1),
        ))
    return result


def compute_rest_periods(activities: List[DayActivity]) -> List[RestPeriod]:
    """
    Identifica e classifica i periodi di riposo nel periodo di attività.

    Un "periodo di riposo" è un segmento continuo con attività = "Riposo"
    di almeno 45 minuti. Viene classificato secondo il Reg. 561/2006:

    Soglie di classificazione (in minuti):
        ≥ 2700 min (45h) → Settimanale (riposo settimanale regolare)
        ≥  660 min (11h) → Regolare    (riposo giornaliero normale)
        ≥  540 min (9h)  → Ridotto     (riposo giornaliero ridotto, max 3/settimana)
        ≥   45 min       → Breve       (pausa obbligatoria durante la guida)

    Gli orari start/end sono calcolati sommando i minuti alla mezzanotte UTC
    del giorno corrispondente (approssimazione: i segmenti ACI sono in UTC).

    Ritorna: lista di RestPeriod, dalla data più recente alla più vecchia.
    """
    rests: List[RestPeriod] = []

    # Processa i giorni in ordine cronologico (necessario per correttezza)
    for day in sorted(activities, key=lambda d: d.date):
        # Mezzanotte UTC del giorno (es. datetime(2026, 5, 9, 0, 0, 0))
        base = datetime.strptime(day.date, "%Y-%m-%d")

        for s, e, a in day.segments():
            if a != "Riposo":
                continue   # considera solo i segmenti di riposo

            dur = e - s   # durata in minuti

            if dur < 45:
                continue   # troppo breve per essere un riposo significativo

            # Calcola ore e minuti per il formato "Xh YY"
            h, m = divmod(dur, 60)

            # Classifica in base alla durata
            if   dur >= 2700: kind = "Settimanale"
            elif dur >= 660:  kind = "Regolare"
            elif dur >= 540:  kind = "Ridotto"
            else:             kind = "Breve"

            rests.append(RestPeriod(
                date=day.date,
                # Calcola ora inizio: mezzanotte + s minuti
                start=(base + timedelta(minutes=s)).strftime("%d/%m/%Y %H:%M"),
                # Calcola ora fine: mezzanotte + e minuti
                end=  (base + timedelta(minutes=e)).strftime("%d/%m/%Y %H:%M"),
                duration_min=dur,
                duration_str=f"{h}h{m:02d}",   # es. "11h00"
                kind=kind,
            ))

    # Ritorna dalla più recente alla più vecchia (come le altre liste)
    return sorted(rests, key=lambda r: r.date, reverse=True)


def enrich(cd: CardData) -> CardData:
    """
    Calcola e inietta i dati derivati nel CardData.

    Chiamato dal controller (data_controller.py) dopo il parsing, prima di
    serializzare in dcc.Store. Modifica il CardData "in-place" (lo stesso oggetto)
    e lo ritorna per comodità di concatenamento:

        cd = enrich(parse_ddd(raw_bytes))

    Campi aggiunti:
        cd.rest_periods:   lista di periodi di riposo classificati
        cd.weekly_summary: lista di riepiloghi settimanali
    """
    cd.rest_periods   = compute_rest_periods(cd.activities)
    cd.weekly_summary = compute_weekly_summary(cd.activities)
    return cd

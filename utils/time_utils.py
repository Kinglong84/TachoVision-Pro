"""
utils/time_utils.py
===================
Modulo di utilità condivise per la gestione dei fusi orari e dei mesi in italiano.

Problema risolto: i timestamp nel file DDD sono in UTC (Tempo Coordinato Universale),
ma all'utente devono essere mostrati in ora italiana (Europe/Rome).
L'Italia è UTC+1 d'inverno (ora solare) e UTC+2 d'estate (ora legale).

Questo modulo viene importato sia dalla view (attivita.py)
sia dal servizio PDF (pdf_service.py) per evitare codice duplicato.
"""

from __future__ import annotations
# 'from __future__ import annotations' permette di usare tipi come str nelle annotazioni
# anche in Python 3.8, dove non sarebbe possibile scrivere 'list[str]' direttamente.

from datetime import datetime, timezone, timedelta
# datetime: classe per rappresentare data e ora
# timezone: classe per rappresentare un fuso orario con offset fisso (es. UTC+2)
# timedelta: classe per rappresentare una differenza di tempo (es. 2 ore)

from typing import List
# List viene usato nelle type hints per indicare "lista di..."


# ── Importazione del modulo fuso orario ──────────────────────────────────────────
# Python 3.9+ include 'zoneinfo', un modulo che gestisce automaticamente
# l'ora legale tramite il database IANA (es. "Europe/Rome" sa quando
# scattano le lancette avanti/indietro ogni anno).
# Su Python 3.8 o se il modulo non è installato, usiamo un fallback manuale.
try:
    from zoneinfo import ZoneInfo
    # ZoneInfo("Europe/Rome") crea un oggetto fuso orario che conosce
    # tutte le regole storiche dell'ora legale italiana.
    _IT_TZ = ZoneInfo("Europe/Rome")
except ImportError:
    # Se zoneinfo non è disponibile, _IT_TZ rimane None
    # e le funzioni useranno un calcolo approssimato.
    _IT_TZ = None          # useremo il fallback manuale


# ── Nomi dei mesi in italiano ─────────────────────────────────────────────────────
# Indice 1-12: MESI_IT[1] = "gennaio", MESI_IT[12] = "dicembre"
# L'indice 0 è lasciato vuoto ("") per poter usare direttamente dt.month (1-based).
MESI_IT = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
           "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]

# Versione abbreviata (3 lettere) per spazi ridotti (es. intestazioni PDF)
MESI_IT_BREVI = ["", "gen", "feb", "mar", "apr", "mag", "giu",
                 "lug", "ago", "set", "ott", "nov", "dic"]


def tz_offset_min(day_date: str) -> int:
    """
    Restituisce l'offset UTC → ora italiana in MINUTI per la data indicata.

    L'Italia usa due offset durante l'anno:
    - UTC+2 (120 minuti) durante l'ora legale (fine marzo – fine ottobre)
    - UTC+1 (60 minuti)  durante l'ora solare (fine ottobre – fine marzo)

    Parametro:
        day_date: stringa nel formato "YYYY-MM-DD" (es. "2026-05-09")

    Ritorna:
        120 se siamo in ora legale (estate, UTC+2)
        60  se siamo in ora solare (inverno, UTC+1)

    Esempio:
        tz_offset_min("2026-05-09")  →  120   (maggio = estate)
        tz_offset_min("2026-01-15")  →   60   (gennaio = inverno)
    """
    try:
        if _IT_TZ:
            # Metodo preciso: usa zoneinfo per calcolare l'offset esatto.
            # strptime converte la stringa "YYYY-MM-DD" in un oggetto datetime.
            # replace(tzinfo=timezone.utc) dice che quella data è in UTC.
            dt = datetime.strptime(day_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            # astimezone(_IT_TZ) converte quel momento nel fuso orario italiano.
            # utcoffset() restituisce la differenza (timedelta) rispetto a UTC.
            # total_seconds() / 60 la converte in minuti.
            return int(dt.astimezone(_IT_TZ).utcoffset().total_seconds() // 60)
    except Exception:
        # Se qualcosa va storto (data malformata, ecc.), passa al fallback.
        pass

    # Fallback approssimato: aprile-ottobre = UTC+2, il resto = UTC+1.
    # Non è perfetto (ignora i giorni esatti di cambio ora), ma è sufficiente
    # per la maggior parte dei casi d'uso.
    try:
        m = int(day_date[5:7])   # estrae il mese dalla stringa "YYYY-MM-DD"
        return 120 if 4 <= m <= 10 else 60
    except Exception:
        return 120    # in caso di errore, assume UTC+2 (orario estivo)


def local_dt(ts_utc: int) -> datetime:
    """
    Converte un timestamp Unix UTC in un oggetto datetime nell'ora italiana.

    Il "timestamp Unix" è il numero di secondi trascorsi dal 1° gennaio 1970 00:00:00 UTC.
    È il formato usato internamente dai tachigrafi per memorizzare gli orari.

    Parametro:
        ts_utc: secondi trascorsi dal 1970-01-01 00:00:00 UTC (intero)

    Ritorna:
        datetime con timezone Europe/Rome applicata

    Esempio:
        local_dt(1746757242)  →  datetime(2026, 5, 9, 6, 20, 42, tzinfo=Rome)
        # 1746757242 UTC = 04:20:42 UTC = 06:20:42 ora italiana (UTC+2)
    """
    if _IT_TZ:
        # datetime.fromtimestamp(ts, tz) converte il timestamp Unix
        # direttamente nel fuso orario specificato, gestendo automaticamente
        # l'ora legale.
        return datetime.fromtimestamp(ts_utc, tz=_IT_TZ)
    # Fallback: aggiungiamo 2 ore fisse a UTC (non gestisce l'ora legale,
    # ma è un'approssimazione ragionevole per l'estate italiana).
    return datetime.fromtimestamp(ts_utc, tz=timezone.utc) + timedelta(hours=2)


def local_time_str(ts_utc: int) -> str:
    """
    Converte un timestamp Unix UTC nella stringa HH:MM:SS in ora italiana.

    Utile per mostrare all'utente l'orario di inserimento/estrazione carta
    in formato leggibile.

    Parametro:
        ts_utc: timestamp Unix in secondi

    Ritorna:
        stringa "HH:MM:SS" (es. "06:20:42")
        oppure "--:--:--" in caso di errore

    Esempio:
        local_time_str(1746757242)  →  "06:20:42"
    """
    try:
        # strftime("%H:%M:%S") formatta il datetime come "HH:MM:SS"
        return local_dt(ts_utc).strftime("%H:%M:%S")
    except Exception:
        # Ritorniamo un valore "segnaposto" visibile all'utente invece di crashare
        return "--:--:--"


def sessions_for_day(sessions: list, day_date: str) -> list:
    """
    Filtra le sessioni veicolo il cui inserimento carta (UTC) cade
    nel giorno UTC indicato.

    Una "sessione" rappresenta un singolo inserimento della carta nel tachigrafo
    (VehicleSession). Il campo 'first_use_utc' è il timestamp Unix del momento
    in cui la carta è stata inserita nel veicolo.

    Parametri:
        sessions:  lista di oggetti VehicleSession
        day_date:  data nel formato "YYYY-MM-DD" (giorno UTC del record attività)

    Ritorna:
        lista ordinata per orario di inserimento (prima le sessioni mattutine)

    Nota: il confronto avviene in UTC perché il file DDD organizza le attività
    per giorno UTC. Convertire in ora locale prima del confronto causerebbe
    disallineamenti vicino alla mezzanotte.
    """
    result = []
    for s in sessions:
        if s.first_use_utc <= 0:
            # Timestamp = 0 significa "non disponibile" (sessione senza orario preciso)
            continue

        # Converte il timestamp Unix in data UTC (senza cambio fuso)
        dt_utc = datetime.fromtimestamp(s.first_use_utc, tz=timezone.utc)

        # Confronta solo la data (ignorando l'ora) in formato "YYYY-MM-DD"
        if dt_utc.strftime("%Y-%m-%d") == day_date:
            result.append(s)

    # Ordina per orario crescente: prima le sessioni del mattino, poi quelle del pomeriggio
    return sorted(result, key=lambda s: s.first_use_utc)


def fmt_month_it(dt: datetime, short: bool = False) -> str:
    """
    Restituisce il nome del mese in italiano per un oggetto datetime.

    Parametri:
        dt:    oggetto datetime Python
        short: se True, usa la forma abbreviata (3 lettere)

    Ritorna:
        Nome del mese in italiano

    Esempio:
        fmt_month_it(datetime(2026, 5, 9))              →  "maggio"
        fmt_month_it(datetime(2026, 5, 9), short=True)  →  "mag"
    """
    # Sceglie la lista appropriata in base al parametro 'short'
    names = MESI_IT_BREVI if short else MESI_IT
    # dt.month è un intero 1-12, che usiamo direttamente come indice
    return names[dt.month]

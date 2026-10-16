"""
controllers/data_controller.py
Gestisce il caricamento dei dati: upload file .DDD, lettura smartcard, modalità demo.
Responsabilità: riceve input grezzo → coordina Model+Service → serializza in Store.
"""

from __future__ import annotations
import os
import base64, random
from datetime import datetime, timedelta, timezone
from typing import Optional

from models.card_data import (
    CardData, DriverInfo, DayActivity, ActivityChange,
    Vehicle, Place,
)
from models.parser import parse_ddd
from models.analytics import enrich


# ── Demo data factory ─────────────────────────────────────────────────────────
def make_demo() -> CardData:
    """
    Carica il file DDD reale di Mario Rossi (sample incluso nel pacchetto)
    come dati demo. Se il file non è disponibile, genera dati sintetici.
    """
    # Prova a caricare il DDD reale
    sample_paths = [
        os.path.join(os.path.dirname(__file__), '..', 'sample_demo.DDD'),
        os.path.join(os.path.dirname(__file__), '..', 'sample_demo_gen2.DDD'),
    ]
    for path in sample_paths:
        path = os.path.normpath(path)
        if os.path.exists(path):
            try:
                from models.parser import parse_ddd
                with open(path, 'rb') as f:
                    raw = f.read()
                cd = parse_ddd(raw)
                cd = enrich(cd)
                cd.demo = True
                cd.driver.filename = os.path.basename(path)
                cd.driver.last_download = cd.driver.last_download or '01/01/2026 10:00'
                return cd
            except Exception:
                pass
    # Fallback sintetico
    rng = random.Random(42)
    base_dt = datetime(2026, 1, 5, tzinfo=timezone.utc)

    driver = DriverInfo(
        surname="ROSSI", firstname="MARIO",
        birth_date="01/01/1980", language="it",
        card_number="I000000000000000",
        issuing_authority="CCIAA DI ROMA",
        issuing_nation="IT",
        issue_date="01/01/2022",
        validity_begin="01/02/2022",
        expiry_date="01/02/2027",
        licence_number="X000000000",
        licence_authority="AUTORITA' COMPETENTE",
        generation="G2 (v1)", renewal_index="3",
        replacement_index="0",
        last_download="01/01/2026 10:00",
        prev_download="01/07/2025 10:00",
        filename="C_20260101_1000_G_ROSSI_I000000000000000.DDD",
        file_size="67485",
    )

    activities = []
    for off in range(28):
        dt = base_dt + timedelta(days=off)
        wd = dt.weekday()
        if wd == 6:
            ch = [ActivityChange(0, "Riposo")]
            km = 0.0
        elif wd == 5:
            s = rng.randint(300, 360)
            ch = [ActivityChange(0,"Riposo"), ActivityChange(s,"Guida"),
                  ActivityChange(s+90,"Lavoro"), ActivityChange(s+150,"Guida"),
                  ActivityChange(s+240,"Riposo")]
            km = float(rng.randint(60, 180))
        else:
            s = rng.randint(260, 330)
            ch = [
                ActivityChange(0, "Riposo"),
                ActivityChange(s, "Disponibilità"),
                ActivityChange(s+20, "Guida"),
                ActivityChange(s+120, "Lavoro"),
                ActivityChange(s+150, "Guida"),
                ActivityChange(s+270, "Riposo"),   # pausa 45 min
                ActivityChange(s+315, "Guida"),
                ActivityChange(s+435, "Lavoro"),
                ActivityChange(s+465, "Guida"),
                ActivityChange(min(s+570, 1380), "Riposo"),
            ]
            km = float(rng.randint(200, 550))

        activities.append(DayActivity(
            date=dt.strftime("%Y-%m-%d"),
            date_display=dt.strftime("%d/%m/%Y"),
            distance_km=km,
            changes=ch,
        ))

    vehicles = [
        Vehicle("BA123ZX", "05/01/2026", "28/01/2026"),
        Vehicle("NA456AB", "10/01/2026", "20/01/2026"),
    ]
    places = [
        Place("05/01/2026 06:00", "2026-01-05", "IT", "Inizio", 120000),
        Place("08/01/2026 18:30", "2026-01-08", "FR", "Inizio", 121450),
        Place("10/01/2026 07:00", "2026-01-10", "DE", "Inizio", 122800),
        Place("15/01/2026 19:00", "2026-01-15", "IT", "Inizio", 124200),
    ]

    cd = CardData(driver=driver, activities=activities,
                  vehicles=vehicles, places=places, demo=True)
    return enrich(cd)


# ── Upload handler ────────────────────────────────────────────────────────────
def download_time_from_filename(filename: str) -> str:
    """
    Nome file standard dei download carta: C_YYYYMMDD_HHMM_<...>.DDD (ora UTC).
    Ritorna "DD/MM/YYYY HH:MM" nel fuso orario delle impostazioni, o "" se assente.
    """
    import re
    from datetime import timezone
    from zoneinfo import ZoneInfo
    from models.settings import load_settings
    m = re.search(r"(?:^|_)C_(\d{8})_(\d{4})", "_" + os.path.basename(filename or ""))
    if not m:
        return ""
    try:
        utc = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        tz = load_settings().timezone
        local = utc.astimezone(ZoneInfo(tz)) if tz else utc.astimezone()
        return local.strftime("%d/%m/%Y %H:%M")
    except (ValueError, KeyError):
        return ""


def from_upload(contents: str, filename: Optional[str] = None) -> CardData:
    """
    Riceve il contenuto base64 da dcc.Upload, lo decodifica, lo parsa.
    In caso di errore restituisce la demo con il messaggio di errore.
    """
    try:
        _, b64 = contents.split(",", 1)
        raw = base64.b64decode(b64)
        cd = parse_ddd(raw)
        cd = enrich(cd)
        cd.demo = False
        if filename:
            cd.driver.filename = filename
            cd.driver.file_size = str(len(raw))
            # la data di scarico è quella
            # registrata sulla carta; se manca, quella nel nome file C_YYYYMMDD_HHMM
            # (UTC). Non usare l'ora del caricamento.
            if not cd.driver.last_download:
                cd.driver.last_download = download_time_from_filename(filename)
        return cd
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Errore caricamento DDD: %s", e, exc_info=True)
        cd = CardData()
        cd.errors = ["Impossibile leggere il file. Verifica che sia un file .DDD valido."]
        return cd


# ── Smartcard handler ─────────────────────────────────────────────────────────
def from_smartcard() -> CardData:
    """
    Legge la carta dal primo lettore disponibile con carta inserita.
    In caso di errore/assenza lettore restituisce la demo con messaggio.
    """
    from services.card_service import PYSCARD_OK, list_readers, get_status, read_card

    if not PYSCARD_OK:
        demo = make_demo()
        demo.errors = ["pyscard non installato. Esegui: pip install pyscard"]
        return demo

    readers = list_readers()
    if not readers:
        demo = make_demo()
        demo.errors = ["Nessun lettore USB rilevato. Collega il lettore e riprova."]
        return demo

    try:
        status = get_status()
        reader_name = next(
            (r["name"] for r in status.get("readers", []) if r.get("card")),
            None,
        )
        if not reader_name:
            demo = make_demo()
            demo.errors = [f"Lettori trovati: {readers}. Inserisci la carta e riprova."]
            return demo

        raw = read_card(reader_name)
        cd = parse_ddd(raw)
        cd = enrich(cd)
        cd.demo = False
        cd.driver.last_download = datetime.now().strftime("%d/%m/%Y %H:%M")
        cd.driver.file_size = str(len(raw))
        return cd
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Errore lettura smartcard: %s", e, exc_info=True)
        demo = make_demo()
        demo.errors = ["Errore durante la lettura della carta. Riprova o riavvia il lettore."]
        return demo

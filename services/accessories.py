"""
services/accessories.py
=======================
Funzioni "Accessori" delle impostazioni.

  - Avviso ogni 28 giorni (warning28day): promemoria con i giorni dall'ultimo
    scarico di ogni conducente (la carta va scaricata almeno ogni 28 giorni,
    Reg. UE 581/2010)
  - Backup automatico settimanale (automaticbackup): zip di archivio, dati
    manuali e impostazioni in ~/TachoVision/backup (ultimi 8)
  - Invio automatico dopo la lettura (automaticsend + email): sul PC apre il
    programma di posta con destinatario, oggetto e testo già compilati e il
    file DDD pronto da allegare
  - Avvio se il lettore è rilevabile (automaticread): gestito dal polling in
    controllers/render_controller.py
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from models.settings import load_settings

log = logging.getLogger(__name__)

BACKUP_DIR = Path.home() / "TachoVision" / "backup"
KEEP_BACKUPS = 8
REMINDER_FROM_DAYS = 21          # avviso dalla terza settimana, scadenza a 28 giorni


def auto_backup_if_due(now: datetime = None) -> Optional[Path]:
    """Crea il backup settimanale se attivo e l'ultimo ha più di 7 giorni."""
    s = load_settings()
    if not s.automaticbackup:
        return None
    now = now or datetime.now()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(BACKUP_DIR.glob("TachoVision_backup_*.zip"))
    if existing:
        last = datetime.fromtimestamp(existing[-1].stat().st_mtime)
        if now - last < timedelta(days=7):
            return None
    from services.archive_service import backup_zip
    path = BACKUP_DIR / f"TachoVision_backup_{now.strftime('%Y%m%d_%H%M%S')}.zip"
    path.write_bytes(backup_zip())
    for old in sorted(BACKUP_DIR.glob("TachoVision_backup_*.zip"))[:-KEEP_BACKUPS]:
        try:
            old.unlink()
        except OSError as e:
            log.warning("Backup vecchio non eliminato (%s): %s", old, e)
    log.info("Backup automatico creato: %s", path)
    return path


def reminders(now: datetime = None) -> List[Tuple[str, str, int]]:
    """
    
    Ritorna (conducente, carta, giorni dall'ultimo scarico) per chi è oltre
    REMINDER_FROM_DAYS giorni.
    """
    s = load_settings()
    if not s.warning28day:
        return []
    from services.archive_service import get_archive
    now = now or datetime.now()
    latest = {}
    for e in get_archive().list_entries():
        try:
            when = datetime.strptime(e.download_date, "%d/%m/%Y %H:%M")
        except (TypeError, ValueError):
            continue
        if e.card_number not in latest or when > latest[e.card_number][1]:
            latest[e.card_number] = (e.driver_name, when)
    out = []
    for card, (name, when) in latest.items():
        days = (now - when).days
        if days >= REMINDER_FROM_DAYS:
            out.append((name, card, days))
    return sorted(out, key=lambda x: -x[2])


def auto_send(cd, raw_bytes: bytes, filename: str) -> Optional[str]:
    """Apre la mail precompilata dopo la lettura, se l'invio automatico è attivo."""
    s = load_settings()
    if not (s.automaticsend and s.email):
        return None
    from services.email_service import (build_email_content, open_mail_client,
                                        save_attachments_to_temp)
    d = cd.driver
    subject, body = build_email_content(d.full_name, d.card_number, d.last_download)
    paths = save_attachments_to_temp([(filename, raw_bytes)])
    ok, msg = open_mail_client([s.email], subject, body, paths)
    return msg if ok else f"Invio automatico non riuscito: {msg}"


# ── Cartella di salvataggio ──────────────────────────────────────────────────────
def copy_to_save_folder(filename: str, raw_bytes: bytes) -> Optional[Path]:
    """Copia lo scarico nella cartella scelta nelle impostazioni (es. Download o una
    chiavetta USB). Vuota = nessuna copia. Un errore non blocca mai la lettura."""
    from models.settings import load_settings
    folder = (load_settings().get("savefolder") or "").strip()
    if not folder:
        return None
    try:
        target = Path(os.path.expandvars(os.path.expanduser(folder)))
        target.mkdir(parents=True, exist_ok=True)
        path = target / filename
        path.write_bytes(raw_bytes)
        return path
    except OSError as e:
        logging.getLogger(__name__).warning("Copia nella cartella di salvataggio non riuscita: %s", e)
        return None

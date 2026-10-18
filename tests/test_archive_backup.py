"""Backup / ripristino / cancella tutto dell'archivio ."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models.manual_data as md
import models.settings as st
from models.card_data import CardData
from models.manual_data import ManualData, Note
from services.archive_service import (ArchiveService, archive_zip, backup_zip, delete_all,
                                      restore_zip)


def _cd(card, surname):
    cd = CardData()
    cd.driver.card_number, cd.driver.surname = card, surname
    cd.driver.last_download = "08/07/2024 19:35"
    return cd


def test_backup_ripristino_e_cancella(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "MANUAL_DIR", tmp_path / "manuale")
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "impostazioni.json")
    a = ArchiveService(str(tmp_path / "archivio"))
    e1 = a.save_ddd(b"AAA", _cd("I111", "ROSSI"))
    a.save_ddd(b"BBB", _cd("I222", "BIANCHI"))
    # data dello scarico (19:35 locali) scritta in UTC nel nome, come i lettori ufficiali
    from datetime import datetime, timezone
    utc = datetime(2024, 7, 8, 19, 35).astimezone(timezone.utc).strftime("%Y%m%d_%H%M")
    assert e1.filename == f"C_{utc}_ROSSI_I111.DDD"
    md.save_manual("I111", ManualData(notes=[Note(1, "Commento", "long", "x")]))
    st.save_settings(st.Settings({"isbus": True}))

    zipped = backup_zip(a)
    assert len(archive_zip(a, "I111")) > 0

    assert delete_all("I111", a) == 1
    assert [e.card_number for e in a.list_entries()] == ["I222"]
    assert not md.load_manual("I111").notes

    b = ArchiveService(str(tmp_path / "ripristino"))
    counts = restore_zip(zipped, b)
    assert counts["file"] == 2 and counts["manuali"] == 1
    assert {e.card_number for e in b.list_entries()} == {"I111", "I222"}
    assert md.load_manual("I111").notes[0].value == "x"

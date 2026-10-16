"""Accessori: promemoria 28 giorni e backup automatico settimanale."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models.settings as st
import services.accessories as acc
import services.archive_service as arch
from models.card_data import CardData


def _setup(tmp_path, monkeypatch, **settings):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "impostazioni.json")
    st.save_settings(st.Settings(settings))
    a = arch.ArchiveService(str(tmp_path / "archivio"))
    monkeypatch.setattr(arch, "get_archive", lambda archive_dir=None: a)
    monkeypatch.setattr(acc, "BACKUP_DIR", tmp_path / "backup")
    return a


def test_promemoria_dopo_21_giorni(tmp_path, monkeypatch):
    a = _setup(tmp_path, monkeypatch, warning28day=True)
    cd = CardData()
    cd.driver.card_number, cd.driver.surname = "I111", "ROSSI"
    cd.driver.last_download = "01/06/2026 10:00"
    a.save_ddd(b"x", cd)
    assert acc.reminders(datetime(2026, 6, 15)) == []
    r = acc.reminders(datetime(2026, 6, 30, 12))
    assert r and r[0][1] == "I111" and r[0][2] == 29


def test_promemoria_disattivato(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, warning28day=False)
    assert acc.reminders() == []


def test_backup_settimanale(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, automaticbackup=True)
    first = acc.auto_backup_if_due(datetime(2026, 6, 1))
    assert first and first.exists()
    assert acc.auto_backup_if_due(datetime.now()) is None      # meno di 7 giorni fa
    _setup(tmp_path, monkeypatch, automaticbackup=False)
    assert acc.auto_backup_if_due(datetime.now() + timedelta(days=30)) is None

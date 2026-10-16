"""Test dei dati inseriti a mano (note, ferie, attività manuali)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models.manual_data as md
from models.card_data import ActivityChange, CardData, DayActivity
from models.manual_data import Holiday, ManualActivity, ManualData, Note, apply_manual

DAY = (date(2026, 6, 2) - date(1970, 1, 1)).days * 1440   # minuto UTC del 02/06/2026


def _cd():
    cd = CardData()
    cd.driver.card_number = "I000000000000000"
    cd.activities = [DayActivity("2026-06-02", "02/06/2026", 0.0,
                                 [ActivityChange(0, "Riposo"), ActivityChange(480, "Guida"),
                                  ActivityChange(720, "Riposo")])]
    return cd


def test_attivita_manuale_sostituisce_il_tratto():
    cd = _cd()
    data = ManualData(activities=[ManualActivity(DAY + 600, DAY + 660, "Lavoro")])
    apply_manual(cd, data)
    segs = cd.activities[0].segments()
    assert (480, 600, "Guida") in segs
    assert (600, 660, "Lavoro") in segs
    assert (660, 720, "Guida") in segs
    assert any(c.manual and c.time == 600 for c in cd.activities[0].changes)


def test_attivita_manuale_su_giorno_assente_crea_il_giorno():
    cd = _cd()
    apply_manual(cd, ManualData(activities=[ManualActivity(DAY + 1440 + 60,
                                                           DAY + 1440 + 120, "Guida")]))
    assert [d.date for d in cd.activities] == ["2026-06-02", "2026-06-03"]
    assert (60, 120, "Guida") in cd.activities[1].segments()


def test_note_e_ferie_collegate(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "MANUAL_DIR", tmp_path)
    data = ManualData(notes=[Note(DAY + 500, "Odometro", "number", "123456")],
                      holidays=[Holiday("2026-06-10", "2026-06-12")])
    md.save_manual("I000000000000000", data)
    cd = _cd()
    raw = cd.to_dict()
    cd2 = CardData.from_dict(raw)          # apply_manual automatico
    assert cd2.notes and cd2.notes[0].value == "123456"
    assert len(cd2.holidays[0].days()) == 3
    md.delete_all("I000000000000000")
    assert not list(tmp_path.glob("*.json"))

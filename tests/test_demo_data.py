"""Dati di esempio (MARIO ROSSI): completi, coerenti e con qualche infrazione tipica."""

from models.demo_data import build_demo
from models.settings import Settings
from models.violations import detect_violations


def test_demo_completa():
    cd = build_demo()
    assert cd.demo and cd.driver.surname == "ROSSI" and cd.driver.card_number.startswith("I0000")
    assert len(cd.activities) > 50 and len(cd.vehicle_sessions) > 40
    assert {p.country for p in cd.places} >= {"IT", "FR", "DE", "AT"}
    assert cd.gnss_records and all(p.gnss_lat is not None for p in cd.places)


def test_demo_infrazioni_di_esempio():
    cd = build_demo()
    codes = {v.code for v in detect_violations(cd.activities, Settings({"timezone": "Europe/Rome",
                                                                         "basecountry": "IT"}), cd)}
    assert {"ContinuousDriving", "DayDriving_9", "Rest_DailyReduced_Fine"} <= codes

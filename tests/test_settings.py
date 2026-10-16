"""Test del modello impostazioni (models/settings.py)."""
import json

from models.settings import (SPEC, Settings, coerce, default_settings,
                             higher_wage_period, load_settings, save_settings)


def test_defaults_match_reference():
    s = default_settings()
    assert s.nightperiod == 1 and s.night_hours == (0, 4)
    assert s.workingtimeframe == 3 and s.reference_weeks == 17
    assert s.holidayhours == 8
    assert s.payedbreaktype == "SHORT15"
    assert s.cardstamping is True and s.fastcardreading is True
    assert s.isbus is False and s.vehicle_check_min == 0
    assert s.wage_period is None


def test_every_spec_has_valid_default():
    for spec in SPEC:
        assert coerce(spec.key, spec.default) == spec.default, spec.key


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "impostazioni.json"
    s = Settings({"isbus": True, "nightperiod": 4, "higherwageperiod": 13,
                  "email": " a@b.it "})
    save_settings(s, p)
    loaded = load_settings(p)
    assert loaded.isbus is True
    assert loaded.night_hours == (0, 7)
    assert loaded.wage_period == (22, 6)
    assert loaded.email == "a@b.it"


def test_invalid_values_fall_back_to_default(tmp_path):
    p = tmp_path / "impostazioni.json"
    p.write_text(json.dumps({"nightperiod": 99, "holidayhours": "x",
                             "firstdayofmonth": 40, "unknown": 1}), encoding="utf-8")
    s = load_settings(p)
    assert s.nightperiod == 1
    assert s.holidayhours == 8
    assert s.firstdayofmonth == 28          # limitato al massimo
    assert "unknown" not in s.to_dict()


def test_corrupt_file_gives_defaults(tmp_path):
    p = tmp_path / "impostazioni.json"
    p.write_text("{non json", encoding="utf-8")
    assert load_settings(p).to_dict() == default_settings().to_dict()


def test_ui_values_are_coerced():
    assert coerce("nightperiod", "4") == 4          # dropdown può dare stringhe
    assert coerce("isbus", ["on"]) is True          # checklist
    assert coerce("isbus", []) is False


def test_higher_wage_mapping():
    assert higher_wage_period(1) == (20, 4)
    assert higher_wage_period(35) == (19, 8)
    assert higher_wage_period(0) is None

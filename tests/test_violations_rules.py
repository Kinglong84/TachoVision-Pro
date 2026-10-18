"""
Test delle regole del motore infrazioni 
(soglie di gravità li.b, guida tra riposi, orario di lavoro WTD, modalità Italia).
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.card_data import ActivityChange, DayActivity
from models.settings import Settings
from models.violations import MI, MSI, SI, VSI, classify, detect_violations

D0 = date(2026, 6, 1)   # lunedì
UTC = {"timezone": "UTC", "basecountry": "DE"}   # regole generali (non Italia)


def _day(offset, changes):
    d = D0 + timedelta(days=offset)
    return DayActivity(d.isoformat(), d.strftime("%d/%m/%Y"), 0.0,
                       [ActivityChange(t, a) for t, a in changes])


def _rest(offset):
    return _day(offset, [(0, "Riposo")])


def _codes(days, **extra):
    return [v.code for v in detect_violations(days, Settings({**UTC, **extra}))]


# ── Soglie di gravità (Allegato I Reg. UE 2016/403 ───────────

def test_soglie_guida_continua():
    assert classify("ContinuousDriving", 270) is None
    assert classify("ContinuousDriving", 271) == MI
    assert classify("ContinuousDriving", 300) == SI
    assert classify("ContinuousDriving", 360) == VSI


def test_soglie_guida_giornaliera_e_msi():
    assert classify("DayDriving_9", 9 * 60 + 1) == MI
    assert classify("DayDriving_9", 10 * 60) == SI
    assert classify("DayDriving_9", 11 * 60) == VSI
    assert classify("DayDriving_9", 13 * 60 + 30) == MSI
    assert classify("DayDriving_9", 13 * 60 + 30, no_msi=True) == VSI


def test_soglie_riposo_giornaliero():
    assert classify("Rest_DailyNormal_Fine", 10 * 60 + 30) == MI
    assert classify("Rest_DailyNormal_Fine", 9 * 60) == SI
    assert classify("Rest_DailyNormal_Fine", 8 * 60) == VSI
    assert classify("Rest_DailyReduced_Fine", 8 * 60 + 30) == MI


def test_soglie_pause_lavoro_in_minuti():
    assert classify("ContinuousWorking_6", 25) == MI
    assert classify("ContinuousWorking_6", 20) == SI
    assert classify("ContinuousWorking_6", 10) == VSI
    assert classify("ContinuousWorking_6", 30) is None


# ── Regole ───────────────────────────────────────────────────────────────────

def test_guida_continua_un_blocco_con_pause_sommate():
    # 3h guida, pausa 20 + 25 min consecutive (riposo+riposo = 45) → nessuna infrazione
    days = [_rest(0), _day(1, [(0, "Riposo"), (360, "Guida"), (540, "Riposo"),
                               (585, "Guida"), (720, "Riposo")])]
    assert "ContinuousDriving" not in _codes(days)


def test_guida_continua_senza_pausa():
    days = [_rest(0), _day(1, [(0, "Riposo"), (360, "Guida"), (680, "Riposo")])]
    viols = [v for v in detect_violations(days, Settings(UTC)) if v.code == "ContinuousDriving"]
    assert len(viols) == 1 and viols[0].value_min == 320 and viols[0].severity == SI
    assert viols[0].detail == "Tempo di guida continuo 05:20 (04:30)"


def test_guida_giornaliera_a_cavallo_mezzanotte_e_un_solo_turno():
    # 18:00-24:00 e 00:00-05:00 guida (con pause) = 11h nello stesso turno
    d1 = [(0, "Riposo"), (1080, "Guida"), (1350, "Riposo"), (1395, "Guida")]
    d2 = [(0, "Guida"), (180, "Riposo"), (225, "Guida"), (450, "Riposo")]
    days = [_rest(0), _day(1, d1), _day(2, d2), _rest(3), _rest(4)]
    codes = _codes(days)
    assert "DayDriving_10" in codes          # 1° estensione oltre 10h


def test_disponibilita_non_e_orario_di_lavoro():
    # 7 giorni con 10h di disponibilità: niente infrazioni sull'orario settimanale
    days = [_day(i, [(0, "Riposo"), (420, "Disponibilità"), (1020, "Riposo")])
            for i in range(7)]
    assert "WeekWorking_60" not in _codes(days)


def test_orario_settimanale_60():
    # 6 giorni da 11h di lavoro = 66h → WeekWorking_60 (SI: ≥ 65h)
    days = [_day(i, [(0, "Riposo"), (360, "Lavoro"), (720, "Riposo"), (765, "Lavoro"),
                     (1065, "Riposo")]) for i in range(6)] + [_rest(6)]
    viols = [v for v in detect_violations(days, Settings(UTC)) if v.code == "WeekWorking_60"]
    assert viols and viols[0].severity == SI


def test_modalita_italia_turno_notturno():
    # lavoro 05:00-17:30 (con pause): tocca la fascia 00-07 → limite 10h in Italia
    ch = [(0, "Riposo"), (300, "Lavoro"), (600, "Riposo"), (645, "Lavoro"),
          (900, "Riposo"), (945, "Lavoro"), (1050, "Riposo")]
    days = [_rest(0), _day(1, ch), _rest(2)]
    it = [v.code for v in detect_violations(days, Settings({"timezone": "UTC",
                                                              "basecountry": "IT"}))]
    assert "Working_IsNight_10" in it
    # Fuori dall'Italia servono almeno 4h nella fascia notturna (00-04 di default)
    assert "Working_IsNight_10" not in _codes(days)


def test_uso_scorretto_commutatore():
    # 12h di "lavoro" nella notte: in realtà era riposo
    days = [_rest(0), _day(1, [(0, "Riposo"), (480, "Guida"), (900, "Lavoro")]),
            _day(2, [(0, "Lavoro"), (360, "Guida"), (600, "Riposo")]), _rest(3)]
    codes = _codes(days)
    assert "Mode_Incorrect_Use" in codes
    assert not [c for c in codes if c.startswith("Rest_Daily")]


def test_ispezione_veicolo():
    days = [_rest(0), _day(1, [(0, "Riposo"), (360, "Lavoro"), (362, "Guida"),
                               (600, "Riposo")]), _rest(2)]
    assert "VehicleCheck" not in _codes(days)                 # impostazione spenta
    v = [x for x in detect_violations(days, Settings({**UTC, "vehiclecheck": 1}))
         if x.code == "VehicleCheck"]
    assert v and v[0].detail.endswith("00:02 (00:05)")

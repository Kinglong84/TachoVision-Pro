"""
Regole aggiunte: simbolo del paese alla frontiera, viaggio virtuale (Polonia),
guida notturna bus in deroga 12 giorni, segni Art. 12. Dati inventati, orari UTC.
"""

from datetime import date, datetime, timedelta

from models.settings import Settings
from models.violations import detect_violations
from tests.test_international_ferry import _build, _place, _workday


def _codes(cd, **settings):
    s = Settings({"timezone": "UTC", "basecountry": "IT", **settings})
    return detect_violations(cd.activities, s, cd)


def _two_days(first_country, second_country, *, same_shift):
    d0 = date(2025, 3, 4)
    ch = _workday(d0) + _workday(d0 + timedelta(days=1)) + _workday(d0 + timedelta(days=2))
    cd = _build(ch, d0 - timedelta(days=1), d0 + timedelta(days=3))
    t = lambda d, h: datetime(d.year, d.month, d.day, h)
    d1 = d0 + timedelta(days=1)
    if same_shift:                           # due luoghi nello stesso turno
        _place(cd, t(d1, 6), first_country)
        _place(cd, t(d1, 15), second_country)
    else:                                     # fine lavoro e ripresa dopo il riposo
        _place(cd, t(d0, 15), first_country)
        _place(cd, t(d1, 6), second_country)
    return cd


def test_frontiera_paesi_non_confinanti():
    v = [x for x in _codes(_two_days("IT", "DE", same_shift=True))
         if x.code == "Missing_CountryCode_Border"]
    assert len(v) == 1 and v[0].detail == "IT|/???/|DE" and v[0].severity == "MI"
    assert not [x for x in _codes(_two_days("IT", "AT", same_shift=True))
                if x.code == "Missing_CountryCode_Border"]


def test_viaggio_virtuale_solo_polonia():
    cd = _two_days("DE", "FR", same_shift=False)
    v = [x for x in _codes(cd, basecountry="PL") if x.code == "VirtualTravel"]
    assert len(v) == 1 and v[0].detail.endswith("(|DE| >>> |FR|)")
    assert not [x for x in _codes(cd) if x.code == "VirtualTravel"]          # base IT


def test_guida_notturna_bus_in_deroga():
    d0 = date(2025, 3, 3)
    ch = []
    for i in range(1, 10):                    # 9 notti di fila: 20:00-23:30 guida
        d = d0 + timedelta(days=i)
        ch += [(datetime(d.year, d.month, d.day, 20), "Guida"),
               (datetime(d.year, d.month, d.day, 23, 30), "Riposo")]
    cd = _build(ch, d0 - timedelta(days=2), d0 + timedelta(days=13))
    night = [x for x in _codes(cd, isbus=True) if x.code == "NightDrivingBus"]
    assert night and all(x.severity == "SI" for x in night)
    assert not [x for x in _codes(cd) if x.code == "NightDrivingBus"]        # non bus


def test_art12_guida_settimanale_overdrive():
    mon = date(2025, 3, 3)
    ch = []
    for i in range(6):                        # 6 giorni da 9h30 = 57h
        d = mon + timedelta(days=i)
        t = lambda h, m=0: datetime(d.year, d.month, d.day, h, m)
        ch += [(t(5), "Guida"), (t(9, 30), "Riposo"), (t(10, 15), "Guida"),
               (t(14, 45), "Riposo"), (t(15, 30), "Guida"), (t(16, 0), "Riposo")]
    cd = _build(ch, mon - timedelta(days=2), mon + timedelta(days=9))
    _place(cd, datetime(2025, 3, 8, 16), "IT")
    w = [x for x in _codes(cd) if x.code == "WeekDriving_one"]
    assert len(w) == 1 and w[0].note == "overdrive"


def test_ottimizzazione_riposo_22h_come_settimanale():
    """Un riposo di 22h dopo 6 giorni di lavoro costa meno come settimanale ridotto
    (Weekly_TooShort_24) che come giornaliero (Weekly_TooLate sui giorni dopo)."""
    mon = date(2025, 3, 3)
    ch = []
    for i in range(12):
        d = mon + timedelta(days=i)
        if i == 6:
            continue                              # domenica: riposo
        start, end = (6, 15)
        if i == 5:
            end = 13                              # sabato: fine 13:00 → 22h fino a dom 11:00?
        ch += [(datetime(d.year, d.month, d.day, start), "Guida"),
               (datetime(d.year, d.month, d.day, 10), "Riposo"),
               (datetime(d.year, d.month, d.day, 10, 45), "Guida"),
               (datetime(d.year, d.month, d.day, end), "Riposo")]
    sun = mon + timedelta(days=6)
    ch += [(datetime(sun.year, sun.month, sun.day, 11), "Lavoro"),
           (datetime(sun.year, sun.month, sun.day, 12), "Riposo")]
    cd = _build(ch, mon - timedelta(days=3), mon + timedelta(days=12))
    v = _codes(cd)
    codes = {x.code for x in v}
    assert "Weekly_TooShort_24" in codes and "Weekly_TooLate" not in codes


def test_slot_secondo_conducente_non_scartato():
    """Le attività con la carta nello slot del secondo conducente (bit 15) sono del
    titolare e vanno lette: scrittura in un DDD e rilettura dal parser."""
    from controllers.archive_controller import _rebuild_ddd_bytes
    from models.card_data import ActivityChange
    from models.demo_data import build_demo
    from models.parser import parse_ddd
    cd = build_demo()
    day = next(d for d in cd.activities if any(c.activity == "Guida" for c in d.changes))
    for c in day.changes:
        c.slot2 = True
    back = parse_ddd(_rebuild_ddd_bytes(cd))
    same = next(d for d in back.activities if d.date == day.date)
    assert [(c.time, c.activity) for c in same.changes] == [(c.time, c.activity) for c in day.changes]
    assert all(c.slot2 for c in same.changes)


def test_pdf_infrazioni_raggruppato_e_firme():
    fitz = __import__("pytest").importorskip("fitz")
    from models.demo_data import build_demo
    from services.report_service import generate
    cd = build_demo()
    plain, _ = generate("infringement", "pdf", cd, "2026-08-01", "2026-10-09")
    txt = fitz.open(stream=plain, filetype="pdf")[0].get_text()
    assert "Firma del conducente" not in txt                 # firme spente
    grouped, _ = generate("infringement", "pdf_grouped", cd, "2026-08-01", "2026-10-09",
                          options=["sign"])
    txt = fitz.open(stream=grouped, filetype="pdf")[0].get_text()
    assert "Firma del conducente" in txt and " (1)" in txt


def test_info_carta_e_lavoro_continuo():
    from models.demo_data import build_demo
    from models.planning import build_plan
    from views.tabs.carta import card_extremes
    cd = build_demo()
    ext = card_extremes(cd)
    assert list(ext) == ["Prima attività", "Ultima attività", "Primo inserimento della carta",
                         "Ultimo prelievo della carta", "Primo codice paese",
                         "Ultimo codice paese"]
    assert all(v != "—" for v in ext.values())
    # a metà turno: 2h30 di guida senza pause da 15 minuti → lavoro continuo 2h45
    d0 = date(2025, 3, 4)
    cd2 = _build([(datetime(2025, 3, 4, 6), "Lavoro"), (datetime(2025, 3, 4, 6, 15), "Guida")],
                 d0 - timedelta(days=1), d0)

    plan = build_plan(cd2.activities, Settings({"timezone": "UTC"}))
    cont = next(g for g in plan.working if g.label == "Continuo (max 6 ore)")
    assert cont.value > 0 and cont.limit == 360

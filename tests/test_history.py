"""
Storico unito del conducente (DddExpander / DddDownloadChecker):
unione degli scarichi, "Dati mancanti" (DataGap) e scarico oltre 28 giorni.
Dati fittizi (MARIO ROSSI).
"""

from datetime import date, datetime, timedelta

from models.card_data import ActivityChange, CardData, DayActivity, DriverInfo
from models.history import Download, build_history, same_driver
from models.settings import Settings
from models.violations import WARN, detect_violations


def _driver(card="I000000000000001"):
    return DriverInfo(surname="ROSSI", firstname="MARIO", birth_date="01/01/1980",
                      card_number=card)


def _card(first: date, days: int, card="I000000000000001", last_download="") -> CardData:
    cd = CardData(driver=_driver(card))
    cd.driver.last_download = last_download
    for i in range(days):
        d = first + timedelta(days=i)
        cd.activities.append(DayActivity(
            date=d.isoformat(), date_display=d.strftime("%d/%m/%Y"), distance_km=100,
            changes=[ActivityChange(0, "Riposo"), ActivityChange(360, "Guida"),
                     ActivityChange(600, "Riposo")]))
    return cd


def test_stesso_conducente():
    assert same_driver(_driver("I000000000000001"), _driver("I000000000000099"))   # rinnovo
    other = DriverInfo(surname="BIANCHI", firstname="LUCA", birth_date="01/01/1980",
                       card_number="I999999999999999")
    assert not same_driver(_driver(), other)
    same_person = DriverInfo(surname="ROSSI", firstname="MARIO", birth_date="01/01/1980",
                             card_number="E123456789012345")
    assert same_driver(_driver(), same_person)


def test_unione_con_dati_mancanti():
    old = _card(date(2025, 3, 1), 10)                       # 01/03 - 10/03
    new = _card(date(2025, 3, 20), 20, last_download="09/04/2025 10:00")   # 20/03 - 08/04
    dls = [Download("C_20250311_0800_ROSSI.DDD", datetime(2025, 3, 11, 8), old)]
    h = build_history(new, downloads=dls)
    assert h.history_files == ["C_20250311_0800_ROSSI.DDD"]
    assert min(d.date for d in h.activities) == "2025-03-01"
    # buco: dall'ultima attività del vecchio file (10/03 10:00) alla prima del nuovo
    (a, b), = h.data_gaps
    t = lambda m: datetime(1970, 1, 1) + timedelta(minutes=m)
    assert t(a) == datetime(2025, 3, 10, 10, 0) and t(b) == datetime(2025, 3, 20, 0, 0)
    # il file aperto non cambia
    assert len(new.activities) == 20
    v = [x for x in detect_violations(h.activities, Settings({"timezone": "UTC"}), h)
         if x.code == "DataGap"]
    assert len(v) == 1 and v[0].severity == WARN and v[0].severity_label == "Avvertenza"
    assert "conteggiato come riposo" in v[0].detail


def test_niente_unione_se_sovrapposti_o_troppo_vicini():
    old = _card(date(2025, 3, 1), 25)                       # arriva al 25/03: sovrapposto
    new = _card(date(2025, 3, 20), 20, last_download="09/04/2025 10:00")
    h = build_history(new, downloads=[Download("a.DDD", datetime(2025, 3, 26, 8), old)])
    assert h.data_gaps == [] and min(d.date for d in h.activities) == "2025-03-01"
    # scarico a meno di 4 giorni dal file aperto: saltato
    h = build_history(new, downloads=[Download("b.DDD", datetime(2025, 4, 7, 8), old)])
    assert h.history_files == []


def test_scarico_oltre_28_giorni():
    old = _card(date(2025, 1, 1), 10)
    new = _card(date(2025, 2, 1), 30, last_download="03/03/2025 10:00")
    h = build_history(new, downloads=[Download("a.DDD", datetime(2025, 1, 11, 9), old)])
    assert h.card_downloads == [["11/01/2025 09:00", "03/03/2025 10:00", 51]]
    v = [x for x in detect_violations(h.activities, Settings({"timezone": "UTC"}), h)
         if x.code == "CardDownload_28"]
    assert len(v) == 1 and v[0].severity == "MI"
    assert v[0].detail == "Sono trascorsi 51 giorni dallo scarico precedente (28)"
    # entro 28 giorni: niente
    h = build_history(new, downloads=[Download("a.DDD", datetime(2025, 2, 10, 9), old)])
    assert h.card_downloads == []

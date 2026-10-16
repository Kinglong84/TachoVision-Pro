"""
Regole: Weekly_TooShort_International (VSI) e FerryButtonInvalid
(avvertenza). Dati sintetici (MARIO ROSSI), orari UTC.
"""

from datetime import date, datetime, timedelta, timezone

from models.card_data import (ActivityChange, CardData, DayActivity, DriverInfo, Place,
                              SpecificCondition)
from models.settings import Settings
from models.violations import WARN, detect_violations

S = Settings({"timezone": "UTC", "basecountry": "IT"})
EPOCH = datetime(1970, 1, 1)


def _m(d: datetime) -> int:
    return int((d - EPOCH).total_seconds() // 60)


def _build(changes, first: date, last: date) -> CardData:
    """changes: [(datetime, attività)] → giorni del DDD."""
    cd = CardData(driver=DriverInfo(surname="ROSSI", firstname="MARIO",
                                    card_number="I000000000000001"))
    by_day = {}
    for when, act in changes:
        by_day.setdefault(when.date(), []).append(ActivityChange(when.hour * 60 + when.minute, act))
    d, cur = first, "Riposo"
    while d <= last:
        ch = by_day.get(d, [])
        if not ch or ch[0].time > 0:
            ch = [ActivityChange(0, cur)] + ch
        cur = ch[-1].activity
        cd.activities.append(DayActivity(date=d.isoformat(), date_display=d.strftime("%d/%m/%Y"),
                                         distance_km=0, changes=ch))
        d += timedelta(days=1)
    return cd


def _workday(day: date, end_hour=15):
    t = lambda h, mi=0: datetime(day.year, day.month, day.day, h, mi)
    return [(t(6), "Guida"), (t(10), "Riposo"), (t(10, 45), "Guida"), (t(13), "Lavoro"),
            (t(end_hour), "Riposo")]


def _place(cd, when: datetime, country: str):
    cd.places.append(Place(datetime=when.strftime("%d/%m/%Y %H:%M"), date=when.date().isoformat(),
                           country=country, entry_type="Fine", odometer_km=0,
                           ts_utc=int(when.replace(tzinfo=timezone.utc).timestamp())))


def _scenario(fourth_week_long: bool) -> CardData:
    mon = date(2025, 3, 3)
    ch, rests = [], []
    for w in range(5):
        week = mon + timedelta(weeks=w)
        days = 6 if w in (1, 2) else 5
        for i in range(days):
            ch += _workday(week + timedelta(days=i))
        if w == 3 and not fourth_week_long:          # sabato 06-09, riposo di 45h esatte
            sat = week + timedelta(days=5)
            ch += [(datetime(sat.year, sat.month, sat.day, 6), "Guida"),
                   (datetime(sat.year, sat.month, sat.day, 9), "Riposo")]
            rests.append((datetime(sat.year, sat.month, sat.day, 9), "IT"))
        else:
            last = week + timedelta(days=days - 1)
            rests.append((datetime(last.year, last.month, last.day, 15),
                          "DE" if w in (1, 2) else "IT"))
    cd = _build(ch, mon - timedelta(days=1), mon + timedelta(weeks=5, days=-1))
    for when, country in rests:
        _place(cd, when, country)
    return cd


def test_due_ridotti_all_estero_non_compensati():
    v = detect_violations(_scenario(False).activities, S, _scenario(False))
    intl = [x for x in v if x.code == "Weekly_TooShort_International"]
    assert len(intl) == 1 and intl[0].severity == "VSI"
    assert intl[0].start.startswith("29/03/25 09:00")
    assert intl[0].detail.endswith(": 15/03/25, 22/03/25")
    # la deroga evita il "riposo settimanale ridotto non compensato" sulle 2 settimane
    assert not [x for x in v if x.code == "Weekly_TooShort_45" and "03/25" in x.start
                and x.start[:2] in ("15", "22")]


def test_due_ridotti_compensati_col_riposo_lungo():
    cd = _scenario(True)                             # 63h: 18h in più compensano 6h + 6h
    v = detect_violations(cd.activities, S, cd)
    assert not [x for x in v if x.code == "Weekly_TooShort_International"]


def _ferry(cd, begin: datetime, end: datetime):
    for when, kind in ((begin, "Inizio traghetto/treno"), (end, "Fine traghetto/treno")):
        cd.specific_conditions.append(SpecificCondition(
            entry_time=when.strftime("%d/%m/%Y %H:%M"), condition_type=kind))


def test_traghetto_senza_riposo():
    cd = _scenario(True)
    _ferry(cd, datetime(2025, 3, 4, 10, 0), datetime(2025, 3, 4, 13, 0))   # di giorno, guida
    _ferry(cd, datetime(2025, 3, 4, 16, 0), datetime(2025, 3, 5, 5, 0))    # di notte, riposo
    v = [x for x in detect_violations(cd.activities, S, cd) if x.code == "FerryButtonInvalid"]
    assert len(v) == 1 and v[0].severity == WARN
    assert v[0].start.startswith("04/03/25 10:00")
    assert "cuccetta" in v[0].detail

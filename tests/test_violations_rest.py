"""
Test riposi giornalieri/settimanali su timeline continua (issue GitHub #2, #3).

I riposi devono essere valutati come periodi continui che attraversano la
mezzanotte e più giorni, non giorno per giorno.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.card_data import DayActivity, ActivityChange
from models.violations import detect_violations

D0 = date(2026, 6, 1)   # lunedì


def _day(offset, changes):
    d = D0 + timedelta(days=offset)
    return DayActivity(d.isoformat(), d.strftime("%d/%m/%Y"), 0.0,
                       [ActivityChange(t, a) for t, a in changes])


def _rest_day(offset):
    return _day(offset, [(0, "Riposo")])


def _work_day(offset, start_h, end_h):
    """Riposo fino a start_h, Guida fino a end_h, poi Riposo."""
    return _day(offset, [(0, "Riposo"), (start_h * 60, "Guida"), (end_h * 60, "Riposo")])


def _codes(days):
    return [v.code for v in detect_violations(days)]


def test_ferie_consecutive_non_sono_riposi_settimanali_ridotti():
    # Issue #2: 30 giorni di ferie = un unico riposo lungo, nessuna infrazione
    days = [_work_day(0, 8, 16)] + [_rest_day(i) for i in range(1, 31)] + [_work_day(31, 8, 16)]
    codes = _codes(days)
    assert "Weekly_TooShort" not in codes
    assert "Weekly_TooLate" not in codes


def test_riposo_notturno_a_cavallo_mezzanotte_non_e_insufficiente():
    # Issue #3: lavoro 08-18 ogni giorno → riposo 18:00→08:00 = 14h, regolare
    days = [_work_day(i, 8, 18) for i in range(5)] + [_rest_day(5), _rest_day(6)]
    codes = _codes(days)
    assert "Daily_TooShort" not in codes
    assert "Daily_TooShort_Reduced" not in codes


def test_riposo_notturno_di_8h_e_insufficiente():
    # lavoro 06-22 → riposo 22:00→06:00 = 8h < 9h
    days = [_work_day(i, 6, 22) for i in range(4)] + [_rest_day(4), _rest_day(5)]
    viols = [v for v in detect_violations(days) if v.code == "Daily_TooShort"]
    assert viols, "atteso almeno un riposo giornaliero insufficiente"
    assert all(v.value_min == 480 for v in viols)


def test_tre_riposi_ridotti_ammessi_il_quarto_no():
    # lavoro 05-20 → riposo 20:00→05:00 = 9h (ridotto). 5 giornate consecutive.
    days = [_rest_day(0)] + [_work_day(i, 5, 20) for i in range(1, 6)] + [_rest_day(6), _rest_day(7)]
    viols = [v for v in detect_violations(days) if v.code == "Daily_TooShort_Reduced"]
    # riposi ridotti: notti 1→2, 2→3, 3→4, 4→5 → 4 ridotti, il 4° è infrazione
    assert len(viols) == 1


def _weeks(weekend_hours, n_weeks=None):
    """
    Settimane lun-ven lavoro 06-16; riposo settimanale da ven 16:00 della
    durata indicata per ogni settimana; preceduto da una settimana di riposo
    e seguito da lavoro fino a fine settimana (dati completi).
    """
    days = [_rest_day(i) for i in range(7)]     # settimana 0: riposo
    acts = []                                  # (inizio, fine, attività) assoluti
    for w, wh in enumerate(weekend_hours):
        mon = 7 * 1440 * (w + 1)
        for d in range(5):
            acts.append((mon + d * 1440 + 360, mon + d * 1440 + 960, "Guida"))
        rest_end = mon + 4 * 1440 + 960 + wh * 60
        nxt = 7 * 1440 * (w + 2)
        if rest_end < nxt:
            # lavoro dalla fine del riposo fino a lun 06:00 con pause notturne da 11h
            s = rest_end
            while s + 600 <= nxt + 360:
                acts.append((s, s + 600, "Guida"))
                s += 600 + 660
    # in ultimo: settimana lun-ven di lavoro, poi riposo fino a fine dati
    last_mon = 7 * 1440 * (len(weekend_hours) + 1)
    for d in range(5):
        acts.append((last_mon + d * 1440 + 360, last_mon + d * 1440 + 960, "Guida"))
    end = last_mon + 7 * 1440
    for day_i in range(7, end // 1440):
        b = day_i * 1440
        ch = [(0, "Riposo")]
        for s, e, a in acts:
            if s < b + 1440 and e > b:
                ch.append((max(s, b) - b, a))
                if e < b + 1440:
                    ch.append((e - b, "Riposo"))
        days.append(_day(day_i, sorted(set(ch))))
    return days


def test_settimane_con_riposo_regolare_nessuna_infrazione():
    # Art. 8§6: ogni weekend 64h (regolare) → nessuna infrazione settimanale
    assert "Weekly_TooShort" not in _codes(_weeks([64, 64]))


def test_un_ridotto_e_un_regolare_in_due_settimane_ammesso():
    # Art. 8§6: in 2 settimane consecutive basta 1 regolare + 1 ridotto ≥24h
    assert "Weekly_TooShort" not in _codes(_weeks([40, 64, 40, 64]))


def test_due_ridotti_consecutivi_infrazione():
    # 2 settimane consecutive con soli riposi ridotti (40h) → infrazione
    weekly = [v for v in detect_violations(_weeks([64, 40, 40, 64])) if v.code == "Weekly_TooShort"]
    assert len(weekly) == 1


def test_guida_continua_a_cavallo_mezzanotte():
    # Guida 22:00 → 03:00 = 5h senza pausa: infrazione Art. 7 anche se spezzata a mezzanotte
    days = [_day(0, [(0, "Riposo"), (1320, "Guida")]),
            _day(1, [(0, "Guida"), (180, "Riposo")])]
    assert "ContinuousDriving" in _codes(days)


def test_guida_4h30_a_cavallo_mezzanotte_ok():
    days = [_day(0, [(0, "Riposo"), (1320, "Guida")]),
            _day(1, [(0, "Guida"), (150, "Riposo")])]
    assert "ContinuousDriving" not in _codes(days)


def test_lavoro_continuo_a_cavallo_mezzanotte():
    # Lavoro 21:00 → 04:00 = 7h senza pausa ≥30min (Dir. 2002/15 Art. 5)
    days = [_day(0, [(0, "Riposo"), (1260, "Lavoro")]),
            _day(1, [(0, "Lavoro"), (240, "Riposo")])]
    assert "ContinuousWorking_6" in _codes(days)


def test_giorni_mancanti_nel_buffer_contano_come_riposo():
    # buco di 20 giorni (carta non inserita) tra due periodi di lavoro
    days = [_work_day(i, 8, 16) for i in range(3)] + [_work_day(i, 8, 16) for i in range(23, 26)]
    assert "Weekly_TooLate" not in _codes(days)


def test_riposo_troncato_a_fine_dati_non_segnalato():
    # i dati finiscono durante il riposo: non si può giudicarne la durata
    days = [_work_day(i, 8, 18) for i in range(5)]
    days.append(_day(5, [(0, "Riposo"), (480, "Guida"), (720, "Riposo")]))
    codes = _codes(days)
    assert "Weekly_TooShort" not in codes
    assert "Daily_TooShort" not in codes

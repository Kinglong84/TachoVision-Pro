"""
Test buffer circolare attività Gen1 (issue GitHub #1).

Annex 1B, CardDriverActivity: activityPointerNewestRecord indica l'INIZIO
del record più recente (il giorno corrente), non la fine dei dati.
Se lo si usa come fine, il giorno corrente sparisce dallo scarico.
"""
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.parser import _decode_activities_gen1


def _record(prev_len, day, acis):
    ts = int(datetime(2026, 6, day, tzinfo=timezone.utc).timestamp())
    body = struct.pack(">IHH", ts, day, 100) + b"".join(struct.pack(">H", a) for a in acis)
    return struct.pack(">HH", prev_len, 4 + len(body)) + body


def _aci(minute, act):
    return (act << 11) | minute


def _buffer(records, size, oldest):
    """Scrive i record in un buffer circolare a partire da `oldest`."""
    buf = bytearray(size)
    pos = oldest
    starts = []
    for r in records:
        starts.append(pos)
        for b in r:
            buf[pos % size] = b
            pos += 1
    newest = starts[-1] % size
    return struct.pack(">HH", oldest, newest) + bytes(buf)


def _days(data):
    return [d.date for d in _decode_activities_gen1(data)]


DAY1 = [_aci(0, 0), _aci(480, 3), _aci(960, 0)]
DAY2 = [_aci(0, 0), _aci(420, 2), _aci(450, 3)]   # giorno corrente, ancora aperto


def test_include_il_record_piu_recente():
    r1 = _record(0, 1, DAY1)
    r2 = _record(len(r1), 2, DAY2)
    data = _buffer([r1, r2], 400, 0)
    assert _days(data) == ["2026-06-01", "2026-06-02"]


def test_record_piu_recente_a_cavallo_del_wrap():
    r1 = _record(0, 1, DAY1)
    r2 = _record(len(r1), 2, DAY2)
    size = 40
    data = _buffer([r1, r2], size, size - len(r1) - 4)   # r2 attraversa la fine del buffer
    assert _days(data) == ["2026-06-01", "2026-06-02"]


def test_un_solo_record():
    r1 = _record(0, 1, DAY1)
    data = _buffer([r1], 400, 0)
    assert _days(data) == ["2026-06-01"]

"""Carte Gen2: code page dei nomi e unione delle sezioni Gen1 (appendice 00) e Gen2 (02)."""

import os

import pytest

from models.parser import _name, _split_sections, parse_ddd


def test_code_page_dei_nomi():
    assert _name(bytes([2]) + "ŁUKASZ WÓJCIK".encode("iso8859_2") + b"\xff" * 5) == "ŁUKASZ WÓJCIK"
    assert _name(bytes([7]) + "ΠΑΠΑΔΟΠΟΥΛΟΣ".encode("iso8859_7")) == "ΠΑΠΑΔΟΠΟΥΛΟΣ"
    assert _name(bytes([5]) + "ИВАНОВ".encode("iso8859_5")) == "ИВАНОВ"
    assert _name(bytes([80]) + "ПЕТРОВ".encode("koi8_r")) == "ПЕТРОВ"
    assert _name(bytes([1]) + b"ROSSI" + b" " * 30) == "ROSSI"


def test_sezioni_tlv():
    blk = lambda fid, cf, data: bytes([fid >> 8, fid & 255, cf, len(data) >> 8, len(data) & 255]) + data
    raw = blk(0x0501, 0, b"\x01" * 10) + blk(0x0501, 2, b"\x01" * 17)
    sec = _split_sections(raw)
    assert len(sec[0][0x0501]) == 10 and len(sec[2][0x0501]) == 17
    assert _split_sections(raw + b"\x05") == {}            # coda non TLV: file non standard


_FULL = [p for p in [os.environ.get("TACHOVISION_REAL_DDD", "")] if p and os.path.exists(p)]


@pytest.mark.skipif(not _FULL, reason="serve un file reale con le due sezioni")
def test_unione_sezioni_su_file_reale():
    raw = open(_FULL[0], "rb").read()
    cd = parse_ddd(raw)
    assert cd.driver.generation.startswith("G2")
    assert any(p.gnss_lat is not None for p in cd.places)      # luoghi Gen2 con GNSS
    g1_only = sum(1 for v in _split_sections(raw)[0])
    assert g1_only and len(cd.places) > 112                     # più del solo buffer Gen1


def test_frontiere_e_carico_scarico_gen2_v2():
    import struct
    from datetime import datetime, timezone
    from models.parser import _decode_border_crossings, _decode_load_unload
    ts = int(datetime(2026, 3, 4, 10, 30, tzinfo=timezone.utc).timestamp())
    coord = lambda v: (v & 0xFFFFFF).to_bytes(3, "big")
    gnss = struct.pack(">I", ts) + bytes([5]) + coord(46300) + coord(13150) + bytes([1])
    border = b"\x00\x00" + bytes([0x1A, 0x01]) + gnss + (123456).to_bytes(3, "big")
    b = _decode_border_crossings(border)
    assert b[0]["country_left"] == "IT" and b[0]["country_entered"] == "AT"
    assert round(b[0]["lat"], 3) == 46.5 and b[0]["odometer_km"] == 123456
    load = b"\x00\x00" + struct.pack(">I", ts) + bytes([2]) + gnss + (99).to_bytes(3, "big")
    lu = _decode_load_unload(load)
    assert lu[0]["operation"] == "Scarico merce" and lu[0]["date"] == "2026-03-04"

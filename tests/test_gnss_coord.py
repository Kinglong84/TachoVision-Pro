"""Coordinate GNSS: formato ±GGGMM.M della norma (gradi e decimi di minuto)."""

from models.parser import _decode_geocoord, _decode_gnss_coord


def _b(v):
    return (v & 0xFFFFFF).to_bytes(3, "big")


def test_gradi_e_minuti():
    assert _decode_gnss_coord(_b(41065)) == round(41 + 6.5 / 60, 6)     # 41°06,5'
    assert _decode_geocoord(_b(16524)) == round(16 + 52.4 / 60, 6)      # 16°52,4'
    assert _decode_geocoord(_b(-3412)) == round(-(3 + 41.2 / 60), 6)    # ovest/sud


def test_minuti_impossibili_scartati():
    assert _decode_geocoord(_b(41700)) is None                          # 70 minuti
    assert _decode_geocoord(_b(0)) is None

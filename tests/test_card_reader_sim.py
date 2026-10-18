"""Lettore di carte collaudato su una carta simulata.

La carta simulata risponde ai comandi (SELECT, READ BINARY, PERFORM HASH, PSO,
UPDATE BINARY) con il contenuto di un file .DDD completo: il lettore deve
riprodurre lo stesso file byte per byte. Il file di riferimento è costruito qui
con dati inventati, così il test non dipende da file reali."""

import struct
from datetime import datetime, timezone

import pytest

import services.card_service as cs
from models.parser import _split_sections


def _blk(fid, cf, data):
    return bytes([fid >> 8, fid & 255, cf, len(data) >> 8, len(data) & 255]) + data


def _reference_file(gen2=True, card_type=1):
    """File .DDD inventato con la struttura di uno scarico completo."""
    app1 = bytes([card_type, 0, 0, 2, 2]) + struct.pack(">HHB", 100, 3, 4)
    app2 = bytes([card_type, 1, 0, 2, 2]) + struct.pack(">HHHHHH", 100, 3, 4, 5, 3, 2)
    out = _blk(0x0002, 0, bytes(range(25))) + _blk(0x0005, 0, b"\x11" * 8) + _blk(0x2F00, 0, b"\x61" * 20)
    s1 = cs.sizes_gen1(app1)
    for fid in cs.GEN1_ORDER:
        data = app1 if fid == 0x0501 else bytes((fid + i) & 255 for i in range(s1[fid]))
        out += _blk(fid, 0, data)
        if fid not in cs.CERTIFICATES:
            out += _blk(fid, 1, b"\x5A" * 128)
    if gen2:
        s2 = cs.sizes_gen2(app2)
        for fid in cs.GEN2_ORDER:
            if fid in cs.CERTIFICATES:
                data = b"\x7F\x21\x81\xC8" + b"\x33" * 0xC8      # 204 byte
            elif fid in s2:
                data = app2 if fid == 0x0501 else bytes((fid * 3 + i) & 255 for i in range(s2[fid]))
            else:
                continue                                       # EF versione 2 assenti
            out += _blk(fid, 2, data)
            if fid not in cs.CERTIFICATES:
                out += _blk(fid, 3, b"\xA5" * 64)
    return out


class FakeConn:
    def __init__(self, raw):
        sec = _split_sections(raw)
        self.files = {"MF": {f: d for f, d in sec[0].items() if f in (0x0002, 0x0005, 0x2F00)},
                      "G1": {f: d for f, d in sec[0].items() if f not in (0x0002, 0x0005, 0x2F00)},
                      "G2": sec.get(2, {})}
        self.sigs = {"G1": sec.get(1, {}), "G2": sec.get(3, {})}
        self.df, self.ef, self.updates = "MF", None, []

    def transmit(self, apdu):
        ins = apdu[1]
        if ins == 0xA4 and apdu[2] == 0x04:
            aid = apdu[5:]
            df = "G1" if aid == cs.AID_GEN1 else "G2" if aid == cs.AID_GEN2 else None
            if df is None or not self.files[df]:
                return [], 0x6A, 0x82
            self.df, self.ef = df, None
            return [], 0x90, 0x00
        if ins == 0xA4:
            fid = apdu[5] << 8 | apdu[6]
            if fid in self.files[self.df]:
                self.ef = fid
                return [], 0x90, 0x00
            return [], 0x6A, 0x82
        if ins == 0xB0:
            # come la carta reale: Le oltre la fine del file → 6700, Le=00 → quello che c'è
            data = self.files[self.df][self.ef]
            off, le = (apdu[2] << 8) | apdu[3], apdu[4]
            if le == 0:
                return list(data[off:off + 256]), 0x90, 0x00
            if off + le > len(data):
                return [], 0x67, 0x00
            return list(data[off:off + le]), 0x90, 0x00
        if ins == 0x2A and apdu[0] == 0x80:
            return [], 0x90, 0x00
        if ins == 0x2A:
            sig = self.sigs[self.df].get(self.ef)
            if sig and apdu[4] not in (len(sig) & 0xFF,):          # Le esatto, come la carta
                return [], 0x67, 0x00
            return (list(sig), 0x90, 0x00) if sig else ([], 0x69, 0x85)
        if ins == 0xD6:
            self.updates.append((self.df, self.ef, bytes(apdu[5:])))
            return [], 0x90, 0x00
        return [], 0x6D, 0x00

    def connect(self): pass
    def disconnect(self): pass


def _read(monkeypatch, raw, **kw):
    conn = FakeConn(raw)

    class Reader:
        def __str__(self): return "Lettore di prova"
        def createConnection(self): return conn

    monkeypatch.setattr(cs, "PYSCARD_OK", True)
    monkeypatch.setattr(cs, "sc_readers", lambda: [Reader()], raising=False)
    return cs.read_card("Lettore di prova", **kw), conn


@pytest.mark.parametrize("gen2", [True, False])
def test_scarico_identico_al_file_completo(monkeypatch, gen2):
    ref = _reference_file(gen2=gen2)
    raw, _ = _read(monkeypatch, ref)
    assert raw == ref
    assert cs.LAST_READ["generation"] == ("G2" if gen2 else "G1")


def test_carta_non_conducente_rifiutata(monkeypatch):
    with pytest.raises(cs.CardReadError, match="non è una carta conducente"):
        _read(monkeypatch, _reference_file(card_type=4))


def test_ef_obbligatorio_mancante(monkeypatch):
    ref = _reference_file(gen2=False)
    sec = _split_sections(ref)
    raw = b"".join(_blk(f, cf, d) for cf in sorted(sec) for f, d in sec[cf].items()
                   if not (f == 0x0505))
    with pytest.raises(cs.CardReadError, match="0505"):
        _read(monkeypatch, raw)


def test_data_di_scarico_scritta_in_ogni_applicazione(monkeypatch):
    raw, conn = _read(monkeypatch, _reference_file(), write_stamp=True)
    assert [(df, ef) for df, ef, _ in conn.updates] == [("G1", 0x050E), ("G2", 0x050E)]
    ts = struct.unpack(">I", conn.updates[0][2])[0]
    assert abs(ts - datetime.now(timezone.utc).timestamp()) < 60
    assert "scritta" in cs.LAST_READ["stamp"]


def test_orologio_non_plausibile():
    assert not cs.clock_plausible(datetime(2020, 1, 1, tzinfo=timezone.utc))
    now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert cs.clock_plausible(now)
    assert not cs.clock_plausible(now, previous=datetime(2027, 6, 1, tzinfo=timezone.utc))


import os as _os

_REAL = [p for p in [_os.environ.get("TACHOVISION_REAL_DDD", "")] if p and _os.path.exists(p)]


@pytest.mark.skipif(not _REAL, reason="serve uno scarico reale completo")
def test_scarico_identico_su_carta_reale_simulata(monkeypatch):
    ref = open(_REAL[0], "rb").read()
    raw, _ = _read(monkeypatch, ref)
    assert raw == ref

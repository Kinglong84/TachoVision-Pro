"""Nome standard del file di scarico: C_aaaaMMgg_HHmm_I_COGNOME_CARTA.DDD (ora UTC)."""

from datetime import datetime, timezone
from types import SimpleNamespace as Driver

from services.archive_service import ddd_filename


def _when():
    return datetime(2026, 10, 18, 9, 5, tzinfo=timezone.utc)


def test_formato_e_pulizia():
    d = Driver(firstname="Mario", surname="D'ANGELO", card_number="I000000000000001")
    assert ddd_filename(d, _when()) == "C_20261018_0905_M_DANGELO_I000000000000001.DDD"
    d = Driver(firstname="Łukasz", surname="Wójcik Nowak", card_number="PL0000000000001")
    assert ddd_filename(d, _when(), ".esm") == "C_20261018_0905_L_WOJCIK_NOWAK_PL0000000000001.esm"
    d = Driver(firstname="", surname="ИВАНОВ", card_number="")
    assert ddd_filename(d, _when()) == "C_20261018_0905_IVANOV_0000000000000000.DDD"

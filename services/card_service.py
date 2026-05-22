"""
services/card_service.py
Servizio di lettura carta tachigrafo via lettore USB (PC/SC).

Protocollo: EU Reg. 2016/799, Appendice 2 — ISO/IEC 7816 T=0/T=1.
Sequenza per file firmati (spec §3.3.3):
  SELECT EF → PERFORM HASH OF FILE → READ BINARY → PSO: COMPUTE DIGITAL SIGNATURE

Output: byte grezzi nel formato DDD (concatenazione oggetti TLV, spec §3.4.2).
"""
from __future__ import annotations
import time
import logging
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

try:
    from smartcard.System import readers as sc_readers
    from smartcard.Exceptions import NoCardException, NoReadersException
    from smartcard.util import toHexString
    PYSCARD_OK = True
except ImportError:
    PYSCARD_OK = False

# ── Application IDs (EU Reg. 2016/799, Appendice 2 §3.5.1.1) ─────────────────
# CLA=00 INS=A4 P1=04 (select by name) P2=0C (no FCI) Lc=06 AID...
AID_GEN1 = [0xFF, 0x54, 0x41, 0x43, 0x48, 0x4F]   # Gen1 (Reg. 3821/85)
AID_GEN2 = [0xFF, 0x53, 0x4D, 0x52, 0x44, 0x54]   # Gen2 (Reg. 2016/799)

# ── File IDs ──────────────────────────────────────────────────────────────────
# File a livello MF: accessibili senza selezione AID, non firmati (spec §3.3.2)
UNSIGNED_FIDS = {
    0x0002: "ICC",
    0x0005: "IC",
    0x0050: "CARD_CERTIFICATE",
    0x0051: "CA_CERTIFICATE",
}

# File applicazione tachigrafica: richiedono SELECT AID prima, letti con hash+firma (spec §3.3.3)
SIGNED_FIDS = {
    0x0501: "APPLICATION_IDENTIFICATION",
    0x0502: "EVENTS_DATA",
    0x0503: "FAULTS_DATA",
    0x0504: "DRIVER_ACTIVITY_DATA",       # attività Gen1
    0x0505: "VEHICLES_USED",
    0x0506: "PLACES_USED",
    0x0507: "CURRENT_USAGE",
    0x0508: "CONTROL_ACTIVITY_DATA",
    0x050E: "LAST_CARD_DOWNLOAD",
    0x0520: "IDENTIFICATION",
    0x0521: "DRIVING_LICENCE_INFO",
    0x0522: "SPECIFIC_CONDITIONS",
    0x0523: "VEHICLEUNITS_USED",          # veicoli Gen2
    0x0524: "ACTIVITY_DATA_V2",           # attività Gen2 v1
}

CARD_TAGS = {**UNSIGNED_FIDS, **SIGNED_FIDS}


# ── APDU helpers ──────────────────────────────────────────────────────────────

def _select_aid(conn, aid: list) -> Tuple[list, int, int]:
    """SELECT application by AID (P1=04 by name, P2=0C no FCI)."""
    return conn.transmit([0x00, 0xA4, 0x04, 0x0C, len(aid)] + aid)


def _select_ef(conn, fid: int) -> Tuple[list, int, int]:
    """SELECT child EF by FID (P1=02 child EF, P2=0C no FCI)."""
    return conn.transmit([0x00, 0xA4, 0x02, 0x0C, 0x02, (fid >> 8) & 0xFF, fid & 0xFF])


def _read_binary(conn, offset: int, length: int) -> Tuple[list, int, int]:
    return conn.transmit([0x00, 0xB0, (offset >> 8) & 0x7F, offset & 0xFF, min(length, 0xFE)])


def _get_response(conn, length: int) -> Tuple[list, int, int]:
    """GET RESPONSE per T=0 quando il comando ritorna 61xx."""
    return conn.transmit([0x00, 0xC0, 0x00, 0x00, min(length, 0xFE)])


def _perform_hash_of_file(conn, generation: str) -> Tuple[int, int]:
    """
    PERFORM HASH OF FILE (spec §3.5.13, TCS_124).
    CLA=80h INS=2Ah P1=90h P2=algoritmo
      Gen1: P2=00h (SHA-1)
      Gen2: P2=01h (SHA-256)
    Ritorna solo SW1, SW2 (nessun dato in risposta).
    """
    algo = 0x00 if generation == "G1" else 0x01
    _, sw1, sw2 = conn.transmit([0x80, 0x2A, 0x90, algo])
    return sw1, sw2


def _compute_digital_signature(conn) -> Optional[bytes]:
    """
    PSO: COMPUTE DIGITAL SIGNATURE (spec §3.5.14, TCS_130).
    CLA=00h INS=2Ah P1=9Eh P2=9Ah Le=00h
    Usa l'hash calcolato da PERFORM HASH OF FILE.
    Gestisce GET RESPONSE (SW=61xx) per protocollo T=0.
    """
    resp, sw1, sw2 = conn.transmit([0x00, 0x2A, 0x9E, 0x9A, 0x00])
    if sw1 == 0x90 and sw2 == 0x00:
        return bytes(resp)
    if sw1 == 0x61:  # T=0: GET RESPONSE con la lunghezza indicata in sw2
        resp, sw1, sw2 = _get_response(conn, sw2)
        if sw1 == 0x90:
            return bytes(resp)
    log.debug("PSO:CDS SW=%02X%02X", sw1, sw2)
    return None


def _read_full(conn, max_size: int = 65535) -> Optional[bytes]:
    """READ BINARY iterativo fino a EOF o max_size."""
    data, offset, chunk = [], 0, 0xFE
    while offset < max_size:
        resp, sw1, sw2 = _read_binary(conn, offset, min(chunk, max_size - offset))
        if sw1 == 0x6B:
            break  # offset oltre il file: nessun dato
        if sw1 == 0x62 and sw2 == 0x82:
            if resp:  # EOF warning: resp contiene i byte effettivamente letti
                data.extend(resp)
            break
        if sw1 == 0x90 and sw2 == 0x00:
            data.extend(resp)
            offset += len(resp)
            if len(resp) < chunk:
                break  # fine file
        elif sw1 == 0x61:
            data.extend(resp)
            offset += len(resp)
        elif sw1 == 0x6C:
            # 6Cxx: lunghezza corretta è sw2, riprova
            resp, sw1, sw2 = _read_binary(conn, offset, sw2)
            if sw1 == 0x90:
                data.extend(resp)
                offset += len(resp)
            break
        elif sw1 == 0x67:
            # 67xx: wrong length, dimezza il chunk
            chunk = max(1, chunk // 2)
            if chunk < 4:
                break
        else:
            log.debug("READ BINARY offset=%d SW=%02X%02X", offset, sw1, sw2)
            break
    return bytes(data) if data else None


def _build_tlv(fid: int, data: bytes, is_signature: bool = False) -> bytes:
    """
    Costruisce un oggetto TLV secondo spec §3.4.2:
      Tag (3 byte): FID_hi || FID_lo || 0x00 per dati, || 0x01 per firma
      Lunghezza (2 byte): big-endian
      Valore: i dati
    """
    suffix = 0x01 if is_signature else 0x00
    tag = bytes([(fid >> 8) & 0xFF, fid & 0xFF, suffix])
    length = bytes([(len(data) >> 8) & 0xFF, len(data) & 0xFF])
    return tag + length + data


# ── API pubblica ──────────────────────────────────────────────────────────────

def list_readers() -> List[str]:
    if not PYSCARD_OK:
        return []
    try:
        return [str(r) for r in sc_readers()]
    except Exception:
        return []


def get_status() -> dict:
    if not PYSCARD_OK:
        return {"available": False, "readers": [], "error": "pyscard non installato"}
    try:
        rds = sc_readers()
        out = {"available": len(rds) > 0, "readers": [], "error": None}
        for r in rds:
            conn = r.createConnection()
            try:
                conn.connect()
                atr = toHexString(conn.getATR())
                conn.disconnect()
                out["readers"].append({"name": str(r), "card": True, "atr": atr})
            except NoCardException:
                out["readers"].append({"name": str(r), "card": False})
            except Exception as e:
                out["readers"].append({"name": str(r), "card": False, "error": str(e)})
        return out
    except NoReadersException:
        return {"available": False, "readers": [], "error": "Nessun lettore collegato"}
    except Exception as e:
        return {"available": False, "readers": [], "error": str(e)}


def read_card(reader_name: str, progress_cb=None, timeout_s: int = 60) -> bytes:
    """
    Legge una carta tachigrafica conforme EU Reg. 2016/799 (Gen1 e Gen2 v1).

    Sequenza completa (spec Appendice 2 §3.3):
      1. ATR / connect
      2. File MF non firmati: SELECT + READ BINARY
      3. SELECT AID (Gen1 poi Gen2)
      4. File applicazione firmati: SELECT + PERFORM HASH + READ BINARY + PSO COMPUTE SIG

    Ritorna i byte grezzi nel formato DDD (concatenazione TLV §3.4.2).
    progress_cb(step, total, message) — opzionale, per aggiornare la UI.
    """
    if not PYSCARD_OK:
        raise RuntimeError("pyscard non installato. Esegui: pip install pyscard")

    available = sc_readers()
    reader = next((r for r in available if str(r) == reader_name), None)
    if not reader:
        raise RuntimeError(f"Lettore non trovato: {reader_name}")

    conn = reader.createConnection()

    if progress_cb:
        progress_cb(0, 100, "Attesa carta…")

    # Attendi carta entro timeout
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            conn.connect()
            break
        except NoCardException:
            time.sleep(0.5)
    else:
        raise RuntimeError("Nessuna carta inserita entro il timeout")

    blocks = []
    generation = None

    # ── Fase 1: file non firmati a livello MF (spec §3.3.2) ──────────────────
    if progress_cb:
        progress_cb(5, 100, "Lettura file di identificazione…")

    for fid, name in UNSIGNED_FIDS.items():
        _, sw1, sw2 = _select_ef(conn, fid)
        if sw1 == 0x90 and sw2 == 0x00:
            ef = _read_full(conn)
            if ef:
                blocks.append(_build_tlv(fid, ef, is_signature=False))
                log.debug("Letto (unsigned) %s [%d byte]", name, len(ef))
        else:
            log.debug("SELECT %s SW=%02X%02X — skip", name, sw1, sw2)

    # ── Fase 2: selezione ADF tachigrafico ───────────────────────────────────
    if progress_cb:
        progress_cb(15, 100, "Selezione applicazione tachigrafica…")

    _, sw1_g1, sw2_g1 = _select_aid(conn, AID_GEN1)
    if sw1_g1 in (0x90, 0x61):
        generation = "G1"
        log.info("AID Gen1 selezionato (SW=%02X%02X)", sw1_g1, sw2_g1)
    else:
        _, sw1_g2, sw2_g2 = _select_aid(conn, AID_GEN2)
        if sw1_g2 in (0x90, 0x61):
            generation = "G2"
            log.info("AID Gen2 selezionato (SW=%02X%02X)", sw1_g2, sw2_g2)
        else:
            log.warning(
                "Nessun AID tachigrafico risponde — Gen1 SW=%02X%02X, Gen2 SW=%02X%02X",
                sw1_g1, sw2_g1, sw1_g2, sw2_g2,
            )

    # ── Fase 3: file firmati dell'applicazione (spec §3.3.3) ─────────────────
    total_signed = len(SIGNED_FIDS)
    for idx, (fid, name) in enumerate(SIGNED_FIDS.items()):
        if progress_cb:
            pct = 20 + int(75 * (idx + 1) / total_signed)
            progress_cb(pct, 100, f"Lettura {name}…")

        # SELECT EF
        _, sw1, sw2 = _select_ef(conn, fid)
        if not (sw1 == 0x90 and sw2 == 0x00):
            log.debug("SELECT %s FID=%04X SW=%02X%02X — skip", name, fid, sw1, sw2)
            continue

        # PERFORM HASH OF FILE (la carta calcola l'hash internamente)
        # Se fallisce (es. carta non supporta il comando su questo file),
        # proseguiamo comunque con la sola lettura dati.
        h_sw1, h_sw2 = _perform_hash_of_file(conn, generation or "G1")
        hash_ok = h_sw1 == 0x90 and h_sw2 == 0x00
        if not hash_ok:
            log.debug("PERFORM HASH %s SW=%02X%02X — lettura senza firma", name, h_sw1, h_sw2)

        # READ BINARY (dati effettivi del file)
        ef = _read_full(conn)
        if not ef:
            continue
        blocks.append(_build_tlv(fid, ef, is_signature=False))

        # PSO: COMPUTE DIGITAL SIGNATURE (solo se HASH è stato calcolato con successo)
        if hash_ok:
            sig = _compute_digital_signature(conn)
            if sig:
                blocks.append(_build_tlv(fid, sig, is_signature=True))
                log.debug("Letto (firmato) %s [data=%d, sig=%d]", name, len(ef), len(sig))
            else:
                log.debug("Firma non disponibile per %s", name)
        else:
            log.debug("Letto (senza firma) %s [%d byte]", name, len(ef))

    # ── Fase 3b: file Gen2 aggiuntivi su carte Gen1 in tachigrafi Gen2 ──────────
    # Alcune carte Gen1 usate su tachigrafi Gen2 (Smart Tachograph) hanno
    # anche i file Gen2 (0x0524 con dati GNSS, 0x0523 VU, 0x050E download).
    # Questi sono accessibili solo dopo SELECT AID Gen2, anche se la carta
    # ha risposto prima all'AID Gen1.
    # NON verifichiamo "already": se la fase 3 ha letto 0x0524 sotto Gen1 AID
    # con dati errati/vuoti, vogliamo rileggerlo sotto Gen2 AID (versione corretta).
    # Il parser _pass1 gestisce i duplicati scegliendo il payload più lungo.
    if generation == "G1":
        _, sw1_g2b, sw2_g2b = _select_aid(conn, AID_GEN2)
        if sw1_g2b in (0x90, 0x61):
            log.info("AID Gen2 accessibile su carta Gen1 (SW=%02X%02X) — lettura GNSS/VU…",
                     sw1_g2b, sw2_g2b)
            print(f"[TachoVision] Fase 3b: AID Gen2 OK (SW={sw1_g2b:02X}{sw2_g2b:02X})")
            GEN2_EXTRA = {
                0x050E: "LAST_CARD_DOWNLOAD",
                0x0523: "VEHICLEUNITS_USED",
                0x0524: "ACTIVITY_DATA_V2",     # contiene waypoint GNSS
                0x0526: "PLACES_AUTHENTICATION",
                0x0527: "GNSS_PLACES_AUTH",
            }
            for fid, name in GEN2_EXTRA.items():
                _, sw1, sw2 = _select_ef(conn, fid)
                if not (sw1 == 0x90 and sw2 == 0x00):
                    log.debug("Gen2-extra SELECT %s FID=%04X SW=%02X%02X — skip",
                              name, fid, sw1, sw2)
                    print(f"[TachoVision] Gen2-extra {name} (FID={fid:04X}): SELECT SW={sw1:02X}{sw2:02X} — skip")
                    continue
                # PERFORM HASH con algoritmo Gen2 (SHA-256, P2=01)
                # richiesto dalla spec prima di READ BINARY su alcune implementazioni
                h_sw1, h_sw2 = _perform_hash_of_file(conn, "G2")
                if h_sw1 != 0x90:
                    log.debug("Gen2-extra HASH %s SW=%02X%02X — lettura senza hash",
                              name, h_sw1, h_sw2)
                ef = _read_full(conn)
                if ef:
                    blocks.append(_build_tlv(fid, ef, is_signature=False))
                    log.info("Letto Gen2-extra %s [%d byte]", name, len(ef))
                    print(f"[TachoVision] Gen2-extra {name}: {len(ef)} byte OK")
                else:
                    print(f"[TachoVision] Gen2-extra {name}: SELECT OK ma dati vuoti")
        else:
            log.info("AID Gen2 NON accessibile su carta Gen1 (SW=%02X%02X) — GNSS non disponibile",
                     sw1_g2b, sw2_g2b)
            print(f"[TachoVision] Fase 3b: AID Gen2 NON accessibile (SW={sw1_g2b:02X}{sw2_g2b:02X}) — nessun GNSS")

    conn.disconnect()

    if not blocks:
        raise RuntimeError(
            "Nessun dato letto dalla carta. "
            "Verifica che la carta tachigrafica sia inserita correttamente. "
            f"AID Gen1 SW={sw1_g1:02X}{sw2_g1:02X}, Gen2 SW={sw1_g2:02X}{sw2_g2:02X}."
            if generation is None else
            "Nessun dato letto dalla carta (AID selezionato ma tutti i file vuoti)."
        )

    if progress_cb:
        progress_cb(100, 100, f"Completato — {len(blocks)} blocchi ({generation or '?'})")

    log.info("Lettura carta completata: %d blocchi TLV, generazione=%s", len(blocks), generation)
    return b"".join(blocks)

"""
controllers/archive_controller.py
Gestisce tutti i callback Dash relativi all'archivio locale dei file .DDD.

FUNZIONALITÀ:
  1. auto_save_ddd:        salva automaticamente il file .DDD ogni volta che vengono
                           caricati nuovi dati (upload utente o lettura smartcard)
  2. refresh_archive:      aggiorna la tabella archivio (stats, alert scadenze, righe)
  3. download_ddd:         scarica un singolo file .DDD nel browser
  4. delete_ddd:           elimina un file dall'archivio locale
  5. update_selection:     aggiorna store-archive-selected in base ai checkbox
  6. select_all:           seleziona/deseleziona tutti i file tramite il checkbox header
  7. update_export_btn:    aggiorna il testo del bottone export con il conteggio selezione
  8. export_all:           esporta i file selezionati (o tutti se nessuno è selezionato)
  9. open_archive_folder:  apre il file manager nella cartella archivio
 10. load_from_archive:    carica un file archiviato nella dashboard (store-data + tab panoramica)
"""

from __future__ import annotations
import base64
from typing import Any

from dash import Input, Output, State, dcc, no_update, callback_context, ALL
from dash.exceptions import PreventUpdate

from services.archive_service import get_archive
from views.tabs.archivio import build_stats, build_due_alerts, build_table


def register(app):

    # ── 1. Salva automaticamente il .DDD quando arrivano nuovi dati ──────────
    @app.callback(
        Output("store-archive", "data"),
        Input("store-data", "data"),
        State("store-archive", "data"),
        prevent_initial_call=True,
    )
    def auto_save_ddd(raw, current_archive):
        if not raw or not raw.get("_raw_bytes"):
            return current_archive or {}

        from models.card_data import CardData
        cd = CardData.from_dict(raw)

        raw_bytes = raw.get("_raw_bytes")
        if raw_bytes:
            raw_bytes = base64.b64decode(raw_bytes)
        else:
            raw_bytes = _rebuild_ddd_bytes(cd)

        archive = get_archive()
        entry = archive.save_ddd(raw_bytes, cd, source=raw.get("_source", "upload"))
        return {"saved": entry.filename, "ts": entry.download_date}

    # ── 2. Aggiorna la visualizzazione dell'archivio ──────────────────────────
    @app.callback(
        Output("archive-stats-row",       "children"),
        Output("archive-due-alerts",      "children"),
        Output("archive-table-container", "children"),
        Input("btn-archive-refresh", "n_clicks"),
        Input("store-archive",        "data"),
    )
    def refresh_archive(n, _store):
        archive = get_archive()
        entries = archive.list_entries()
        return build_stats(entries), build_due_alerts(entries), build_table(entries)

    # ── 3. Download singolo file .DDD nel browser ─────────────────────────────
    @app.callback(
        Output("download-ddd-file", "data"),
        Input({"type": "btn-dl-ddd", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def download_ddd(n_clicks_list):
        ctx = callback_context
        if not ctx.triggered or not any(n_clicks_list):
            raise PreventUpdate

        import json
        btn      = ctx.triggered[0]["prop_id"]
        filename = json.loads(btn.rsplit(".", 1)[0])["index"]

        archive = get_archive()
        raw = archive.get_bytes(filename)
        if raw is None:
            raise PreventUpdate

        return dcc.send_bytes(raw, filename)

    # ── 4. Elimina file dall'archivio ─────────────────────────────────────────
    @app.callback(
        Output("store-archive", "data", allow_duplicate=True),
        Input({"type": "btn-del-ddd", "index": ALL}, "n_clicks"),
        State("store-archive", "data"),
        prevent_initial_call=True,
    )
    def delete_ddd(n_clicks_list, current):
        ctx = callback_context
        if not ctx.triggered or not any(n_clicks_list):
            raise PreventUpdate

        import json
        btn      = ctx.triggered[0]["prop_id"]
        filename = json.loads(btn.rsplit(".", 1)[0])["index"]
        get_archive().delete(filename)
        return {**(current or {}), "deleted": filename}

    # ── 5. Aggiorna store-archive-selected in base ai checkbox ────────────────
    @app.callback(
        Output("store-archive-selected", "data"),
        Input({"type": "chk-ddd", "index": ALL}, "value"),
        State({"type": "chk-ddd", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def update_selection(values, ids):
        """Raccoglie i filename dei checkbox spuntati e li salva nello store."""
        selected = [id_["index"] for val, id_ in zip(values, ids) if val]
        return selected

    # ── 6. Seleziona/deseleziona tutti tramite checkbox header ────────────────
    @app.callback(
        Output({"type": "chk-ddd", "index": ALL}, "value"),
        Input("chk-archive-all", "value"),
        State({"type": "chk-ddd", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def select_all(all_val, ids):
        """Imposta tutti i checkbox a selezionato o deselezionato."""
        new_val = ["sel"] if all_val else []
        return [new_val for _ in ids]

    # ── 7. Aggiorna label del bottone export con conteggio selezione ──────────
    @app.callback(
        Output("btn-export-all", "children"),
        Input("store-archive-selected", "data"),
    )
    def update_export_btn(selected):
        if selected:
            return f"📋 Esporta {len(selected)} selezionati"
        return "📋 Esporta tutti"

    # ── 8. Export verso cartella esterna ─────────────────────────────────────
    @app.callback(
        Output("export-result", "children"),
        Input("btn-export-all",    "n_clicks"),
        State("input-export-path", "value"),
        State("store-archive-selected", "data"),
        prevent_initial_call=True,
    )
    def export_all(n, dest_path, selected):
        """
        Esporta i file selezionati (o tutti se nessuno selezionato)
        nella cartella specificata dall'utente.
        """
        if not n or not dest_path:
            return "⚠️ Inserisci prima il percorso di destinazione."

        archive  = get_archive()
        entries  = archive.list_entries()

        if selected:
            to_export = [e for e in entries if e.filename in selected]
        else:
            to_export = entries

        if not to_export:
            return "Nessun file da esportare."

        results = {}
        for entry in to_export:
            results[entry.filename] = archive.export_to_folder(
                entry.filename, dest_path.strip()
            )

        ok  = sum(1 for v in results.values() if v)
        err = sum(1 for v in results.values() if not v)

        if err == 0:
            return f"✅ {ok} file copiati con successo in: {dest_path}"
        return f"⚠️ {ok} copiati, {err} errori. Verifica che il percorso sia accessibile."

    # ── 9. Apri cartella archivio nel file manager ────────────────────────────
    @app.callback(
        Output("btn-open-archive-dir", "title"),
        Input("btn-open-archive-dir", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_archive_folder(n):
        import subprocess, platform
        path = get_archive().archive_path_str
        try:
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", path])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass
        return f"Cartella: {path}"

    # ── 10. Carica file archiviato nella dashboard ────────────────────────────
    @app.callback(
        Output("store-data", "data", allow_duplicate=True),
        Output("store-tab",  "data", allow_duplicate=True),
        Input({"type": "btn-load-ddd", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def load_from_archive(n_clicks_list):
        ctx = callback_context
        if not ctx.triggered or not any(n_clicks_list):
            raise PreventUpdate

        import json
        from models.parser import parse_ddd
        from models.analytics import enrich
        from models.card_data import CardData

        btn      = ctx.triggered[0]["prop_id"]
        filename = json.loads(btn.rsplit(".", 1)[0])["index"]

        raw = get_archive().get_bytes(filename)
        if raw is None:
            raise PreventUpdate

        cd = parse_ddd(raw)
        cd = enrich(cd)
        d  = cd.to_dict()
        d["_raw_bytes"] = base64.b64encode(raw).decode("ascii")
        d["_source"]    = "archivio"

        return d, "panoramica"


# ── Helper: ricostruzione DDD dai dati parsati ────────────────────────────────
def _rebuild_ddd_bytes(cd) -> bytes:
    """Fallback: ricostruisce un file .DDD sintetico dai dati parsati."""
    import struct
    import dataclasses

    def _tlv(tag: int, data: bytes) -> bytes:
        hi, lo   = (tag >> 8) & 0xFF, tag & 0xFF
        lhi, llo = (len(data) >> 8) & 0xFF, len(data) & 0xFF
        return bytes([hi, lo, 0x00, lhi, llo]) + data

    def _u32be(v: int) -> bytes:
        return struct.pack(">I", max(0, v))

    def _str_bytes(s: str, n: int) -> bytes:
        b = s.encode("latin-1", errors="replace")
        return b[:n].ljust(n, b"\x00")

    blocks = []
    d = cd.driver
    from datetime import datetime

    def _ts(s):
        if not s: return _u32be(0)
        for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M"):
            try: return _u32be(int(datetime.strptime(s, fmt).timestamp()))
            except: pass
        return _u32be(0)

    ident = (
        bytes([0, 0, 0]) +
        _str_bytes(d.card_number, 16) +
        _str_bytes(d.issuing_authority, 36) +
        _ts(d.issue_date) +
        _ts(d.validity_begin) +
        _ts(d.expiry_date) +
        bytes([0]) + _str_bytes(d.surname, 35) +
        bytes([0]) + _str_bytes(d.firstname, 35) +
        _ts(d.birth_date) +
        _str_bytes(d.language, 2)
    )
    blocks.append(_tlv(0x0520, ident))

    act_records = bytearray()
    act_records += b"\x00" * 4

    for day in cd.activities:
        try:
            dt_ts = int(datetime.strptime(day.date, "%Y-%m-%d").timestamp())
        except:
            continue

        ch = sorted(day.changes, key=lambda c: c.time)
        aci_bytes = bytearray()
        for c in ch:
            act_map  = {"Riposo": 0, "Disponibilità": 1, "Lavoro": 2, "Guida": 3}
            act_bits = act_map.get(c.activity, 0)
            manual_bit = 1 if c.manual else 0
            aci = (0 << 15) | (manual_bit << 14) | (act_bits << 10) | (c.time & 0x3FF)
            aci_bytes += struct.pack(">H", aci)

        dist    = max(0, min(65535, int(day.distance_km * 10)))
        rec_len = 12 + len(aci_bytes)
        rec = (
            struct.pack(">H", 0) +
            struct.pack(">H", rec_len) +
            _u32be(dt_ts) +
            struct.pack(">H", 1) +
            struct.pack(">H", dist) +
            bytes(aci_bytes)
        )
        act_records += rec

    blocks.append(_tlv(0x0504, bytes(act_records)))

    if cd.vehicles:
        veh_data = struct.pack(">H", len(cd.vehicles))
        for v in cd.vehicles:
            vrn_b = _str_bytes(v.vrn, 13)
            first = _ts(v.first_use)
            last  = _ts(v.last_use)
            rec = bytes([0, 0, 0]) + vrn_b + first + last + bytes([0, 0, 0])
            veh_data += rec
        blocks.append(_tlv(0x0505, veh_data))

    return b"".join(blocks)

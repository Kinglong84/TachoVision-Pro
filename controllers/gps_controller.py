"""
controllers/gps_controller.py
==============================
Gestisce la navigazione interattiva verso i dati GPS:
  1. navigate_to_gnss: click sull'icona GPS in attività o luoghi
                       → naviga a luoghi con filtro data e seleziona il tracciato
  2. clear_gnss_filter: click su "✕ Rimuovi filtro" nel banner
                        → azzera il filtro data sulla mappa
"""

from __future__ import annotations
import json

from dash import Input, Output, State, callback_context, ALL, no_update
from dash.exceptions import PreventUpdate


def register(app):

    # ── 1. Click icona GPS (attività o luoghi) → naviga + imposta filtro data ──
    @app.callback(
        Output("store-tab",       "data", allow_duplicate=True),
        Output("store-gnss-date", "data", allow_duplicate=True),
        Input({"type": "btn-gps-day",   "index": ALL}, "n_clicks"),
        Input({"type": "btn-gps-place", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def navigate_to_gnss(day_clicks, place_clicks):
        """
        Gestisce il click sulle icone GPS:
        - btn-gps-day  (tab attività): index = "YYYY-MM-DD" → vai a luoghi + filtra
        - btn-gps-place (tab luoghi):  index = "N|YYYY-MM-DD" → filtra in loco
        """
        ctx = callback_context
        all_clicks = (day_clicks or []) + (place_clicks or [])
        if not ctx.triggered or not any(c for c in all_clicks if c):
            raise PreventUpdate

        btn = ctx.triggered[0]["prop_id"]
        try:
            btn_id = json.loads(btn.rsplit(".", 1)[0])
        except Exception:
            raise PreventUpdate

        btn_type = btn_id.get("type", "")
        idx = str(btn_id.get("index", ""))

        if btn_type == "btn-gps-day":
            # Naviga alla tab luoghi e imposta il filtro data
            return "luoghi", idx

        if btn_type == "btn-gps-place":
            # Già nella tab luoghi: aggiorna solo il filtro
            # idx ha forma "N|YYYY-MM-DD"
            iso_date = idx.split("|", 1)[1] if "|" in idx else None
            return no_update, iso_date

        raise PreventUpdate

    # ── 2. Pulsante "✕ Rimuovi filtro" → azzera filtro GPS ───────────────────
    @app.callback(
        Output("store-gnss-date", "data", allow_duplicate=True),
        Input("btn-gnss-clear", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_gnss_filter(n):
        """Rimuove il filtro data dalla mappa GPS mostrando tutti i waypoint."""
        if n:
            return None
        raise PreventUpdate

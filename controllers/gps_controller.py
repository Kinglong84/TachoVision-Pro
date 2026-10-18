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


    # ── 3. Navigatore della mappa (primo / prec. / adatta / succ. / ultimo / livello) ──
    @app.callback(
        Output("gnss-map", "figure"),
        Output("gnss-view", "data"),
        Output("gnss-caption", "children"),
        Output("gnss-layer", "children"),
        Input("gnss-first", "n_clicks"),
        Input("gnss-prev", "n_clicks"),
        Input("gnss-fit", "n_clicks"),
        Input("gnss-next", "n_clicks"),
        Input("gnss-last", "n_clicks"),
        Input("gnss-layer", "n_clicks"),
        State("gnss-points", "data"),
        State("gnss-view", "data"),
        prevent_initial_call=True,
    )
    def navigate_map(_f, _p, _a, _n, _l, _y, points, view):
        from views.tabs.luoghi import gnss_figure
        if not points:
            raise PreventUpdate
        trig = callback_context.triggered[0]["prop_id"].split(".")[0]
        view = dict(view or {"idx": None, "layer": "strade"})
        idx, last = view.get("idx"), len(points) - 1
        if trig == "gnss-first":
            idx = 0
        elif trig == "gnss-last":
            idx = last
        elif trig == "gnss-prev":
            idx = last if idx is None else max(0, idx - 1)
        elif trig == "gnss-next":
            idx = 0 if idx is None else min(last, idx + 1)
        elif trig == "gnss-fit":
            idx = None
        elif trig == "gnss-layer":
            view["layer"] = "strade" if view.get("layer") == "satellite" else "satellite"
        view["idx"] = idx
        caption = (f"{len(points)} punti" if idx is None
                   else f"{idx + 1}/{len(points)} · {points[idx]['time']}")
        label = "Strade" if view["layer"] == "satellite" else "Satellite"
        return gnss_figure(points, idx, view["layer"]), view, caption, label

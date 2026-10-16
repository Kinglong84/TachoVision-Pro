"""
controllers/activities_controller.py
====================================
Menu della tab Attività (periodo, giorno ◁ ▷, cosa mostrare, vista).

"""

from datetime import date, timedelta

from dash import Input, Output, State, callback_context, no_update
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from views.tabs.attivita import build_blocks


def register(app):

    @app.callback(
        Output("act-day", "date"),
        Output("act-period", "value"),
        Input("act-prev", "n_clicks"),
        Input("act-next", "n_clicks"),
        State("act-day", "date"),
        prevent_initial_call=True,
    )
    def step_day(_p, _n, current):
        """Le frecce passano alla vista "Giorno" e spostano la data di un giorno."""
        if not current:
            raise PreventUpdate
        trig = callback_context.triggered[0]["prop_id"]
        delta = -1 if trig.startswith("act-prev") else 1
        return (date.fromisoformat(current[:10]) + timedelta(days=delta)).isoformat(), "day"

    @app.callback(
        Output("blocks-attivita", "children"),
        Input("act-period", "value"),
        Input("act-kinds", "value"),
        Input("act-view", "value"),
        Input("act-day", "date"),
        Input("store-manual-rev", "data"),
        State("store-data", "data"),
    )
    def update(period, kinds, view, day, _rev, raw):
        if not raw:
            raise PreventUpdate
        trig = [t["prop_id"] for t in callback_context.triggered]
        if trig == ["act-day.date"] and period != "day":
            period = "day"                        # scegliere una data apre quel giorno
        return build_blocks(CardData.from_dict(raw), period, kinds, view,
                            (day or "")[:10] or None)

"""
controllers/dashboard_controller.py
===================================
Navigazione del disco della Dashboard (giorno precedente / successivo).
"""

from dash import Input, Output, State, callback_context
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from views.tabs.panoramica import build_hero, worked_days


def register(app):

    @app.callback(
        Output("disc-hero-wrap", "children"),
        Output("disc-day", "data"),
        Input("disc-prev", "n_clicks"),
        Input("disc-next", "n_clicks"),
        State("disc-day", "data"),
        State("store-data", "data"),
        prevent_initial_call=True,
    )
    def step(_p, _n, current, raw):
        trig = callback_context.triggered[0]
        if not raw or not trig["value"]:
            raise PreventUpdate
        cd = CardData.from_dict(raw)
        worked = worked_days(cd)
        if not worked:
            raise PreventUpdate
        i = worked.index(current) if current in worked else len(worked) - 1
        i += -1 if trig["prop_id"].startswith("disc-prev") else 1
        i = max(0, min(len(worked) - 1, i))
        return build_hero(cd, worked[i]), worked[i]

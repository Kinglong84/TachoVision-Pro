"""
controllers/worktime_controller.py
==================================
Menu della tab Riepilogo (vista, sintesi, riposi, ordinamento, fascia maggiorata).

"""

from dash import Input, Output, State
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from views.tabs.riepilogo import build_periods


def register(app):

    @app.callback(
        Output("wt-periods", "children"),
        Output("store-wt-view", "data"),
        Input("wt-view", "value"),
        Input("wt-options", "value"),
        Input("wt-order", "value"),
        State("store-data", "data"),
    )
    def update(view, options, order, raw):
        if not raw:
            raise PreventUpdate
        # l'export usa la vista mostrata (giorno/turno, sintesi, fascia)
        return (build_periods(CardData.from_dict(raw), view, options, order),
                {"view": view, "options": options or [], "order": order})

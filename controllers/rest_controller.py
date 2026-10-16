"""
controllers/rest_controller.py
==============================
Filtro periodo della tab Riposo.

"""

from dash import Input, Output, State
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from views.tabs.riposo import build_list


def register(app):

    @app.callback(
        Output("rest-list", "children"),
        Input("rest-period", "value"),
        State("store-data", "data"),
    )
    def update_list(period, raw):
        if not raw:
            raise PreventUpdate
        return build_list(CardData.from_dict(raw), period)

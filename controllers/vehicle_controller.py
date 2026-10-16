"""
controllers/vehicle_controller.py
=================================
Menu della tab Veicoli (riepiloghi settimanali/mensili, ordinamento).

"""

from dash import Input, Output, State
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from views.tabs.veicoli import build_list


def register(app):

    @app.callback(
        Output("veh-list", "children"),
        Input("veh-summary", "value"),
        Input("veh-order", "value"),
        State("store-data", "data"),
    )
    def update(summary, order, raw):
        if not raw:
            raise PreventUpdate
        return build_list(CardData.from_dict(raw), summary, order)

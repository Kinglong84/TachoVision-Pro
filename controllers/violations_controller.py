"""
controllers/violations_controller.py
====================================
Callback dei filtri della tab Infrazioni.

Ogni cambio di filtro ricostruisce l'elenco con views.tabs.infrazioni.build_list().
"""

from dash import ALL, Input, Output, State
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from views.tabs.infrazioni import build_list


def register(app):

    @app.callback(
        Output("viol-list", "children"),
        Input("viol-period", "value"),
        Input("viol-sev", "value"),
        Input({"type": "viol-code-filter", "group": ALL}, "value"),
        Input("viol-details", "value"),
        State("store-data", "data"),
    )
    def update_list(period, sevs, code_groups, details, raw):
        if not raw:
            raise PreventUpdate
        codes = [c for group in (code_groups or []) for c in (group or [])]
        return build_list(CardData.from_dict(raw), period, sevs, codes, details)

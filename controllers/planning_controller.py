"""
controllers/planning_controller.py
==================================
Macchina del tempo della tab Pianificazione.

"Voglio ancora lavorare" / "Voglio riposarmi" per giorni/ore/minuti:
ricalcola la pianificazione come se il tempo fosse passato.
"""

from dash import Input, Output, State
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from views.tabs.pianificazione import build_content


def register(app):

    @app.callback(
        Output("plan-content", "children"),
        Input("plan-mode", "value"),
        Input("plan-days", "value"),
        Input("plan-hours", "value"),
        Input("plan-minutes", "value"),
        State("store-data", "data"),
        prevent_initial_call=True,
    )
    def update(mode, days, hours, minutes, raw):
        if not raw:
            raise PreventUpdate
        total = (int(days or 0) * 24 + int(hours or 0)) * 60 + int(minutes or 0)
        mode = None if mode == "none" else mode
        return build_content(CardData.from_dict(raw), mode, total)

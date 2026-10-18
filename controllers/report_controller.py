"""
controllers/report_controller.py
================================
Download dei report dalle barre "PDF/EXCEL" delle tab.

Nel browser il file viene scaricato (equivale a "Copia su file"); da lì si
può aprire o allegare a una e-mail.
"""

from dash import ALL, Input, Output, State, callback_context, dcc, no_update
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from services.report_service import generate


def register(app):

    @app.callback(
        Output("download-report", "data"),
        Output({"type": "exp-msg", "report": ALL}, "children"),
        Input({"type": "exp-btn", "report": ALL}, "n_clicks"),
        State({"type": "exp-fmt", "report": ALL}, "value"),
        State({"type": "exp-range", "report": ALL}, "start_date"),
        State({"type": "exp-range", "report": ALL}, "end_date"),
        State({"type": "exp-opt", "report": ALL}, "value"),
        State({"type": "exp-btn", "report": ALL}, "id"),
        State("store-data", "data"),
        State("store-wt-view", "data"),
        prevent_initial_call=True,
    )
    def download(clicks, fmts, starts, ends, opts, ids, raw, wt_view):
        trig = callback_context.triggered[0]
        if not raw or not trig["value"]:
            raise PreventUpdate
        import json
        report = json.loads(trig["prop_id"].split(".")[0])["report"]
        i = next(k for k, x in enumerate(ids) if x["report"] == report)
        msgs = [""] * len(ids)
        try:
            data, name = generate(report, fmts[i], CardData.from_dict(raw), starts[i], ends[i],
                              view=wt_view, options=opts[i] if i < len(opts) else [])
        except Exception as e:      # il messaggio va mostrato vicino al pulsante
            msgs[i] = f"⚠️ Impossibile creare il file: {e}"
            return no_update, msgs
        if isinstance(data, bytes):
            return dcc.send_bytes(data, name), msgs
        return dcc.send_string(data, name), msgs

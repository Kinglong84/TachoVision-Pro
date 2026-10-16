"""
controllers/settings_controller.py
==================================
Callback della tab Impostazioni.

  - Salva: legge tutti i controlli {"type": "setting", "key": ...} e scrive
    ~/TachoVision/impostazioni.json
  - Predefiniti: chiede conferma, poi ripristina i valori di fabbrica
  - Il testo sotto ogni interruttore cambia subito (acceso/spento)

Dopo il salvataggio aggiorna "store-settings": i callback che dipendono
dalle impostazioni (render_page) ridisegnano la tab con i nuovi valori.
"""

from dash import ALL, MATCH, Input, Output, State, no_update
from dash.exceptions import PreventUpdate

from models.settings import (SPEC_BY_KEY, Settings, coerce, default_settings,
                             save_settings)
from views.tabs.impostazioni import worktime_formula


def _collect(values, ids) -> Settings:
    return Settings({i["key"]: coerce(i["key"], v) for i, v in zip(ids, values)})


def register(app):

    @app.callback(
        Output({"type": "setting-state", "key": MATCH}, "children"),
        Input({"type": "setting", "key": MATCH}, "value"),
        State({"type": "setting", "key": MATCH}, "id"),
        prevent_initial_call=True,
    )
    def toggle_text(value, cid):
        spec = SPEC_BY_KEY[cid["key"]]
        return spec.on_text if value else spec.off_text

    @app.callback(
        Output("settings-worktime-formula", "children"),
        Input({"type": "setting", "key": ALL}, "value"),
        State({"type": "setting", "key": ALL}, "id"),
        prevent_initial_call=True,
    )
    def update_formula(values, ids):
        return worktime_formula(_collect(values, ids))

    @app.callback(
        Output("settings-status", "children"),
        Output("store-settings", "data"),
        Input("btn-settings-save", "n_clicks"),
        State({"type": "setting", "key": ALL}, "value"),
        State({"type": "setting", "key": ALL}, "id"),
        prevent_initial_call=True,
    )
    def save(n, values, ids):
        if not n:
            raise PreventUpdate
        s = _collect(values, ids)
        try:
            save_settings(s)
        except OSError as e:
            return f"⚠️ Salvataggio non riuscito: {e}", no_update
        return "✔ Impostazioni salvate", s.to_dict()

    @app.callback(
        Output("confirm-settings-defaults", "displayed"),
        Input("btn-settings-defaults", "n_clicks"),
        prevent_initial_call=True,
    )
    def ask_defaults(n):
        return bool(n)

    @app.callback(
        Output("settings-status", "children", allow_duplicate=True),
        Output("store-settings", "data", allow_duplicate=True),
        Output({"type": "setting", "key": ALL}, "value"),
        Input("confirm-settings-defaults", "submit_n_clicks"),
        State({"type": "setting", "key": ALL}, "id"),
        prevent_initial_call=True,
    )
    def reset_defaults(n, ids):
        if not n:
            raise PreventUpdate
        s = default_settings()
        try:
            save_settings(s)
        except OSError as e:
            return f"⚠️ Salvataggio non riuscito: {e}", no_update, [no_update] * len(ids)
        # I controlli vengono riportati ai valori predefiniti senza ridisegnare la tab
        values = []
        for i in ids:
            v = s.get(i["key"])
            values.append((["on"] if v else []) if SPEC_BY_KEY[i["key"]].kind == "bool" else v)
        return "✔ Impostazioni predefinite ripristinate", s.to_dict(), values

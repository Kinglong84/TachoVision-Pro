"""
controllers/manual_controller.py
================================
Inserimento e cancellazione dei dati manuali (note, ferie, attività manuali).

Dopo ogni modifica aggiorna "store-manual-rev": la tab Attività (e ogni altra
schermata al prossimo ridisegno) rilegge i dati con apply_manual().
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from dash import ALL, Input, Output, State, callback_context, no_update
from dash.exceptions import PreventUpdate

from models.manual_data import (Holiday, ManualActivity, Note, load_manual, save_manual)
from models.settings import load_settings
from views.manual_panel import manual_list


def _tz():
    tz = load_settings().timezone
    return ZoneInfo(tz) if tz else datetime.now().astimezone().tzinfo


def _minute(day: str, hhmm: str, tz) -> int:
    dt = datetime.strptime(f"{day[:10]} {hhmm.strip()}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    return int(dt.timestamp() // 60)


def register(app):

    @app.callback(
        Output("man-status", "children"),
        Output("man-list", "children"),
        Output("store-manual-rev", "data"),
        Output("man-group", "options"),
        Input("man-add", "n_clicks"),
        Input({"type": "man-del", "id": ALL}, "n_clicks"),
        Input("man-group-add", "n_clicks"),
        State("man-kind", "value"),
        State("man-date", "date"), State("man-time", "value"),
        State("man-date-end", "date"), State("man-time-end", "value"),
        State("man-activity", "value"), State("man-group", "value"),
        State("man-value", "value"),
        State("man-group-name", "value"), State("man-group-type", "value"),
        State("store-data", "data"), State("store-manual-rev", "data"),
        prevent_initial_call=True,
    )
    def change(_add, dels, _grp, kind, d0, t0, d1, t1, act, group, value,
               gname, gtype, raw, rev):
        if not raw:
            raise PreventUpdate
        trig = callback_context.triggered[0]
        if not trig["value"]:
            raise PreventUpdate      # componenti appena creati (n_clicks = 0): nessun click reale
        card = raw.get("driver", {}).get("card_number", "")
        data = load_manual(card)
        tz = _tz()
        msg = ""
        try:
            pid = trig["prop_id"]
            if pid.startswith("{"):
                import json
                data.delete(json.loads(pid.split(".")[0])["id"])
                msg = "✔ Cancellato"
            elif pid.startswith("man-group-add"):
                name = (gname or "").strip()
                if not name:
                    return "⚠️ Inserisci il nome del gruppo", no_update, no_update, no_update
                if name not in [g for g, _ in data.groups]:
                    data.groups.append([name, gtype])
                msg = f"✔ Gruppo «{name}» creato"
            elif kind == "note":
                if not group:
                    return "⚠️ Scegli un gruppo di note!", no_update, no_update, no_update
                gtype_of = dict((g, t) for g, t in data.groups).get(group, "short")
                if gtype_of == "number" and value:
                    float(str(value).replace(",", "."))
                data.notes.append(Note(_minute(d0, t0, tz), group, gtype_of, (value or "").strip()))
                msg = "✔ Nota aggiunta"
            elif kind == "holiday":
                first, last = d0[:10], (d1 or d0)[:10]
                if last < first:
                    first, last = last, first
                data.holidays.append(Holiday(first, last))
                msg = "✔ Ferie aggiunte"
            else:
                a, b = _minute(d0, t0, tz), _minute(d1 or d0, t1, tz)
                if b <= a:
                    return "⚠️ La fine deve essere dopo l'inizio", no_update, no_update, no_update
                data.activities.append(ManualActivity(a, b, act))
                msg = "✔ Attività manuale aggiunta"
            save_manual(card, data)
        except ValueError:
            return "⚠️ Data, ora (HH:MM) o numero non validi", no_update, no_update, no_update
        except OSError as e:
            return f"⚠️ Salvataggio non riuscito: {e}", no_update, no_update, no_update
        groups = [{"label": g, "value": g} for g, _ in data.groups]
        return msg, manual_list(data, tz), (rev or 0) + 1, groups

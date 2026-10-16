"""
views/manual_panel.py
=====================
Pannello "Dati inseriti a mano" della tab Attività.

Contiene un
pannello con i tre tipi di dati, l'elenco dei dati già inseriti e la
cancellazione. Callback in controllers/manual_controller.py.
"""

from datetime import datetime, timezone

from dash import dcc, html

from models.manual_data import MANUAL_ACTIVITIES, NOTE_TYPES, ManualData
from views.theme import C, btn_style

_INPUT = {"background": C["surface"], "border": f"1px solid {C['border']}",
          "color": C["text"], "borderRadius": "6px", "padding": "5px 8px"}
_LBL = {"fontSize": "0.74rem", "color": C["muted"], "fontWeight": "700", "marginBottom": "3px"}
_TYPE_LABEL = dict(NOTE_TYPES)


def _field(label, child):
    return html.Div([html.Div(label, style=_LBL), child])


def manual_list(data: ManualData, tz) -> html.Div:
    def fmt(m):
        return datetime.fromtimestamp(m * 60, tz=timezone.utc).astimezone(tz).strftime(
            "%d/%m/%Y %H:%M")

    rows = []
    for a in sorted(data.activities, key=lambda x: -x.start):
        rows.append(("✍", f"{a.activity}: {fmt(a.start)} → {fmt(a.end)}", a.id))
    for h in sorted(data.holidays, key=lambda x: x.first, reverse=True):
        rows.append(("🏖", f"Ferie: {h.first[8:]}/{h.first[5:7]}/{h.first[:4]} → "
                           f"{h.last[8:]}/{h.last[5:7]}/{h.last[:4]}", h.id))
    for n in sorted(data.notes, key=lambda x: -x.minute):
        val = f" — {n.value}" if n.value else ""
        rows.append(("📝", f"{n.group} ({fmt(n.minute)}){val}", n.id))
    if not rows:
        return html.Div("Nessun dato inserito a mano.", style={"color": C["muted"],
                                                               "fontSize": "0.82rem"})
    return html.Div([
        html.Div([
            html.Span(f"{icon} {text}", style={"fontSize": "0.82rem"}),
            html.Button("🗑", id={"type": "man-del", "id": item_id}, n_clicks=0,
                        title="Cancella", style={"background": "none", "border": "none",
                                                 "cursor": "pointer", "color": C["danger"]}),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "borderBottom": f"1px solid {C['border']}", "padding": "4px 0"})
        for icon, text, item_id in rows
    ])


def panel(data: ManualData, tz, default_date: str) -> html.Details:
    groups = [{"label": f"{g} ({_TYPE_LABEL.get(t, t)})", "value": g} for g, t in data.groups]
    return html.Details([
        html.Summary("✍ Dati inseriti a mano (note, ferie, attività manuali)",
                     style={"cursor": "pointer", "fontWeight": "600"}),
        html.Div([
            dcc.RadioItems(id="man-kind", value="note", inline=True,
                           options=[{"label": " Nota", "value": "note"},
                                    {"label": " Ferie", "value": "holiday"},
                                    {"label": " Attività manuale", "value": "activity"}],
                           labelStyle={"marginRight": "18px", "fontSize": "0.84rem",
                                       "color": C["text"]}),
            html.Div([
                _field("Dal / giorno", dcc.DatePickerSingle(
                    id="man-date", date=default_date, display_format="DD/MM/YYYY",
                    first_day_of_week=1)),
                _field("Ora (HH:MM)", dcc.Input(id="man-time", value="08:00",
                                                 style={**_INPUT, "width": "80px"})),
                _field("Al", dcc.DatePickerSingle(
                    id="man-date-end", date=default_date, display_format="DD/MM/YYYY",
                    first_day_of_week=1)),
                _field("Ora fine", dcc.Input(id="man-time-end", value="09:00",
                                             style={**_INPUT, "width": "80px"})),
                _field("Attività", dcc.Dropdown(
                    id="man-activity", value="Lavoro", clearable=False,
                    options=[{"label": "Interruzione/Riposo" if a == "Riposo" else a,
                              "value": a} for a in MANUAL_ACTIVITIES],
                    style={"width": "180px", "color": "#000"})),
                _field("Gruppo di note", dcc.Dropdown(
                    id="man-group", value=data.groups[0][0] if data.groups else None,
                    clearable=False, options=groups, style={"width": "220px", "color": "#000"})),
                _field("Valore / testo", dcc.Input(id="man-value", value="",
                                                    style={**_INPUT, "width": "220px"})),
            ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap",
                      "alignItems": "flex-end", "margin": "10px 0"}),
            html.Div([
                html.Button("➕ Aggiungi", id="man-add", n_clicks=0, style=btn_style(C["accent"])),
                html.Span(id="man-status", style={"fontSize": "0.82rem", "marginLeft": "10px"}),
            ]),
            html.Details([
                html.Summary("+ Nuovo gruppo di note", style={"cursor": "pointer",
                                                              "fontSize": "0.82rem",
                                                              "marginTop": "10px"}),
                html.Div([
                    _field("Nome della nota", dcc.Input(id="man-group-name", value="",
                                                        style={**_INPUT, "width": "200px"})),
                    _field("Tipo di nota", dcc.Dropdown(
                        id="man-group-type", value="short", clearable=False,
                        options=[{"label": l, "value": v} for v, l in NOTE_TYPES],
                        style={"width": "160px", "color": "#000"})),
                    html.Button("Crea gruppo", id="man-group-add", n_clicks=0,
                                style=btn_style(C["muted"])),
                ], style={"display": "flex", "gap": "12px", "alignItems": "flex-end",
                          "marginTop": "6px"}),
            ]),
            html.Div(manual_list(data, tz), id="man-list", style={"marginTop": "14px"}),
        ], style={"padding": "10px 4px"}),
    ], style={"background": C["surface"], "border": f"1px solid {C['border']}",
              "borderRadius": "8px", "padding": "10px 14px", "marginBottom": "12px"})

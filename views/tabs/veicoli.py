"""
views/tabs/veicoli.py
======================
Tab "Veicoli": utilizzo del veicolo.

Contenuto:
  - ogni sessione: "DD/MM/YY HH:MM - DD/MM/YY HH:MM (HH:MM)", targa,
    odometro inizio e fine, km, ore di guida; pulsante mappa se ci sono
    posizioni GPS
  - riepiloghi settimanali o mensili (ore di guida, km)
  - ordinamento Periodo/Giorno
In più: tabella dei veicoli distinti (targa, periodo, km).

Dati: models/vehicle_report.py · callback: controllers/vehicle_controller.py
"""

from collections import defaultdict

from dash import dcc, html

from models.card_data import CardData
from models.settings import load_settings
from models.vehicle_report import vehicle_periods
from views.components import empty_state, section
from views.tabs.riepilogo import ORDERS
from views.export_bar import bar_for
from views.theme import C

_MONO = {"fontFamily": "'Overpass'", "fontSize": "0.82rem"}


def _hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _dist(km, unit):
    return f"{km * 0.621371:.0f}mi" if unit == "MILES" else f"{km}km"


def build_list(cd: CardData, summary: str, order: str) -> html.Div:
    s = load_settings()
    periods = vehicle_periods(cd, s, summary, order)
    if not periods:
        return empty_state("L'elenco di utilizzo del veicolo è vuoto")
    out = []
    for p in periods:
        rows = []
        for r in p.rows:
            rows.append(html.Div([
                html.Div(r.period, style={**_MONO, "fontWeight": "600"}),
                html.Div([
                    html.Span(r.vrn, style={"fontWeight": "700", "width": "110px"}),
                    html.Span(f"🚛 {_hm(r.drive)}", style={**_MONO, "width": "90px"}),
                    html.Span(f"{r.odo_begin}", style={**_MONO, "width": "90px",
                                                       "color": C["muted"]}),
                    html.Span(f"{r.odo_end}", style={**_MONO, "width": "90px",
                                                     "color": C["muted"]}),
                    html.Span(_dist(r.km, s.distanceunit), style={**_MONO, "width": "80px",
                                                                  "fontWeight": "600"}),
                    html.Button("🗺", id={"type": "btn-gps-day", "index": r.gnss_date},
                                n_clicks=0, title="Mappa", className="gps-day-btn")
                    if r.gnss_date else None,
                ], style={"display": "flex", "gap": "10px", "alignItems": "center",
                          "flexWrap": "wrap", "marginTop": "3px"}),
            ], style={"background": "#FF6B6B14", "borderRadius": "6px",
                      "padding": "7px 10px", "marginBottom": "6px"}))
        out.append(html.Div([
            *rows,
            html.Div([
                html.Span(p.label, style={"color": C["danger"], "fontWeight": "600"}),
                html.Span([html.Span(f"🚛 {_hm(p.drive)}", style={**_MONO, "marginRight": "16px"}),
                           html.Span(_dist(p.km, s.distanceunit),
                                     style={**_MONO, "fontWeight": "700"})]),
            ], style={"display": "flex", "justifyContent": "space-between", "flexWrap": "wrap",
                      "borderTop": f"2px solid {C['danger']}55", "padding": "6px 4px 2px"}),
        ], style={"background": C["card"], "border": f"1px solid {C['border']}",
                  "borderRadius": "8px", "padding": "10px", "marginBottom": "12px"}))
    return html.Div(out)


def _vehicles_table(cd: CardData) -> html.Table:
    agg = defaultdict(lambda: {"first": None, "last": None, "km": 0, "n": 0})
    for v in cd.vehicle_sessions:
        a = agg[v.vrn]
        a["n"] += 1
        a["km"] += max(0, (v.odo_end_km or 0) - (v.odo_begin_km or 0))
        a["first"] = min(filter(None, [a["first"], v.first_use_utc])) if v.first_use_utc else a["first"]
        a["last"] = max(filter(None, [a["last"], v.last_use_utc])) if v.last_use_utc else a["last"]
    from datetime import datetime
    def d(ts):
        return datetime.fromtimestamp(ts).strftime("%d/%m/%Y") if ts else "—"
    rows = [html.Tr([html.Td(vrn, style={"fontWeight": "600"}), html.Td(d(a["first"])),
                     html.Td(d(a["last"])), html.Td(str(a["n"])), html.Td(f"{a['km']} km")])
            for vrn, a in sorted(agg.items(), key=lambda x: -(x[1]["last"] or 0))]
    return html.Table([html.Thead(html.Tr([html.Th(h) for h in
                                           ["Targa", "Primo uso", "Ultimo uso", "Sessioni", "Km"]])),
                       html.Tbody(rows)], className="veh-table")


def render(cd: CardData) -> html.Div:
    lbl = {"fontSize": "0.82rem", "color": C["text"]}
    label = {"fontSize": "0.74rem", "color": C["muted"], "fontWeight": "700", "marginBottom": "4px"}
    controls = section(
        "Utilizzo del veicolo",
        html.Div([
            html.Div([html.Div("Riepiloghi", style=label),
                      dcc.RadioItems(id="veh-summary", value="month", persistence=True,
                                     persistence_type="local",
                                     options=[{"label": " Riepiloghi settimanali", "value": "week"},
                                              {"label": " Riepiloghi mensili", "value": "month"}],
                                     labelStyle={**lbl, "display": "block"})]),
            html.Div([html.Div("Ordinamento", style=label),
                      dcc.RadioItems(id="veh-order", value="dec_inc", persistence=True,
                                     persistence_type="local",
                                     options=[{"label": f" {l}", "value": v} for v, l in ORDERS],
                                     labelStyle={**lbl, "display": "block"})]),
        ], style={"display": "flex", "gap": "40px", "flexWrap": "wrap"}),
    )
    extra = html.Details([
        html.Summary(f"🚛 Veicoli distinti ({len({v.vrn for v in cd.vehicle_sessions})})",
                     style={"cursor": "pointer", "color": C["muted"]}),
        _vehicles_table(cd),
    ], style={"marginBottom": "12px"}) if cd.vehicle_sessions else None
    return html.Div([controls, bar_for(cd, "vehicle", 62), bar_for(cd, "gps", 62), extra,
                     html.Div(build_list(cd, "month", "dec_inc"), id="veh-list")])

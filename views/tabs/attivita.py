"""
views/tabs/attivita.py
=======================
Tab "Attività": attività giorno per giorno, in ora locale.

Schermata:
  - intestazione del giorno "6 luglio 2024 (sabato)" e grafico 24h con i paesi
  - elenco: "HH:MM:SS  icona  info  ΔT=HH:MM", carta inserita/estratta con
    targa e km, paese, eventi/guasti, condizioni specifiche
  - menu: periodo 7 / 28 / 56 giorni / intero periodo, oppure un singolo giorno
    con frecce ◁ ▷; cosa mostrare (Attività, Carta, Paese, Eventi);
    vista grafico / elenco
  - colori della palette scelta nelle impostazioni
In più: totali guida/lavoro/km del giorno e link alla mappa GPS.

Righe: models/day_events.py · callback: controllers/activities_controller.py
"""

from datetime import date, timedelta

from dash import dcc, html

from models.card_data import CardData
from models.day_events import build_days
from models.settings import load_settings
from views.charts import day_gantt
from views.manual_panel import panel as manual_panel
from views.components import empty_state, section
from views.tabs.infrazioni import _valid_until
from views.export_bar import bar_for
from views.theme import C

_ICONS = {"Guida": "🚛", "Lavoro": "⛏", "Disponibilità": "⊙", "Riposo": "🛏"}
_INFO = {"manuale": "✍", "equipaggio": "👥", "sconosciuta": "?"}
_KIND_ICON = {"card": "🪪", "place": "📍", "event": "", "condition": "⛴", "note": "📝",
              "holiday": "🏖"}

SHOW_OPTIONS = [("activity", "Attività"), ("card", "Carta"), ("place", "Paese"),
                ("event", "Evento"), ("note", "Nota"), ("holiday", "Ferie")]
PERIODS = [("7", "Ultimi 7 giorni"), ("28", "Ultimi 28 giorni"),
           ("56", "Ultimi 56 giorni"), ("all", "Intero periodo"), ("day", "Giorno")]

_MONO = {"fontFamily": "'Overpass'", "fontSize": "0.8rem"}


def _hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _day_card(day, colors, show_graph, show_list, gnss_dates):
    head = html.Div([
        html.Span(day.title, style={"fontWeight": "600"}),
        html.Span([
            html.Span(f"🚛 {_hm(day.drive)}", style={**_MONO, "marginRight": "12px"}),
            html.Span(f"⛏ {_hm(day.work)}", style={**_MONO, "marginRight": "12px"}),
            html.Span(f"{day.km:.0f} km", style=_MONO),
            html.Button("📍 GPS", id={"type": "btn-gps-day", "index": day.date.isoformat()},
                        n_clicks=0, className="gps-day-btn",
                        style={"marginLeft": "12px", "fontSize": "0.72rem"})
            if day.date.isoformat() in gnss_dates else None,
        ]),
    ], style={"display": "flex", "justifyContent": "space-between", "flexWrap": "wrap",
              "gap": "8px", "background": "#FF6B6B22" if day.date.weekday() < 6 else "#4A6FA522",
              "padding": "6px 10px", "borderRadius": "6px"})
    graph = html.Div([
        html.Div(" · ".join(day.countries), style={"fontSize": "0.72rem",
                                                   "color": C["muted"], "marginTop": "4px"})
        if day.countries else None,
        dcc.Graph(figure=day_gantt(day.segments, colors), config={"displayModeBar": False},
                  style={"height": "70px"}),
    ]) if show_graph and day.segments else None
    lines = []
    if show_list:
        for ln in day.lines:
            if ln.kind == "activity":
                lines.append(html.Div([
                    html.Span(ln.time, style={**_MONO, "color": C["muted"], "width": "72px"}),
                    html.Span(_ICONS.get(ln.activity, ""), title=ln.activity,
                              style={"width": "22px", "color": colors.get(ln.activity)}),
                    html.Span(ln.activity, style={"width": "110px", "fontSize": "0.8rem",
                                                  "color": colors.get(ln.activity)}),
                    html.Span(_INFO.get(ln.info, ""), title=ln.info,
                              style={"width": "20px", "color": C["warning"]}),
                    html.Span(ln.length, style={**_MONO, "color": C["muted"]}),
                ], style={"display": "flex", "gap": "6px", "alignItems": "center"}))
            else:
                lines.append(html.Div([
                    html.Span(ln.time, style={**_MONO, "color": C["muted"], "width": "72px"}),
                    html.Span(f"{_KIND_ICON.get(ln.kind, '')} {ln.text}",
                              style={"fontSize": "0.8rem",
                                     "color": C["danger"] if ln.kind == "event" else C["text"]}),
                ], style={"display": "flex", "gap": "6px"}))
    return html.Div([head, graph,
                     html.Div(lines, style={"padding": "6px 4px 0 10px",
                                            "borderLeft": f"2px solid {C['border']}",
                                            "marginTop": "6px"}) if lines else None],
                    className="day-block",
                    style={"background": C["card"], "border": f"1px solid {C['border']}",
                           "borderRadius": "8px", "padding": "10px", "marginBottom": "10px"})


def build_blocks(cd: CardData, period: str, kinds, view, day_iso: str = None):
    s = load_settings()
    end = _valid_until(cd).date()
    if period == "day" and day_iso:
        first = last = date.fromisoformat(day_iso)
    elif period in ("7", "28", "56"):
        first, last = end - timedelta(days=int(period) - 1), end
    else:
        first = last = None
    days = build_days(cd, s, kinds or [], first, last)
    days = [d for d in days if d.segments or d.lines]
    if not days:
        return empty_state("L'elenco delle attività è vuoto")
    view = view or []
    gnss_dates = {g.date for g in cd.gnss_records} if cd.gnss_records else set()
    colors = s.colors
    return html.Div([_day_card(d, colors, "graph" in view, "list" in view, gnss_dates)
                     for d in reversed(days)])


def render(cd: CardData) -> html.Div:
    if not cd.activities:
        return empty_state("Nessuna attività nel file")
    last = _valid_until(cd).date()
    first_day = min(d.date for d in cd.activities)
    lbl = {"fontSize": "0.82rem", "color": C["text"]}
    label = {"fontSize": "0.74rem", "color": C["muted"], "fontWeight": "700", "marginBottom": "4px"}
    s = load_settings()
    legend = html.Div([
        html.Span([html.Span("■ ", style={"color": col}), name],
                  style={"marginRight": "14px", "fontSize": "0.78rem"})
        for name, col in s.colors.items()
    ], style={"marginTop": "8px"})
    controls = section(
        "Attività",
        html.Div([
            html.Div([html.Div("Periodo", style=label),
                      dcc.RadioItems(id="act-period", value="7", persistence=True,
                                     persistence_type="local",
                                     options=[{"label": f" {l}", "value": v} for v, l in PERIODS],
                                     labelStyle={**lbl, "display": "block"})]),
            html.Div([html.Div("Giorno", style=label),
                      html.Div([
                          html.Button("◁", id="act-prev", n_clicks=0),
                          dcc.DatePickerSingle(id="act-day", date=last.isoformat(),
                                               min_date_allowed=first_day,
                                               max_date_allowed=last.isoformat(),
                                               display_format="DD/MM/YYYY",
                                               first_day_of_week=1),
                          html.Button("▷", id="act-next", n_clicks=0),
                      ], style={"display": "flex", "gap": "6px", "alignItems": "center"})]),
            html.Div([html.Div("Mostra", style=label),
                      dcc.Checklist(id="act-kinds", persistence=True, persistence_type="local",
                                    value=[v for v, _ in SHOW_OPTIONS],
                                    options=[{"label": f" {l}", "value": v}
                                             for v, l in SHOW_OPTIONS],
                                    labelStyle={**lbl, "display": "block"})]),
            html.Div([html.Div("Vista", style=label),
                      dcc.Checklist(id="act-view", value=["graph", "list"], persistence=True,
                                    persistence_type="local",
                                    options=[{"label": " Grafico", "value": "graph"},
                                             {"label": " Elenco", "value": "list"}],
                                    labelStyle={**lbl, "display": "block"})]),
        ], style={"display": "flex", "gap": "36px", "flexWrap": "wrap"}),
        legend,
    )
    from zoneinfo import ZoneInfo
    from models.manual_data import load_manual
    tz = ZoneInfo(s.timezone) if s.timezone else None
    manual = manual_panel(load_manual(cd.driver.card_number), tz, last.isoformat())
    return html.Div([controls, bar_for(cd, "activities", 7), manual,
                     html.Div(build_blocks(cd, "7", [v for v, _ in SHOW_OPTIONS],
                                           ["graph", "list"]), id="blocks-attivita")])

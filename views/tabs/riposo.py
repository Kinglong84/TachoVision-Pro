"""
views/tabs/riposo.py
=====================
Tab "Riposo": periodi di riposo del conducente.

Schermata (dalla più recente):
  - riposo: periodo, tipo (regolare/ridotto/frazionato/multipresenza/settimanale),
    settimana di riferimento, compensazione dei settimanali ridotti, paese
  - turno successivo: guida (guida continua massima), lavoro, disponibilità
  - a ogni settimana: tempo di guida settimanale e quindicinale
  - menu periodo 7 / 28 / 56 giorni / intero periodo
In più: istogramma delle durate (in fondo, richiudibile).

Dati: models/rest_report.build_report(). Filtro periodo: controllers/rest_controller.py.
"""

from datetime import datetime, timedelta, timezone

from dash import dcc, html

from models.card_data import CardData
from models.rest_report import RestEntry, ShiftEntry, WeekEntry, build_report, _dur
from models.settings import COUNTRY_OPTIONS, load_settings

_COUNTRY_NAMES = dict(COUNTRY_OPTIONS)
from views.charts import hist_rest
from views.components import empty_state, section
from views.tabs.infrazioni import PERIOD_OPTIONS, _valid_until
from views.export_bar import bar_for
from views.theme import C

KIND_COLORS = {
    "WeeklyNormal": C["accent"], "WeeklyReduced": "#38BDF8",
    "DailyNormal": C["success"], "DailySplit": C["success"], "DailyStaff": C["success"],
    "DailyReduced": C["disp"], "Insufficient": C["danger"],
}
_COMP_COLORS = {"done": C["success"], "required": C["warning"], "missing": C["danger"]}
_MONO = {"fontFamily": "'Overpass'", "fontSize": "0.84rem"}
_LABEL = {"fontSize": "0.74rem", "color": C["muted"]}


def _rest_card(e: RestEntry) -> html.Div:
    color = KIND_COLORS.get(e.kind, C["muted"])
    flags = []
    if e.reduced:
        flags.append("ridotto")
    if e.truncated:
        flags.append("inizio/fine dati")
    return html.Div([
        html.Div(e.period, style={**_MONO, "fontWeight": "600"}),
        html.Div([html.Span(e.text, style={"color": color}),
                  html.Span(f"  {e.weeks}", style=_LABEL) if e.weeks else None],
                 style={"fontSize": "0.86rem", "marginTop": "3px"}),
        html.Div(e.compensation, style={"fontSize": "0.8rem", "marginTop": "3px",
                                        "color": _COMP_COLORS.get(e.compensation_state)})
        if e.compensation else None,
        html.Div([html.Span("Paese: ", style=_LABEL), html.Span(_COUNTRY_NAMES.get(e.country, e.country))],
                 style={"fontSize": "0.8rem", "marginTop": "3px"}) if e.country else None,
        html.Div(" · ".join(flags), style={**_LABEL, "marginTop": "3px"}) if flags else None,
    ], style={"background": color + "14", "borderLeft": f"4px solid {color}",
              "borderRadius": "6px", "padding": "9px 12px", "margin": "8px 0"})


def _shift_row(e: ShiftEntry, fmt: str) -> html.Div:
    def part(icon, label, val, extra=""):
        return html.Span([html.Span(icon, title=label), f" {_dur(val, fmt)}{extra}"],
                         style={**_MONO, "marginRight": "18px"})
    tags = []
    if e.crew:
        tags.append("multipresenza")
    if e.split:
        tags.append("riposo frazionato")
    return html.Div([
        html.Div(e.period, style=_LABEL),
        html.Div([
            part("🚛", "Guida", e.drive, f" ({_dur(e.drive_cont, fmt)} continuo)"),
            part("⛏", "Lavoro", e.work),
            part("⊙", "Disponibilità", e.avail),
            html.Span(" · ".join(tags), style=_LABEL) if tags else None,
        ], style={"marginTop": "2px"}),
    ], style={"padding": "4px 12px 4px 16px"})


def _week_box(e: WeekEntry, fmt: str) -> html.Div:
    return html.Div([
        html.Div(f"Tempo di guida (settimana: {e.week})",
                 style={"fontSize": "0.8rem", "fontWeight": "600"}),
        html.Div([
            html.Span("Quindicinale: ", style=_LABEL),
            html.Span(_dur(e.two_week, fmt), style={**_MONO, "marginRight": "24px",
                                                    "color": C["danger"] if e.two_week > 90 * 60 else C["text"]}),
            html.Span("Settimanale: ", style=_LABEL),
            html.Span(_dur(e.one_week, fmt), style={**_MONO,
                                                    "color": C["danger"] if e.one_week > 56 * 60 else C["text"]}),
        ]),
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderRadius": "6px", "padding": "8px 12px", "margin": "12px 0"})


def build_list(cd: CardData, period: str) -> html.Div:
    s = load_settings()
    rep = build_report(cd.activities, cd, s)
    items = rep.items
    if period and period != "all":
        since = _valid_until(cd) - timedelta(days=int(period))
        limit = int(since.replace(tzinfo=timezone.utc).timestamp() // 60) - 24 * 60
        items = [i for i in items if i.start >= limit]
    if not items:
        return empty_state("La lista è vuota")
    fmt = s.intervalformat
    out = []
    for it in reversed(items):                        # dalla più recente
        if isinstance(it, RestEntry):
            out.append(_rest_card(it))
        elif isinstance(it, ShiftEntry):
            out.append(_shift_row(it, fmt))
        else:
            out.append(_week_box(it, fmt))
    return html.Div(out)


def render(cd: CardData) -> html.Div:
    return html.Div([
        bar_for(cd, "rest", 28),
        section(
            "Periodi di riposo",
            html.Div([
                html.Span("Periodo:", style={**_LABEL, "marginRight": "10px"}),
                dcc.RadioItems(
                    id="rest-period", value="28", persistence=True, persistence_type="local",
                    options=[{"label": f" {lbl}", "value": val} for val, lbl in PERIOD_OPTIONS],
                    inline=True, labelStyle={"marginRight": "16px", "fontSize": "0.82rem",
                                             "color": C["text"]},
                ),
            ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
                      "marginBottom": "8px"}),
            html.Div(build_list(cd, "28"), id="rest-list"),
        ),
        html.Details([
            html.Summary("📊 Distribuzione delle durate dei riposi",
                         style={"cursor": "pointer", "color": C["muted"]}),
            dcc.Graph(figure=hist_rest(cd.rest_periods), config={"displayModeBar": False}),
        ], style={"marginTop": "12px"}) if cd.rest_periods else None,
    ])

"""
views/tabs/pianificazione.py
============================
Tab "Pianificazione": tempi di guida/lavoro residui e prossimi riposi.

Due schede:
  LAVORO — Tempo di guida (giornaliero, giorni estesi ★★, settimanale,
           quindicinale), Orario di lavoro (settimanale, media del periodo,
           giornaliero), Prossimo riposo giornaliero (entro e non oltre,
           durate, ridotti ★★★), Prossimo riposo settimanale
  RIPOSO — Riposo attuale (iniziato alle…), Possibili orari finali,
           Compensazioni
"Progetti futuri" (macchina del tempo): simula di lavorare o riposare
ancora per un certo tempo. Calcoli in models/planning.py; il callback è in
controllers/planning_controller.py.
"""

from dash import dcc, html

from models.card_data import CardData
from models.planning import build_plan
from models.settings import load_settings
from views.components import empty_state, section
from views.theme import C

_MONO = {"fontFamily": "'Overpass'", "fontSize": "0.9rem"}
_LABEL = {"fontSize": "0.84rem"}
_TAB = {"background": C["surface"], "color": C["muted"], "border": f"1px solid {C['border']}",
        "padding": "10px", "fontWeight": "600", "letterSpacing": "1px"}
_TAB_SEL = {**_TAB, "color": C["accent"], "borderTop": f"3px solid {C['accent']}",
            "background": C["card"]}
_INPUT = {"background": C["surface"], "border": f"1px solid {C['border']}",
          "color": C["text"], "borderRadius": "6px", "padding": "4px 8px", "width": "70px"}


def _hm(m: int) -> str:
    m = max(0, int(m))
    return f"{m // 60:02d}:{m % 60:02d}"


def _row(label, value, extra=None, color=None):
    return html.Div([
        html.Span(label, style=_LABEL),
        html.Span([extra, html.Span(value, style={**_MONO, "color": color or C["text"]})],
                  style={"display": "flex", "gap": "10px", "alignItems": "center"}),
    ], style={"display": "flex", "justifyContent": "space-between", "gap": "12px",
              "padding": "7px 0", "borderBottom": f"1px solid {C['border']}"})


def _gauge(g):
    pct = min(100, g.value * 100 / g.limit) if g.limit else 0
    color = C["danger"] if g.over or pct >= 100 else C["warning"] if pct >= 85 else C["success"]
    bar = html.Div(html.Div(style={"width": f"{pct:.0f}%", "height": "100%",
                                   "background": color, "borderRadius": "3px"}),
                   style={"width": "120px", "height": "6px", "background": C["border"],
                          "borderRadius": "3px"}, title=f"Restano {_hm(g.left)}")
    return _row(g.label, _hm(g.value), bar, color if g.over else None)


def _stars(used: int, total: int):
    return html.Span("★" * used + "☆" * (total - used),
                     style={"color": C["warning"], "letterSpacing": "2px"})


def build_content(cd: CardData, mode: str = None, minutes: int = 0) -> html.Div:
    s = load_settings()
    # calcolata sullo storico unito del conducente
    from models.history import history_for
    h = cd if cd.demo else history_for(cd)
    p = build_plan(h.activities, s, mode, minutes, cd.driver.last_download)
    if p is None:
        return empty_state("Nessuna attività nel file")

    msgs = html.Div([
        html.Div(m, style={"color": C["danger"] if "finire" in m else
                           C["warning"] if "Continua" in m else C["success"],
                           "fontWeight": "600"}) for m in p.messages
    ], style={"marginBottom": "10px"})

    lavoro = html.Div([
        section("Tempo Di Guida",
                _gauge(p.driving[0]),
                _row("Giorno esteso (max 2)", "", _stars(p.extended_used, 2)),
                *[_gauge(g) for g in p.driving[1:]]),
        section("Orario di lavoro", *[_gauge(g) for g in p.working]),
        section("Prossimo periodo di riposo giornaliero",
                _row("Entro e non oltre", p.daily_rest_before),
                *[_row(t, f"{h}h") for t, h in p.daily_rest_options],
                _row("Ridotto (max 3)", "", _stars(p.reduced_used, 3))),
        section("Prossimo periodo di riposo settimanale",
                _row("Entro e non oltre", p.weekly_rest_before or "—"),
                _row("Durata (ridotto possibile)" if p.weekly_rest_hours == 24
                     else "Durata (regolare)", f"{p.weekly_rest_hours}h")),
        section("Prossimo periodo di riposo settimanale regolare",
                _row("Entro e non oltre", p.weekly_regular_before or "—"),
                _row("Durata", "45h")) if p.weekly_rest_hours == 24 else None,
    ])

    if p.in_rest:
        riposo = html.Div([
            section("Periodo di riposo attuale",
                    _row("Ha Iniziato", p.current_rest_start),
                    _row("Durata finora", _hm(p.current_rest_len))),
            section("Possibili Orari Finali",
                    *[_row(o.label, o.end) for o in p.end_options]),
            section("Compensazione",
                    *([html.Div(c, style={**_LABEL, "padding": "4px 0"}) for c in p.compensations]
                      or [html.Div("Nessuna compensazione dovuta",
                                   style={**_LABEL, "color": C["muted"]})])),
        ])
    else:
        riposo = html.Div([
            section("Periodo di riposo attuale",
                    html.Div("Il conducente non è in riposo all'istante di riferimento.",
                             style={**_LABEL, "color": C["muted"]})),
            section("Compensazione",
                    *([html.Div(c, style={**_LABEL, "padding": "4px 0"}) for c in p.compensations]
                      or [html.Div("Nessuna compensazione dovuta",
                                   style={**_LABEL, "color": C["muted"]})])),
        ])

    return html.Div([
        html.Div(f"Situazione al: {p.reference}", style={"color": C["muted"],
                                                          "fontSize": "0.84rem",
                                                          "marginBottom": "6px"}),
        msgs,
        dcc.Tabs([
            dcc.Tab(label="LAVORO", value="lavoro", children=lavoro, style=_TAB, selected_style=_TAB_SEL),
            dcc.Tab(label="RIPOSO", value="riposo", children=riposo, style=_TAB, selected_style=_TAB_SEL),
        ], value="riposo" if p.in_rest and not mode else "lavoro", colors={"border": C["border"], "primary": C["accent"],
                               "background": C["surface"]}),
    ])


def render(cd: CardData) -> html.Div:
    time_machine = section(
        "Progetti futuri",
        html.Div([
            dcc.RadioItems(
                id="plan-mode", value="none",
                options=[{"label": " Situazione allo scarico", "value": "none"},
                         {"label": " Voglio ancora lavorare", "value": "work"},
                         {"label": " Voglio riposarmi", "value": "rest"}],
                inline=True, labelStyle={"marginRight": "18px", "fontSize": "0.84rem",
                                         "color": C["text"]}),
            html.Div([
                html.Span("Per quanto tempo:", style=_LABEL),
                dcc.Input(id="plan-days", type="number", min=0, max=30, value=0, style=_INPUT),
                html.Span("giorno", style=_LABEL),
                dcc.Input(id="plan-hours", type="number", min=0, max=23, value=0, style=_INPUT),
                html.Span("ora", style=_LABEL),
                dcc.Input(id="plan-minutes", type="number", min=0, max=59, value=0,
                          style=_INPUT),
                html.Span("min", style=_LABEL),
            ], style={"display": "flex", "gap": "8px", "alignItems": "center",
                      "marginTop": "8px", "flexWrap": "wrap"}),
        ]),
    )
    return html.Div([time_machine, html.Div(build_content(cd), id="plan-content")])

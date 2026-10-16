"""
views/tabs/panoramica.py
========================
Tab "Dashboard": la prima schermata dopo aver caricato un file.

In apertura il disco del cronotachigrafo della giornata (l'elemento che ogni
autista riconosce: 24 ore in cerchio, un anello per attività), accanto il
verdetto di conformità in parole semplici e quanto si può ancora guidare.
Sotto: infrazioni principali, guida degli ultimi 14 giorni, veicoli recenti.

Navigazione tra le giornate: controllers/dashboard_controller.py.
"""

from datetime import date, timedelta

import dash_bootstrap_components as dbc
from dash import dcc, html

from models.analytics import compute_stats
from models.card_data import CardData
from models.violations import MI, MSI, SI, VSI, violation_summary
from views.charts import bar_daily_driving, tacho_disc
from views.components import section
from views.theme import C

_WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def _hm(m: int) -> str:
    return f"{m // 60}:{m % 60:02d}"


def worked_days(cd: CardData) -> list:
    """Giorni (data del DDD) con guida o lavoro, in ordine."""
    return sorted(d.date for d in cd.activities
                  if d.minutes_of("Guida") + d.minutes_of("Lavoro") > 0)


def _verdict(viols: list, cd: CardData):
    """Verdetto sulle ultime 8 settimane (il periodo predefinito)."""
    from views.tabs.infrazioni import _valid_until
    since = (_valid_until(cd) - timedelta(days=56)).date().isoformat()
    recent = [v for v in viols if v.date >= since]
    if not recent:
        return "In regola", "ok", "Nessuna infrazione nelle ultime 8 settimane."
    n = len(recent)
    head = f"{n} infrazion{'e' if n == 1 else 'i'} da verificare"
    if max(v.stars for v in recent) >= 3:
        return head, "bad", "Almeno una è molto grave: controlla la scheda Infrazioni."
    return head, "warn", "Nelle ultime 8 settimane nessuna è molto grave."


def _top_violations(viols: list) -> html.Div:
    """Le 3 infrazioni più gravi del file (o le prime 3, se tutte minori)."""
    serious = sorted((v for v in viols if v.severity in (MSI, VSI, SI)), key=lambda v: -v.stars)
    shown = (serious or viols)[:3]
    if not shown:
        return html.Div("Nessuna infrazione nel file.",
                        style={"color": C["success"], "padding": "6px 0"})
    return html.Div([
        html.Div([
            html.Span(v.severity, title=v.severity_label, style={
                "background": v.color, "color": "#fff", "borderRadius": "3px",
                "padding": "2px 8px", "fontSize": "0.78rem", "fontWeight": "800",
                "minWidth": "42px", "textAlign": "center"}),
            html.Div([
                html.Div(v.description, style={"fontWeight": "600", "fontSize": "0.92rem",
                                               "lineHeight": "1.3"}),
                html.Div(f"{v.period} — {v.detail}",
                         style={"fontSize": "0.84rem", "color": C["muted"]}),
            ], style={"flex": "1", "minWidth": 0}),
        ], style={"display": "flex", "gap": "12px", "alignItems": "flex-start",
                  "padding": "9px 0", "borderBottom": f"1px solid {C['border']}"})
        for v in shown
    ])


def build_hero(cd: CardData, day_iso: str = None) -> html.Div:
    """Disco della giornata + verdetto. day_iso: data del DDD (None = l'ultima)."""
    from models.day_events import build_days
    from models.planning import build_plan
    from models.settings import load_settings

    s = load_settings()
    worked = worked_days(cd)
    if not worked:
        return html.Div("Nel file non ci sono giornate con guida o lavoro.",
                        className="section-card")
    day_iso = day_iso if day_iso in worked else worked[-1]
    d0 = date.fromisoformat(day_iso)
    days = build_days(cd, s, {"card", "place"}, d0, d0)
    day = days[0] if days else None
    drive = day.drive if day else 0
    work = day.work if day else 0

    marks = []                     # carta inserita (verde) / estratta (rossa) sul bordo
    vrns = []
    for ln in (day.lines if day else []):
        if ln.kind != "card":
            continue
        minute = int(ln.time[:2]) * 60 + int(ln.time[3:5])
        inserted = ln.text.startswith("Card In")
        marks.append((minute, C["accent"] if inserted else C["danger"],
                      f"{ln.time[:5]} carta {'inserita' if inserted else 'estratta'}"))
        vrn = ln.text.split("(")[1].split(",")[0]
        if vrn not in vrns:
            vrns.append(vrn)

    from models.history import violations_with_history
    headline, tone, lead = _verdict(violations_with_history(cd), cd)
    from models.history import history_for
    plan = build_plan((cd if cd.demo else history_for(cd)).activities, s,
                      last_download=cd.driver.last_download)
    if plan:
        lead += (f" Allo scarico del {plan.reference} può ancora guidare "
                 f"{_hm(plan.driving[0].left)} in giornata e "
                 f"{_hm(plan.driving[1].left)} in settimana.")

    i = worked.index(day_iso)
    title = f"{_WEEKDAYS[d0.weekday()].capitalize()} {d0.day} {_MONTHS[d0.month - 1]} {d0.year}"

    def fact(value, label, small=False):
        return html.Div([
            html.Div(value, className="disc-fact-value",
                     style={"fontSize": "1.2rem"} if small else None),
            html.Div(label, className="disc-fact-label"),
        ])

    return html.Div([
        html.Div(dcc.Graph(
            figure=tacho_disc(day.segments if day else [], s.colors, marks,
                              hub_top=_hm(drive), hub_bottom="ore di guida"),
            config={"displayModeBar": False, "responsive": True},
            style={"width": "100%", "height": "100%"}), className="disc-figure"),
        html.Div([
            html.Div(title, className="disc-day"),
            html.H2(headline, className=f"disc-verdict disc-verdict--{tone}"),
            html.P(lead, className="disc-lead"),
            html.Div([
                fact(_hm(drive), "di guida"),
                fact(_hm(work), "di altro lavoro"),
                fact(f"{(day.km if day else 0):.0f} km", "percorsi"),
                fact(", ".join(vrns) or "—", "veicolo" if len(vrns) < 2 else "veicoli",
                     small=True),
            ], className="disc-facts"),
            html.Div([html.Span([html.I(style={"background": col}), act])
                      for act, col in s.colors.items()], className="disc-legend"),
            html.Div([
                html.Button("◁ Giorno precedente", id="disc-prev", n_clicks=0,
                            disabled=i == 0),
                html.Button("Giorno successivo ▷", id="disc-next", n_clicks=0,
                            disabled=i == len(worked) - 1),
                html.Span(f"Giornata {i + 1} di {len(worked)} con attività",
                          style={"color": C["muted"], "fontSize": "0.86rem"}),
            ], className="disc-nav"),
        ]),
    ], className="disc-hero")


def render(cd: CardData) -> html.Div:
    stats = compute_stats(cd)
    from models.history import violations_with_history
    viols = violations_with_history(cd)
    vs = violation_summary(viols)

    def sort_key(v):
        return v.last_use[6:] + v.last_use[3:5] + v.last_use[:2]

    vehicles = html.Div([
        html.Div([
            html.Span(v.vrn, className="vrn-badge"),
            html.Span(f"{v.first_use} – {v.last_use}",
                      style={"fontSize": "0.86rem", "color": C["muted"], "marginLeft": "12px"}),
        ], style={"padding": "7px 0", "borderBottom": f"1px solid {C['border']}"})
        for v in sorted(cd.vehicles, key=sort_key, reverse=True)[:6]
    ] or [html.Div("Nessun veicolo nel file", style={"color": C["muted"]})])

    km = f"{int(stats.get('total_km', 0)):,}".replace(",", ".")
    totals = html.P(
        f"Il file copre {stats.get('days', 0)} giorni, di cui {stats.get('driving_days', 0)} "
        f"con guida: {stats.get('driving_h', 0)} ore al volante e {km} km in tutto.",
        style={"color": C["muted"], "margin": "-4px 4px 16px"})

    return html.Div([
        dcc.Store(id="disc-day"),
        html.Div(build_hero(cd), id="disc-hero-wrap"),
        totals,
        dbc.Row([
            dbc.Col(section(f"Infrazioni più gravi ({vs['total']} nel file)",
                            _top_violations(viols)), lg=6),
            dbc.Col(section("Guida degli ultimi 14 giorni",
                            dcc.Graph(figure=bar_daily_driving(cd.activities),
                                      config={"displayModeBar": False})), lg=6),
        ], className="g-3"),
        section("Veicoli usati di recente", vehicles),
    ])

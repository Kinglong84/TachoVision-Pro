"""
views/tabs/riepilogo.py
========================
Tab "Riepilogo": riepilogo del tempo di lavoro.

Menu in alto:
  - vista: Settimanale/Giorno, Mensile/Giorno, Settimanale/Turno, Mensile/Turno
  - Sintesi (solo intestazioni dei periodi), Riposo (righe dei riposi nella vista turno)
  - ordinamento: Periodo ↓ - Giorno ↓ / Periodo ↑ - Giorno ↑ / Periodo ↑ - Giorno ↓
  - fascia salariale maggiorata (se impostata)
Ogni periodo: righe G / L / D / Interruzione / km e totale "G + L + D + P = totale".
In più: grafico dell'andamento settimanale (richiudibile).

Calcoli: models/worktime.py · callback: controllers/worktime_controller.py
"""

from dash import dcc, html

from models.card_data import CardData
from models.settings import load_settings
from models.worktime import build_worktime
from views.charts import bar_weekly
from views.components import empty_state, section
from views.export_bar import bar_for
from views.theme import C

VIEWS = [("weekly_day", "Settimanale/Giorno"), ("monthly_day", "Mensile/Giorno"),
         ("weekly_shift", "Settimanale/Turno"), ("monthly_shift", "Mensile/Turno")]
ORDERS = [("inc_inc", "Periodo ↓ - Giorno ↓"), ("dec_dec", "Periodo ↑ - Giorno ↑"),
          ("dec_inc", "Periodo ↑ - Giorno ↓")]

_MONO = {"fontFamily": "'Overpass'", "fontSize": "0.82rem", "textAlign": "right",
         "whiteSpace": "nowrap"}
_LABEL = {"fontSize": "0.74rem", "color": C["muted"], "fontWeight": "700", "marginBottom": "4px"}


def _hm(m: int, fmt: str) -> str:
    m = max(0, int(m))
    return f"{m / 60:05.2f}" if fmt == "HHHH" else f"{m // 60:02d}:{m % 60:02d}"


def _km(v: float, unit: str) -> str:
    return f"{v * 0.621371:.0f}mi" if unit == "MILES" else f"{v:.0f}km"


def _cells(sm, s, bold=False, color=None):
    fmt = s.intervalformat
    st = {**_MONO, "fontWeight": "700" if bold else "400"}
    if color:
        st["color"] = color
    return [html.Td(_hm(sm.drive, fmt), style={**st, "color": color or C["guida"]}),
            html.Td(_hm(sm.work, fmt), style={**st, "color": color or C["lavoro"]}),
            html.Td(_hm(sm.avail, fmt), style={**st, "color": color or C["disp"]}),
            html.Td(_hm(sm.brk, fmt), style={**st, "color": color or C["riposo"]}),
            html.Td(_km(sm.km, s.distanceunit), style=st)]


def _summary_line(p, s):
    """ G + L + D + P = totale   km"""
    fmt = s.intervalformat
    parts = [_hm(p.sums.drive, fmt), _hm(p.sums.work, fmt)]
    if s.payedavailability:
        parts.append(_hm(p.sums.avail, fmt))
    if s.payedbreaktype != "NO":
        parts.append(_hm(p.sums.brk, fmt))
    text = " + ".join(parts) + f" = {_hm(p.sums.total(s), fmt)}"
    counters = [f"Giorni lavorati: {p.work_days}", f"Turni notturni: {p.night_shifts}"]
    if p.nights_abroad:
        counters.append(f"Notti fuori paese base: {p.nights_abroad}")
    if p.holidays:
        counters.append(f"Ferie: {p.holidays}")
    return html.Div([
        html.Div([html.Span(text, style={"fontFamily": "'Overpass'", "fontWeight": "700"}),
                  html.Span(_km(p.sums.km, s.distanceunit),
                            style={"fontFamily": "'Overpass'"})],
                 style={"display": "flex", "justifyContent": "space-between", "gap": "12px"}),
        html.Div(" · ".join(counters), style={"fontSize": "0.76rem", "marginTop": "3px"}),
    ], style={"background": "#F59E0B22", "border": "1px solid #F59E0B55",
              "borderRadius": "6px", "padding": "8px 12px", "marginTop": "6px"})


def build_periods(cd: CardData, view: str, options, order: str) -> html.Div:
    s = load_settings()
    options = options or []
    periods = build_worktime(cd, view, s, order)
    if not periods:
        return empty_state("L'elenco dei lavori è vuoto")
    only_header = "header" in options
    show_rests = "rests" in options
    show_wage = "wage" in options and s.wage_period is not None
    head = html.Thead(html.Tr([html.Th(""), html.Th("🚛 Guida"), html.Th("⛏ Lavoro"),
                               html.Th("⊙ Disp."), html.Th("☕ Interr."), html.Th("km")]))
    out = []
    for p in periods:
        body = []
        if not only_header:
            for r in p.rows:
                if r.kind == "rest":
                    if show_rests:
                        body.append(html.Tr([html.Td(f"🛏 {r.label}", colSpan=6,
                                                     style={"color": C["muted"],
                                                            "fontSize": "0.78rem"})]))
                    continue
                if r.kind == "day" and r.sums.drive + r.sums.work + r.sums.avail == 0:
                    continue                            # giorni senza lavoro
                body.append(html.Tr([html.Td(r.label, style={"fontSize": "0.8rem",
                                                             "whiteSpace": "nowrap"}),
                                     *_cells(r.sums, s)]))
                if show_wage and r.wage and (r.wage.drive + r.wage.work):
                    w0, w1 = s.wage_period
                    body.append(html.Tr([html.Td(f"  ↳ {w0:02d}-{w1:02d}",
                                                 style={"fontSize": "0.74rem",
                                                        "color": C["muted"]}),
                                         *_cells(r.wage, s, color=C["muted"])]))
        body.append(html.Tr([html.Td("IN TOTALE", style={"fontWeight": "700",
                                                         "fontSize": "0.8rem"}),
                             *_cells(p.sums, s, bold=True)]))
        if show_wage and p.wage:
            body.append(html.Tr([html.Td("Fascia maggiorata", style={"fontSize": "0.78rem",
                                                                     "color": C["muted"]}),
                                 *_cells(p.wage, s, color=C["muted"])]))
        out.append(html.Div([
            html.Div(p.label, style={"color": C["danger"], "fontWeight": "600",
                                     "marginBottom": "6px"}),
            html.Table([head, html.Tbody(body)], className="veh-table"),
            _summary_line(p, s),
        ], style={"background": C["card"], "border": f"1px solid {C['border']}",
                  "borderRadius": "8px", "padding": "12px", "marginBottom": "12px"}))
    return html.Div(out)


def render(cd: CardData) -> html.Div:
    s = load_settings()
    opt = [{"label": " Sintesi", "value": "header"}, {"label": " Riposo", "value": "rests"}]
    if s.wage_period:
        w0, w1 = s.wage_period
        opt.append({"label": f" Fascia maggiorata {w0:02d}:00-{w1:02d}:00", "value": "wage"})
    lbl = {"fontSize": "0.82rem", "color": C["text"]}
    controls = section(
        "Riepilogo del tempo di lavoro",
        html.Div([
            html.Div([html.Div("Vista", style=_LABEL),
                      dcc.RadioItems(id="wt-view", value="monthly_day", persistence=True,
                                     persistence_type="local",
                                     options=[{"label": f" {l}", "value": v} for v, l in VIEWS],
                                     labelStyle={**lbl, "display": "block"})]),
            html.Div([html.Div("Opzioni", style=_LABEL),
                      dcc.Checklist(id="wt-options", value=["rests"], persistence=True,
                                    persistence_type="local", options=opt,
                                    labelStyle={**lbl, "display": "block"})]),
            html.Div([html.Div("Ordinamento", style=_LABEL),
                      dcc.RadioItems(id="wt-order", value="dec_inc", persistence=True,
                                     persistence_type="local",
                                     options=[{"label": f" {l}", "value": v} for v, l in ORDERS],
                                     labelStyle={**lbl, "display": "block"})]),
        ], style={"display": "flex", "gap": "40px", "flexWrap": "wrap"}),
    )
    chart = html.Details([
        html.Summary("📊 Andamento settimanale", style={"cursor": "pointer",
                                                       "color": C["muted"]}),
        dcc.Graph(figure=bar_weekly(cd.weekly_summary), config={"displayModeBar": False}),
    ], style={"marginBottom": "12px"}) if cd.weekly_summary else None
    return html.Div([controls, bar_for(cd, "worktime", 62), chart,
                     html.Div(build_periods(cd, "monthly_day", ["rests"], "dec_inc"),
                              id="wt-periods")])

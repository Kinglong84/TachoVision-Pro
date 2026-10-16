"""
views/countries.py
==================
Sezione "Paesi visitati" (in cima alla tab Luoghi).

  - "L'autista non ha lavorato al di fuori del paese di base" se tutti i luoghi
    sono nel paese base (impostazione "Paese base")
  - per ogni soggiorno: periodo, paese, entrata/uscita (carta o frontiera),
    ore Guida/Lavoro/Disponibilità/Interruzione, distanza
  - totali per paese 
"""

from dash import html

from models.settings import load_settings
from models.vehicle_report import country_stays, country_totals
from views.components import section
from views.theme import C

_MONO = {"fontFamily": "'Overpass'", "fontSize": "0.8rem"}


def _hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _sums(x):
    return html.Span([
        html.Span(f"🚛 {_hm(x.drive)}", style={**_MONO, "marginRight": "12px"}),
        html.Span(f"⛏ {_hm(x.work)}", style={**_MONO, "marginRight": "12px"}),
        html.Span(f"⊙ {_hm(x.avail)}", style={**_MONO, "marginRight": "12px"}),
        html.Span(f"🛏 {_hm(x.brk)}", style={**_MONO, "marginRight": "12px"}),
        html.Span(f"Distanza: {x.distance}km", style={**_MONO, "fontWeight": "600"}),
    ])


def countries_section(cd) -> html.Div:
    s = load_settings()
    stays, only_base = country_stays(cd, s)
    if not cd.places:
        body = [html.Div("L'elenco dei paesi è vuoto", style={"color": C["muted"]})]
    elif only_base:
        body = [html.Div("L'autista non ha lavorato al di fuori del paese di base",
                         style={"color": C["success"], "fontWeight": "600"})]
    else:
        totals = country_totals(stays)
        body = [
            html.Div([html.Div([html.Span(t.name, style={"fontWeight": "600",
                                                         "width": "160px"}), _sums(t)],
                               style={"display": "flex", "flexWrap": "wrap", "gap": "6px",
                                      "padding": "4px 0",
                                      "borderBottom": f"1px solid {C['border']}"})
                      for t in totals], style={"marginBottom": "12px"}),
            html.Details([
                html.Summary(f"Soggiorni ({len(stays)})", style={"cursor": "pointer"}),
                *[html.Div([
                    html.Div(st.period, style={**_MONO, "fontWeight": "600"}),
                    html.Div([html.Span(st.name, style={"fontWeight": "600",
                                                        "marginRight": "12px"}),
                              html.Span(f"{st.entered} → {st.left}",
                                        style={"fontSize": "0.76rem", "color": C["muted"]})]),
                    _sums(st),
                ], style={"padding": "6px 0", "borderBottom": f"1px solid {C['border']}"})
                    for st in reversed(stays)],
            ]),
        ]
    from views.export_bar import bar_for
    return section("Paesi visitati", bar_for(cd, "country", 365), *body)

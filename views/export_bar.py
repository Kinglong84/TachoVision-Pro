"""
views/export_bar.py
===================
Barra "PDF/EXCEL" riutilizzabile nelle tab.

Formato (Pdf / Pdf solo grafico / Excel) + periodo Dal/Al + Scarica.
Il download è gestito da controllers/report_controller.py (dcc.Download
"download-report" in app.py).
"""

from dash import dcc, html

from services.report_service import EXPORT_OPTIONS, FORMAT_LABEL, FORMATS, TITLES
from views.theme import C, btn_style


def export_bar(report: str, date_from: str = None, date_to: str = None,
               min_date: str = None, max_date: str = None) -> html.Div:
    fmts = FORMATS[report]
    return html.Div([
        html.Span(f"⬇ {TITLES[report]}", style={"fontSize": "0.82rem", "fontWeight": "600"}),
        dcc.RadioItems(
            id={"type": "exp-fmt", "report": report}, value=fmts[0], inline=True,
            options=[{"label": " Pdf (cronologico)" if report == "infringement" and f == "pdf"
                      else f" {FORMAT_LABEL[f]}", "value": f} for f in fmts],
            labelStyle={"marginRight": "12px", "fontSize": "0.8rem", "color": C["text"]}),
        dcc.DatePickerRange(
            id={"type": "exp-range", "report": report}, start_date=date_from,
            end_date=date_to, min_date_allowed=min_date, max_date_allowed=max_date,
            display_format="DD/MM/YYYY", first_day_of_week=1,
            start_date_placeholder_text="Dal", end_date_placeholder_text="Al"),
        dcc.Checklist(
            id={"type": "exp-opt", "report": report}, value=[], persistence=True,
            persistence_type="local",
            options=[{"label": f" {lbl}", "value": v} for v, lbl in EXPORT_OPTIONS.get(report, [])],
            labelStyle={"fontSize": "0.8rem", "color": C["text"]},
            style={} if EXPORT_OPTIONS.get(report) else {"display": "none"}),
        html.Button("Scarica", id={"type": "exp-btn", "report": report}, n_clicks=0,
                    style=btn_style(C["accent"])),
        html.Span(id={"type": "exp-msg", "report": report},
                  style={"fontSize": "0.78rem", "color": C["warning"]}),
    ], style={"display": "flex", "gap": "12px", "alignItems": "center", "flexWrap": "wrap",
              "background": C["surface"], "border": f"1px dashed {C['border']}",
              "borderRadius": "8px", "padding": "8px 12px", "marginBottom": "12px"})


def bar_for(cd, report: str, days: int = 28) -> html.Div:
    """Barra con periodo predefinito: ultimi `days` giorni fino allo scarico."""
    from datetime import timedelta
    from views.tabs.infrazioni import _valid_until
    if not cd.activities:
        return export_bar(report)
    last = _valid_until(cd).date()
    first = min(d.date for d in cd.activities)
    start = max(first, (last - timedelta(days=days - 1)).isoformat())
    return export_bar(report, start, last.isoformat(), first, last.isoformat())

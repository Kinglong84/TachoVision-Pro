"""
views/tabs/impostazioni.py
==========================
Tab "Impostazioni": tutte le impostazioni modificabili.

5 sezioni (Impostazioni di base, Legislazioni,
Riepilogo del tempo di lavoro, Accessori, Aspetto) e stesse voci.
La pagina è generata da models/settings.SPEC: per aggiungere un'impostazione
basta aggiungerla lì.

Ogni controllo ha id {"type": "setting", "key": <chiave>}: il
settings_controller li legge tutti insieme con un pattern-matching callback.
"""

from dash import dcc, html

from models.settings import SECTIONS, SPEC, Settings, load_settings
from views.components import section
from views.theme import C, btn_style


_INPUT_STYLE = {
    "background": C["surface"], "border": f"1px solid {C['border']}",
    "color": C["text"], "borderRadius": "6px", "padding": "6px 10px",
    "fontSize": "0.84rem", "minWidth": "260px",
}


def _control(spec, value):
    cid = {"type": "setting", "key": spec.key}
    if spec.kind == "bool":
        return html.Div([
            dcc.Checklist(
                id=cid, options=[{"label": "", "value": "on"}],
                value=["on"] if value else [], inputStyle={"marginRight": "6px"},
            ),
            # Descrizione stato acceso/spento, sotto ogni interruttore
            html.Span(spec.on_text if value else spec.off_text,
                      id={"type": "setting-state", "key": spec.key},
                      style={"color": C["muted"], "fontSize": "0.78rem"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "4px"})
    if spec.kind == "select":
        return dcc.Dropdown(
            id=cid, value=value, clearable=False, searchable=len(spec.options) > 12,
            options=[{"label": lbl, "value": val} for val, lbl in spec.options],
            style={"minWidth": "320px", "color": "#000", "fontSize": "0.84rem"},
        )
    if spec.kind == "int":
        return dcc.Input(id=cid, type="number", value=value, min=spec.min,
                         max=spec.max, step=1, style={**_INPUT_STYLE, "minWidth": "90px"})
    return dcc.Input(id=cid, type="email" if spec.key == "email" else "text",
                     value=value, debounce=True, style=_INPUT_STYLE)


def _row(spec, value):
    return html.Div([
        html.Div([
            html.Div(spec.label, style={"fontSize": "0.88rem"}),
            html.Div(spec.help, style={"color": C["muted"], "fontSize": "0.74rem"})
            if spec.help else None,
        ], style={"flex": "1", "minWidth": "240px"}),
        _control(spec, value),
    ], style={"display": "flex", "alignItems": "center", "gap": "16px",
              "flexWrap": "wrap", "padding": "10px 0",
              "borderBottom": f"1px solid {C['border']}"})


def render(cd=None, settings: Settings = None) -> html.Div:
    """La tab non dipende dal file DDD caricato (cd ignorato)."""
    s = settings or load_settings()
    sections = []
    for sec_id, icon, title in SECTIONS:
        rows = [_row(spec, s.get(spec.key)) for spec in SPEC if spec.section == sec_id]
        if sec_id == "worktime":
            rows.append(html.Div(id="settings-worktime-formula",
                                 children=worktime_formula(s),
                                 style={"padding": "10px 0", "color": C["muted"],
                                        "fontSize": "0.82rem"}))
        sections.append(section(f"{icon}  {title}", *rows))

    return html.Div([
        html.Div([
            html.Button("💾  Salva impostazioni", id="btn-settings-save", n_clicks=0,
                        style=btn_style(C["accent"])),
            html.Button("↺  Predefiniti", id="btn-settings-defaults", n_clicks=0,
                        style=btn_style(C["warning"])),
            html.Span(id="settings-status",
                      style={"color": C["success"], "fontSize": "0.84rem"}),
        ], style={"display": "flex", "gap": "10px", "alignItems": "center",
                  "marginBottom": "16px"}),
        dcc.ConfirmDialog(
            id="confirm-settings-defaults",
            message="Sei sicuro di voler ripristinare tutte le impostazioni "
                    "al loro valore predefinito?",
        ),
        *sections,
    ])


def worktime_formula(s: Settings) -> str:
    """Formula del tempo di lavoro retribuito secondo le impostazioni correnti."""
    parts = ["Guida", "Lavoro"]
    if s.payedavailability:
        parts.append("Disponibilità")
    if s.payedbreaktype != "NO":
        parts.append("Interruzione")
    return "Tempo di lavoro = " + " + ".join(parts)

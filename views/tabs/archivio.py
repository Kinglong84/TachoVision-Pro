"""
views/tabs/archivio.py
=======================
Tab "Archivio": gestione dei file .DDD archiviati localmente sul PC.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from views.components import section, badge, empty_state, alert_banner
from views.theme import C


DUE_COLORS = {
    "scaduto":    C["guida"],
    "urgente":    C["guida"],
    "attenzione": C["disp"],
    "ok":         C["success"],
    "unknown":    C["muted"],
}

DUE_LABELS = {
    "scaduto":    "⛔ Scaduto",
    "urgente":    "🔴 Urgente",
    "attenzione": "🟡 Attenzione",
    "ok":         "✅ OK",
    "unknown":    "— ",
}

# Stile bottone azione tabella
def _btn(label, color, id_dict):
    return html.Button(
        label,
        id=id_dict,
        n_clicks=0,
        style={
            "background": color + "22",
            "border": f"1px solid {color}44",
            "color": color,
            "borderRadius": "4px",
            "padding": "3px 10px",
            "cursor": "pointer",
            "fontSize": "0.75rem",
            "marginRight": "4px",
            "fontFamily": "'Overpass'",
        },
    )


def render(cd=None) -> html.Div:
    """
    Costruisce la tab Archivio con dati pre-caricati dall'archivio su disco.
    Pre-fill al primo render per evitare la tabella vuota alla navigazione iniziale.
    """
    from services.archive_service import get_archive
    entries = get_archive().list_entries()

    return html.Div([

        # ── Header: stats + pulsanti ────────────────────────────────────────────
        dbc.Row([
            dbc.Col(html.Div(build_stats(entries), id="archive-stats-row"), md=8),
            dbc.Col(html.Div([
                html.Button(
                    "🔄 Aggiorna", id="btn-archive-refresh", n_clicks=0,
                    style={
                        "background": C["surface"], "border": f"1px solid {C['border']}",
                        "color": C["text"], "borderRadius": "8px", "padding": "8px 14px",
                        "cursor": "pointer", "fontSize": "0.82rem", "marginRight": "8px",
                        "fontFamily": "'Overpass'",
                    },
                ),
                html.Button(
                    "📁 Apri cartella", id="btn-open-archive-dir", n_clicks=0,
                    style={
                        "background": C["accent"] + "22", "border": f"1px solid {C['accent']}44",
                        "color": C["accent"], "borderRadius": "8px", "padding": "8px 14px",
                        "cursor": "pointer", "fontSize": "0.82rem", "fontFamily": "'Overpass'",
                    },
                ),
            ], style={"display": "flex", "alignItems": "center", "justifyContent": "flex-end"}), md=4),
        ], className="g-3 mb-3"),

        # ── Alert scadenze ──────────────────────────────────────────────────────
        html.Div(build_due_alerts(entries), id="archive-due-alerts"),

        # ── Sezione Export ──────────────────────────────────────────────────────
        section("📤 Esporta verso storage esterno (USB / LAN / NAS)",
            dbc.Row([
                dbc.Col(dcc.Input(
                    id="input-export-path",
                    placeholder="Es: D:\\archivio_tacho  oppure  \\\\NAS\\scarichi",
                    style={
                        "width": "100%", "background": C["surface"],
                        "border": f"1px solid {C['border']}",
                        "color": C["text"], "borderRadius": "6px",
                        "padding": "8px 12px",
                        "fontFamily": "'Overpass'", "fontSize": "0.82rem",
                    },
                    debounce=True,
                ), md=8),
                dbc.Col(html.Div([
                    html.Button(
                        "📋 Esporta tutti",
                        id="btn-export-all",
                        n_clicks=0,
                        style={
                            "background": C["riposo"] + "22",
                            "border": f"1px solid {C['riposo']}44",
                            "color": C["riposo"], "borderRadius": "8px",
                            "padding": "8px 14px", "cursor": "pointer",
                            "fontSize": "0.82rem", "fontFamily": "'Overpass'",
                            "width": "100%",
                        },
                    ),
                ]), md=4),
            ], className="g-2"),
            html.Div(id="export-result", style={"marginTop": "8px", "fontSize": "0.8rem"}),
        ),

        # ── filtro, backup, ripristino, zip, cancella
        tools_section(entries),

        # ── Tabella file archiviati ─────────────────────────────────────────────
        section("🗄️ File .DDD archiviati",
            html.Div(build_table(entries), id="archive-table-container"),
        ),

    ])


def build_stats(entries: list) -> html.Div:
    total    = len(entries)
    scad     = sum(1 for e in entries if e.due_status in ("scaduto", "urgente"))
    total_mb = sum(e.file_size for e in entries) / 1_048_576

    return dbc.Row([
        dbc.Col(html.Div([
            html.Div("🗄️", className="stat-icon"),
            html.Div(str(total), className="stat-value"),
            html.Div("File archiviati", className="stat-label"),
        ], className="stat-card"), xs=4),
        dbc.Col(html.Div([
            html.Div("🔴", className="stat-icon", style={"color": C["guida"]}),
            html.Div(str(scad), className="stat-value", style={"color": C["guida"]}),
            html.Div("Scadenze urgenti", className="stat-label"),
        ], className="stat-card"), xs=4),
        dbc.Col(html.Div([
            html.Div("💾", className="stat-icon", style={"color": C["accent"]}),
            html.Div(f"{total_mb:.1f} MB", className="stat-value", style={"color": C["accent"]}),
            html.Div("Spazio usato", className="stat-label"),
        ], className="stat-card"), xs=4),
    ], className="g-3")


def build_due_alerts(entries: list) -> html.Div:
    urgent = [e for e in entries if e.due_status in ("scaduto", "urgente")]
    if not urgent:
        return html.Div()
    return html.Div([
        alert_banner(
            f"⛔  {e.driver_name} — carta {e.card_number}: "
            f"{'SCADUTO' if e.due_status == 'scaduto' else f'scadenza tra {e.days_until_due} giorni'} "
            f"(prossimo scarico entro il {e.next_due})",
            color=C["guida"],
        )
        for e in urgent
    ])


def build_table(entries: list) -> html.Div:
    if not entries:
        return empty_state("Nessun file archiviato. Carica un .DDD o leggi una carta.")

    rows = []
    for e in entries:
        row = html.Tr([

            # Colonna checkbox selezione (dcc.Checklist a singola opzione)
            html.Td(
                dcc.Checklist(
                    id={"type": "chk-ddd", "index": e.filename},
                    options=[{"label": "", "value": "sel"}],
                    value=[],
                    inputStyle={"cursor": "pointer", "width": "14px", "height": "14px",
                                "accentColor": C["accent"]},
                    style={"margin": "0"},
                ),
                style={"width": "30px", "paddingLeft": "8px"},
            ),

            html.Td(html.Span(e.driver_name, style={"fontWeight": "600", "fontSize": "0.88rem"})),
            html.Td(e.card_number, style={"fontFamily": "'Overpass'", "fontSize": "0.8rem"}),
            html.Td(e.download_date, style={"fontFamily": "'Overpass'", "fontSize": "0.78rem", "color": C["muted"]}),
            html.Td([
                html.Div(e.next_due, style={"fontFamily": "'Overpass'", "fontSize": "0.78rem"}),
                html.Div(
                    f"{e.days_until_due}gg" if e.days_until_due is not None else "—",
                    className="due-urgent" if e.due_status in ("scaduto", "urgente") else None,
                    style={"fontSize": "0.72rem", "color": DUE_COLORS.get(e.due_status, C["muted"])},
                ),
            ]),
            html.Td(badge(DUE_LABELS.get(e.due_status, "—"), DUE_COLORS.get(e.due_status, C["muted"]))),
            html.Td(f"{e.file_size/1024:.1f} KB",
                    style={"fontFamily": "'Overpass'", "fontSize": "0.78rem", "textAlign": "right"}),
            html.Td(html.Span(e.source, style={"fontSize": "0.72rem", "color": C["muted"]})),
            html.Td([
                _btn("📊 Carica", C["success"], {"type": "btn-load-ddd", "index": e.filename}),
                _btn("⬇ .DDD",   C["accent"],  {"type": "btn-dl-ddd",   "index": e.filename}),
                _btn("🗑",        C["guida"],   {"type": "btn-del-ddd",   "index": e.filename}),
            ]),
        ])
        rows.append(row)

    # Checkbox "seleziona tutti" nell'intestazione
    select_all_chk = dcc.Checklist(
        id="chk-archive-all",
        options=[{"label": "", "value": "all"}],
        value=[],
        inputStyle={"cursor": "pointer", "width": "14px", "height": "14px",
                    "accentColor": C["accent"]},
        style={"margin": "0"},
    )

    return html.Table([
        html.Thead(html.Tr([
            html.Th(select_all_chk, style={"width": "30px", "paddingLeft": "8px"}),
            html.Th("Conducente"), html.Th("Carta"), html.Th("Scarico"),
            html.Th("Prossimo scarico"), html.Th("Stato"), html.Th("Dim."),
            html.Th("Fonte"), html.Th(""),
        ])),
        html.Tbody(rows),
    ], className="veh-table")


def tools_section(entries: list) -> html.Div:
    """Filtro conducente, Backup/Ripristino su file,
    Zip, Cancella tutto (tutti o il conducente selezionato, con i dati manuali)."""
    drivers = {}
    for e in entries:
        drivers.setdefault(e.card_number, e.driver_name)
    options = [{"label": "Tutti", "value": "ALL"}] + [
        {"label": f"{name} ({card})", "value": card} for card, name in sorted(
            drivers.items(), key=lambda x: x[1] or "")]
    btn = {"borderRadius": "8px", "padding": "7px 12px", "cursor": "pointer",
           "fontSize": "0.82rem", "background": C["surface"], "color": C["text"],
           "border": f"1px solid {C['border']}"}
    return section(
        "🧰 Gestione archivio",
        html.Div([
            html.Div([html.Div("Conducente", style={"fontSize": "0.74rem", "color": C["muted"]}),
                      dcc.Dropdown(id="archive-driver", value="ALL", clearable=False,
                                   options=options,
                                   style={"width": "320px", "color": "#000"})]),
            html.Button("💾 Backup su file", id="btn-backup-file", n_clicks=0, style=btn),
            dcc.Upload(html.Div("♻️ Ripristina da file", style=btn), id="upload-backup",
                       accept=".zip", multiple=False),
            html.Button("🗜 Zip", id="btn-archive-zip", n_clicks=0, style=btn),
            html.Button("🗑 Cancella tutto!", id="btn-delete-all", n_clicks=0,
                        style={**btn, "color": C["danger"], "borderColor": C["danger"] + "66"}),
        ], style={"display": "flex", "gap": "10px", "alignItems": "flex-end",
                  "flexWrap": "wrap"}),
        html.Div(id="archive-tools-msg", style={"fontSize": "0.82rem", "marginTop": "8px"}),
        dcc.ConfirmDialog(id="confirm-delete-all", message=""),
        dcc.Download(id="download-archive-tool"),
    )

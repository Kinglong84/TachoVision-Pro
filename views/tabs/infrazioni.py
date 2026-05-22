"""
views/tabs/infrazioni.py
========================
Tab "Infrazioni": visualizzazione delle violazioni al Reg. CE 561/2006
e alla Direttiva 2002/15/CE sul tempo di lavoro degli autotrasportatori.

Le infrazioni vengono rilevate da models/violations.py e qui presentate:
  1. Riga di 4 stat-card (conteggio per severità)
  2. Se nessuna infrazione: messaggio verde "Conforme"
  3. Se ci sono infrazioni: accordion per categoria normativa

Ogni categoria normativa (es. "Guida continua Art. 7") è un pannello
espandibile (html.Details) con le singole infrazioni in tabella.
I pannelli con infrazioni gravi/molto gravi sono aperti di default.

Riferimento normativo:
  Reg. CE 561/2006 → guida e riposo
  Dir. 2002/15/CE → orario di lavoro totale degli autotrasportatori
"""

from collections import defaultdict
from dash import html
import dash_bootstrap_components as dbc

from views.components import (
    section, badge, empty_state,
    filter_bar, filter_blocks_input, filter_count_badge
)
from views.theme import C, SEV_COLORS
from models.violations import detect_violations, violation_summary, SEV_VERY, SEV_HIGH, SEV_LOW
from models.card_data import CardData

# ID contenitore infrazioni per il filtro JavaScript
_TABLE_ID = "table-infrazioni"


# ── Mappa codice infrazione → categoria normativa ─────────────────────────────────
# Raggruppa i codici dell'app Android in categorie leggibili con riferimento normativo.
# I codici corrispondono ai nomi HTML nell'APK (es. "ContinuousDriving").
_CATEGORY = {
    "ContinuousDriving":    "Guida continua (Art. 7)",
    "DayDriving":           "Guida giornaliera (Art. 6§1)",
    "WeekDriving_one":      "Guida settimanale (Art. 6§2)",
    "WeekDriving_two":      "Guida bisettimanale (Art. 6§3)",
    "BiWeekDriving":        "Guida bisettimanale (Art. 6§3)",
    "Daily_TooShort":       "Riposo giornaliero (Art. 8§1)",
    "Daily_TooLate":        "Riposo giornaliero (Art. 8§1)",
    "Weekly_TooShort":      "Riposo settimanale (Art. 8§6)",
    "Weekly_TooShort_NOC":  "Riposo settimanale ridotto (Art. 8§6)",
    "ContinuousWorking_69": "Lavoro continuo (Dir. 2002/15 Art. 5)",
    "WeekWorking_48":       "Ore lavoro settimanali (Dir. 2002/15 Art. 4)",
    "WeekWorking_60":       "Ore lavoro settimanali max (Dir. 2002/15 Art. 4)",
    "Working_IsNight_10":   "Lavoro notturno (Dir. 2002/15 Art. 7)",
}

# Icone per ogni categoria (visualizzata nell'intestazione del pannello)
_CAT_ICON = {
    "Guida continua (Art. 7)":                    "🚗",
    "Guida giornaliera (Art. 6§1)":               "📅",
    "Guida settimanale (Art. 6§2)":               "📆",
    "Guida bisettimanale (Art. 6§3)":             "📆",
    "Riposo giornaliero (Art. 8§1)":              "🛏",
    "Riposo settimanale (Art. 8§6)":              "😴",
    "Riposo settimanale ridotto (Art. 8§6)":      "😴",
    "Lavoro continuo (Dir. 2002/15 Art. 5)":      "🔧",
    "Ore lavoro settimanali (Dir. 2002/15 Art. 4)": "⏱",
    "Ore lavoro settimanali max (Dir. 2002/15 Art. 4)": "⏱",
    "Lavoro notturno (Dir. 2002/15 Art. 7)":      "🌙",
}


def _cat(code: str) -> str:
    """Ritorna la categoria leggibile per un codice infrazione, o "Altro"."""
    return _CATEGORY.get(code, "Altro")


def _viol_row(v) -> html.Tr:
    """
    Costruisce una riga della tabella per una singola infrazione.

    Colonne:
        Data:       data dell'infrazione in formato italiano
        Infrazione: titolo + dettaglio normativo
        Valori:     valore rilevato, limite normativo, eccesso
        Severità:   badge colorato con icona e livello
    """
    return html.Tr([
        # Colonna data
        html.Td(v.date_display,
                style={"fontFamily": "'DM Mono'", "fontSize": "0.8rem",
                       "color": C["muted"], "whiteSpace": "nowrap"}),

        # Colonna infrazione: titolo + dettaglio
        html.Td([
            html.Div(v.description, style={"fontWeight": "600", "fontSize": "0.85rem"}),
            html.Div(v.detail, style={"fontSize": "0.78rem", "color": C["muted"], "marginTop": "2px"}),
        ]),

        # Colonna valori: rilevato, limite, eccesso
        html.Td([
            html.Div(f"Rilevato: {v.value_h}",  style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem"}),
            html.Div(f"Limite:   {v.limit_h}",  style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem", "color": C["muted"]}),
            html.Div(f"Eccesso:  {v.excess_h}", style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem", "color": v.color}),
        ]),

        # Colonna severità: punto pulsante + badge colorato
        html.Td(html.Span([
            # "ping-dot": animazione CSS pulsante (cerchio rosso lampeggiante)
            # mostrata solo per le infrazioni più gravi (Molto Grave)
            html.Span(className="ping-dot") if v.severity == "Molto Grave" else None,
            badge(f"{v.icon} {v.severity}", v.color),
        ], style={"display": "flex", "alignItems": "center", "gap": "4px"})),
    ])


def _group_badge(items: list) -> html.Span:
    """
    Costruisce i mini-badge con conteggio per severità nell'intestazione del gruppo.

    Mostra per ogni severità presente nel gruppo un badge con il conteggio:
    es. "2" (rosso) "1" (arancione) = 2 molto gravi, 1 grave nel gruppo.

    Parametro 'items': lista di Violation per questo gruppo/categoria.
    """
    # Conta le infrazioni per severità
    counts = defaultdict(int)
    for v in items:
        counts[v.severity] += 1

    parts = []
    # Itera per severità decrescente (dal più grave al meno grave)
    for sev, color in [(SEV_VERY, C["danger"]), (SEV_HIGH, C["warning"]), (SEV_LOW, "#F59E0B")]:
        if counts[sev]:
            parts.append(html.Span(f"{counts[sev]}", style={
                "background": color + "22",
                "border": f"1px solid {color}55",
                "color": color,
                "borderRadius": "10px",
                "padding": "1px 8px",
                "fontSize": "0.72rem",
                "fontWeight": "700",
                "marginLeft": "6px",
            }))
    return html.Span(parts)


def render(cd: CardData) -> html.Div:
    """
    Costruisce la tab Infrazioni completa.

    Flusso:
    1. Rileva le infrazioni tramite detect_violations()
    2. Calcola il riepilogo per severità (violation_summary)
    3. Mostra le stat-card con i conteggi
    4. Se nessuna infrazione, mostra "Conforme"
    5. Altrimenti raggruppa per categoria e mostra accordion
    """
    viols = detect_violations(cd.activities)   # lista di Violation
    vs    = violation_summary(viols)            # {SEV_VERY: N, SEV_HIGH: N, SEV_LOW: N, "total": N}

    # ── Riga stat-card: 3 severità + totale ──────────────────────────────────────
    stat_row = dbc.Row([
        dbc.Col(html.Div([
            html.Div("🚨", className="stat-icon", style={"color": SEV_COLORS[SEV_VERY]}),
            html.Div(str(vs[SEV_VERY]), className="stat-value", style={"color": SEV_COLORS[SEV_VERY]}),
            html.Div("Molto Gravi", className="stat-label"),
        ], className="stat-card"), xs=4, md=3),

        dbc.Col(html.Div([
            html.Div("🔴", className="stat-icon", style={"color": SEV_COLORS[SEV_HIGH]}),
            html.Div(str(vs[SEV_HIGH]), className="stat-value", style={"color": SEV_COLORS[SEV_HIGH]}),
            html.Div("Gravi", className="stat-label"),
        ], className="stat-card"), xs=4, md=3),

        dbc.Col(html.Div([
            html.Div("🟡", className="stat-icon", style={"color": SEV_COLORS[SEV_LOW]}),
            html.Div(str(vs[SEV_LOW]), className="stat-value", style={"color": SEV_COLORS[SEV_LOW]}),
            html.Div("Lievi", className="stat-label"),
        ], className="stat-card"), xs=4, md=3),

        dbc.Col(html.Div([
            html.Div("⚠️", className="stat-icon"),
            html.Div(str(vs["total"]), className="stat-value"),
            html.Div("Totale", className="stat-label"),
        ], className="stat-card"), xs=12, md=3),
    ], className="g-3 mb-3")

    # ── Caso nessuna infrazione ───────────────────────────────────────────────────
    if not viols:
        body = section(
            "Infrazioni Reg. CE 561/2006 + Dir. 2002/15/CE",
            html.Div("✅  Nessuna infrazione rilevata",
                     style={"textAlign": "center", "color": C["success"], "padding": "32px",
                            "fontSize": "0.95rem"}),
        )
        return html.Div([stat_row, body])

    # ── Raggruppa le infrazioni per categoria normativa ───────────────────────────
    by_cat: dict = defaultdict(list)
    for v in viols:
        by_cat[_cat(v.code)].append(v)   # chiave = categoria (es. "Guida continua (Art. 7)")

    # ── Costruisce i pannelli accordion per categoria ─────────────────────────────
    accordions = []
    for cat_name, items in sorted(by_cat.items()):   # ordine alfabetico per categoria
        icon = _CAT_ICON.get(cat_name, "⚠️")

        # Tabella delle infrazioni per questa categoria
        tbl = html.Table(
            [html.Thead(html.Tr([html.Th(h) for h in ["Data", "Infrazione", "Valori", "Severità"]])),
             html.Tbody([_viol_row(v) for v in items])],
            className="veh-table",
            style={"margin": "0"},
        )

        # Pannello accordion HTML nativo
        # open=True: aperto di default se contiene infrazioni gravi/molto gravi
        accordions.append(
            html.Details([
                html.Summary([
                    html.Span(icon, style={"fontSize": "1rem", "marginRight": "8px"}),
                    html.Span(cat_name, style={"flex": "1"}),   # etichetta espandidle
                    _group_badge(items),                         # mini-badge per severità
                    html.Span("▼", className="viol-group-chevron"),  # freccia giù
                ]),
                tbl,
            ], className="viol-group",
               # Apre automaticamente i pannelli con infrazioni gravi o molto gravi
               open=True if items and any(v.severity in (SEV_VERY, SEV_HIGH) for v in items) else False),
        )

    # Contenitore con id stabile per il filtro JS globale
    accordion_wrapper = html.Div(
        accordions,
        id=_TABLE_ID,
        style={"marginTop": "4px"},
    )

    return html.Div([
        stat_row,
        section(
            f"Infrazioni Reg. CE 561/2006 + Dir. 2002/15/CE ({vs['total']})",
            filter_bar(
                filter_blocks_input("Cerca infrazione / data...", _TABLE_ID, width="280px"),
                filter_count_badge(_TABLE_ID),
            ),
            accordion_wrapper,
        ),
    ])

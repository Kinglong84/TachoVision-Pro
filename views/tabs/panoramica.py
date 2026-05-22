"""
views/tabs/panoramica.py
========================
Tab "Dashboard / Panoramica": vista di riepilogo ad alto livello.

Questa tab è la prima che vede l'utente dopo aver caricato un file DDD.
Mostra una "foto istantanea" dello stato del conducente:
  - KPI numerici (giorni, km, ore guida, veicoli)
  - Semaforo di conformità (verde/giallo/rosso)
  - Grafico donut distribuzione ore
  - Le infrazioni più gravi (max 3)
  - Bar chart ore guida ultimi 14 giorni
  - Lista veicoli

La funzione principale 'render(cd)' viene chiamata da views/tabs/__init__.py
tramite la funzione render_tab() che smista verso la view giusta.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
# dbc.Row/Col: layout a griglia Bootstrap (12 colonne) per disporre le sezioni

from views.components import stat_card, section, badge
from views.charts import donut_hours, bar_daily_driving
from views.theme import C, SEV_COLORS
from models.analytics import compute_stats
from models.violations import detect_violations, violation_summary, SEV_VERY, SEV_HIGH, SEV_LOW
from models.card_data import CardData


def _semaphore(vs: dict) -> html.Div:
    """
    Costruisce il pannello "semaforo" di conformità.

    Determina il colore e il messaggio in base al tipo di infrazioni presenti:
      🚨 Rosso  → ci sono infrazioni "Molto Grave"
      ⚠️ Arancione → solo infrazioni "Grave"
      🟡 Giallo → solo infrazioni "Lieve"
      ✅ Verde  → nessuna infrazione

    Parametro 'vs': dizionario dal violation_summary()
    { SEV_VERY: 2, SEV_HIGH: 0, SEV_LOW: 3, "total": 5 }
    """
    # Valutazione a cascata: dal più grave al più lieve
    if vs[SEV_VERY] > 0:
        color, icon, label = C["danger"], "🚨", "NON CONFORME"
        detail = f"{vs[SEV_VERY]} molto gravi · {vs[SEV_HIGH]} gravi · {vs[SEV_LOW]} lievi"
    elif vs[SEV_HIGH] > 0:
        color, icon, label = C["warning"], "⚠️", "ATTENZIONE"
        detail = f"{vs[SEV_HIGH]} infrazioni gravi · {vs[SEV_LOW]} lievi"
    elif vs[SEV_LOW] > 0:
        color, icon, label = "#F59E0B", "🟡", "VERIFICA"
        detail = f"{vs[SEV_LOW]} infrazioni lievi"
    else:
        color, icon, label = C["success"], "✅", "CONFORME"
        detail = "Nessuna infrazione rilevata"

    # Il pannello ha sfondo colorato molto trasparente (+ "10" = 6% opacità)
    return html.Div([
        html.Div(icon, style={"fontSize": "2.6rem", "lineHeight": "1"}),
        html.Div(label, className="semaphore-status", style={"color": color}),
        html.Div(detail, className="semaphore-detail"),
    ], className="semaphore-card", style={
        "background": color + "10",
        "border": f"2px solid {color}44",
    })


def _top_violations(viols: list) -> html.Div:
    """
    Mostra le top 3 infrazioni più gravi (o le prime 3 se tutte lievi).

    Se non ci sono infrazioni, mostra un messaggio positivo verde.

    Parametro 'viols': lista di oggetti Violation dal detect_violations()
    """
    # Prima prova a mostrare solo le gravi/molto gravi
    serious = [v for v in viols if v.severity in (SEV_VERY, SEV_HIGH)]
    # Se non ce ne sono, mostra le prime 3 in assoluto (lievi)
    shown   = (serious or viols)[:3]   # max 3 infrazioni

    if not shown:
        return html.Div("✅ Nessuna infrazione grave",
                        style={"color": C["success"], "fontSize": "0.85rem", "padding": "8px 0"})

    rows = []
    for v in shown:
        # Per ogni infrazione: badge severità | titolo + data | eccesso
        rows.append(html.Div([
            # Badge colorato con icona e severità
            html.Span(f"{v.icon} {v.severity}", style={
                "background": v.color + "22",
                "border": f"1px solid {v.color}44",
                "color": v.color,
                "borderRadius": "4px",
                "padding": "2px 8px",
                "fontSize": "0.72rem",
                "fontWeight": "700",
                "whiteSpace": "nowrap",
            }),
            # Titolo e data (in un div flessibile che si adatta allo spazio)
            html.Div([
                html.Div(v.description, style={"fontSize": "0.82rem", "fontWeight": "600"}),
                html.Div(v.date_display, style={"fontSize": "0.72rem", "color": C["muted"],
                                                 "fontFamily": "'DM Mono'"}),
            ], style={"flex": "1", "minWidth": 0}),   # flex:1 = occupa lo spazio restante
            # Eccesso rispetto al limite (es. "+1h30")
            html.Span(v.excess_h, style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem",
                                          "color": v.color, "whiteSpace": "nowrap"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "10px",
                  "padding": "7px 0", "borderBottom": f"1px solid {C['border']}"}))

    return html.Div(rows)


def render(cd: CardData) -> html.Div:
    """
    Costruisce il layout completo della tab Panoramica.

    Parametro 'cd': oggetto CardData con tutti i dati della carta.

    Struttura del layout (griglia Bootstrap):
        Riga 1: 4 stat_card (giorni, guida, km, veicoli)
        Riga 2: semaforo (md=4) | donut (md=5) | top-infrazioni (md=3)
        Riga 3: bar-chart guida (md=8) | lista veicoli (md=4)
    """
    # Calcola i KPI (statistiche aggregate)
    stats = compute_stats(cd)

    # Rileva le infrazioni e crea il riepilogo {severità: conteggio}
    viols = detect_violations(cd.activities)
    vs    = violation_summary(viols)

    # ── Riga statistiche (4 card numeriche) ───────────────────────────────────────
    stat_row = dbc.Row([
        stat_card("📅", "Giorni totali",   str(stats.get("days", 0))),
        stat_card("🚛", "Giorni di guida", str(stats.get("driving_days", 0)), C["guida"]),
        stat_card("⏱", "Ore di guida",    f"{stats.get('driving_h', 0)}h",   C["lavoro"]),
        # Formato italiano: 123.456 km (punto come separatore migliaia)
        stat_card("📍", "Km percorsi",
                  f"{int(stats.get('total_km', 0)):,}".replace(",", "."), C["riposo"]),
    ], className="g-3 mb-3")   # g-3 = gutter (spazio) tra le colonne, mb-3 = margin-bottom

    # ── Lista veicoli (pannello laterale) ─────────────────────────────────────────
    vehicles_list = html.Div([
        # Una riga per veicolo: icona + targa + date
        html.Div([
            html.Span("🚛 ", style={"color": C["accent"]}),
            html.Span(v.vrn, style={"fontFamily": "'DM Mono'", "fontWeight": "600"}),
            html.Span(f"  {v.first_use} → {v.last_use}",
                      style={"fontSize": "0.75rem", "color": C["muted"], "marginLeft": "8px"}),
        ], style={"padding": "6px 0", "borderBottom": f"1px solid {C['border']}"})
        for v in cd.vehicles
    # Se non ci sono veicoli, mostra un messaggio placeholder
    ] or [html.Div("Nessun veicolo", style={"color": C["muted"]})])

    # ── Assemblaggio layout finale ────────────────────────────────────────────────
    return html.Div([
        stat_row,   # riga 1: 4 KPI

        # Riga 2: semaforo + donut + top infrazioni (totale 4+5+3 = 12 colonne Bootstrap)
        dbc.Row([
            dbc.Col(section("Stato conformità", _semaphore(vs)), md=4),
            dbc.Col(section("Distribuzione ore",
                # dcc.Graph: widget Plotly; config={"displayModeBar": False} nasconde la toolbar
                dcc.Graph(figure=donut_hours(stats.get("hours", {})),
                          config={"displayModeBar": False})), md=5),
            dbc.Col(section(f"Top infrazioni ({vs['total']} tot.)", _top_violations(viols)), md=3),
        ], className="g-3 mb-3"),

        # Riga 3: bar-chart guida + veicoli
        dbc.Row([
            dbc.Col(section("Ore guida giornaliere (ultimi 14 giorni)",
                dcc.Graph(figure=bar_daily_driving(cd.activities),
                          config={"displayModeBar": False})), md=8),
            dbc.Col(section("Veicoli", vehicles_list), md=4),
        ], className="g-3"),
    ])

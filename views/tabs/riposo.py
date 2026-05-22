"""
views/tabs/riposo.py
=====================
Tab "Riposo": analisi e visualizzazione dei periodi di riposo del conducente.

Secondo il Reg. CE 561/2006, il conducente deve rispettare i seguenti riposi:
  - Riposo giornaliero: almeno 11h consecutive (o 9h ridotto, max 3x/settimana)
  - Riposo settimanale: almeno 45h (o 24h ridotto)
  - Pausa guida: 45 minuti (o 15+30) ogni 4.5h di guida

I periodi di riposo sono già calcolati da models/analytics.py (compute_rest_periods)
e salvati nel campo cd.rest_periods come lista di RestPeriod classificati.

La tab mostra:
  1. Istogramma (histogramma) della distribuzione delle durate
  2. Tabella di tutti i periodi ≥ 45 minuti con tipo, inizio, fine, durata
"""

from dash import html, dcc
from views.components import section, badge, empty_state
from views.charts import hist_rest   # istogramma distribuzione durate riposo
from views.theme import C
from models.card_data import CardData


# Colori per tipo di riposo (coerenti con la classificazione normativa)
KIND_COLORS = {
    "Regolare":    C["success"],   # verde: riposo giornaliero ≥ 11h (Art. 8 §1)
    "Ridotto":     C["disp"],      # arancione: riposo giornaliero ≥ 9h (tollerato)
    "Settimanale": C["accent"],    # ciano: riposo settimanale ≥ 45h (Art. 8 §6)
    "Breve":       C["muted"],     # grigio: pausa ≥ 45 min durante la guida (Art. 7)
}


def render(cd: CardData) -> html.Div:
    """
    Costruisce la tab Riposo con istogramma e tabella.

    Se non ci sono periodi di riposo significativi (tutti < 45 min),
    mostra un messaggio vuoto.
    """
    rests = cd.rest_periods   # lista di RestPeriod, dalla più recente

    if not rests:
        return empty_state("Nessun periodo di riposo ≥ 45 minuti trovato")

    # ── Costruisce le righe della tabella ─────────────────────────────────────────
    rows = [
        html.Tr([
            # Data e ora inizio riposo (formato "DD/MM/YYYY HH:MM")
            html.Td(r.start,        style={"fontFamily":"'DM Mono'","fontSize":"0.8rem","whiteSpace":"nowrap"}),
            # Data e ora fine riposo
            html.Td(r.end,          style={"fontFamily":"'DM Mono'","fontSize":"0.8rem",
                                           "color":C["muted"],"whiteSpace":"nowrap"}),
            # Durata in formato "Xh YY" colorata in base al tipo
            html.Td(r.duration_str, style={"fontFamily":"'DM Mono'","fontWeight":"600",
                                            "color":KIND_COLORS.get(r.kind, C["text"])}),
            # Badge colorato con il tipo di riposo
            html.Td(badge(r.kind, KIND_COLORS.get(r.kind, C["muted"]))),
        ])
        for r in rests   # list comprehension: una riga per ogni periodo di riposo
    ]

    # ── Layout: istogramma + tabella ──────────────────────────────────────────────
    return html.Div([
        # Istogramma che mostra quante soste hanno ogni durata
        # (frecce verticali segnano le soglie 9h e 11h)
        section("Distribuzione periodi di riposo",
            dcc.Graph(figure=hist_rest(rests), config={"displayModeBar": False})),

        # Tabella completa di tutti i periodi ≥ 45 min
        section(f"Tutti i periodi ≥ 45 min ({len(rests)})",
            html.Table([
                html.Thead(html.Tr([html.Th(h) for h in ["Inizio","Fine","Durata","Tipo"]])),
                html.Tbody(rows),
            ], className="veh-table")),
    ])

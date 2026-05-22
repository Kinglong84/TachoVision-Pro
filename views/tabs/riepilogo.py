"""
views/tabs/riepilogo.py
========================
Tab "Riepilogo": statistiche settimanali ore e km.

Mostra per ogni settimana ISO (lunedì–domenica):
  - Ore di Guida, Lavoro, Disponibilità, Riposo
  - Totale lavoro (guida + lavoro + disponibilità)
  - Km percorsi
  - Flag ⚠️ se superati i limiti del Reg. 561/2006

I dati arrivano già calcolati da models/analytics.py (campo cd.weekly_summary).
"""

from dash import html, dcc
from views.components import section, empty_state
from views.charts import bar_weekly         # grafico a barre settimanali
from views.theme import C
from models.card_data import CardData


def render(cd: CardData) -> html.Div:
    """
    Costruisce la tab Riepilogo con grafico e tabella settimanale.

    Se non ci sono dati settimanali (file DDD senza attività),
    mostra un messaggio vuoto.
    """
    weekly = cd.weekly_summary   # lista di WeekSummary, dalla più recente

    if not weekly:
        return empty_state("Nessun dato settimanale disponibile")

    # ── Costruisce le righe della tabella ─────────────────────────────────────────
    rows = []
    for w in weekly:
        # Determina se questa settimana ha superato i limiti normativi
        # over56h: guida > 56h/settimana (Reg. 561 Art. 6 §3)
        # over48h_work: tot. lavoro > 48h (Dir. 2002/15/CE)
        flag = "⚠️" if (w.over56h or w.over48h_work) else "✅"

        # Crea una riga HTML con tutte le colonne
        rows.append(html.Tr([
            # Settimana (es. "Sett. 11/05/2026")
            html.Td(f"Sett. {w.week_label}",
                    style={"fontFamily":"'DM Mono'","fontSize":"0.8rem",
                           "color":C["muted"],"whiteSpace":"nowrap"}),
            # Giorni attivi nella settimana
            html.Td(str(w.days), style={"textAlign":"center"}),
            # Ore guida (colorate in rosso per evidenziare)
            html.Td(w.guida,         style={"color":C["guida"],"fontFamily":"'DM Mono'","textAlign":"center"}),
            # Ore lavoro
            html.Td(w.lavoro,        style={"color":C["lavoro"],"fontFamily":"'DM Mono'","textAlign":"center"}),
            # Ore disponibilità
            html.Td(w.disponibilita, style={"color":C["disp"],"fontFamily":"'DM Mono'","textAlign":"center"}),
            # Ore riposo
            html.Td(w.riposo,        style={"color":C["riposo"],"fontFamily":"'DM Mono'","textAlign":"center"}),
            # Totale lavoro (guida + lavoro + disponibilità) — in grassetto
            html.Td(w.totale_lavoro, style={"fontFamily":"'DM Mono'","textAlign":"center","fontWeight":"600"}),
            # Km (arrotondati a intero, senza decimali)
            html.Td(f"{w.km:.0f}",   style={"fontFamily":"'DM Mono'","textAlign":"right"}),
            # Flag infrazione
            html.Td(flag,            style={"textAlign":"center"}),
        ]))

    # ── Layout: grafico + tabella ─────────────────────────────────────────────────
    return html.Div([
        # Grafico a barre: guida e totale lavoro per le ultime 12 settimane
        section("Andamento settimanale (ultime 12 settimane)",
            dcc.Graph(figure=bar_weekly(weekly), config={"displayModeBar": False})),

        # Tabella dettagliata con tutte le settimane
        section(f"Dettaglio settimanale ({len(weekly)} settimane)",
            html.Table([
                # Intestazione fissa (repeatRows nel PDF)
                html.Thead(html.Tr([html.Th(h) for h in
                    ["Settimana","Gg","Guida","Lavoro","Dispon.","Riposo","Tot.Lavoro","Km","⚠"]])),
                html.Tbody(rows),
            ], className="veh-table")),   # classe CSS per lo stile tabella
    ])

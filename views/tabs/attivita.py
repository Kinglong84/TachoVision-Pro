"""
views/tabs/attivita.py
=======================
Tab "Attività": visualizzazione giornaliera di tutte le attività del conducente.

Mostra gli ultimi 90 giorni presenti nel file DDD come una lista di card,
una per ogni giorno. Ogni card contiene:
  - Intestazione colorata con data e giorno della settimana
  - Mini-Gantt orizzontale (grafico Plotly) con le attività del giorno
  - Badge riassuntivi (ore guida, ore lavoro, km percorsi)
  - Pannello espandibile "Dettaglio sessione" con:
      - Riga verde "Carta inserita" (inizio sessione veicolo)
      - Lista dei segmenti di attività con orario e durata
      - Riga rossa "Carta disinserita" (fine sessione veicolo)

ORARI IN ORA LOCALE:
  Il tachigrafo registra tutto in UTC. Le ore vengono convertite
  all'ora locale italiana (Europe/Rome) tramite utils/time_utils.py.
  In estate (CEST): UTC+2 = +120 min; in inverno (CET): UTC+1 = +60 min.

FILTRO LATO CLIENT (JavaScript):
  La tab usa il sistema di filtro JS in assets/filter.js.
  L'input di ricerca filtra le card per testo (data, giorno).
  Il counter badge mostra quante card sono visibili dopo il filtro.
"""

from datetime import datetime
from dash import html, dcc

from views.components import (
    activity_legend,      # legenda colori attività (Guida/Lavoro/Disp./Riposo)
    empty_state,          # messaggio "nessun dato" per quando non ci sono attività
    filter_bar,           # barra contenitore per i filtri
    filter_blocks_input,  # input testuale che filtra le card .day-block via JS
    filter_count_badge,   # badge che mostra "N risultati" dopo il filtro
)
from views.charts import mini_gantt   # grafico Gantt per un singolo giorno
from views.theme import C, ACT_COLORS, WEEKDAYS_IT
from models.card_data import CardData, VehicleSession

# ID del contenitore delle card giorni — usato dal filtro JavaScript
# Il filtro cerca dentro il div con questo id e mostra/nasconde i .day-block
_BLOCKS_ID = "blocks-attivita"

# Icone per ogni tipo di attività (usate nelle righe del dettaglio sessione)
_ACT_ICONS = {
    "Guida":         "🚗",
    "Lavoro":        "🔧",
    "Disponibilità": "⏳",
    "Riposo":        "🛏",
}

# Importazione delle funzioni di utilità per la conversione UTC → ora locale.
# Definite in utils/time_utils.py per evitare duplicazione tra questa tab e pdf_service.py.
from utils.time_utils import (
    tz_offset_min as _tz_offset_min,       # calcola l'offset UTC→locale in minuti per una data
    local_dt as _local_dt,                 # converte timestamp Unix UTC in datetime locale
    local_time_str as _local_time_str,     # converte timestamp Unix UTC in stringa "HH:MM"
    sessions_for_day as _sessions_for_day, # filtra le sessioni veicolo per un giorno specifico
)


def _fmt_time(m: int, tz_off: int = 0) -> str:
    """
    Converte minuti da mezzanotte UTC in stringa orario locale "HH:MM:00".

    Parametri:
        m:      minuti dall'inizio della giornata UTC (es. 480 = 08:00 UTC)
        tz_off: offset fuso orario in minuti (es. 120 per UTC+2)

    Esempio: m=480, tz_off=120 → (480+120)%1440 = 600 → "10:00:00"
    Il % 1440 gestisce il rollover mezzanotte (es. 23:30 + 2h = 01:30 del giorno dopo).
    """
    m = (m + tz_off) % 1440   # converti in minuti locali con rollover
    return f"{m // 60:02d}:{m % 60:02d}:00"


def _fmt_dur(m: int) -> str:
    """
    Formatta una durata in minuti come "ΔT=H:MM".
    Il simbolo Δ (delta) indica una variazione/differenza di tempo.
    Esempio: 95 minuti → "ΔT=1:35"
    """
    h, mn = divmod(m, 60)   # divmod: quoziente e resto della divisione (ore, minuti)
    return f"ΔT={h}:{mn:02d}"


def _card_in_row(s: VehicleSession) -> html.Div:
    """
    Costruisce la riga verde "Carta inserita" all'inizio di una sessione veicolo.

    Mostra:
      - Cerchio verde 🟢 + orario inserimento (da first_use_utc, convertito in locale)
      - Targa del veicolo (VRN)
      - Odometro all'inserimento in km (formato italiano con punto separatore migliaia)

    Il colore di sfondo è C["success"] + "12" (success con 7% di opacità):
    es. "#00FF00" + "12" = "#00FF0012" (verde quasi trasparente come sfondo).
    """
    dt       = _local_dt(s.first_use_utc)      # datetime locale dall'UTC
    time_str = dt.strftime("%H:%M:%S")          # formato orario "HH:MM:SS"
    km_str   = f"{s.odo_begin_km:,}".replace(",", ".")   # "123.456" formato italiano

    return html.Div([
        html.Span("🟢", style={"marginRight": "6px"}),
        # Orario inserimento carta (verde grassetto)
        html.Span(time_str, style={
            "fontFamily": "'DM Mono'", "fontSize": "0.78rem",
            "fontWeight": "700", "color": C["success"], "minWidth": "58px",
        }),
        # Label "Carta inserita"
        html.Span("Carta inserita", style={
            "fontSize": "0.78rem", "color": C["success"],
            "fontWeight": "600", "minWidth": "105px",
        }),
        # Targa veicolo (es. "— AA000BB")
        html.Span(f"— {s.vrn}", style={
            "fontFamily": "'DM Mono'", "fontSize": "0.78rem",
            "color": C["text"], "marginRight": "10px",
        }),
        # Odometro inizio sessione
        html.Span(f"{km_str} km", style={
            "fontFamily": "'DM Mono'", "fontSize": "0.75rem",
            "color": C["muted"],
        }),
    ], style={
        "display": "flex", "alignItems": "center", "gap": "4px",
        "padding": "4px 8px", "marginBottom": "2px",
        "background": C["success"] + "12",   # sfondo verde molto tenue
        "borderRadius": "4px", "borderLeft": f"3px solid {C['success']}",
    })


def _card_out_row(s: VehicleSession) -> html.Div:
    """
    Costruisce la riga rossa "Carta disinserita" alla fine di una sessione veicolo.

    Mostra:
      - Cerchio rosso 🔴 + orario disinserimento (da last_use_utc)
      - Targa + odometro finale + delta km percorsi (solo se ragionevole: 0 < Δ ≤ 5000)

    Il delta km viene mostrato solo se positivo e ≤ 5000 km
    (valori irragionevoli come 65535 km indicano dati corrotti o sessioni fantasma).
    """
    dt       = _local_dt(s.last_use_utc)
    time_str = dt.strftime("%H:%M:%S")
    km_str   = f"{s.odo_end_km:,}".replace(",", ".")
    delta    = s.odo_end_km - s.odo_begin_km
    # Mostra il delta solo se è un valore plausibile
    delta_str = f" (+{delta} km)" if 0 < delta <= 5000 else ""

    return html.Div([
        html.Span("🔴", style={"marginRight": "6px"}),
        html.Span(time_str, style={
            "fontFamily": "'DM Mono'", "fontSize": "0.78rem",
            "fontWeight": "700", "color": C["danger"], "minWidth": "58px",
        }),
        html.Span("Carta disinserita", style={
            "fontSize": "0.78rem", "color": C["danger"],
            "fontWeight": "600", "minWidth": "105px",
        }),
        html.Span(f"— {s.vrn}", style={
            "fontFamily": "'DM Mono'", "fontSize": "0.78rem",
            "color": C["text"], "marginRight": "10px",
        }),
        # Odometro fine + delta km percorsi durante la sessione
        html.Span(f"{km_str} km{delta_str}", style={
            "fontFamily": "'DM Mono'", "fontSize": "0.75rem",
            "color": C["muted"],
        }),
    ], style={
        "display": "flex", "alignItems": "center", "gap": "4px",
        "padding": "4px 8px", "marginTop": "2px",
        "background": C["danger"] + "12",   # sfondo rosso molto tenue
        "borderRadius": "4px", "borderLeft": f"3px solid {C['danger']}",
    })


_DATE_INPUT_STYLE = {
    "background": C["surface"],
    "border": f"1px solid {C['border']}",
    "color": C["text"],
    "borderRadius": "6px",
    "padding": "5px 8px",
    "fontSize": "0.78rem",
    "fontFamily": "'DM Mono', monospace",
    "outline": "none",
    "colorScheme": "dark",
}


def _build_blocks(shown: list, cd: "CardData", gnss_dates: set = None) -> list:
    """
    Costruisce la lista di card HTML per i giorni in `shown`.
    Estratta da render() per essere richiamata anche dal callback di filtro.
    gnss_dates: set di date ISO (YYYY-MM-DD) per cui esistono waypoint GPS.
    """
    gnss_dates = gnss_dates or set()
    blocks = []
    for day in shown:
        # Parsing della data per ottenere il giorno della settimana
        dt = datetime.strptime(day.date, "%Y-%m-%d")
        wd = WEEKDAYS_IT[dt.weekday()]   # "Lunedì", "Martedì", ecc.

        # Colore intestazione: rosso per i giorni lavorativi (lun-sab), blu per domenica
        hdr = "#FF6B6B" if dt.weekday() < 6 else "#4A6FA5"

        # Offset fuso orario per questo giorno specifico (gestisce DST automaticamente)
        tz_off = _tz_offset_min(day.date)

        # Ore guida e lavoro del giorno (in minuti)
        h_guida = day.minutes_of("Guida")
        h_lav   = day.minutes_of("Lavoro")
        km      = day.distance_km

        # Filtra le sessioni veicolo (inserimento/disinserimento carta) per questo giorno
        day_sessions = _sessions_for_day(cd.vehicle_sessions, day.date)

        # ── Costruisce le righe del dettaglio segmenti ──────────────────────────
        seg_rows = []
        for s, e, act in day.segments():
            dur = e - s   # durata del segmento in minuti
            if dur <= 0:
                continue   # skip segmenti di durata nulla
            icon  = _ACT_ICONS.get(act, "⊙")
            color = ACT_COLORS.get(act, C["muted"])
            seg_rows.append(html.Div([
                # Orario inizio in ora locale (es. "08:30:00")
                html.Span(_fmt_time(s, tz_off), style={
                    "color": C["muted"], "minWidth": "40px",
                    "fontFamily": "'DM Mono'", "fontSize": "0.75rem",
                }),
                # Icona + nome attività (es. "🚗 Guida")
                html.Span(f"{icon} {act}", style={
                    "color": color, "minWidth": "130px",
                    "fontSize": "0.75rem", "fontWeight": "500",
                }),
                # Durata del segmento (es. "ΔT=1:35")
                html.Span(_fmt_dur(dur), style={
                    "color": C["muted"], "fontFamily": "'DM Mono'",
                    "fontSize": "0.75rem",
                }),
            ], style={"display": "flex", "gap": "10px", "padding": "1px 0",
                      "alignItems": "center"}))

        # ── Costruisce il pannello dettaglio (espandibile) ──────────────────────
        detail_children = []
        # Prima sessione: riga "Carta inserita"
        if day_sessions:
            detail_children.append(_card_in_row(day_sessions[0]))

        # Segmenti di attività con bordo sinistro per indicare la timeline
        if seg_rows:
            detail_children.append(html.Div(seg_rows, style={
                "marginTop": "6px", "marginBottom": "6px",
                "paddingLeft": "8px",
                "borderLeft": f"2px solid {C['border']}",  # linea verticale a sinistra
            }))

        # Ultima sessione: riga "Carta disinserita"
        if day_sessions:
            detail_children.append(_card_out_row(day_sessions[-1]))

        # html.Details: elemento HTML nativo espandibile/collassabile
        # Mostra "Dettaglio sessione" come summary (clickabile per aprire)
        # Viene creato solo se ci sono dati da mostrare (segmenti o sessioni)
        detail_panel = html.Details([
            html.Summary("Dettaglio sessione", style={
                "cursor": "pointer", "fontSize": "0.75rem",
                "color": C["muted"], "marginTop": "8px",
                "userSelect": "none",  # impedisce la selezione del testo sul click
                "listStyle": "none",   # nasconde il triangolino predefinito del browser
            }),
            html.Div(detail_children, style={"marginTop": "6px"}),
        ]) if (seg_rows or day_sessions) else html.Div()

        # ── Badge riassuntivi ────────────────────────────────────────────────────
        # Mostrati sotto il Gantt: ore guida, ore lavoro, km percorsi
        badges = html.Div([
            html.Span(f"🚗 Guida {h_guida//60}h{h_guida%60:02d}",
                      style={"color": C["guida"], "fontSize": "0.8rem",
                             "marginRight": "14px", "fontFamily": "'DM Mono'"}),
            html.Span(f"🔧 Lavoro {h_lav//60}h{h_lav%60:02d}",
                      style={"color": C["lavoro"], "fontSize": "0.8rem",
                             "marginRight": "14px", "fontFamily": "'DM Mono'"}),
            html.Span(f"📍 {km:.0f} km",
                      style={"color": C["accent"], "fontSize": "0.8rem",
                             "fontFamily": "'DM Mono'"}),
        ], style={"marginTop": "4px"})

        # ── Assembla la card del giorno ─────────────────────────────────────────
        # Struttura:
        #   <div class="day-block">       ← target del filtro JS
        #     <div> intestazione </div>   ← colore hdr (rosso/blu)
        #     <div>                       ← corpo card (sfondo scuro)
        #       <dcc.Graph>               ← mini-Gantt
        #       badges
        #       detail_panel
        #     </div>
        #   </div>
        # Icona GPS solo nei giorni che hanno waypoint registrati
        gps_btn = []
        if day.date in gnss_dates:
            gps_btn = [html.Button(
                "🛰️",
                id={"type": "btn-gps-day", "index": day.date},
                n_clicks=0,
                title="Visualizza traccia GPS di questo giorno",
                style={
                    "background": "transparent", "border": "none",
                    "cursor": "pointer", "fontSize": "0.95rem",
                    "marginLeft": "8px", "padding": "0 4px",
                    "lineHeight": "1", "color": "white",
                    "opacity": "0.9", "flexShrink": "0",
                },
            )]

        blocks.append(html.Div([
            # Intestazione: data + giorno della settimana (+ icona GPS se disponibile)
            html.Div([
                html.Span(f"{day.date_display} ({wd})"),
                *gps_btn,
            ], style={
                "background": hdr, "color": "white",
                "padding": "6px 12px", "borderRadius": "6px 6px 0 0",   # angoli superiori arrotondati
                "fontSize": "0.82rem", "fontWeight": "600",
                "letterSpacing": "0.3px",
                "display": "flex", "alignItems": "center",
            }),
            # Corpo della card
            html.Div([
                # Mini-Gantt: il grafico più importante della card
                # tz_off: offset in minuti per mostrare l'asse X in ora locale
                dcc.Graph(figure=mini_gantt(day.changes, day.date, tz_off),
                          config={"displayModeBar": False},
                          style={"borderRadius": "0"}),
                badges,
                detail_panel,
            ], style={
                "padding": "8px 12px", "background": C["card"],
                "borderRadius": "0 0 6px 6px",    # angoli inferiori arrotondati
                "border": f"1px solid {C['border']}", "borderTop": "none",
            }),
        # className="day-block": classe usata dal filtro JS (assets/filter.js)
        # per individuare le card e mostrarle/nasconderle durante il filtraggio
        ], className="day-block"))

    return blocks


def render(cd: CardData) -> html.Div:
    """
    Costruisce la tab Attività con le card per il periodo selezionato.

    Mostra di default gli ultimi 90 giorni. I date-picker nella barra filtri
    permettono di scegliere qualsiasi finestra temporale presente nel DDD.
    Il filtro testuale JavaScript opera sui blocchi già renderizzati lato server.
    """
    if not cd.activities:
        return empty_state("Nessuna attività disponibile")

    all_acts = cd.activities
    date_min = all_acts[0].date   # prima data disponibile nella carta (ISO)
    date_max = all_acts[-1].date  # ultima data disponibile nella carta (ISO)

    # Default: mostra tutti i dati disponibili (max 365 giorni per performance)
    shown = list(reversed(all_acts[-365:]))
    default_from = shown[-1].date if shown else date_min  # oldest in the shown slice
    gnss_dates = {g.date for g in cd.gnss_records} if cd.gnss_records else set()

    # ── Barra filtri ─────────────────────────────────────────────────────────
    bars = filter_bar(
        filter_blocks_input("Cerca data / giorno...", _BLOCKS_ID, width="180px"),
        filter_count_badge(_BLOCKS_ID),
        # Separatore
        html.Span("│", style={"color": C["border"], "padding": "0 6px"}),
        # Label + date picker "Dal"
        html.Span("Dal", style={
            "color": C["muted"], "fontSize": "0.78rem", "whiteSpace": "nowrap",
        }),
        dcc.Input(
            id="input-attivita-from",
            type="date",
            value=default_from,
            min=date_min,
            max=date_max,
            debounce=True,
            style=_DATE_INPUT_STYLE,
        ),
        # Label + date picker "al"
        html.Span("al", style={
            "color": C["muted"], "fontSize": "0.78rem", "whiteSpace": "nowrap",
        }),
        dcc.Input(
            id="input-attivita-to",
            type="date",
            value=date_max,
            min=date_min,
            max=date_max,
            debounce=True,
            style=_DATE_INPUT_STYLE,
        ),
        # Contatore giorni mostrati
        html.Span(
            id="attivita-days-count",
            children=f"{len(shown)} giorni",
            style={"color": C["muted"], "fontSize": "0.78rem",
                   "marginLeft": "auto", "whiteSpace": "nowrap"},
        ),
    )

    return html.Div([
        activity_legend(),
        bars,
        html.Div(_build_blocks(shown, cd, gnss_dates=gnss_dates), id=_BLOCKS_ID),
    ])

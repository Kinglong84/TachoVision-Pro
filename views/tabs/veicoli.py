"""
views/tabs/veicoli.py
======================
Tab "Veicoli": lista dei veicoli usati dal conducente con dettaglio sessioni.

Ogni veicolo è presentato come un pannello espandibile (html.Details/Summary):
  - Intestazione: targa, periodo uso, km totali, numero sessioni, VIN
  - Dettaglio (aperto al click): lista delle singole sessioni con date e km

Struttura dati:
  cd.vehicles         → lista di Vehicle (veicoli unici aggregati)
  cd.vehicle_sessions → lista di VehicleSession (singoli inserimenti carta)

I veicoli sono già deduplicati dal parser; le sessioni sono tutti i singoli
inserimenti, potenzialmente più per stesso veicolo.
"""

from collections import defaultdict
# defaultdict: dizionario che crea automaticamente un valore default per chiavi mancanti
# Usato per raggruppare le sessioni per targa (vrn)

from dash import html
import dash_bootstrap_components as dbc

from views.components import (
    section, empty_state, filter_bar, filter_blocks_input, filter_count_badge
)
from views.theme import C
from models.card_data import CardData

# ID del contenitore dei blocchi veicolo (usato dal filtro JS)
_WRAP_ID = "veh-cards-wrap"


def _km(v: int) -> str:
    """
    Formatta un numero intero di km in formato leggibile con separatore migliaia.

    Usa il punto come separatore (convenzione italiana: 1.234 km).
    Ritorna "—" se il valore è 0 o None.

    Esempi:
        _km(83755) → "83.755 km"
        _km(0)     → "—"
    """
    return f"{v:,} km".replace(",", ".") if v else "—"


def _session_rows(sessions: list) -> html.Div:
    """
    Costruisce la lista delle sessioni per un veicolo.

    Ogni riga mostra: numero sessione | data inizio → data fine | km percorsi.

    Parametro 'sessions': lista di VehicleSession per questo veicolo.
    Il codice gestisce sia oggetti dataclass (v.km) sia dizionari (dal JSON Store).
    """
    if not sessions:
        return html.Div("Nessuna sessione disponibile",
                        style={"color": C["muted"], "fontSize": "0.78rem", "padding": "8px 0"})

    rows = []
    for i, s in enumerate(sessions, 1):   # enumerate(sessions, 1) → indice parte da 1
        # Calcola km percorsi: usa la property .km se disponibile, altrimenti calcola
        km = s.km if hasattr(s, "km") else (
            (s.odo_end_km - s.odo_begin_km) if s.odo_end_km and s.odo_begin_km else 0
        )
        rows.append(html.Div([
            # Numero sessione (es. "#01", "#02", ...)
            html.Span(f"#{i:02d}", style={"color": C["accent"], "minWidth": "28px",
                                           "fontWeight": "600"}),
            # Data inserimento carta
            html.Span(s.first_use or "—", style={"minWidth": "90px"}),
            html.Span("→", style={"color": C["muted"]}),
            # Data rimozione carta
            html.Span(s.last_use  or "—", style={"minWidth": "90px"}),
            # Km percorsi nella sessione (allineati a destra con marginLeft: auto)
            html.Span(_km(km), style={"color": C["riposo"], "marginLeft": "auto"}),
        ], className="session-row"))

    return html.Div(rows)


def _vehicle_card(v, sessions: list) -> html.Details:
    """
    Costruisce un pannello espandibile (accordion) per un singolo veicolo.

    html.Details/Summary è un elemento HTML nativo che funziona senza JavaScript:
    - html.Summary: intestazione cliccabile (sempre visibile)
    - html.Details: contenuto espandibile (visibile solo quando aperto)
    - open=False: il pannello è chiuso di default

    Parametri:
        v:        oggetto Vehicle (targa, date, km totali, VIN)
        sessions: lista delle VehicleSession per questo veicolo
    """
    km_str  = _km(v.total_km)   # km totali formattati
    n_sess  = len(sessions)     # numero di sessioni
    has_km  = bool(v.total_km)  # True se abbiamo dati km

    # Costruisce gli elementi dell'intestazione (sempre visibili)
    header_items = [
        html.Span("🚛", style={"fontSize": "1.2rem", "marginRight": "4px"}),
        # Targa in grassetto e accent
        html.Span(v.vrn, style={
            "fontFamily": "'DM Mono'", "fontWeight": "700",
            "fontSize": "1rem", "color": C["accent"], "marginRight": "14px",
        }),
        # Periodo utilizzo (primo uso → ultimo uso)
        html.Span(f"{v.first_use} → {v.last_use}",
                  style={"fontSize": "0.78rem", "color": C["muted"],
                         "fontFamily": "'DM Mono'", "marginRight": "14px"}),
    ]

    # Aggiunge km totali se disponibili
    if has_km:
        header_items.append(html.Span(km_str, style={
            "fontSize": "0.82rem", "color": C["riposo"],
            "fontFamily": "'DM Mono'", "fontWeight": "600",
        }))

    # Aggiunge conteggio sessioni
    if n_sess:
        header_items.append(html.Span(
            f"  ·  {n_sess} sess.",
            style={"fontSize": "0.75rem", "color": C["muted"], "marginLeft": "auto"},
        ))

    # Aggiunge VIN se disponibile (solo Gen2)
    if v.vin:
        header_items.append(html.Span(v.vin, style={
            "fontSize": "0.72rem", "color": C["muted"],
            "fontFamily": "'DM Mono'", "marginLeft": "12px",
        }))

    # Pannello completo con accordion HTML nativo
    return html.Details([
        html.Summary(header_items, className="veh-card-header"),
        html.Div([
            html.Div("Sessioni di utilizzo", style={
                "fontSize": "0.62rem", "color": C["muted"],
                "textTransform": "uppercase",   # testo in maiuscolo
                "letterSpacing": "1.8px",       # spazio tra le lettere (stile label)
                "padding": "10px 0 6px",
            }),
            _session_rows(sessions),   # lista righe sessioni
        ], className="veh-card-sessions"),
    ], className="veh-card", open=False)   # chiuso di default


def render(cd: CardData) -> html.Div:
    """
    Costruisce la tab Veicoli completa.

    Se non ci sono veicoli, mostra un messaggio vuoto.
    Altrimenti:
    1. Raggruppa le sessioni per targa (per associarle ai veicoli)
    2. Calcola statistiche aggregate (km totali, n. sessioni)
    3. Crea i pannelli espandibili per ogni veicolo
    4. Aggiunge barra di filtro testuale
    """
    if not cd.vehicles:
        return empty_state("Nessun veicolo registrato")

    # Raggruppa le sessioni per targa: {"GV824TP": [sess1, sess2, ...], ...}
    sessions_by_vrn: dict = defaultdict(list)
    for s in cd.vehicle_sessions:
        sessions_by_vrn[s.vrn].append(s)

    # Statistiche aggregate per l'intestazione della sezione
    total_km_all = sum(v.total_km for v in cd.vehicles if v.total_km)
    n_sessions   = len(cd.vehicle_sessions)

    # Costruisce gli elementi del riepilogo (km totali + n. sessioni)
    summary_items = []
    if total_km_all:
        summary_items.append(
            html.Span(f"Km totali: {total_km_all:,} km".replace(",", "."),
                      style={"fontWeight": "600", "color": C["accent"]})
        )
    if n_sessions:
        summary_items.append(
            html.Span(f"  ·  {n_sessions} sessioni su {len(cd.vehicles)} veicoli",
                      style={"color": C["muted"], "fontSize": "0.85rem"})
        )

    # Crea un pannello espandibile per ogni veicolo
    cards = [_vehicle_card(v, sessions_by_vrn.get(v.vrn, [])) for v in cd.vehicles]

    # Assemblaggio layout
    parts = []
    if summary_items:
        # Riga riepilogo km + sessioni
        parts.append(html.Div(summary_items,
                               style={"marginBottom": "12px", "fontSize": "0.9rem"}))

    # Barra di filtro: cerca per targa o VIN
    parts.append(filter_bar(
        filter_blocks_input("Cerca targa / VIN...", _WRAP_ID, width="260px"),
        filter_count_badge(_WRAP_ID),
    ))

    # Contenitore dei pannelli veicolo (id usato dal filtro JS)
    parts.append(html.Div(cards, id=_WRAP_ID))

    return section(f"Veicoli utilizzati ({len(cd.vehicles)})", *parts)

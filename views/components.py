"""
views/components.py
===================
Componenti Dash riutilizzabili, privi di logica di business.

Questo modulo contiene "mattoni" UI: funzioni che ricevono dati semplici
(stringhe, numeri, dizionari) e restituiscono elementi Dash (html.Div, html.Table, ecc.).
I componenti qui sono usati da più tab diverse, evitando duplicazione di codice.

Principio: questi componenti NON calcolano nulla, NON fanno parsing.
Ricevono dati già pronti e li presentano graficamente.

Struttura dei componenti principali:
  stat_card()         → card statistica (icona + valore + etichetta)
  section()           → pannello con titolo
  badge()             → etichetta colorata inline
  driver_badge()      → barra del conducente in cima alla pagina
  alert_banner()      → messaggio di avviso colorato
  veh_table()         → tabella veicoli
  filter_bar()        → barra filtri orizzontale
  filter_input()      → input testo per filtrare tabelle (<tr>)
  filter_blocks_input() → input testo per filtrare blocchi (.day-block)
  filter_select()     → dropdown per filtrare tabelle per colonna
  filter_count_badge() → badge numerico "N risultati"
  empty_state()       → messaggio "nessun dato" centrato
  activity_legend()   → legenda colori per le 4 attività
  info_row()          → riga label: valore (scheda carta)
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
# dbc = Dash Bootstrap Components: componenti che usano Bootstrap CSS
# (es. dbc.Col per il layout a griglia)

from views.theme import C, ACT_COLORS, SEV_COLORS, badge_style, card_style, muted_text_style, mono_style


def stat_card(icon: str, label: str, value: str, color: str = None) -> dbc.Col:
    """
    Card statistica: mostra un'icona, un valore numerico e un'etichetta.

    Usata nella tab "Panoramica" per mostrare i KPI (ore guida, km, ecc.).
    Il componente dbc.Col permette il layout a griglia responsive:
    xs=6 → occupa metà pagina su schermi piccoli
    md=3 → un quarto su schermi medi/grandi (4 card per riga)

    Parametri:
        icon:   emoji o testo da usare come icona (es. "🚗")
        label:  etichetta descrittiva (es. "Ore di guida")
        value:  valore da mostrare in grande (es. "473h")
        color:  colore esadecimale; se None usa l'accent predefinito
    """
    color = color or C["accent"]
    return dbc.Col(
        html.Div([
            html.Div(icon,  className="stat-icon",  style={"color": color}),
            html.Div(value, className="stat-value", style={"color": color}),
            html.Div(label, className="stat-label"),
        ], className="stat-card",
           style={"borderColor": color + "33"}),   # bordo laterale sinistro colorato
        xs=6, md=3,   # layout responsive Bootstrap
    )


def section(title: str, *children, extra_style: dict = None) -> html.Div:
    """
    Pannello (sezione) con titolo in cima e contenuto variabile.

    *children permette di passare un numero qualsiasi di elementi figli:
    section("Titolo", html.P("testo"), html.Button("clicca"))

    Il pannello usa la classe CSS "section-card" definita in assets/style.css.
    """
    extra = extra_style or {}
    return html.Div([
        html.Div(title, className="section-title"),   # titolo della sezione
        *children,   # * "spacchetta" la tupla dei figli
    ], className="section-card", style=extra if extra else None)


def badge(text: str, color: str) -> html.Span:
    """
    Etichetta colorata inline (testo con sfondo e bordo semitrasparente).

    Usata per mostrare stati, categorie, tag (es. "🔴 Grave", "G1", "IT").

    Parametri:
        text:  testo del badge (es. "Molto Grave")
        color: colore esadecimale (#RRGGBB)
    """
    return html.Span(text, style=badge_style(color))


def driver_badge(driver: dict, demo: bool) -> html.Div:
    """
    Barra del conducente: mostrata in cima alla pagina quando un file è caricato.

    Mostra nome, numero carta e data scadenza. Se demo=True aggiunge " 🔵 DEMO".

    Parametro 'driver': dizionario con le info del conducente
    (perché arriva da to_dict() → CardData.driver.__dict__)
    """
    # Concatena nome + cognome, rimuove spazi iniziali/finali, default "—"
    name   = f"{driver.get('firstname','')} {driver.get('surname','')}".strip() or "—"
    card_n = driver.get("card_number", "—")
    expiry = driver.get("expiry_date", "—")
    suffix = " 🔵 DEMO" if demo else ""    # indicatore visivo modalità demo

    return html.Div([
        html.Div([
            html.Span("👤", style={"fontSize": "2rem"}),
            html.Div([
                # Nome completo + eventuale suffisso DEMO
                html.Div(name + suffix, className="driver-name"),
                # Riga con numero carta e scadenza
                html.Div(f"Carta: {card_n}  ·  Scadenza: {expiry}",
                         className="driver-meta"),
            ]),
        ], style={"display": "flex", "alignItems": "center", "gap": "14px"}),
    ], className="driver-badge")


def alert_banner(text: str, color: str = None) -> html.Div:
    """
    Bandiera di avviso/errore colorata.

    Usata per mostrare errori di parsing o avvertimenti all'utente.
    Il colore predefinito è l'accent (ciano), ma può essere cambiato
    per errori (rosso) o avvisi (arancione).
    """
    color = color or C["accent"]
    return html.Div(text, style={
        "background": color + "12",         # sfondo molto trasparente (7% opacità)
        "border": f"1px solid {color}33",   # bordo parzialmente trasparente
        "color": color,
        "borderRadius": "6px",
        "padding": "8px 16px",
        "fontSize": "0.8rem",
        "marginBottom": "8px",
    })


def veh_table(vehicles: list) -> html.Table:
    """
    Tabella HTML dei veicoli usati dal conducente.

    La tabella adatta dinamicamente le colonne in base ai dati disponibili:
    - "Km totali" viene mostrata solo se almeno un veicolo ha km > 0
    - "VIN" viene mostrata solo per carte Gen2 (Gen1 non ha VIN)

    Parametro 'vehicles': lista di Vehicle (dataclass) o dict (dallo Store).
    Il codice supporta entrambe le forme perché a volte i dati arrivano
    come oggetti Python, altre volte come dizionari JSON dallo Store.
    """
    # Controlla se ci sono VIN o km da mostrare (per decidere le colonne)
    has_vin = any((v.get("vin") if isinstance(v, dict) else v.vin) for v in vehicles)
    has_km  = any((v.get("total_km", 0) if isinstance(v, dict) else v.total_km) for v in vehicles)

    rows = []
    for v in vehicles:
        # Estrae i campi sia da dict che da dataclass (doppia forma)
        vrn      = v["vrn"]            if isinstance(v, dict) else v.vrn
        fu       = v["first_use"]      if isinstance(v, dict) else v.first_use
        lu       = v["last_use"]       if isinstance(v, dict) else v.last_use
        vin      = (v.get("vin", "")   if isinstance(v, dict) else v.vin) or ""
        total_km = (v.get("total_km", 0) if isinstance(v, dict) else v.total_km) or 0

        # Celle base (sempre presenti)
        cells = [
            html.Td(html.Span(vrn, className="vrn-badge")),   # targa con stile speciale
            html.Td(fu),    # data primo utilizzo
            html.Td(lu),    # data ultimo utilizzo
        ]

        # Colonna km totali (solo se almeno un veicolo ha km)
        if has_km:
            # Formato italiano: 1.234 km (punto come separatore migliaia)
            km_str = f"{total_km:,} km".replace(",", ".") if total_km else "—"
            cells.append(html.Td(km_str, style={"fontFamily": "'DM Mono'",
                                                  "fontSize": "0.8rem",
                                                  "textAlign": "right"}))

        # Colonna VIN (solo Gen2)
        if has_vin:
            cells.append(html.Td(vin or "—", style={"fontFamily": "'DM Mono'",
                                                      "fontSize": "0.75rem",
                                                      "color": C["muted"]}))

        rows.append(html.Tr(cells))

    # Intestazioni colonne (corrispondono all'ordine delle celle)
    headers = ["Targa", "Primo utilizzo", "Ultimo utilizzo"]
    if has_km:
        headers.append("Km totali")
    if has_vin:
        headers.append("VIN")

    return html.Table([
        # Intestazione tabella
        html.Thead(html.Tr([html.Th(h) for h in headers])),
        # Corpo tabella (o riga "nessun veicolo" se lista vuota)
        html.Tbody(rows or [html.Tr([html.Td("Nessun veicolo",
                                              colSpan=len(headers),
                                              style={"color": C["muted"]})])]),
    ], className="veh-table")


def filter_bar(*inputs) -> html.Div:
    """
    Contenitore orizzontale per i controlli di filtro (input, select, badge).

    Accetta un numero variabile di elementi (*inputs) e li dispone
    in riga con flexbox. Usato sopra le tabelle o le liste filtrabili.

    Esempio:
        filter_bar(
            filter_input("Cerca...", "my-table"),
            filter_count_badge("my-table"),
        )
    """
    return html.Div(list(inputs), style={
        "display": "flex",        # disposizione orizzontale
        "gap": "10px",            # spazio tra gli elementi
        "alignItems": "center",   # allineamento verticale centrato
        "flexWrap": "wrap",       # va a capo su schermi piccoli
        "marginBottom": "12px",
    })


# Stile CSS base condiviso da tutti gli input di filtro
_INPUT_STYLE = {
    "background": C["surface"],
    "border": f"1px solid {C['border']}",
    "color": C["text"],
    "borderRadius": "6px",
    "padding": "6px 12px",
    "fontSize": "0.82rem",
    "outline": "none",   # rimuove il bordo blu di focus del browser
}


def filter_input(placeholder: str, target_id: str, width: str = "220px") -> html.Div:
    """
    Input testo che filtra le righe (<tr>) di una tabella tramite JavaScript.

    Il filtro è implementato in assets/filter.js che legge l'attributo
    HTML personalizzato 'data-filter-table' per sapere quale tabella filtrare.

    Parametri:
        placeholder: testo guida nell'input vuoto (es. "Cerca targa...")
        target_id:   id HTML della tabella da filtrare
        width:       larghezza CSS dell'input (es. "220px")
    """
    return html.Div(
        dcc.Input(
            type="text",
            placeholder=f"🔍 {placeholder}",
            debounce=False,              # aggiorna il filtro ad ogni tasto premuto
            className="tv-filter-input",
            style={**_INPUT_STYLE, "width": width},
        ),
        **{"data-filter-table": target_id},   # attributo HTML personalizzato letto dal JS
        style={"display": "inline-block"},
    )


def filter_blocks_input(placeholder: str, target_id: str, width: str = "220px") -> html.Div:
    """
    Input testo che filtra i blocchi (.day-block) invece delle righe di tabella.

    Funziona come filter_input ma usa 'data-filter-blocks' e la classe
    "tv-filter-blocks". Lo script JS in assets/filter.js gestisce entrambi i casi.
    Usato nella tab Attività dove ogni giorno è un div con classe "day-block".

    Parametri:
        placeholder: testo guida
        target_id:   id del contenitore dei blocchi (html.Div con id=target_id)
        width:       larghezza CSS
    """
    return html.Div(
        dcc.Input(
            type="text",
            placeholder=f"🔍 {placeholder}",
            debounce=False,
            className="tv-filter-blocks",    # classe diversa: gestita da JS per blocchi
            style={**_INPUT_STYLE, "width": width},
        ),
        **{"data-filter-blocks": target_id},   # attributo HTML per i blocchi
        style={"display": "inline-block"},
    )


def filter_select(label: str, options: list, target_id: str, col: int = 0) -> html.Select:
    """
    Dropdown (menu a tendina) che filtra le righe di una tabella per colonna.

    Usato per filtrare per paese, tipo di attività, ecc.
    Il filtro è gestito da assets/filter.js che legge 'data-filter-select'
    e 'data-filter-col' per sapere quale colonna confrontare.

    Parametri:
        label:     etichetta del primo option ("Tutti")
        options:   lista di valori possibili (es. ["IT", "DE", "FR"])
        target_id: id della tabella da filtrare
        col:       indice della colonna da confrontare (0-based)
    """
    # Prima opzione "Tutti" (valore vuoto = nessun filtro)
    opts = [html.Option("Tutti", value="")] + [html.Option(o, value=o) for o in options]
    return html.Select(
        opts,
        **{"data-filter-select": target_id, "data-filter-col": str(col)},
        className="tv-filter-select",
        style={**_INPUT_STYLE, "cursor": "pointer"},
    )


def filter_count_badge(target_id: str) -> html.Span:
    """
    Badge numerico che mostra "X risultati" e viene aggiornato via JavaScript.

    È inizialmente nascosto (display: none). Il filtro JS lo rende visibile
    e aggiorna il testo con il conteggio delle righe/blocchi visibili.

    Parametro:
        target_id: id del contenitore filtrato (usato per costruire l'id del badge)
                   Il badge ha id="{target_id}-count" che il JS usa per trovarlo.
    """
    return html.Span(
        id=f"{target_id}-count",    # il JS cerca questo id per aggiornare il testo
        style={
            "background": C["accent"] + "22",
            "color": C["accent"],
            "border": f"1px solid {C['accent']}44",
            "borderRadius": "12px",
            "padding": "2px 10px",
            "fontSize": "0.78rem",
            "display": "none",   # nascosto di default, mostrato dal JS quando c'è un filtro
        },
    )


def empty_state(msg: str) -> html.Div:
    """
    Messaggio centrato "nessun dato disponibile".

    Mostrato quando una tab non ha dati da visualizzare
    (es. nessuna infrazione, nessun luogo, ecc.).
    """
    return html.Div(msg, style={
        "color": C["muted"],
        "padding": "48px 0",      # ampio spazio verticale per centrare visivamente
        "textAlign": "center",
        "fontSize": "0.9rem",
    })


def activity_legend() -> html.Div:
    """
    Legenda grafica dei 4 colori usati per le attività tachigrafo.

    Mostra un quadratino colorato affiancato dal nome dell'attività,
    ripetuto per ognuna delle 4 attività definite in ACT_COLORS.
    """
    return html.Div([
        # Per ogni attività/colore, crea una coppia (quadratino + testo)
        html.Span([
            html.Span("", style={
                "display": "inline-block",
                "width": "12px", "height": "12px",
                "background": col,              # quadratino colorato
                "borderRadius": "2px",
                "marginRight": "4px",
                "verticalAlign": "middle",      # allineato verticalmente al testo
            }),
            html.Span(act, style={"fontSize": "0.75rem", "color": C["muted"],
                                   "marginRight": "14px"}),
        ])
        for act, col in ACT_COLORS.items()   # itera su tutte le attività
    ], style={"marginBottom": "12px", "display": "flex", "flexWrap": "wrap"})


def info_row(label: str, value: str, mono: bool = False) -> html.Div:
    """
    Riga informativa "etichetta: valore" per le schede dettaglio.

    Usata nella tab Carta per mostrare i campi del conducente:
    "Numero carta: I100000333422003"
    "Data nascita:  29/09/1984"

    Parametri:
        label: etichetta (es. "Numero carta")
        value: valore (es. "I100000333422003"); se vuoto mostra "—"
        mono:  se True applica font monospaced al valore (per codici/numeri)
    """
    return html.Div([
        html.Div(label, className="info-label"),    # etichetta a sinistra
        html.Div(value or "—", className="info-value",
                 style=mono_style("0.9rem") if mono else {}),
    ], className="info-field")

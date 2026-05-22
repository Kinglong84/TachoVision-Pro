"""
views/tabs/carta.py
====================
Tab "Carta": informazioni complete della carta tachigrafica e del conducente.

Questa tab è una "scheda identità" della carta:
  - Dati anagrafici del conducente (nome, nascita, lingua)
  - Dati della patente di guida (numero, autorità rilasciante)
  - Dati della carta tachigrafica (numero, generazione, scadenza, emittente)
  - Informazioni sull'ultimo scarico dati e il file caricato
  - Tabelle di eventi, guasti e condizioni speciali (EF_EVENTS, EF_FAULTS, EF_SPECIFIC_CONDITIONS)

Layout: 3 colonne Bootstrap nella riga superiore (titolare | carta | download),
        poi eventi+guasti affiancati, poi condizioni speciali.
"""

from dash import html
import dash_bootstrap_components as dbc

from views.components import section, info_row, empty_state
from views.theme import C
from models.card_data import CardData


def _events_table(cd: CardData) -> html.Div:
    """
    Costruisce la tabella degli eventi tachigrafo (EF_EVENTS_DATA).

    Gli "eventi" sono situazioni anomale registrate automaticamente:
    es. guida senza carta inserita, conflitto dati, ecc.
    (max 50 eventi mostrati per performance).
    """
    if not cd.events:
        return html.Div("Nessun evento registrato.",
                        style={"color": C["muted"], "fontSize": "0.82rem", "padding": "8px 0"})

    rows = [html.Tr([
        # Orario inizio evento
        html.Td(e.begin_time, style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem", "whiteSpace": "nowrap"}),
        # Orario fine evento (o "—" se evento puntuale)
        html.Td(e.end_time or "—",   style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem", "whiteSpace": "nowrap"}),
        # Tipo evento (descrizione human-readable)
        html.Td(e.event_type, style={"fontSize": "0.82rem"}),
        # Targa del veicolo (o "—" se non applicabile)
        html.Td(e.vehicle or "—",    style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem"}),
    ]) for e in cd.events[:50]]   # max 50 eventi

    return html.Table([
        html.Thead(html.Tr([html.Th(h) for h in ["Inizio", "Fine", "Tipo evento", "Veicolo"]])),
        html.Tbody(rows),
    ], className="veh-table")


def _faults_table(cd: CardData) -> html.Div:
    """
    Costruisce la tabella dei guasti tachigrafo (EF_FAULTS_DATA).

    I "guasti" (fault) sono problemi hardware/software registrati dal sistema:
    es. problemi con il sensore di moto, errori di comunicazione VU-carta.
    Distinti dagli eventi (che sono comportamentali, non hardware).
    """
    if not cd.faults:
        return html.Div("Nessun guasto registrato.",
                        style={"color": C["muted"], "fontSize": "0.82rem", "padding": "8px 0"})

    rows = [html.Tr([
        html.Td(f.begin_time, style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem", "whiteSpace": "nowrap"}),
        html.Td(f.end_time or "—",   style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem", "whiteSpace": "nowrap"}),
        html.Td(f.fault_type, style={"fontSize": "0.82rem"}),
        html.Td(f.vehicle or "—",    style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem"}),
    ]) for f in cd.faults[:50]]

    return html.Table([
        html.Thead(html.Tr([html.Th(h) for h in ["Inizio", "Fine", "Tipo guasto", "Veicolo"]])),
        html.Tbody(rows),
    ], className="veh-table")


def _conditions_table(cd: CardData) -> html.Div:
    """
    Costruisce la tabella delle condizioni specifiche (EF_SPECIFIC_CONDITIONS).

    Le "condizioni specifiche" sono registrate dal conducente manualmente:
    es. traghetto, attività fuori EU, ecc.
    Permettono di escludere certi periodi dal calcolo delle infrazioni.
    """
    if not cd.specific_conditions:
        return html.Div("Nessuna condizione specifica registrata.",
                        style={"color": C["muted"], "fontSize": "0.82rem", "padding": "8px 0"})

    rows = [html.Tr([
        html.Td(sc.entry_time,     style={"fontFamily": "'DM Mono'", "fontSize": "0.78rem", "whiteSpace": "nowrap"}),
        html.Td(sc.condition_type, style={"fontSize": "0.82rem"}),
    ]) for sc in cd.specific_conditions[:50]]

    return html.Table([
        html.Thead(html.Tr([html.Th(h) for h in ["Data/Ora", "Condizione"]])),
        html.Tbody(rows),
    ], className="veh-table")


def render(cd: CardData) -> html.Div:
    """
    Costruisce la tab Carta con tutte le sezioni.

    'd' è abbreviazione di 'cd.driver' (DriverInfo) per comodità.
    info_row(label, value, mono=True) mostra "etichetta: valore" con font monospace.
    """
    d = cd.driver   # scorciatoia per DriverInfo

    return html.Div([

        # ── Riga 1: 3 colonne dati principali ─────────────────────────────────────
        dbc.Row([

            # Colonna 1: dati anagrafici + patente
            dbc.Col(section("Titolare",
                info_row("Cognome",  d.surname),
                info_row("Nome",     d.firstname),
                info_row("Nascita",  d.birth_date),
                # Lingua in maiuscolo (es. "it" → "IT")
                info_row("Lingua",   d.language.upper()),
                # Sottotitolo sezione patente
                html.Div("Patente di guida", className="section-title", style={"marginTop": "16px"}),
                info_row("Autorità", d.licence_authority),
                # mono=True: usa font monospaced per il numero patente
                info_row("Numero",   d.licence_number, mono=True),
            ), md=4),

            # Colonna 2: dati carta tachigrafica
            dbc.Col(section("Carta tachigrafica",
                info_row("Numero carta",    d.card_number, mono=True),
                # Generazione: "G1" (Reg. 3821/85) o "G2 (v1)" (Reg. 2016/799)
                info_row("Generazione",     d.generation),
                info_row("Indice rinnovo",  d.renewal_index),
                info_row("Indice sostituzione", d.replacement_index),
                html.Div("Emissione", className="section-title", style={"marginTop": "16px"}),
                # Nazione che ha emesso la carta (codice ISO, es. "IT")
                info_row("Stato membro",    d.issuing_nation),
                info_row("Autorità",        d.issuing_authority),
                info_row("Data emissione",  d.issue_date),
                info_row("Inizio validità", d.validity_begin),
                info_row("Scadenza",        d.expiry_date),
            ), md=4),

            # Colonna 3: info scarico e file
            dbc.Col(section("Download & File",
                # Data dell'ultimo scarico dati dalla carta (EF_CARD_DOWNLOAD)
                info_row("Ultimo download",     d.last_download),
                info_row("Download precedente", d.prev_download),
                info_row("Compatibilità",       d.generation),
                html.Div("File", className="section-title", style={"marginTop": "16px"}),
                info_row("Nome file",   d.filename, mono=True),
                # Dimensione del file DDD in byte (utile per debugging)
                info_row("Dimensione", f"{d.file_size} byte" if d.file_size else "—"),
            ), md=4),

        ], className="g-3"),

        # ── Riga 2: eventi + guasti ────────────────────────────────────────────────
        dbc.Row([
            dbc.Col(section(f"Eventi tachigrafo ({len(cd.events)})", _events_table(cd)), md=6),
            dbc.Col(section(f"Guasti tachigrafo ({len(cd.faults)})", _faults_table(cd)), md=6),
        ], className="g-3 mt-0"),

        # ── Riga 3: condizioni specifiche ─────────────────────────────────────────
        dbc.Row([
            dbc.Col(section(f"Condizioni specifiche ({len(cd.specific_conditions)})",
                            _conditions_table(cd)), md=12),
        ], className="g-3 mt-0"),

    ])

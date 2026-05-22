"""
controllers/render_controller.py
=================================
Controller principale: orchestratore del rendering della pagina.

Questo controller gestisce due callback fondamentali:
1. load_data()   → converte il file .DDD caricato in dati strutturati
2. render_page() → ridisegna la pagina ogni volta che cambiano i dati o la tab

Flusso di dati:
  Upload .DDD → load_data() → store-data (JSON nel browser)
  store-data o store-tab cambia → render_page() → aggiorna UI

La separazione tra caricamento (load_data) e rendering (render_page)
permette di navigare tra le tab senza ricaricare il file DDD.
"""

from dash import Input, Output, State, no_update, html
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from views.theme import C, SIDEBAR_GROUPS, btn_style
from views.components import driver_badge, alert_banner
from views.tabs import render_tab   # funzione che seleziona la view giusta per ogni tab


def _sidebar(active: str) -> html.Div:
    """
    Costruisce il pannello di navigazione laterale (sidebar).

    La sidebar mostra i gruppi di tab con i relativi bottoni.
    Il bottone della tab attiva ha la classe CSS "nav-item--active"
    (evidenziato visivamente).

    Parametro:
        active: tab_id della tab attualmente attiva (es. "attivita")

    Ritorna:
        html.Div con struttura: sidebar > nav > gruppi > bottoni
    """
    groups = []

    # Per ogni gruppo di tab (es. "Conformità", "Attività", ecc.)
    for group_name, items in SIDEBAR_GROUPS:

        # Crea i bottoni di navigazione per questo gruppo
        nav_items = [
            html.Button(
                [
                    html.Span(icon, className="nav-icon"),    # emoji icona
                    html.Span(label, className="nav-label"),  # testo etichetta
                ],
                id=f"tab-btn-{tid}",   # id univoco: "tab-btn-attivita", ecc.
                n_clicks=0,            # contatore click (usato dal nav_controller)
                # Classe CSS: aggiunge "--active" se questa è la tab corrente
                className="nav-item nav-item--active" if tid == active else "nav-item",
            )
            for tid, icon, label in items
        ]

        # Raggruppa le voci con un'etichetta di gruppo
        groups.append(html.Div([
            html.Div(group_name, className="nav-group-label"),  # es. "Conformità"
            *nav_items,
        ], className="nav-group"))

    # La sidebar include anche un bottone per comprimere/espandere
    return html.Div([
        html.Button("◀", className="sidebar-collapse-btn", title="Comprimi sidebar"),
        html.Nav(groups, className="sidebar-nav"),
    ], className="sidebar")


def _welcome_screen() -> html.Div:
    """
    Schermata di benvenuto mostrata quando nessun file DDD è caricato.

    Incoraggia l'utente a caricare un file o consultare l'archivio.
    Il design è centrato verticalmente con un pannello centrale.
    """
    return html.Div([
        html.Div([
            html.Div("🚛", style={"fontSize": "3.5rem", "marginBottom": "16px"}),
            html.H2("TachoVision Pro", style={
                "color": C["accent"], "marginBottom": "8px",
                "fontFamily": "'DM Mono'", "fontWeight": "500",
            }),
            html.P(
                "Seleziona un file .DDD per visualizzare le attività del conducente.",
                style={"color": C["muted"], "marginBottom": "28px", "fontSize": "0.95rem"},
            ),
            html.Div([
                # Zona drag & drop (solo visuale, il vero upload è nell'header)
                html.Div([
                    html.Span("📁  "),
                    html.Span("Carica file .DDD"),
                ], style={
                    "background": C["accent"] + "22",
                    "border": f"1.5px dashed {C['accent']}",
                    "borderRadius": "10px", "padding": "14px 28px",
                    "color": C["accent"], "fontSize": "0.95rem",
                    "marginBottom": "4px",
                }),
                html.P(
                    "Usa il pulsante Carica .DDD nella barra in alto",
                    style={"color": C["muted"], "fontSize": "0.8rem", "marginBottom": "20px"},
                ),
                html.Div("oppure", style={
                    "color": C["muted"], "marginBottom": "20px", "fontSize": "0.85rem",
                }),
                # Bottone per navigare all'archivio (gestito da nav_controller)
                html.Button(
                    "📚  Consulta Archivio",
                    id="btn-welcome-archive",
                    n_clicks=0,
                    style=btn_style(C["accent"]),
                ),
            ], style={"display": "flex", "flexDirection": "column", "alignItems": "center"}),
        ], style={
            "background": C["surface"],
            "border": f"1px solid {C['border']}",
            "borderRadius": "16px",
            "padding": "48px 40px",
            "textAlign": "center",
            "maxWidth": "460px",
        }),
    ], style={
        "display": "flex",
        "justifyContent": "center",   # centra orizzontalmente
        "alignItems": "center",       # centra verticalmente
        "minHeight": "55vh",          # occupa almeno il 55% dell'altezza della finestra
    })


def register(app):
    """Registra i callback di rendering sull'istanza Dash."""

    # ── Callback 1a: lettura carta tachigrafica USB ───────────────────────────────
    @app.callback(
        Output("store-data", "data", allow_duplicate=True),
        Input("btn-read-card", "n_clicks"),
        prevent_initial_call=True,
    )
    def load_from_card(n_clicks):
        """
        Legge la carta dal primo lettore USB, parsa i dati e li salva nello store.
        Passa i byte grezzi in _raw_bytes (base64) così auto_save_ddd li archivia.
        """
        import base64
        from datetime import datetime
        from models.parser import parse_ddd
        from models.analytics import enrich
        from services.card_service import PYSCARD_OK, list_readers, get_status, read_card

        if not n_clicks:
            raise PreventUpdate

        # Verifica lettore disponibile
        if not PYSCARD_OK:
            from controllers.data_controller import make_demo
            demo = make_demo()
            demo.errors = ["pyscard non installato. Esegui: pip install pyscard"]
            return demo.to_dict()

        readers = list_readers()
        if not readers:
            from controllers.data_controller import make_demo
            demo = make_demo()
            demo.errors = ["Nessun lettore USB rilevato. Collega il lettore e riprova."]
            return demo.to_dict()

        try:
            status = get_status()
            reader_name = next(
                (r["name"] for r in status.get("readers", []) if r.get("card")), None
            )
            if not reader_name:
                from controllers.data_controller import make_demo
                demo = make_demo()
                demo.errors = [f"Lettori trovati: {readers}. Inserisci la carta e riprova."]
                return demo.to_dict()

            # Leggi i byte grezzi dalla carta
            raw_bytes = read_card(reader_name)

            # Parsa e arricchisci
            cd = parse_ddd(raw_bytes)
            cd = enrich(cd)
            cd.demo = False
            cd.driver.last_download = datetime.now().strftime("%d/%m/%Y %H:%M")
            cd.driver.file_size = str(len(raw_bytes))

            d = cd.to_dict()
            # Encode base64 dei byte grezzi → auto_save_ddd li salva su disco e in archivio
            d["_raw_bytes"] = base64.b64encode(raw_bytes).decode("ascii")
            d["_source"] = "smartcard"
            return d

        except Exception as e:
            from controllers.data_controller import make_demo
            demo = make_demo()
            demo.errors = [f"Errore lettura carta: {e}"]
            return demo.to_dict()

    # ── Callback 1b: caricamento file .DDD ────────────────────────────────────────
    @app.callback(
        Output("store-data", "data"),       # salva il CardData serializzato nello Store
        Input("upload-ddd", "contents"),    # triggera quando l'utente carica un file
        State("upload-ddd", "filename"),    # nome del file (non triggera il callback)
        prevent_initial_call=True,
    )
    def load_data(contents, filename):
        """
        Decodifica il file .DDD caricato e lo salva in store-data.

        dcc.Upload fornisce il file come stringa Base64:
        "data:application/octet-stream;base64,AABBCC..."
        La parte prima della virgola è il MIME type; dopo la virgola ci sono
        i byte del file codificati in Base64.

        Salva anche i byte grezzi in _raw_bytes per l'archivio locale.
        """
        from controllers.data_controller import from_upload

        if not contents:
            raise PreventUpdate   # nessun file caricato

        # from_upload decodifica Base64, fa parsing DDD, applica analytics
        cd = from_upload(contents, filename)
        d = cd.to_dict()   # serializza per lo Store (JSON)

        # Aggiunge i byte grezzi allo Store (per salvarli nell'archivio)
        if not cd.errors:
            try:
                # contents è "data:...;base64,DATI" → prende solo "DATI"
                _, b64 = contents.split(",", 1)
                d["_raw_bytes"] = b64          # byte grezzi in Base64
                d["_source"] = "upload"        # provenienza (upload vs smartcard)
            except Exception:
                pass

        return d   # salvato in store-data → triggera render_page()

    # ── Callback 2: rendering della pagina ────────────────────────────────────────
    @app.callback(
        Output("driver-bar",  "children"),   # barra conducente in cima
        Output("sidebar-nav", "children"),   # pannello di navigazione
        Output("tab-content", "children"),   # contenuto principale della tab
        Input("store-data",      "data"),    # triggera quando cambiano i dati
        Input("store-tab",       "data"),    # triggera quando cambia la tab
        Input("store-gnss-date", "data"),    # triggera quando cambia il filtro GPS
    )
    def render_page(raw, active_tab, gnss_date):
        """
        Ridisegna l'intera pagina ogni volta che cambiano i dati o la tab.

        Questo callback ha due Input: viene chiamato sia quando viene caricato
        un nuovo file DDD (store-data cambia) sia quando l'utente naviga
        tra le tab (store-tab cambia). In entrambi i casi, ridisegna tutto.

        Se raw è None/vuoto (nessun file caricato), mostra la welcome screen.
        Altrimenti mostra la tab selezionata con i dati reali.
        """
        active_tab = active_tab or "panoramica"   # default alla tab panoramica

        if not raw:
            sidebar = _sidebar(active_tab)
            # Archivio e condivisione non richiedono un file caricato
            if active_tab in ("archivio", "condivisione"):
                content = render_tab(active_tab, None)
                return html.Div(), sidebar, content
            return html.Div(), sidebar, _welcome_screen()

        # Deserializza il CardData dallo Store (da dict JSON a oggetto Python)
        cd = CardData.from_dict(raw)

        # Crea i banner di errore (mostrati se il parsing ha avuto problemi)
        banners = [alert_banner(f"⚠️  {err}", color="#F59E0B") for err in cd.errors]

        # Barra del conducente (mostra nome, numero carta, ecc.)
        badge = html.Div([
            *banners,   # eventuali banner di errore sopra la barra
            driver_badge(cd.driver.__dict__, False),
        ], style={"margin": "16px 24px 0"},
           className="driver-badge-outer")

        # Sidebar con la tab corrente evidenziata
        sidebar = _sidebar(active_tab)

        # Rendering della tab richiesta (attivita, infrazioni, veicoli, ecc.)
        try:
            content = render_tab(active_tab, cd, gnss_date=gnss_date)
        except Exception as e:
            # In caso di errore nella tab, mostra un messaggio invece di crashare
            content = html.Div(
                f"Errore nel rendering della tab: {e}",
                style={"color": C["guida"], "padding": "24px"},
            )

        return badge, sidebar, content

    # ── Callback 3: filtro finestra temporale attività ────────────────────────────
    @app.callback(
        Output("blocks-attivita",    "children"),
        Output("attivita-days-count", "children"),
        Input("input-attivita-from", "value"),
        Input("input-attivita-to",   "value"),
        State("store-data",          "data"),
        prevent_initial_call=True,
    )
    def filter_attivita_range(date_from, date_to, raw):
        """
        Aggiorna le card attività quando l'utente cambia il range di date.

        Filtra cd.activities al periodo selezionato e ricostruisce i blocchi.
        """
        if not raw:
            raise PreventUpdate

        cd = CardData.from_dict(raw)
        days = cd.activities

        if date_from:
            days = [d for d in days if d.date >= date_from]
        if date_to:
            days = [d for d in days if d.date <= date_to]

        shown = list(reversed(days))

        from views.tabs.attivita import _build_blocks
        gnss_dates = {g.date for g in cd.gnss_records} if cd.gnss_records else set()
        blocks = _build_blocks(shown, cd, gnss_dates=gnss_dates)
        count_label = f"{len(shown)} giorni"
        return blocks, count_label

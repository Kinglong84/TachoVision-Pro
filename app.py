"""
app.py — TachoVision Pro (architettura MVC)
==========================================
Questo è il PUNTO DI INGRESSO dell'applicazione: il primo file che viene
eseguito quando si avvia il server.

Responsabilità di questo file:
1. Creare l'applicazione Dash (il "motore" web)
2. Definire il layout HTML scheletro della pagina
3. Registrare i controller (che gestiscono gli eventi utente)
4. Avviare il server web

NON contiene logica di business né rendering di componenti.
La logica è separata nei moduli models/, views/, controllers/, services/.

Architettura MVC (Model-View-Controller):
  Model      → models/      — dati e logica di dominio
  View       → views/       — componenti visivi Dash/HTML
  Controller → controllers/ — gestione eventi e coordinamento
"""

# ── Logging base ─────────────────────────────────────────────────────────────────
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# ── Importazioni framework ────────────────────────────────────────────────────────
import dash
# Dash è il framework Python che permette di creare app web reattive
# usando solo Python (senza scrivere JavaScript a mano).

import dash_bootstrap_components as dbc
# Bootstrap è un framework CSS che fornisce layout a griglia e componenti
# grafici pronti all'uso (colonne, card, bottoni stilizzati, ecc.).

from dash import dcc, html
# dcc = Dash Core Components: componenti interattivi (Input, Upload, Graph, Store, ecc.)
# html = Componenti HTML Dash: rappresentano tag HTML (Div, Span, Button, ecc.)

from views.theme import C, btn_style, EXTERNAL_STYLESHEETS
# C = dizionario con i colori dell'app (palette dark)
# btn_style = funzione che genera stili CSS per i bottoni
# EXTERNAL_STYLESHEETS = lista di URL di fogli di stile esterni (Bootstrap, Google Fonts)


# ── Creazione dell'applicazione Dash ─────────────────────────────────────────────
app = dash.Dash(
    __name__,                           # identifica il modulo corrente per trovare gli asset
    external_stylesheets=EXTERNAL_STYLESHEETS,   # CSS esterni da caricare (Bootstrap, font)
    title="TachoVision Pro",            # titolo mostrato nel browser (tab/barra del titolo)
    suppress_callback_exceptions=True,  # non generare errori per componenti creati dinamicamente
)

# 'server' è l'oggetto Flask sottostante a Dash.
# Serve per il deployment in produzione con gunicorn/waitress (server WSGI).
server = app.server


# ── Layout della pagina ──────────────────────────────────────────────────────────
# Il layout Dash è un albero di componenti Python che rappresenta l'HTML della pagina.
# Ogni componente ha un 'id' univoco che i callback usano per riferirsi a lui.
# 'html.Div' è come un <div> in HTML; 'dcc.Store' è un contenitore dati invisibile.
app.layout = html.Div([

    # ── Storage invisibili (dcc.Store) ────────────────────────────────────────────
    # dcc.Store è un componente invisibile che salva dati nel browser dell'utente.
    # Funziona come localStorage: i dati persistono durante la sessione ma non
    # vengono trasmessi finché non servono.
    dcc.Store(id="store-data"),          # contiene il CardData serializzato (il file DDD parsato)
    dcc.Store(id="store-tab", data="panoramica"),  # tab attiva al momento (default: panoramica)
    dcc.Store(id="store-archive"),              # segnale per aggiornare l'archivio locale
    dcc.Store(id="store-archive-selected", data=[]),  # file selezionati per export
    dcc.Store(id="store-card-status"),         # stato lettore (per polling)
    dcc.Store(id="store-gnss-date", data=None),  # data filtro mappa GPS (YYYY-MM-DD)

    # ── Download invisibili (dcc.Download) ────────────────────────────────────────
    # dcc.Download triggera il download di un file nel browser quando viene "riempito"
    # da un callback. Non è visibile nella pagina.
    dcc.Download(id="download-csv"),         # scarica il CSV delle attività
    dcc.Download(id="download-pdf-act"),     # scarica il PDF delle attività
    dcc.Download(id="download-pdf-viol"),    # scarica il PDF delle infrazioni
    dcc.Download(id="download-pdf-week"),    # scarica il PDF del riepilogo settimanale
    dcc.Download(id="download-ddd-file"),    # scarica file .DDD dall'archivio

    # ── Header superiore (barra fissa) ────────────────────────────────────────────
    # La barra in cima alla pagina, visibile sempre (CSS: position: sticky).
    html.Div([

        # -- Logo TachoVision --
        html.Div([
            html.Span("🚛", style={"fontSize": "1.4rem"}),
            # "DM Mono" è un font monospaced (larghezza fissa per ogni carattere)
            html.Span("TACHOVISION",
                      style={"fontFamily": "'DM Mono'", "fontWeight": "500"}),
            # Badge "PRO" con colore accent semitrasparente
            html.Span("PRO", style={
                "background": C["accent"] + "22",   # colore + "22" = 13% opacità (hex)
                "border":     f"1px solid {C['accent']}44",  # bordo 27% opacità
                "color":      C["accent"],
                "fontSize":   "0.65rem",
                "padding":    "2px 8px",
                "borderRadius": "2px",
                "letterSpacing": "2px",   # spazio tra le lettere
            }),
        ], style={"display": "flex", "alignItems": "center", "gap": "10px",
                  "color": C["accent"]}),

        # -- Campo di ricerca globale --
        # Questo input ha un attributo HTML personalizzato 'data-filter-table'
        # che viene letto dallo script JavaScript assets/filter.js per
        # filtrare dinamicamente i contenuti della tab.
        html.Div(
            dcc.Input(
                id="global-search",
                type="text",
                placeholder="🔍  Cerca in tutta la pagina...",
                debounce=False,          # aggiorna ad ogni tasto (senza attendere)
                className="tv-filter-input",
                style={
                    "background": C["surface"], "border": f"1px solid {C['border']}",
                    "color": C["text"], "borderRadius": "8px",
                    "padding": "8px 16px", "fontSize": "0.84rem",
                    "width": "260px", "outline": "none",
                },
            ),
            **{"data-filter-table": "tab-content"},   # attributo HTML usato dal JS
            style={"flex": "1", "maxWidth": "300px"},
        ),

        # -- Zona azioni (upload + download) --
        html.Div([

            # Bottone lettura carta tachigrafica tramite lettore USB
            html.Button(
                [html.Span("🪪 "), html.Span("Leggi Carta", style={"fontSize": "0.85rem"})],
                id="btn-read-card",
                n_clicks=0,
                style={
                    "border": f"1.5px solid {C['accent']}88",
                    "borderRadius": "8px", "padding": "9px 14px",
                    "cursor": "pointer", "background": C["surface"],
                    "color": C["accent"], "display": "flex",
                    "alignItems": "center", "gap": "6px",
                    "fontSize": "0.85rem",
                },
            ),

            # Upload file .DDD
            # dcc.Upload è il componente Dash che gestisce il drag & drop
            # o la selezione tramite finestra di dialogo del file system.
            dcc.Upload(
                id="upload-ddd",
                children=html.Div([
                    html.Span("📁 "),
                    html.Span("Carica .DDD", style={"fontSize": "0.85rem"}),
                ], style={
                    "border": f"1.5px dashed {C['border']}",
                    "borderRadius": "8px", "padding": "9px 14px",
                    "cursor": "pointer", "background": C["surface"],
                    "color": C["muted"], "display": "flex",
                    "alignItems": "center", "gap": "6px",
                }),
                accept=".ddd,.DDD",          # solo file con estensione .ddd o .DDD
                max_size=50 * 1024 * 1024,   # dimensione massima: 50 MB
            ),

            # Bottoni di download (CSV e 3 tipi di PDF)
            # Ogni bottone ha un id univoco; i controller intercettano i click
            # tramite callback e triggherano il download corrispondente.
            html.Div([
                html.Button("📥 CSV",            id="btn-csv",       n_clicks=0,
                            style=btn_style(C["accent"])),
                html.Button("📄 PDF Attività",   id="btn-pdf-act",   n_clicks=0,
                            style=btn_style("#C084FC")),    # viola
                html.Button("📄 PDF Infrazioni", id="btn-pdf-viol",  n_clicks=0,
                            style=btn_style("#C084FC")),
                html.Button("📄 PDF Riepilogo",  id="btn-pdf-week",  n_clicks=0,
                            style=btn_style("#C084FC")),
            ], style={"display": "flex", "gap": "6px"}),

        ], style={"display": "flex", "gap": "10px",
                  "alignItems": "center", "flexWrap": "wrap"}),

    ], className="app-header"),   # la classe CSS "app-header" è definita in assets/


    # ── Corpo dell'app: sidebar + contenuto principale ──────────────────────────
    # Layout a due colonne: navigazione laterale + area principale.
    html.Div([

        # -- Sidebar di navigazione --
        # Questa div viene RIEMPITA dinamicamente dal render_controller
        # in base alla tab attiva. Non contiene HTML fisso qui.
        html.Div(id="sidebar-nav"),

        # -- Area principale --
        html.Div([
            # Barra del conducente (nome, numero carta): riempita dal controller
            html.Div(id="driver-bar"),
            # Contenuto della tab corrente: riempito dal controller
            html.Div(
                html.Div(id="tab-content"),
                style={"padding": "20px 24px"},   # margine interno
            ),
        ], className="main-content"),   # classe CSS per il pannello principale

    ], className="app-body"),   # classe CSS per il layout body (flexbox)

], style={
    "minHeight": "100vh",    # l'app occupa almeno tutta l'altezza della finestra
    "background": C["bg"],   # sfondo scuro della palette
    "color": C["text"],      # colore testo predefinito
    "fontFamily": "'Space Grotesk', sans-serif",   # font principale dell'app
})


# ── Registrazione dei controller ─────────────────────────────────────────────────
# I controller sono moduli Python che definiscono i callback Dash.
# Un "callback" è una funzione Python che viene chiamata automaticamente
# ogni volta che un componente cambia (click, input, ecc.).
# 'register(app)' passa l'istanza Dash al controller che vi attacca i callback.
from controllers import render_controller, nav_controller, export_controller, archive_controller, share_controller, gps_controller

render_controller.register(app)    # gestisce rendering tab e upload
nav_controller.register(app)       # gestisce click sui bottoni sidebar
export_controller.register(app)    # gestisce download CSV e PDF
archive_controller.register(app)   # gestisce archivio file DDD locali
share_controller.register(app)     # gestisce invio email e upload cloud
gps_controller.register(app)       # gestisce navigazione interattiva mappa GPS


# ── Avvio del server web ─────────────────────────────────────────────────────────
# Questo blocco viene eseguito SOLO se il file viene lanciato direttamente
# (python app.py), non quando viene importato da un altro modulo.
if __name__ == "__main__":
    import sys
    # Forza l'output della console a UTF-8 per visualizzare emoji e caratteri
    # italiani (accenti, ecc.) anche su Windows con codepage cp1252.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n" + "─" * 60)
    print("  TachoVision Pro  --  architettura MVC")
    print("─" * 60)
    print("  http://localhost:8050")
    print("─" * 60 + "\n")
    # debug=False: non mostrare errori dettagliati nel browser (più sicuro)
    # host="0.0.0.0": accetta connessioni da qualsiasi indirizzo di rete
    # port=8050: porta TCP su cui risponde il server
    app.run(debug=False, host="0.0.0.0", port=8050)  # nosec B104 — LAN locale, intenzionale

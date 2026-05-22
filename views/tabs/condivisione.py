"""
views/tabs/condivisione.py
===========================
Tab "Condivisione": invia i file tachigrafo via email o caricali su cloud.

Due sezioni:
  1. EMAIL: apre il client email locale (Outlook, Thunderbird, Mail...)
     con i file già allegati. NON invia email direttamente.
     Usa il protocollo mailto: del sistema operativo.

  2. CLOUD: carica il file .DDD su Google Drive, OneDrive o Dropbox.
     Ogni provider ha un flusso di autenticazione diverso:
       - Google Drive: OAuth2 con file credentials.json (da Google Cloud Console)
       - OneDrive: Device Code Flow (Microsoft) — genera un codice da inserire online
       - Dropbox: Personal Access Token (da dropbox.com/developers)

ARCHITETTURA:
  Come archivio.py, questa tab dipende dal controller (share_controller.py)
  per tutta la logica. render() costruisce solo la struttura HTML statica
  con gli id dei componenti interattivi. Il controller gestisce i callback.

PROVIDER CLOUD SUPPORTATI:
  I servizi cloud sono implementati in services/cloud_service.py.
  Ogni classe (GoogleDriveService, OneDriveService, DropboxService) espone:
    - is_authenticated() → bool
    - is_configured() → bool (es. file credentials.json presente)
    - get_account_info() → str (es. "mario.rossi@gmail.com")
"""

from dash import html, dcc
import dash_bootstrap_components as dbc

from views.theme import C, btn_style
from views.components import section


# ── Colori dei brand cloud ────────────────────────────────────────────────────
# Usati per i bordi e i pulsanti di ogni provider card.
# I colori ufficiali dei brand garantiscono che l'utente riconosca il servizio.
PROVIDER_COLORS = {
    "Google Drive": "#EA4335",   # rosso Google
    "OneDrive":     "#0078D4",   # blu Microsoft
    "Dropbox":      "#0061FF",   # blu Dropbox
}

PROVIDER_ICONS = {
    "Google Drive": "📗",
    "OneDrive":     "📘",
    "Dropbox":      "📦",
}


def _provider_card(name: str, authenticated: bool, note: str = "") -> html.Div:
    """
    Costruisce la card per un singolo provider cloud.

    Parametri:
        name:          nome del provider (es. "Google Drive")
        authenticated: True se l'utente ha già effettuato il login
        note:          testo aggiuntivo sotto lo stato (es. info sull'account)

    La card contiene:
      - Header con icona, nome e stato connessione
      - Pulsante "Connetti" / "Disconnetti" (cambia in base a `authenticated`)
      - Pulsante "Carica .DDD" (disabilitato se non autenticato)

    I pulsanti usano id pattern dict per il pattern matching nel controller:
      id={"type": "btn-cloud-auth",   "index": name}
      id={"type": "btn-cloud-upload", "index": name}
    """
    # Colore e icona del provider corrente
    color = PROVIDER_COLORS.get(name, C["accent"])
    icon  = PROVIDER_ICONS.get(name, "☁️")

    return html.Div([

        # ── Header card: icona + nome + stato ──────────────────────────────────
        html.Div([
            html.Span(icon, style={"fontSize": "1.8rem"}),
            html.Div([
                html.Div(name, style={"fontWeight": "600", "fontSize": "1rem"}),
                # Stato connessione: verde "Connesso" o grigio "Non connesso"
                # Se c'è una nota (es. info account), viene aggiunta dopo " — "
                html.Div(
                    ("✅ Connesso" if authenticated else "⚪ Non connesso")
                    + (f" — {note}" if note else ""),
                    style={"fontSize": "0.75rem",
                           "color": C["success"] if authenticated else C["muted"],
                           "marginTop": "2px"},
                ),
            ], style={"marginLeft": "12px"}),
        # display:flex + alignItems:center = elementi affiancati, centrati verticalmente
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "12px"}),

        # ── Pulsante autenticazione ─────────────────────────────────────────────
        # Se già connesso: mostra "Disconnetti" in grigio
        # Se non connesso: mostra "Connetti account" nel colore del provider
        # **dict: operatore "unpacking" — espande il dizionario btn_style() come parametri CSS
        html.Button(
            "🔓 Disconnetti" if authenticated else "🔗 Connetti account",
            id={"type": "btn-cloud-auth", "index": name},
            n_clicks=0,
            style={**btn_style(C["muted"] if authenticated else color),
                   "width": "100%", "marginBottom": "8px"},
        ),

        # ── Pulsante upload ─────────────────────────────────────────────────────
        # disabled=True: non cliccabile se non autenticato (grayed out + cursor:not-allowed)
        html.Button(
            f"☁️ Carica .DDD su {name}",
            id={"type": "btn-cloud-upload", "index": name},
            n_clicks=0,
            disabled=not authenticated,   # disabilita se non connesso
            style={**btn_style(color),
                   "width": "100%",
                   "opacity": "1" if authenticated else "0.35",     # semi-trasparente se disabilitato
                   "cursor": "pointer" if authenticated else "not-allowed"},
        ),

    # Stile contenitore card: sfondo scuro, bordo colorato del provider, angoli arrotondati
    ], style={
        "background": C["card"],
        "border": f"1px solid {color}44",   # "+44" = colore al 27% di opacità (hex)
        "borderRadius": "10px",
        "padding": "18px",
    })


def render(cd=None) -> html.Div:
    """
    Costruisce la tab Condivisione completa.

    Il parametro `cd` non viene usato (ma è richiesto dall'interfaccia
    comune delle tab — vedi render_controller.py).

    NOTA: i servizi cloud e l'email vengono importati DENTRO la funzione
    (import locale) per evitare che errori di importazione (es. librerie
    mancanti come msal, dropbox) blocchino l'avvio dell'intera app.
    """
    # Importazioni locali: se una libreria manca, solo questa tab fallisce,
    # non tutta l'applicazione
    from services.cloud_service import GoogleDriveService, OneDriveService, DropboxService
    from services.email_service import EmailConfig

    # Istanzia i servizi cloud e legge lo stato di autenticazione
    gd  = GoogleDriveService()    # Google Drive
    od  = OneDriveService()       # OneDrive (Microsoft)
    dbx = DropboxService()        # Dropbox
    cfg = EmailConfig.load()      # Configurazione email (destinatari salvati)

    # ── Sezione Email ──────────────────────────────────────────────────────────
    email_section = section("📧 Invia tramite client email locale",

        # Banner informativo: spiega che non si tratta di un SMTP diretto
        html.Div(
            "Salva i file selezionati e apre il tuo client email (Outlook, Thunderbird, "
            "Mail…) con i file già allegati. Non viene inviata nessuna email automaticamente.",
            style={"fontSize": "0.84rem", "color": C["muted"], "marginBottom": "16px",
                   "background": C["surface"], "borderRadius": "6px",
                   "padding": "10px 14px",
                   # Bordo sinistro colorato = stile "info callout"
                   "borderLeft": f"3px solid {C['accent']}"},
        ),

        dbc.Row([

            # Colonna sinistra: input destinatari email
            dbc.Col([
                # Label piccola sopra l'input (stile "micro-label")
                html.Div("Destinatari (opzionale — separati da virgola)",
                         style={"fontSize": "0.72rem", "color": C["muted"],
                                "textTransform": "uppercase", "letterSpacing": "1px",
                                "marginBottom": "6px"}),
                # Campo testo per i destinatari
                # value=...: pre-popola con i destinatari salvati nelle impostazioni
                dcc.Input(
                    id="email-recipients",
                    value=", ".join(cfg.default_recipients),   # lista → stringa separata da virgola
                    placeholder="responsabile@azienda.it, trasportatore@azienda.it",
                    style={
                        "width": "100%", "background": C["surface"],
                        "border": f"1px solid {C['border']}", "color": C["text"],
                        "borderRadius": "6px", "padding": "9px 12px",
                        "fontSize": "0.82rem", "fontFamily": "'DM Mono', monospace",
                        "marginBottom": "6px",
                    },
                ),
                # Pulsante per salvare i destinatari come predefiniti nel file di config
                html.Button("💾 Salva come predefiniti", id="btn-save-recipients",
                            n_clicks=0,
                            style={**btn_style(C["muted"]), "fontSize": "0.75rem",
                                   "padding": "5px 12px"}),
                # Feedback al salvataggio (es. "✅ Salvato")
                html.Div(id="recipients-save-result",
                         style={"fontSize": "0.75rem", "marginTop": "4px"}),
            ], md=6),

            # Colonna destra: checklist allegati
            dbc.Col([
                html.Div("File da allegare",
                         style={"fontSize": "0.72rem", "color": C["muted"],
                                "textTransform": "uppercase", "letterSpacing": "1px",
                                "marginBottom": "8px"}),
                # Checklist Dash: l'utente seleziona quali file allegare all'email.
                # options: lista di {"label": ..., "value": ...}
                # value: valori selezionati di default ("ddd" e "pdf_viol")
                dcc.Checklist(
                    id="email-attachments",
                    options=[
                        {"label": "  📁 File .DDD originale",       "value": "ddd"},
                        {"label": "  📄 PDF Attività",               "value": "pdf_act"},
                        {"label": "  📄 PDF Infrazioni",             "value": "pdf_viol"},
                        {"label": "  📄 PDF Riepilogo settimanale",  "value": "pdf_week"},
                        {"label": "  📊 CSV Attività",               "value": "csv"},
                    ],
                    value=["ddd", "pdf_viol"],   # selezione predefinita
                    inputStyle={"marginRight": "6px"},
                    style={"fontSize": "0.85rem", "color": C["text"],
                           "lineHeight": "2.2"},   # interlinea generosa per leggibilità
                ),
            ], md=6),

        ], className="g-3"),

        # Pulsante principale: apre il mailto: con i file allegati
        html.Button(
            "📧  Apri client email con allegati",
            id="btn-open-mail-client",
            n_clicks=0,
            style={
                **btn_style(C["accent"]),
                "width": "100%", "marginTop": "16px",
                "padding": "13px", "fontSize": "0.95rem",
                "fontWeight": "600", "textAlign": "center",
            },
        ),

        # Area risultato: mostra il path dei file salvati, eventuali errori
        # whiteSpace:pre-wrap: preserva i newline nel testo del controller
        html.Div(id="email-open-result",
                 style={"marginTop": "12px", "fontSize": "0.82rem",
                        "whiteSpace": "pre-wrap", "lineHeight": "1.6"}),
    )

    # ── Sezione Cloud ──────────────────────────────────────────────────────────
    # Legge le info account Dropbox (es. email utente) per mostrare nella nota
    dbx_info = dbx.get_account_info()

    cloud_section = section("☁️ Archiviazione Cloud",

        # Banner descrittivo
        html.Div(
            "I file .DDD vengono caricati nella cartella TachoVision del tuo storage cloud.",
            style={"fontSize": "0.84rem", "color": C["muted"], "marginBottom": "16px",
                   "background": C["surface"], "borderRadius": "6px",
                   "padding": "10px 14px",
                   "borderLeft": f"3px solid {C['riposo']}"},   # bordo verde-azzurro
        ),

        # ── Riga 3 card provider affiancate ──────────────────────────────────
        dbc.Row([
            # Google Drive: mostra se credentials.json è presente
            dbc.Col(_provider_card(
                "Google Drive", gd.is_authenticated(),
                note="credentials.json " + ("✅" if gd.is_configured() else "❌ mancante"),
            ), md=4),
            # OneDrive: usa Device Code Flow (non richiede file di configurazione)
            dbc.Col(_provider_card(
                "OneDrive", od.is_authenticated(),
                note="login con account Microsoft",
            ), md=4),
            # Dropbox: mostra l'email dell'account se disponibile
            dbc.Col(_provider_card(
                "Dropbox", dbx.is_authenticated(),
                note=dbx_info or "inserisci token personale",   # fallback se non autenticato
            ), md=4),
        ], className="g-3 mb-3"),

        # ── Input token Dropbox ────────────────────────────────────────────────
        # Dropbox usa un Personal Access Token: l'utente lo genera su dropbox.com/developers
        # type="password" → il testo viene nascosto con ••••• per sicurezza
        html.Div([
            html.Div("Token Dropbox (Personal Access Token da dropbox.com/developers)",
                     style={"fontSize": "0.72rem", "color": C["muted"],
                            "textTransform": "uppercase", "letterSpacing": "1px",
                            "marginBottom": "6px"}),
            dbc.Row([
                # Input per il token (tipo password: testo nascosto)
                dbc.Col(dcc.Input(id="dropbox-token-input", type="password",
                                   placeholder="sl.xxxxxx...",
                                   style={"width": "100%", "background": C["surface"],
                                          "border": f"1px solid {C['border']}",
                                          "color": C["text"], "borderRadius": "6px",
                                          "padding": "8px 12px", "fontSize": "0.82rem",
                                          "fontFamily": "'DM Mono', monospace"}), md=9),
                # Pulsante salva token
                dbc.Col(html.Button("✅ Salva", id="btn-dropbox-token", n_clicks=0,
                                     style=btn_style("#0061FF")), md=3),
            ], className="g-2"),
            # Feedback al salvataggio del token
            html.Div(id="dropbox-token-result",
                     style={"marginTop": "6px", "fontSize": "0.8rem"}),
        ], style={"marginBottom": "16px"}),

        # ── Pannelli di autenticazione dinamici ────────────────────────────────
        # Questi div vengono popolati dal controller quando l'utente clicca "Connetti":
        # - gdrive: mostra il link OAuth2 per autorizzare l'app Google
        # - onedrive: mostra il codice device (da inserire su microsoft.com/devicelogin)
        html.Div(id="gdrive-auth-panel"),
        html.Div(id="onedrive-device-code-panel"),

        # ── Carica su tutti i provider connessi ───────────────────────────────
        html.Button(
            "☁️  Carica su tutti i provider connessi",
            id="btn-cloud-upload-all", n_clicks=0,
            style={**btn_style(C["riposo"]),
                   "marginTop": "8px", "padding": "10px 20px"},
        ),
        # Risultato upload per singolo provider (aggiornato da btn-cloud-upload)
        html.Div(id="cloud-upload-result",  style={"marginTop": "10px",
                                                     "fontSize": "0.82rem",
                                                     "whiteSpace": "pre-wrap"}),
        # Risultato upload su tutti i provider (aggiornato da btn-cloud-upload-all)
        html.Div(id="cloud-upload-all-result", style={"marginTop": "6px",
                                                        "fontSize": "0.82rem",
                                                        "whiteSpace": "pre-wrap"}),
    )

    # Assembla le due sezioni nell'ordine: prima email, poi cloud
    return html.Div([email_section, cloud_section])

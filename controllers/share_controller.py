"""
controllers/share_controller.py
=================================
Callback per la condivisione del file .DDD e dei report via email e cloud.

FUNZIONALITÀ:
  1. open_email:          salva i file allegati in /tmp e apre il client email locale
  2. save_recipients:     salva i destinatari predefiniti nel file di configurazione
  3. save_dropbox_token:  valida e salva il Personal Access Token Dropbox
  4. cloud_auth:          gestisce connect/disconnect per Google Drive e OneDrive
                          (mostra i pannelli di autenticazione OAuth2 / Device Code)
  5. gdrive_confirm:      completa l'autenticazione Google Drive con il codice ricevuto
  6. od_confirm:          completa l'autenticazione OneDrive via Device Code Flow
  7. cloud_upload_single: carica il .DDD su un singolo provider cloud
  8. cloud_upload_all:    carica il .DDD su tutti i provider cloud connessi

FLUSSI DI AUTENTICAZIONE CLOUD:
  Google Drive (OAuth2):
    1. cloud_auth ottiene l'URL di autorizzazione (get_auth_url)
    2. L'utente apre il link, autorizza, riceve un codice
    3. gdrive_confirm invia il codice a complete_auth() → salva il token

  OneDrive (Device Code Flow):
    1. cloud_auth avvia il flow (start_device_flow) → ottiene codice utente
    2. L'utente va su microsoft.com/devicelogin e inserisce il codice
    3. od_confirm chiama complete_device_flow() → verifica e salva il token

  Dropbox (Personal Access Token):
    - Nessun OAuth: l'utente genera il token su dropbox.com/developers
    - save_dropbox_token valida il token e lo salva
"""

from __future__ import annotations
import json
from typing import List

from dash import Input, Output, State, dcc, html, no_update, ALL, callback_context
from dash.exceptions import PreventUpdate

from models.card_data import CardData
from services.email_service import (
    EmailConfig,              # configurazione email (destinatari salvati)
    build_email_content,      # genera subject e body dell'email
    save_attachments_to_temp, # salva i file allegati in una cartella temporanea
    open_mail_client,         # apre il client email locale con mailto:
)
from services.cloud_service import (
    GoogleDriveService,   # servizio Google Drive (OAuth2)
    OneDriveService,      # servizio OneDrive (Microsoft, Device Code Flow)
    DropboxService,       # servizio Dropbox (Personal Access Token)
    upload_to_all,        # carica su tutti i provider autenticati in un colpo solo
)
from services.archive_service import get_archive
from views.theme import C


# ── Helper: costruisci la lista degli allegati ────────────────────────────────
def _build_attachments(cd: CardData, choices: List[str]) -> List[tuple]:
    """
    Costruisce la lista degli allegati da includere nell'email o nell'upload cloud.

    Parametri:
        cd:      CardData della carta corrente
        choices: lista di codici allegato scelti dall'utente tramite la Checklist:
                 "ddd"     → file .DDD originale
                 "pdf_act" → PDF attività
                 "pdf_viol"→ PDF infrazioni
                 "pdf_week"→ PDF riepilogo settimanale
                 "csv"     → CSV attività

    Ritorna: lista di tuple (filename, bytes) da passare a save_attachments_to_temp().

    I servizi PDF vengono importati localmente (non in cima al file) per due motivi:
      1. Evitare import circolari (share_controller → pdf_service → altri)
      2. Evitare che errori di importazione rari blocchino l'avvio dell'app
    """
    from services.pdf_service import (
        generate_activities,     # genera PDF con tutte le attività
        generate_violations_pdf, # genera PDF con le infrazioni
        generate_weekly,         # genera PDF con il riepilogo settimanale
    )
    from controllers.export_controller import _to_csv          # genera CSV attività
    from controllers.archive_controller import _rebuild_ddd_bytes  # fallback DDD

    attachments = []

    if "ddd" in choices:
        # Cerca il file .DDD originale nell'archivio locale
        archive  = get_archive()
        entries  = archive.list_entries()
        # next() con default None: trova il primo match o None se non trovato
        matching = next(
            (e for e in entries if e.card_number == cd.driver.card_number), None
        )
        # Se il file è nell'archivio, usa quello; altrimenti ricostruisce un DDD sintetico
        raw = archive.get_bytes(matching.filename) if matching else _rebuild_ddd_bytes(cd)
        if raw:
            # Nome file nel formato standard dei DDD: C_DATA_COGNOME_CARTA.DDD
            ts    = (cd.driver.last_download or "").replace("/", "-").replace(" ", "_").replace(":", "")
            fname = f"C_{ts}_{cd.driver.surname}_{cd.driver.card_number}.DDD"
            attachments.append((fname, raw))

    if "pdf_act" in choices:
        attachments.append((
            f"Attivita_{cd.driver.surname}.pdf",
            generate_activities(cd),   # bytes del PDF generato da ReportLab
        ))

    if "pdf_viol" in choices:
        attachments.append((
            f"Infrazioni_{cd.driver.surname}.pdf",
            generate_violations_pdf(cd),
        ))

    if "pdf_week" in choices:
        attachments.append((
            f"Riepilogo_{cd.driver.surname}.pdf",
            generate_weekly(cd),
        ))

    if "csv" in choices:
        # _to_csv() ritorna una stringa; encode("utf-8") la converte in bytes
        attachments.append((
            f"Attivita_{cd.driver.surname}.csv",
            _to_csv(cd).encode("utf-8"),
        ))

    return attachments


def _result_box(msg: str, ok: bool) -> html.Div:
    """
    Crea un box colorato con il risultato di un'operazione.

    ok=True:  sfondo verde tenue con bordo verde (operazione riuscita)
    ok=False: sfondo rosso tenue con bordo rosso (operazione fallita)

    Il colore + "11" = 7% di opacità (sfondo quasi trasparente).
    Il colore + "33" = 20% di opacità (bordo leggermente visibile).
    """
    color = C["success"] if ok else C["guida"]
    return html.Div(msg, style={
        "background": color + "11",
        "border": f"1px solid {color}33",
        "color": color,
        "borderRadius": "6px",
        "padding": "10px 14px",
        "whiteSpace": "pre-wrap",   # preserva i newline nel testo del messaggio
        "lineHeight": "1.6",
    })


def register(app):
    """
    Registra tutti i callback di condivisione nell'app Dash.
    Chiamata una sola volta all'avvio in app.py.
    """

    # ── 1. Apri client email locale ───────────────────────────────────────────
    @app.callback(
        Output("email-open-result", "children"),
        Input("btn-open-mail-client", "n_clicks"),
        State("email-recipients",  "value"),    # destinatari (stringa separata da virgola)
        State("email-attachments", "value"),    # lista codici allegato selezionati
        State("store-data",        "data"),     # dati carta corrente
        prevent_initial_call=True,
    )
    def open_email(n, recipients_str, attach_choices, raw):
        """
        Salva i file selezionati in una cartella temporanea e apre il client email.

        Il client email viene aperto con il protocollo mailto: del SO.
        Non viene inviata alcuna email automaticamente — l'utente deve cliccare "Invia".

        Flusso:
          1. Deserializza i dati carta da raw (JSON → CardData)
          2. Analizza i destinatari (split su virgola)
          3. Genera subject e body dell'email
          4. Costruisce gli allegati richiesti
          5. Salva i file in /tmp (o %TEMP% su Windows)
          6. Apre il mailto: con i path dei file allegati
        """
        if not n:
            raise PreventUpdate
        if not raw:
            return _result_box("❌ Nessun dato carta caricato.", False)

        cd = CardData.from_dict(raw)

        # Analizza i destinatari: "a@b.it, c@d.it" → ["a@b.it", "c@d.it"]
        rcpts = [r.strip() for r in (recipients_str or "").split(",") if r.strip()]

        # Genera subject e body predefiniti per l'email
        subject, body = build_email_content(
            cd.driver.full_name,
            cd.driver.card_number,
            cd.driver.last_download or "—",
        )

        # Costruisce gli allegati scelti dall'utente
        attachments = _build_attachments(cd, attach_choices or [])
        if not attachments:
            return _result_box("⚠️ Seleziona almeno un file da allegare.", False)

        # Salva i file in una cartella temporanea e ottieni i path assoluti
        paths = save_attachments_to_temp(attachments)

        # Apre il client email (ok=True se si apre con successo)
        ok, msg = open_mail_client(rcpts, subject, body, paths)
        return _result_box(msg, ok)

    # ── 2. Salva destinatari predefiniti nel file di configurazione ───────────
    @app.callback(
        Output("recipients-save-result", "children"),
        Input("btn-save-recipients", "n_clicks"),
        State("email-recipients", "value"),   # valore corrente dell'input destinatari
        prevent_initial_call=True,
    )
    def save_recipients(n, val):
        """
        Salva i destinatari inseriti come predefiniti per le future email.

        EmailConfig.load(): legge il file di configurazione (~/.tachovision/email.json)
        cfg.save(): sovrascrive il file con i nuovi destinatari
        """
        if not n:
            raise PreventUpdate
        cfg = EmailConfig.load()
        # Analizza la stringa: "a@b.it, c@d.it" → ["a@b.it", "c@d.it"]
        cfg.default_recipients = [r.strip() for r in (val or "").split(",") if r.strip()]
        cfg.save()
        return html.Span("✅ Salvati", style={"color": C["success"]})

    # ── 3. Salva e valida il token Dropbox ────────────────────────────────────
    @app.callback(
        Output("dropbox-token-result", "children"),
        Input("btn-dropbox-token", "n_clicks"),
        State("dropbox-token-input", "value"),   # token inserito dall'utente (nascosto con *****)
        prevent_initial_call=True,
    )
    def save_dropbox_token(n, token):
        """
        Valida il Personal Access Token Dropbox e lo salva se valido.

        DropboxService().save_token(token) fa una chiamata API di test
        per verificare che il token sia valido, poi lo salva nel file di config.
        Ritorna True se la validazione ha successo, False altrimenti.
        """
        if not n or not token:
            raise PreventUpdate
        ok = DropboxService().save_token(token)
        return _result_box(
            "✅ Token Dropbox valido e salvato. Ricarica la tab." if ok
            else "❌ Token non valido o connessione fallita.",
            ok,
        )

    # ── 4. Autenticazione cloud (connect/disconnect) ──────────────────────────
    @app.callback(
        Output("gdrive-auth-panel",          "children"),   # pannello auth Google Drive
        Output("onedrive-device-code-panel", "children"),   # pannello auth OneDrive
        Output("cloud-upload-result",        "children"),   # messaggio risultato
        Input({"type": "btn-cloud-auth", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def cloud_auth(n_clicks_list):
        """
        Gestisce il click su "Connetti" / "Disconnetti" per ogni provider cloud.

        Usa pattern matching: Input({"type":"btn-cloud-auth","index":ALL},"n_clicks")
        cattura i click su tutti i pulsanti di tipo "btn-cloud-auth".
        callback_context.triggered[0]["prop_id"] → json.loads → {"index": "Google Drive"}
        Così si sa quale provider ha ricevuto il click.

        Google Drive (se non connesso):
          - Verifica che credentials.json esista (is_configured)
          - Genera URL di autorizzazione OAuth2 (get_auth_url)
          - Mostra il pannello con link + input per il codice

        OneDrive (se non connesso):
          - Avvia il Device Code Flow (start_device_flow)
          - Mostra il pannello con il codice da inserire su microsoft.com/devicelogin

        Se già connesso: disconnette e mostra messaggio di conferma.

        no_update: valore speciale Dash che dice "non aggiornare questo output".
        Usato quando il callback triggera per un provider ma non deve toccare gli output
        degli altri (es. click su Google Drive non deve toccare il pannello OneDrive).
        """
        ctx = callback_context
        if not ctx.triggered or not any(n for n in n_clicks_list if n):
            raise PreventUpdate

        # Identifica il provider dal prop_id del pulsante cliccato
        btn  = ctx.triggered[0]["prop_id"]
        name = json.loads(btn.split(".")[0])["index"]

        # Inizializza gli output come "non aggiornare" (no_update)
        gdrive_panel = no_update
        od_panel     = no_update
        result       = no_update

        if name == "Google Drive":
            svc = GoogleDriveService()
            if svc.is_authenticated():
                # Già connesso → disconnetti
                svc.logout()
                result = _result_box("✅ Disconnesso da Google Drive.", True)
            elif svc.is_configured():
                # credentials.json presente → avvia OAuth2
                try:
                    url = svc.get_auth_url()
                    # Mostra il pannello con link e input per il codice
                    gdrive_panel = html.Div([
                        html.Div("1. Apri questo link e autorizza l'accesso:",
                                 style={"fontSize":"0.82rem","color":C["text"],"marginBottom":"6px"}),
                        html.A(url, href=url, target="_blank",   # apri in nuova scheda
                               style={"color":"#EA4335","fontSize":"0.78rem","wordBreak":"break-all"}),
                        html.Div("2. Incolla il codice ricevuto:",
                                 style={"fontSize":"0.82rem","color":C["text"],
                                        "marginTop":"10px","marginBottom":"6px"}),
                        html.Div(style={"display":"flex","gap":"8px"}, children=[
                            dcc.Input(id="gdrive-auth-code",
                                      placeholder="Codice autorizzazione Google",
                                      style={"flex":"1","background":C["surface"],
                                             "border":f"1px solid {C['border']}",
                                             "color":C["text"],"borderRadius":"6px",
                                             "padding":"8px 12px","fontSize":"0.82rem"}),
                            html.Button("✅ Conferma", id="btn-gdrive-confirm",
                                        n_clicks=0,
                                        style={"background":"#EA433522",
                                               "border":"1px solid #EA433544",
                                               "color":"#EA4335","borderRadius":"6px",
                                               "padding":"8px 14px","cursor":"pointer",
                                               "fontFamily":"'Space Grotesk'"}),
                        ]),
                        # Feedback dopo aver inserito il codice
                        html.Div(id="gdrive-confirm-result",
                                 style={"marginTop":"6px","fontSize":"0.8rem"}),
                    ], style={"background":C["surface"],"borderRadius":"8px",
                               "padding":"14px","marginTop":"10px"})
                except Exception as e:
                    result = _result_box(f"❌ {e}", False)
            else:
                # credentials.json mancante → istruzioni per l'utente
                result = _result_box(
                    "❌ File credentials.json non trovato.\n"
                    "Scaricalo da Google Cloud Console e salvalo in:\n"
                    "~/TachoVision/config/gdrive_credentials.json",
                    False,
                )

        elif name == "OneDrive":
            svc = OneDriveService()
            if svc.is_authenticated():
                svc.logout()
                result = _result_box("✅ Disconnesso da OneDrive.", True)
            else:
                try:
                    # Avvia il Device Code Flow: genera codice utente
                    flow = svc.start_device_flow()
                    # Mostra il codice che l'utente deve inserire su microsoft.com/devicelogin
                    od_panel = html.Div([
                        html.Div("Vai su:", style={"fontSize":"0.82rem","color":C["text"],"marginBottom":"6px"}),
                        html.A(flow["verification_uri"], href=flow["verification_uri"],
                               target="_blank",
                               style={"color":"#0078D4","fontWeight":"bold"}),
                        html.Div("e inserisci il codice:",
                                 style={"fontSize":"0.82rem","color":C["text"],
                                        "margin":"8px 0 6px"}),
                        # Codice device in grande (facile da leggere e digitare)
                        html.Code(flow["user_code"],
                                  style={"background":C["surface"],"padding":"6px 14px",
                                         "borderRadius":"4px","fontSize":"1.2rem",
                                         "letterSpacing":"4px","color":"#0078D4",
                                         "fontWeight":"bold"}),
                        html.Button("✅ Ho inserito il codice", id="btn-od-confirm",
                                    n_clicks=0,
                                    style={"display":"block","marginTop":"12px",
                                           "background":"#0078D422","border":"1px solid #0078D444",
                                           "color":"#0078D4","borderRadius":"6px",
                                           "padding":"8px 14px","cursor":"pointer",
                                           "fontFamily":"'Space Grotesk'"}),
                        html.Div(id="od-confirm-result",
                                 style={"marginTop":"6px","fontSize":"0.8rem"}),
                    ], style={"background":C["surface"],"borderRadius":"8px",
                               "padding":"14px","marginTop":"10px"})
                except Exception as e:
                    result = _result_box(f"❌ {e}", False)

        elif name == "Dropbox":
            # Dropbox: logout diretto (non c'è un flusso multi-step)
            DropboxService().logout()
            result = _result_box("✅ Disconnesso da Dropbox.", True)

        return gdrive_panel, od_panel, result

    # ── 5. Conferma autorizzazione Google Drive ───────────────────────────────
    @app.callback(
        Output("gdrive-confirm-result", "children"),
        Input("btn-gdrive-confirm", "n_clicks"),
        State("gdrive-auth-code", "value"),   # codice inserito dall'utente
        prevent_initial_call=True,
    )
    def gdrive_confirm(n, code):
        """
        Completa l'autenticazione Google Drive con il codice di autorizzazione.

        complete_auth(code) scambia il codice con i token OAuth2 e li salva.
        Dopo questa chiamata, is_authenticated() ritorna True per le sessioni future.
        """
        if not n or not code:
            raise PreventUpdate
        ok = GoogleDriveService().complete_auth(code.strip())
        return _result_box(
            "✅ Google Drive collegato! Ricarica la tab." if ok
            else "❌ Codice non valido o scaduto. Riprova.",
            ok,
        )

    # ── 6. Conferma OneDrive (verifica che il Device Code sia stato usato) ────
    @app.callback(
        Output("od-confirm-result", "children"),
        Input("btn-od-confirm", "n_clicks"),
        prevent_initial_call=True,
    )
    def od_confirm(n):
        """
        Verifica che l'utente abbia completato il Device Code Flow su Microsoft.

        complete_device_flow() fa polling all'API Microsoft per verificare
        se il codice è stato inserito e autorizzato. Ha un timeout incorporato.
        Se l'utente non ha ancora inserito il codice, ritorna False.
        """
        if not n:
            raise PreventUpdate
        ok = OneDriveService().complete_device_flow()
        return _result_box(
            "✅ OneDrive collegato! Ricarica la tab." if ok
            else "❌ Timeout o errore. Riprova.",
            ok,
        )

    # ── 7. Upload su un singolo provider cloud ────────────────────────────────
    @app.callback(
        Output("cloud-upload-result", "children", allow_duplicate=True),
        # allow_duplicate=True: anche cloud_auth scrive su questo Output
        Input({"type": "btn-cloud-upload", "index": ALL}, "n_clicks"),
        State("store-data", "data"),
        prevent_initial_call=True,
    )
    def cloud_upload_single(n_clicks_list, raw):
        """
        Carica il file .DDD sul provider cloud il cui pulsante è stato cliccato.

        Recupera i byte del .DDD dall'archivio locale (o li ricostruisce come fallback).
        svc.upload(filename, bytes): carica il file e ritorna (ok, messaggio).

        svc_map: dizionario che mappa il nome del provider all'istanza del servizio.
        Permette di trattare tutti i provider in modo uniforme.
        """
        ctx = callback_context
        if not ctx.triggered or not any(n for n in n_clicks_list if n) or not raw:
            raise PreventUpdate

        btn  = ctx.triggered[0]["prop_id"]
        name = json.loads(btn.split(".")[0])["index"]   # es. "Google Drive"
        cd   = CardData.from_dict(raw)

        # Cerca il file .DDD nell'archivio
        archive  = get_archive()
        entries  = archive.list_entries()
        matching = next((e for e in entries if e.card_number == cd.driver.card_number), None)
        raw_bytes = archive.get_bytes(matching.filename) if matching else None

        # Fallback: ricostruisce il DDD dai dati parsati
        if not raw_bytes:
            from controllers.archive_controller import _rebuild_ddd_bytes
            raw_bytes = _rebuild_ddd_bytes(cd)

        fname = matching.filename if matching else f"{cd.driver.card_number}.DDD"

        # Mappa nome → istanza del servizio cloud
        svc_map = {
            "Google Drive": GoogleDriveService(),
            "OneDrive":     OneDriveService(),
            "Dropbox":      DropboxService(),
        }
        svc = svc_map.get(name)
        if not svc:
            raise PreventUpdate

        ok, msg = svc.upload(fname, raw_bytes)
        return _result_box(f"{name}: {msg}", ok)

    # ── 8. Upload su tutti i provider connessi in un colpo solo ───────────────
    @app.callback(
        Output("cloud-upload-all-result", "children"),
        Input("btn-cloud-upload-all", "n_clicks"),
        State("store-data", "data"),
        prevent_initial_call=True,
    )
    def cloud_upload_all(n, raw):
        """
        Carica il file .DDD su tutti i provider cloud autenticati simultaneamente.

        upload_to_all() (da services/cloud_service.py) itera tutti i servizi,
        chiama .upload() su quelli autenticati e raccoglie i risultati.
        Ritorna: [{"provider": "Google Drive", "ok": True, "message": "..."}, ...]

        Il messaggio finale è multi-riga (uno per provider) usando join.
        all_ok: True solo se TUTTI i provider hanno uploadato con successo.
        """
        if not n or not raw:
            raise PreventUpdate

        cd = CardData.from_dict(raw)

        # Recupera i byte del .DDD (stesso pattern di cloud_upload_single)
        archive  = get_archive()
        entries  = archive.list_entries()
        matching = next((e for e in entries if e.card_number == cd.driver.card_number), None)
        raw_bytes = archive.get_bytes(matching.filename) if matching else None

        if not raw_bytes:
            from controllers.archive_controller import _rebuild_ddd_bytes
            raw_bytes = _rebuild_ddd_bytes(cd)

        fname = matching.filename if matching else f"{cd.driver.card_number}.DDD"

        # Carica su tutti i provider autenticati
        results = upload_to_all(fname, raw_bytes)

        if not results:
            return _result_box(
                "⚠️ Nessun provider cloud connesso.\n"
                "Configura almeno un account nella sezione cloud sopra.",
                False,
            )

        # Costruisce un messaggio multi-riga con il risultato per ogni provider
        lines  = [f"{r['provider']}: {r['message']}" for r in results]
        all_ok = all(r["ok"] for r in results)   # True solo se tutti OK
        return _result_box("\n".join(lines), all_ok)

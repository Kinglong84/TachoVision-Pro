"""
controllers/nav_controller.py
==============================
Controller per la navigazione tra le tab dell'applicazione.

Responsabilità: intercettare il click su qualsiasi bottone della sidebar
e aggiornare lo store "store-tab" con l'id della tab selezionata.

Come funziona la navigazione in Dash:
  1. L'utente clicca un bottone nella sidebar (es. "📅 Attività")
  2. Questo callback viene chiamato con n_clicks > 0 su quel bottone
  3. Identifica quale bottone è stato cliccato tramite callback_context
  4. Aggiorna store-tab con il tab_id corrispondente (es. "attivita")
  5. render_controller.render_page() si attiva (perché store-tab è cambiato)
     e ridisegna la pagina con la nuova tab
"""

from dash import Input, Output, State, callback_context, no_update
# Input:   trigger del callback (cambio del valore)
# Output:  cosa il callback aggiorna
# State:   valore letto ma che non triggera il callback
# callback_context: oggetto globale che dice quale Input ha scatenato il callback
# no_update: valore sentinella che dice a Dash "non aggiornare questo Output"

from dash.exceptions import PreventUpdate
# PreventUpdate: eccezione che interrompe il callback senza aggiornare nulla
# (più pulita di "return no_update" in certi contesti)

from views.theme import TABS
# TABS: lista piatta [(tab_id, etichetta), ...] derivata da SIDEBAR_GROUPS
# Usata per generare dinamicamente tutti gli Input del callback


def register(app):
    """
    Registra i callback di navigazione sull'istanza Dash.

    Questa funzione viene chiamata da app.py al momento dell'avvio.
    Definisce i callback dentro register() per evitare conflitti quando
    il modulo viene importato: i callback vengono attaccati all'app solo
    quando register() viene esplicitamente chiamato.
    """

    # ── Callback principale: click bottoni sidebar → aggiorna tab attiva ──────────
    @app.callback(
        Output("store-tab", "data"),   # aggiorna il valore di store-tab
        # Input lista: uno per ogni bottone nella sidebar
        # [Input("tab-btn-panoramica", "n_clicks"), Input("tab-btn-infrazioni", ...), ...]
        [Input(f"tab-btn-{tid}", "n_clicks") for tid, _ in TABS],
        State("store-tab", "data"),    # legge la tab corrente senza triggerare
        prevent_initial_call=True,     # non eseguire al caricamento della pagina
    )
    def switch_tab(*args):
        """
        Determina quale bottone è stato cliccato e ritorna il tab_id corrispondente.

        *args raccoglie tutti i parametri: n_clicks per ogni bottone + la State.
        L'ultimo elemento di args è sempre la State (tab corrente).
        """
        # L'ultimo argomento è lo State (tab corrente)
        current = args[-1]

        # callback_context.triggered è una lista di dict con:
        #   {"prop_id": "tab-btn-attivita.n_clicks", "value": 1}
        ctx = callback_context
        if not ctx.triggered:
            # Nessun trigger = chiamata iniziale, non dovrebbe succedere
            # grazie a prevent_initial_call=True, ma per sicurezza:
            return current

        # Estrae l'id del componente che ha triggerato il callback
        # "tab-btn-attivita.n_clicks" → split(".")[0] → "tab-btn-attivita"
        btn_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # Trova il tab_id corrispondente al bottone cliccato
        for tid, _ in TABS:
            if btn_id == f"tab-btn-{tid}":
                return tid   # ritorna "attivita", "infrazioni", ecc.

        # Se non trovato (non dovrebbe succedere), mantieni la tab corrente
        return current

    # ── Callback secondario: bottone "Archivio" dalla welcome screen ─────────────
    @app.callback(
        # allow_duplicate=True perché store-tab ha già un Output nel callback sopra.
        # Dash normalmente non permette due callback con lo stesso Output;
        # allow_duplicate lo consente specificando esplicitamente l'intenzione.
        Output("store-tab", "data", allow_duplicate=True),
        Input("btn-welcome-archive", "n_clicks"),
        prevent_initial_call=True,
    )
    def welcome_go_archive(n):
        """
        Quando si clicca "Consulta Archivio" nella schermata di benvenuto,
        naviga direttamente alla tab archivio.
        """
        if n:
            return "archivio"   # porta l'utente direttamente all'archivio
        raise PreventUpdate     # n=0 = caricamento iniziale, non fare nulla

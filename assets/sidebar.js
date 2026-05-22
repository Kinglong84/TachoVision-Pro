/**
 * TachoVision Pro — sidebar collapse/expand
 *
 * Gestisce il toggle (apri/chiudi) della sidebar tramite click sul pulsante
 * con classe "sidebar-collapse-btn".
 *
 * MECCANISMO:
 *   - Aggiunge/rimuove la classe CSS "sidebar-collapsed" sul <body>
 *   - La classe "sidebar-collapsed" viene intercettata dal foglio di stile
 *     (assets/style.css) che restrinse la sidebar con una transizione animata
 *   - La preferenza dell'utente viene salvata in localStorage in modo persistente:
 *     anche dopo un refresh della pagina, la sidebar resta nello stato scelto
 *
 * WHY JAVASCRIPT PURO (non callback Dash):
 *   I callback Dash sono Python-side: ogni interazione richiede un round-trip HTTP
 *   verso il server (~50-200ms). Per un toggle UI istantaneo come aprire/chiudere
 *   la sidebar, il JS puro è la scelta giusta — l'animazione resta fluida a 60fps
 *   e sopravvive ai re-render di Dash (che non tocca le classi CSS di <body>).
 *
 * IIFE (Immediately Invoked Function Expression): (function() { ... })()
 *   Il codice è incapsulato in una funzione anonima auto-invocata.
 *   Vantaggio: le variabili interne (STORAGE_KEY, isCollapsed, ecc.) non
 *   "inquinano" il namespace globale (window.*) — evita conflitti con
 *   altri script o librerie.
 */

(function () {
    "use strict";   /* modalità strict: rileva errori comuni (es. variabili non dichiarate) */

    /** Chiave usata in localStorage per salvare la preferenza sidebar */
    var STORAGE_KEY = "tv-sidebar-collapsed";

    /**
     * Ritorna true se la sidebar è attualmente collassata.
     * Controlla la presenza della classe "sidebar-collapsed" sul <body>.
     * document.body.classList: lista delle classi CSS dell'elemento <body>.
     */
    function isCollapsed() {
        return document.body.classList.contains("sidebar-collapsed");
    }

    /**
     * Applica lo stato collapsed/expanded alla sidebar.
     *
     * 1. Aggiunge o rimuove "sidebar-collapsed" da document.body.classList
     *    → il CSS risponde con la transizione animata della sidebar
     * 2. Aggiorna il testo dei pulsanti toggle:
     *    ▶ (freccia destra) quando collassata (per indicare "espandi")
     *    ◀ (freccia sinistra) quando espansa (per indicare "comprimi")
     *
     * document.querySelectorAll(".sidebar-collapse-btn"): seleziona TUTTI i
     * pulsanti toggle (potrebbe essercene uno in cima e uno in fondo alla sidebar).
     * forEach: itera su ognuno per aggiornarli tutti.
     */
    function applyCollapsed(collapsed) {
        if (collapsed) {
            document.body.classList.add("sidebar-collapsed");
        } else {
            document.body.classList.remove("sidebar-collapsed");
        }
        /* Aggiorna testo e tooltip del pulsante toggle */
        document.querySelectorAll(".sidebar-collapse-btn").forEach(function (btn) {
            btn.textContent = collapsed ? "▶" : "◀";
            btn.title       = collapsed ? "Espandi sidebar" : "Comprimi sidebar";
        });
    }

    /**
     * Legge lo stato salvato in localStorage e lo applica alla pagina.
     * Chiamata all'avvio per ripristinare la preferenza dell'utente.
     *
     * localStorage: storage del browser persistente tra sessioni (non scade).
     * Diverso da sessionStorage (dura solo finché la tab è aperta).
     *
     * Il try/catch gestisce browser con localStorage disabilitato
     * (es. modalità privata con impostazioni di privacy restrittive).
     */
    function restoreState() {
        try {
            var saved = localStorage.getItem(STORAGE_KEY);
            if (saved === "1") applyCollapsed(true);   /* "1" = collassata */
        } catch (e) {
            /* localStorage non disponibile: ignora silenziosamente */
        }
    }

    /**
     * Event delegation per il pulsante toggle della sidebar.
     *
     * Ascolta tutti i click su document e filtra quelli sui pulsanti .sidebar-collapse-btn.
     * e.target.closest(".sidebar-collapse-btn"): risale il DOM dal target cliccato
     * fino al primo antenato con quella classe (utile se il click è su un figlio del button).
     *
     * Pattern event delegation: un solo listener su document invece di N listener
     * su N pulsanti — funziona anche per pulsanti creati DOPO il caricamento dello script
     * (es. dopo un re-render Dash).
     *
     * localStorage.setItem: salva la preferenza ("1" = collassata, "0" = espansa).
     */
    document.addEventListener("click", function (e) {
        if (e.target.closest(".sidebar-collapse-btn")) {
            var next = !isCollapsed();   /* inverte lo stato corrente */
            applyCollapsed(next);
            try {
                localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
            } catch (e) {
                /* localStorage non disponibile: la preferenza non viene salvata */
            }
        }
    });

    /**
     * MutationObserver sulla sidebar: mantiene sincronizzati testo e tooltip del pulsante
     * anche dopo che Dash ha re-renderizzato il componente sidebar.
     *
     * Problema: Dash rigenera il DOM della sidebar ad ogni callback che la tocca.
     * Il bottone viene ricreato → perde il testo ▶/◀ impostato da applyCollapsed().
     *
     * Soluzione: osserva i figli diretti di #sidebar-nav. Quando cambiano
     * (Dash ha re-renderizzato), richiama applyCollapsed(isCollapsed())
     * per riallineare testo e tooltip al DOM appena ricreato.
     *
     * childList:true — notifica quando i figli diretti vengono aggiunti/rimossi
     * subtree:false  — non osserva i discendenti (evita callback eccessivi)
     */
    var sidebarObserver = new MutationObserver(function () {
        applyCollapsed(isCollapsed());   /* riallinea il testo del pulsante */
    });

    /**
     * Attiva l'observer sul div #sidebar-nav.
     * Chiamata sia a DOMContentLoaded sia dopo un timeout (fallback per SPA).
     */
    function attachObserver() {
        var nav = document.getElementById("sidebar-nav");
        if (nav) {
            sidebarObserver.observe(nav, { childList: true, subtree: false });
        }
    }

    /**
     * DOMContentLoaded: il DOM è stato costruito, ma gli script esterni
     * (es. Plotly, React di Dash) potrebbero non essere ancora caricati.
     * È il momento giusto per:
     *   1. Ripristinare lo stato sidebar da localStorage
     *   2. Attivare l'observer sulla sidebar
     */
    document.addEventListener("DOMContentLoaded", function () {
        restoreState();
        attachObserver();
    });

    /**
     * Fallback con setTimeout 500ms.
     * Dash è una Single Page Application (SPA) basata su React.
     * In certi casi (hot-reload del server, navigazione SPA), DOMContentLoaded
     * si spara prima che Dash abbia renderizzato la sidebar.
     * Il timeout garantisce che venga eseguito anche in questi edge cases.
     */
    setTimeout(function () {
        restoreState();
        attachObserver();
    }, 500);

})();

/**
 * TachoVision Pro — filtro lato client per tabelle e card (day-block)
 *
 * Questo script implementa il filtraggio in tempo reale degli elementi
 * della pagina senza chiamate al server. Tutto avviene nel browser (client-side),
 * rendendo l'interfaccia istantanea anche con centinaia di righe o card.
 *
 * STRUTTURA HTML ATTESA:
 *
 *   Filtro testuale per RIGHE DI TABELLA (tbody tr):
 *     <div data-filter-table="<id>">        ← wrapper div con attributo data-*
 *       <input class="tv-filter-input">     ← input di testo (da dcc.Input Dash)
 *     </div>
 *
 *   Filtro testuale per CARD GIORNO / VEICOLO / VIOLAZIONE:
 *     <div data-filter-blocks="<id>">
 *       <input class="tv-filter-blocks">
 *     </div>
 *
 *   Filtro DROPDOWN (html.Select nativo, non Dash):
 *     <select class="tv-filter-select"
 *             data-filter-select="<id>"    ← id del contenitore target
 *             data-filter-col="<N>">       ← colonna della tabella da filtrare (0-indexed)
 *
 *   Badge contatore visibili risultati:
 *     <span id="<target-id>-count">         ← aggiornato automaticamente dallo script
 *
 *   Ricerca GLOBALE (su tutta la tab corrente):
 *     <div data-filter-table="tab-content">
 *       <input class="tv-filter-input">
 *     </div>
 *
 * MECCANISMO:
 *   1. L'utente digita nell'input → evento "input" catturato via delegation
 *   2. getTargetId() identifica quale contenitore filtrare (dall'attributo data-*)
 *   3. applyFilters() legge tutti i filtri attivi per quel target
 *   4. Per ogni riga/card: verifica se il testo corrisponde → show/hide via style.display
 *   5. Aggiorna il counter badge con il numero di risultati visibili
 *
 * WHY CLIENT-SIDE:
 *   Dash normalmente gestisce la logica via callback Python.
 *   Per il filtraggio in tempo reale (keystroke), un callback Python sarebbe
 *   troppo lento (round-trip HTTP ~100-500ms). Il JS lo fa in <5ms nel browser.
 *   Dopo ogni re-render Dash, un MutationObserver ripristina i filtri.
 */

(function () {
    "use strict";

    /* ── Funzioni di utilità (private, prefisso implicito da IIFE closure) ── */

    /**
     * Trova l'ID del contenitore target a partire dall'elemento che ha ricevuto l'evento.
     *
     * Due casi:
     *  - Dropdown (select): l'attributo data-filter-select è sull'elemento stesso
     *  - Input testuale: l'attributo data-filter-table o data-filter-blocks è
     *    sul div WRAPPER (genitore dell'input, aggiunto da components.py)
     *
     * el.closest() risale l'albero DOM fino a trovare il primo antenato che
     * corrisponde al selettore CSS specificato.
     */
    function getTargetId(el) {
        /* Dropdown: attributo sull'elemento stesso */
        if (el.dataset.filterSelect) return el.dataset.filterSelect;
        /* Input: cerca il wrapper div con data-filter-table o data-filter-blocks */
        var wrapper = el.closest("[data-filter-table], [data-filter-blocks]");
        if (wrapper) return wrapper.dataset.filterTable || wrapper.dataset.filterBlocks;
        return null;
    }

    /**
     * Ritorna true se il target è un contenitore di card/block (non tabella).
     * Usata per scegliere se filtrare <tr> o .day-block/.veh-card.
     */
    function isBlocksTarget(targetId) {
        return !!document.querySelector('[data-filter-blocks="' + targetId + '"]');
    }

    /* ── Raccolta filtri attivi ── */

    /**
     * Raccoglie tutti i filtri attivi (testo + select) per un dato target.
     *
     * Ritorna: { text: ["parola1", "parola2"], selects: [{value, col}, ...] }
     *   text:    lista di termini di ricerca testuale (tutti devono matchare: AND logico)
     *   selects: filtri colonna da dropdown (valore + numero colonna)
     */
    function getFilters(targetId) {
        var text    = [];
        var selects = [];

        /* Input testuali dentro wrapper data-filter-table o data-filter-blocks */
        document.querySelectorAll(
            '[data-filter-table="' + targetId + '"] .tv-filter-input, ' +
            '[data-filter-blocks="' + targetId + '"] .tv-filter-blocks'
        ).forEach(function (inp) {
            var v = (inp.value || "").toLowerCase().trim();
            if (v) text.push(v);
        });

        /* Select dropdown con data-filter-select="targetId" */
        document.querySelectorAll('[data-filter-select="' + targetId + '"]').forEach(function (sel) {
            var v = (sel.value || "").toLowerCase().trim();
            if (v) selects.push({
                value: v,
                col: parseInt(sel.dataset.filterCol || "0", 10)  /* colonna 0-indexed */
            });
        });

        return { text: text, selects: selects };
    }

    /* ── Logica di filtraggio principale ── */

    /**
     * Applica tutti i filtri attivi al contenitore target.
     *
     * Tre modalità:
     *  1. Ricerca globale (targetId="tab-content"): cerca in tutto il contenuto della tab
     *  2. Card blocks: mostra/nasconde .day-block, .veh-card, .viol-group
     *  3. Righe tabella: mostra/nasconde <tr> in <tbody>, con supporto filtro colonna
     *
     * Algoritmo di matching:
     *  - text: OGNI termine deve essere presente nel testo dell'elemento (AND logico)
     *  - selects: OGNI filtro colonna deve matchare (AND logico)
     *  - Il testo viene comparato case-insensitive (.toLowerCase())
     *
     * visible conta gli elementi mostrati, usato per aggiornare il badge counter.
     */
    function applyFilters(targetId) {
        var target = document.getElementById(targetId);
        if (!target) return;

        var f         = getFilters(targetId);
        var hasFilter = f.text.length > 0 || f.selects.length > 0;
        var visible   = 0;

        /* ── Caso speciale: ricerca globale su tutta la tab ── */
        if (targetId === "tab-content") {
            var query = f.text.join(" ");
            /* Filtra tutte le righe di tabella nella tab */
            target.querySelectorAll("tbody tr").forEach(function (row) {
                var show = !query || row.textContent.toLowerCase().includes(query);
                row.style.display = show ? "" : "none";
                if (show) visible++;
            });
            /* Filtra tutte le card/block nella tab */
            target.querySelectorAll(".day-block, .veh-card, .viol-group").forEach(function (block) {
                var show = !query || block.textContent.toLowerCase().includes(query);
                block.style.display = show ? "" : "none";
                if (show) visible++;
            });
            return; /* non aggiorna il counter per la ricerca globale */
        }

        /* ── Filtro card/block (attività, veicoli, infrazioni) ── */
        if (isBlocksTarget(targetId)) {
            target.querySelectorAll(".day-block, .veh-card, .viol-group").forEach(function (block) {
                var text = block.textContent.toLowerCase();
                /* Array.every(): ritorna true solo se TUTTI i termini sono presenti (AND) */
                var show = f.text.every(function (q) { return text.includes(q); });
                block.style.display = show ? "" : "none";
                if (show) visible++;
            });

        } else {
            /* ── Filtro righe tabella ── */
            var tbody = target.querySelector("tbody");
            if (!tbody) return;

            tbody.querySelectorAll("tr").forEach(function (row) {
                var text = row.textContent.toLowerCase();

                /* Verifica tutti i termini testuali (AND) */
                var showText = f.text.every(function (q) { return text.includes(q); });

                /* Verifica tutti i filtri colonna (AND) */
                var showSel = f.selects.every(function (s) {
                    var cells = row.querySelectorAll("td");
                    var cell  = cells[s.col];  /* colonna specificata nel data-filter-col */
                    return cell && cell.textContent.toLowerCase().includes(s.value);
                });

                var show = showText && showSel;
                row.style.display = show ? "" : "none";
                if (show) visible++;
            });
        }

        /* ── Aggiorna il badge counter ── */
        /* L'elemento counter ha id="<targetId>-count" (es. "table-luoghi-count") */
        var counter = document.getElementById(targetId + "-count");
        if (counter) {
            if (hasFilter) {
                counter.textContent = visible + " risultati";
                counter.style.display = "inline";
            } else {
                /* Nessun filtro attivo: nascondi il badge */
                counter.textContent = "";
                counter.style.display = "none";
            }
        }
    }

    /* ── Event delegation ── */

    /**
     * Event delegation: anziché attaccare un listener a ogni input/select,
     * ascolta su document (un solo listener per tutti gli elementi presenti e futuri).
     * Quando arriva un evento, controlla se il target è un filtro e agisce.
     *
     * Questo pattern è necessario perché Dash crea e distrugge elementi dinamicamente:
     * i listener attachati a elementi specifici vengono persi ad ogni re-render.
     */
    document.addEventListener("input", function (e) {
        var targetId = getTargetId(e.target);
        if (targetId) applyFilters(targetId);
    });

    document.addEventListener("change", function (e) {
        /* "change" cattura i select dropdown (non emettono "input") */
        var targetId = getTargetId(e.target);
        if (targetId) applyFilters(targetId);
    });

    /* ── MutationObserver: ripristina i filtri dopo re-render Dash ── */

    /**
     * Problema: quando Dash aggiorna il DOM (cambio tab, aggiornamento callback),
     * le righe/card vengono RICREATE → style.display viene resettato a "".
     * Se l'utente aveva un filtro attivo, tutte le righe tornano visibili.
     *
     * Soluzione: MutationObserver osserva i cambiamenti nel contenitore "tab-content".
     * Quando rileva un cambiamento (childList: modifica ai figli diretti):
     *   1. Resetta display="" su tutti gli elementi (per sicurezza)
     *   2. Riapplica i filtri che hanno ancora un valore nell'input
     *
     * _pendingReset: flag per evitare che il timer scatti più volte in rapida successione
     *   (Dash può fare più aggiornamenti in breve tempo).
     *
     * setTimeout(fn, 150): attende 150ms prima di riapplicare.
     *   Questo garantisce che Dash abbia completato il rendering prima che il filtro venga riapplicato.
     */
    var _pendingReset = false;
    var observer = new MutationObserver(function () {
        if (_pendingReset) return;  /* già in attesa, non scatenare un secondo timer */
        _pendingReset = true;
        setTimeout(function () {
            _pendingReset = false;
            /* Reset: rende visibili tutti gli elementi prima di riapplicare */
            document.querySelectorAll("tbody tr, .day-block, .veh-card, .viol-group").forEach(function (el) {
                el.style.display = "";
            });
            /* Riapplica i filtri che hanno ancora un valore */
            document.querySelectorAll(".tv-filter-input, .tv-filter-blocks, .tv-filter-select").forEach(function (inp) {
                if ((inp.value || "").trim()) {
                    var targetId = getTargetId(inp);
                    if (targetId) applyFilters(targetId);
                }
            });
        }, 150);
    });

    /**
     * Avvia l'observer sul contenitore "tab-content" non appena il DOM è pronto.
     * childList:true — notifica quando i figli DIRETTI cambiano
     * subtree:false  — NON osserva i discendenti (troppo costoso per l'intero DOM)
     */
    document.addEventListener("DOMContentLoaded", function () {
        var tabContent = document.getElementById("tab-content");
        if (tabContent) {
            observer.observe(tabContent, { childList: true, subtree: false });
        }
    });

})();
/* Fine IIFE (Immediately Invoked Function Expression):
   tutto il codice è in una funzione anonima eseguita immediatamente.
   Questo evita di inquinare il namespace globale (window.*) con le variabili locali. */

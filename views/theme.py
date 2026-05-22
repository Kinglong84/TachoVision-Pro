"""
views/theme.py
==============
Costanti visive centralizzate: palette colori, stili CSS inline, helper Plotly.

Questo file è l'"unico punto di verità" per tutto ciò che riguarda l'aspetto grafico
dell'applicazione. Se vuoi cambiare un colore o uno stile, modifichi SOLO questo file
e la modifica si propaga automaticamente a tutti i componenti che lo importano.

Concetti chiave:
  - I colori sono stringhe esadecimali (#RRGGBB) usate sia in CSS che in Plotly
  - Gli stili CSS in Dash sono dizionari Python (camelCase invece di kebab-case)
    es. "border-radius" diventa "borderRadius"
  - Le funzioni *_style() restituiscono dizionari CSS da passare a style={}
"""


# ── Palette colori dark ───────────────────────────────────────────────────────────
# C è il dizionario principale dei colori. Tutti i componenti vi accedono tramite
# chiave semantica (es. C["guida"] invece di "#EF4444") così un cambio di colore
# si fa in un solo posto.
C = {
    # Sfondi (dal più scuro al più chiaro)
    "bg":      "#070B14",   # sfondo principale della pagina (quasi nero blu)
    "surface": "#0D1424",   # sfondo pannelli (leggermente più chiaro)
    "card":    "#111C30",   # sfondo card/blocchi interni
    "border":  "#1E2D45",   # colore bordi e divisori

    # Testi
    "text":    "#E2EAF4",   # testo principale (bianco blu)
    "muted":   "#5A7A9B",   # testo secondario/attenuato (grigio blu)

    # Colore accentuativo principale (ciano/azzurro)
    "accent":  "#00C2FF",

    # Colori per le 4 attività del tachigrafo
    "guida":   "#EF4444",   # rosso acceso — Guida (l'attività più regolamentata)
    "lavoro":  "#3B82F6",   # blu — Lavoro (es. carico/scarico)
    "disp":    "#F59E0B",   # arancione/giallo — Disponibilità (attesa)
    "riposo":  "#10B981",   # verde — Riposo

    # Alias semantici (usati nei componenti per chiarezza)
    "success": "#10B981",   # verde (stesso del riposo)
    "warning": "#F59E0B",   # arancione (stesso della disponibilità)
    "danger":  "#EF4444",   # rosso (stesso della guida)
}


# ── Mappa colori per tipo di attività ────────────────────────────────────────────
# Usata nei grafici e nelle legende: mappa il nome attività → colore hex
ACT_COLORS = {
    "Guida":         C["guida"],
    "Lavoro":        C["lavoro"],
    "Disponibilità": C["disp"],
    "Riposo":        C["riposo"],
}


# ── Colori per severità infrazioni ───────────────────────────────────────────────
SEV_COLORS = {
    "Molto Grave": "#DC2626",   # rosso scuro
    "Grave":       "#EF4444",   # rosso
    "Lieve":       "#F59E0B",   # arancione
}

# Emoji corrispondenti a ciascuna severità (per icone visive nelle tabelle)
SEV_ICONS = {
    "Molto Grave": "🚨",
    "Grave":       "🔴",
    "Lieve":       "🟡",
}


# ── Struttura della sidebar di navigazione ───────────────────────────────────────
# Lista di gruppi, ciascuno con nome e lista di tab:
# (tab_id, icona_emoji, etichetta_testuale)
# L'ordine qui determina l'ordine nella sidebar.
SIDEBAR_GROUPS = [
    ("Conformità", [
        ("panoramica",     "📊", "Dashboard"),     # tab panoramica generale
        ("infrazioni",     "⚠️",  "Infrazioni"),    # tab infrazioni al Reg. 561
        ("riposo",         "😴", "Riposo"),         # tab analisi periodi riposo
        ("pianificazione", "📋", "Pianificazione"), # tab calcolo ore rimanenti
    ]),
    ("Attività", [
        ("attivita",  "📅", "Attività"),    # tab attività giornaliere dettagliate
        ("riepilogo", "⏱",  "Riepilogo"),  # tab riepilogo settimanale
    ]),
    ("Mezzi & Percorsi", [
        ("veicoli", "🚛", "Veicoli"),   # tab lista veicoli usati
        ("luoghi",  "📍", "Luoghi"),    # tab luoghi e mappa
    ]),
    ("Documento", [
        ("carta",    "🪪",  "Carta"),    # tab info carta e conducente
        ("archivio", "🗄️", "Archivio"), # tab archivio file DDD locali
    ]),
    ("Gestione", [
        ("condivisione", "📤", "Report & Export"),  # tab email/cloud/export
    ]),
]

# Lista piatta derivata da SIDEBAR_GROUPS: [(tab_id, etichetta), ...]
# Usata da nav_controller per registrare i callback di navigazione.
TABS = [(tid, lbl) for _, items in SIDEBAR_GROUPS for tid, _, lbl in items]


# ── Nomi giorni settimana in italiano ────────────────────────────────────────────
# Indice 0 = Lunedì, 6 = Domenica (come datetime.weekday() di Python)
WEEKDAYS_IT = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"]


# ── Funzioni helper per stili CSS inline ─────────────────────────────────────────
# Queste funzioni restituiscono dizionari Python che vengono passati a style={}
# nei componenti Dash. Usarle evita di ripetere gli stessi valori ovunque.

def card_style(**extra):
    """
    Stile base per i pannelli "card" (sfondo scuro con bordo).

    **extra permette di aggiungere/sovrascrivere proprietà CSS inline:
    card_style(padding="10px") → aggiunge padding="10px" al dizionario base
    """
    return {
        "background": C["card"],
        "border": f"1px solid {C['border']}",
        "borderRadius": "10px",    # angoli arrotondati
        "padding": "20px",
        "marginBottom": "16px",    # spazio sotto ogni card
        **extra,                   # eventuali sovrascritture/aggiuntive
    }

def muted_text_style(size="0.78rem"):
    """Stile per testo secondario (colore attenuato, dimensione configurabile)."""
    return {"color": C["muted"], "fontSize": size}

def mono_style(size="0.82rem"):
    """Stile per testo monospaced (numeri, codici, timestamp)."""
    return {"fontFamily": "'DM Mono', monospace", "fontSize": size}

def badge_style(color: str):
    """
    Stile per badge colorati (etichette piccole con bordo).

    Il colore viene usato con due diverse opacità:
    - sfondo: colore + "22" (13% opacità in hex = 0x22/0xFF ≈ 13%)
    - bordo:  colore + "55" (33% opacità)
    - testo:  colore pieno (100%)
    """
    return {
        "background": color + "22",          # sfondo semitrasparente
        "border": f"1px solid {color}55",    # bordo parzialmente trasparente
        "color": color,                       # testo nel colore pieno
        "padding": "2px 10px",
        "borderRadius": "4px",
        "fontSize": "0.75rem",
        "fontWeight": "600",
        "whiteSpace": "nowrap",              # non va a capo
        "display": "inline-block",
    }

def btn_style(color: str = None):
    """
    Stile per i bottoni dell'interfaccia (sfondo traslucido, bordo colorato).

    Se color è None, usa il colore accent predefinito.
    """
    color = color or C["accent"]
    return {
        "background": color + "22",          # sfondo al 13% di opacità
        "border": f"1px solid {color}44",    # bordo al 27% di opacità
        "color": color,
        "borderRadius": "8px",
        "padding": "9px 14px",
        "cursor": "pointer",                 # cursore a mano al passaggio del mouse
        "fontSize": "0.82rem",
        "fontFamily": "'Space Grotesk', sans-serif",
        "whiteSpace": "nowrap",
    }


# ── Layout base per grafici Plotly ────────────────────────────────────────────────
def plotly_base(**overrides) -> dict:
    """
    Restituisce un dizionario di proprietà di layout per i grafici Plotly.

    Plotly usa update_layout(**dict) per configurare l'aspetto del grafico.
    Questa funzione fornisce le impostazioni base per lo stile dark dell'app:
    - sfondo trasparente (si vede lo sfondo della card)
    - font e colori allineati alla palette
    - animazioni fluide all'ingresso dei dati

    **overrides permette di sovrascrivere/aggiungere proprietà specifiche:
    plotly_base(height=300, barmode="stack")
    """
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)",   # sfondo del "foglio" Plotly: trasparente
        plot_bgcolor="rgba(0,0,0,0)",    # sfondo dell'area del grafico: trasparente
        font=dict(family="'DM Mono', monospace", color=C["text"], size=11),
        hoverlabel=dict(
            bgcolor="#111C30",                       # sfondo tooltip
            bordercolor="rgba(0,194,255,0.3)",       # bordo tooltip (ciano traslucido)
            font=dict(color=C["text"], size=11),
            align="left",
        ),
        margin=dict(l=10, r=10, t=30, b=10),   # margini interni (left/right/top/bottom)
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),   # legenda trasparente
        # Animazione ingresso: le tracce appaiono con un'animazione di 500ms
        transition=dict(duration=500, easing="cubic-in-out"),
        # Stile assi predefinito (sovrascritto dai grafici specifici se necessario)
        xaxis=dict(
            gridcolor=C["border"],   # colore griglia
            showline=False,          # non mostrare la linea degli assi
            zeroline=False,          # non mostrare la linea dello zero
            tickcolor=C["muted"],    # colore etichette asse
            gridwidth=0.5,           # spessore linee griglia
        ),
        yaxis=dict(
            gridcolor=C["border"], showline=False, zeroline=False,
            tickcolor=C["muted"], gridwidth=0.5,
        ),
    )
    # Aggiorna con le sovrascritture specifiche del grafico chiamante
    base.update(overrides)
    return base

def axis_style(**extra) -> dict:
    """
    Restituisce lo stile predefinito per un singolo asse Plotly.

    Usato da singoli grafici per configurare un asse specifico
    mantenendo coerenza con il tema dell'app.

    Esempio:
        fig.update_layout(xaxis=dict(**axis_style(), title="Date"))
    """
    return dict(
        gridcolor=C["border"],
        showline=False,
        zeroline=False,
        tickcolor=C["muted"],
        **extra,   # eventuali sovrascritture (es. title="Ore")
    )


# ── Fogli di stile esterni ────────────────────────────────────────────────────────
# Lista di URL caricati come <link rel="stylesheet"> nell'HTML della pagina.
# Viene passata a dash.Dash(external_stylesheets=...).
EXTERNAL_STYLESHEETS = [
    # Bootstrap 5.3: framework CSS per il layout a griglia e componenti base
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css",
    # Google Fonts: DM Mono (monospaced per numeri/codici) e Space Grotesk (sans-serif principale)
    "https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500"
    "&family=Space+Grotesk:wght@300;400;600;700&display=swap",
]

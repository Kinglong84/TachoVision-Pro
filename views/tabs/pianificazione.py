"""
views/tabs/pianificazione.py
=============================
Tab "Pianificazione": verifica compliance guida/lavoro rispetto ai limiti normativi.

Mostra per la settimana più recente nel file DDD quanto il conducente
si avvicina ai limiti del Reg. CE 561/2006 e Dir. 2002/15/CE,
con barre di avanzamento colorate (verde/arancione/rosso).

Sezioni:
  🚗 Tempo di guida:
      - Guida giornaliera (ultimo giorno): max 9h, esteso 10h (max 2×/sett.)
      - Guida settimanale: max 56h
      - Guida bisettimanale: max 90h (due settimane consecutive)
  ⏱ Orario di lavoro (Dir. 2002/15/CE):
      - Settimanale: max 60h
      - Media 4 mesi: max 48h/settimana

NOTA: i dati si riferiscono all'ultima settimana PRESENTE NEL FILE DDD.
Per un calcolo real-time, caricare un file DDD recente.
"""

from datetime import datetime, timedelta
from dash import html
import dash_bootstrap_components as dbc

from views.components import section, empty_state
from views.theme import C
from models.card_data import CardData


def _pct_color(pct: float) -> str:
    """
    Restituisce il colore della barra in base alla percentuale di utilizzo del limite.

    ≥ 100% → rosso   (limite superato o al limite)
    ≥  85% → arancione (zona di attenzione, prossimo al limite)
    <  85% → verde   (a norma, margine sufficiente)
    """
    if pct >= 100: return C["danger"]
    if pct >= 85:  return C["warning"]
    return C["success"]


def _fmt_min(m: int) -> str:
    """Converte minuti in stringa "Xh YY" (es. 495 → "8h15")."""
    h, mn = divmod(abs(m), 60)   # divmod ritorna (quoziente, resto)
    return f"{h}h{mn:02d}"


def _progress(pct: float) -> html.Div:
    """
    Barra di avanzamento CSS pura (senza librerie aggiuntive).

    Struttura HTML:
        <div style="background: grigio; ...">   ← barra sfondo (vuota)
            <div style="width: X%; background: colore;">  ← barra riempita
            </div>
        </div>

    La larghezza della barra interna è min(pct, 100)% per non sforare.
    Il colore cambia in base alla percentuale con _pct_color().
    """
    color = _pct_color(pct)
    return html.Div(
        # Barra interna colorata (riempita in proporzione alla percentuale)
        html.Div(style={
            "height": "6px",
            "borderRadius": "3px",
            "width": f"{min(pct, 100):.1f}%",   # min() evita overflow > 100%
            "background": color,
        }),
        # Contenitore della barra (sfondo grigio = "vuoto")
        style={"background": C["border"], "borderRadius": "3px",
               "height": "6px", "marginTop": "5px", "marginBottom": "14px"},
    )


def _limit_row(label: str, current_min: int, limit_min: int, sub: str = "") -> html.Div:
    """
    Riga di una singola misura: etichetta, valore/limite, barra di avanzamento.

    Struttura visiva:
        [Etichetta]  [sottotitolo norma]         [valore / limite colorato]
        ████████░░░░░░░░░░░░░░░░░░░░░░  ← barra progress

    Parametri:
        label:       nome della misura (es. "Guida settimanale")
        current_min: valore attuale in minuti
        limit_min:   limite normativo in minuti
        sub:         testo secondario con riferimento normativo
    """
    # Calcola la percentuale di utilizzo del limite (0-100+ %)
    pct   = (current_min / limit_min * 100) if limit_min else 0
    color = _pct_color(pct)

    return html.Div([
        # Riga con label a sinistra e "valore/limite" a destra
        html.Div([
            html.Span(label, style={"fontSize": "0.83rem", "color": C["text"]}),
            # Sottotitolo (es. "max 56h · sett. 11/05/2026")
            html.Span(sub,   style={"fontSize": "0.72rem", "color": C["muted"],
                                    "marginLeft": "8px"}),
            # "valore / limite" allineato a destra (marginLeft: auto in flexbox)
            html.Span(f"{_fmt_min(current_min)} / {_fmt_min(limit_min)}",
                      style={"fontFamily": "'DM Mono'", "fontSize": "0.82rem",
                             "color": color, "marginLeft": "auto", "fontWeight": "600"}),
        ], style={"display": "flex", "alignItems": "center"}),
        # Barra di avanzamento sotto la riga
        _progress(pct),
    ])


def render(cd: CardData) -> html.Div:
    """
    Costruisce la tab Pianificazione con i dati della settimana più recente.

    Estrae le informazioni necessarie dal weekly_summary e dalle attività,
    poi compone le due sezioni (guida e lavoro).
    """
    ws   = cd.weekly_summary   # lista WeekSummary, dalla più recente
    acts = cd.activities       # lista DayActivity, in ordine cronologico

    if not ws and not acts:
        return empty_state("Dati insufficienti per il calcolo della pianificazione")

    # Prende l'ultima settimana (indice 0) e la penultima (indice 1)
    last_week = ws[0] if ws else None
    prev_week = ws[1] if len(ws) > 1 else None

    # ── Calcolo valori per la sezione Guida ──────────────────────────────────────
    weekly_guida  = last_week.guida_min         if last_week else 0
    weekly_lavoro = last_week.totale_lavoro_min if last_week else 0

    # Guida bisettimanale = settimana corrente + settimana precedente
    biweekly_guida = weekly_guida + (prev_week.guida_min if prev_week else 0)

    week_label = last_week.week_label if last_week else "—"

    # ── Media 4 mesi per il calcolo Dir. 2002/15 ─────────────────────────────────
    # Usa le ultime 17 settimane (~4 mesi = 16 settimane + margine)
    months4_weeks = ws[:17]
    months4_avg   = int(
        sum(w.totale_lavoro_min for w in months4_weeks) / len(months4_weeks)
    ) if months4_weeks else 0

    # ── Guida ultimo giorno disponibile ──────────────────────────────────────────
    # acts[-1] = ultimo giorno nel file (cronologicamente il più recente)
    last_day_guida = acts[-1].minutes_of("Guida") if acts else 0

    # ── Conteggio giorni "estesi" (guida > 9h) nella settimana ──────────────────
    # Il conducente può superare 9h (fino a 10h) max 2 volte a settimana
    extended_days = 0
    if last_week and acts:
        # Range della settimana corrente
        wk_start = datetime.strptime(last_week.week_start, "%Y-%m-%d")
        wk_end   = wk_start + timedelta(days=7)
        for day in acts:
            # Controlla se il giorno cade nella settimana corrente
            if wk_start <= datetime.strptime(day.date, "%Y-%m-%d") < wk_end:
                if day.minutes_of("Guida") > 540:   # 540 min = 9h
                    extended_days += 1

    # Rappresentazione visiva con stelline: ★★ = 2 usate, ☆☆ = 0 usate
    stars_used = min(extended_days, 2)
    stars_str  = "★" * stars_used + "☆" * (2 - stars_used)
    ext_color  = (C["danger"]  if extended_days > 2 else   # superato il limite
                  C["warning"] if extended_days == 2 else   # al limite
                  C["success"])                              # ancora margine

    # ── Sezione guida ─────────────────────────────────────────────────────────────
    guida_section = section("🚗 Tempo di guida", html.Div([
        _limit_row("Giornaliero (ultimo giorno)", last_day_guida, 540,
                   "max 9h / 10h esteso"),
        _limit_row("Settimanale", weekly_guida, 3360,
                   f"max 56h · sett. {week_label}"),
        _limit_row("Quindicinale (2 settimane)", biweekly_guida, 5400,
                   "max 90h"),
        # Riga speciale per i giorni estesi usati (con stelline)
        html.Div([
            html.Span("Giorni estesi usati questa settimana:",
                      style={"fontSize": "0.83rem", "color": C["text"]}),
            html.Span(f"  {stars_str}  {extended_days}/2",
                      style={"fontFamily": "'DM Mono'", "fontSize": "0.85rem",
                             "color": ext_color, "marginLeft": "8px"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px"}),
    ]))

    # ── Sezione orario di lavoro ──────────────────────────────────────────────────
    lavoro_section = section("⏱ Orario di lavoro", html.Div([
        _limit_row("Settimanale", weekly_lavoro, 3600,
                   f"max 60h · sett. {week_label}"),
        _limit_row(f"Media 4 mesi ({len(months4_weeks)} settimane)",
                   months4_avg, 2880, "max 48h/settimana"),
    ]))

    # Nota informativa (i dati si riferiscono al file caricato, non al tempo reale)
    note = html.Div(
        f"ℹ️  Dati riferiti all'ultima settimana disponibile nel file ({week_label}). "
        "Per la pianificazione in tempo reale caricare un file DDD aggiornato.",
        style={"color": C["muted"], "fontSize": "0.78rem", "marginTop": "16px",
               "borderTop": f"1px solid {C['border']}", "paddingTop": "12px"},
    )

    # Layout: guida e lavoro affiancati (6+6 = 12 colonne Bootstrap)
    return html.Div([
        dbc.Row([
            dbc.Col(guida_section,  md=6),
            dbc.Col(lavoro_section, md=6),
        ], className="g-3"),
        note,
    ])

"""
views/charts.py
================
Tutti i grafici Plotly dell'applicazione.

Questo modulo contiene SOLO la presentazione visiva dei dati.
NON contiene logica di business (calcoli, regole normative, parsing).
Le funzioni ricevono i dati già elaborati dal Model/Analytics e
restituiscono oggetti go.Figure pronti da inserire in dcc.Graph.

GRAFICI DISPONIBILI:
  empty_fig()           → figura vuota con messaggio (usata come fallback)
  donut_hours()         → ciambella distribuzione ore (tab Panoramica)
  bar_daily_driving()   → barre ore guida giornaliere (tab Panoramica)
  mini_gantt()          → gantt orizzontale per un giorno (tab Attività)
  bar_weekly()          → barre guida+lavoro per settimana (tab Riepilogo)
  hist_rest()           → istogramma periodi di riposo (tab Riposo)
  pie_countries()       → torta paesi visitati (tab Luoghi)

TECNOLOGIA:
  Plotly Graph Objects (go.*): libreria Python per grafici interattivi.
  Alternativa: Plotly Express (px.*) più semplice ma meno personalizzabile.
  Usiamo go.* per controllo totale su stile e animazioni.

TEMA SCURO:
  Tutti i grafici usano plotly_base() (da views/theme.py) che imposta
  sfondi trasparenti e colori coerenti con il tema dark dell'app.
  axis_style() imposta le griglie e i font degli assi.
"""

from __future__ import annotations
from datetime import datetime
from typing import Dict, List

import plotly.graph_objects as go   # libreria grafici Plotly (oggetti a basso livello)

from views.theme import C, ACT_COLORS, plotly_base, axis_style


def empty_fig(msg: str = "Nessun dato") -> go.Figure:
    """
    Crea una figura Plotly vuota con un messaggio centrato.

    Usata come fallback quando non ci sono dati da visualizzare.
    L'annotazione è un testo posizionato al centro (x=0.5, y=0.5)
    nello spazio normalizzato della figura (0=sinistra/basso, 1=destra/alto).
    showarrow=False: non mostra la freccia dell'annotazione.
    """
    fig = go.Figure()
    fig.update_layout(**plotly_base(height=180, annotations=[dict(
        text=msg, x=.5, y=.5, showarrow=False,
        font=dict(size=13, color=C["muted"]),
    )]))
    return fig


def donut_hours(hours: Dict[str, float]) -> go.Figure:
    """
    Grafico a ciambella (donut) con la distribuzione delle ore per attività.
    Usato nella tab Panoramica per mostrare Guida / Lavoro / Disponibilità / Riposo.

    Parametro 'hours': dizionario {nome_attività: ore_totali}
    Esempio: {"Guida": 235.5, "Lavoro": 40.2, "Riposo": 3450.0}

    Il grafico filtra le attività con ore = 0 (non le mostra).
    hole=0.65: lo "spazio vuoto" al centro è il 65% → forma a ciambella.
    pull=[0.05 ...]: la fetta più grande viene "tirata fuori" di 5% per enfasi.
    rotation=90: la prima fetta parte dall'alto (12 ore dell'orologio).
    """
    # Filtra le attività con ore > 0 (non mostrare vuoti)
    labels = [k for k, v in hours.items() if v > 0]
    values = [v for v in hours.values()   if v > 0]
    # Mappa ogni attività al suo colore (da ACT_COLORS in theme.py)
    colors = [ACT_COLORS.get(l, "#888") for l in labels]
    total  = round(sum(values), 1)   # ore totali (mostrate al centro del donut)

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.65,       # 65% del raggio è vuoto (forma donut)
        # pull: estrae la fetta più grande di 5% per evidenziarla
        pull=[0.05 if v == max(values) else 0 for v in values],
        rotation=90,     # inizia dall'alto (12 dell'orologio)
        direction="clockwise",
        sort=False,      # mantiene l'ordine originale del dizionario
        marker=dict(
            colors=colors,
            line=dict(color=C["bg"], width=2.5),   # bordo scuro tra le fette
        ),
        # Template tooltip: %{label}=attività, %{value:.1f}=ore, %{percent}=percentuale
        hovertemplate="<b>%{label}</b><br>%{value:.1f}h — %{percent}<extra></extra>",
        textinfo="none",   # non mostrare testo sulle fette
    ))
    fig.update_layout(**plotly_base(
        height=220,
        margin=dict(l=0, r=90, t=0, b=0),   # spazio a destra per la legenda
        # Annotazione centrale: ore totali in grassetto
        annotations=[dict(text=f"<b>{total}h</b>", x=.5, y=.5, showarrow=False,
                          font=dict(size=18, color=C["text"]))],
        # Legenda verticale a destra del grafico
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="v", x=1, y=.5),
    ))
    return fig


def bar_daily_driving(activities: list) -> go.Figure:
    """
    Bar chart delle ore di guida per le ultime 14 giornate.
    Usato nella tab Panoramica per mostrare l'andamento recente.

    Le barre sono colorate in rosso se guida > 9h (potenziale infrazione),
    altrimenti in giallo (colore "lavoro" del tema).
    La linea tratteggiata orizzontale a 9h è il riferimento normativo (Art. 6§1).

    Il codice gestisce due formati di `activities`:
      - Lista di oggetti DayActivity (caso normale)
      - Lista di dizionari Python (caso fallback da dcc.Store, dopo serializzazione JSON)
    Questo perché dcc.Store serializza tutto in JSON: gli oggetti diventano dict.
    """
    days = activities[-14:]   # solo le ultime 14 giornate (due settimane)
    dates, hours_list = [], []

    for day in days:
        # Recupera i segmenti: gestisce sia oggetti DayActivity che dict
        segs = day.segments() if hasattr(day, "segments") else []
        if not segs:
            # Fallback: il giorno è un dizionario (proveniente da dcc.Store JSON)
            from models.card_data import DayActivity, ActivityChange
            # Ricostruisce gli oggetti ActivityChange dai dizionari
            changes = [ActivityChange(**c) if isinstance(c, dict) else c
                       for c in day.get("changes", [])]
            # Ricostruisce il DayActivity temporaneo per chiamare segments()
            dummy = DayActivity(day["date"], day["date_display"],
                                day["distance_km"], changes)
            segs = dummy.segments()
            dates.append(day["date_display"])
        else:
            dates.append(day.date_display)

        # Somma i minuti di Guida del giorno e converte in ore
        h = sum(e - s for s, e, a in segs if a == "Guida") / 60
        hours_list.append(round(h, 2))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=dates, y=hours_list,
        marker=dict(
            # Rosso se supera 9h (Art. 6§1), giallo-arancio altrimenti
            color=[C["guida"] if h > 9 else C["lavoro"] for h in hours_list],
            opacity=[1.0 if h > 9 else 0.85 for h in hours_list],
            line=dict(width=0),   # nessun bordo sulle barre
            cornerradius=4,       # angoli leggermente arrotondati
        ),
        name="Ore guida",
        hovertemplate="<b>%{x}</b><br><b>%{y:.1f}h</b><extra></extra>",
    ))
    # Linea di riferimento tratteggiata a 9h (limite giornaliero)
    fig.add_hline(y=9, line=dict(color="#F59E0B", dash="dot", width=1.5),
                  annotation=dict(text=" limite 9h", font_size=9,
                                  font_color="#F59E0B", x=1, xanchor="right"))
    fig.update_layout(**plotly_base(
        height=200,
        margin=dict(l=35, r=10, t=20, b=55),
        xaxis=dict(gridcolor=C["border"], showline=False, zeroline=False,
                   tickcolor=C["muted"], gridwidth=0.5),
        yaxis=dict(gridcolor=C["border"], showline=False, zeroline=False,
                   tickcolor=C["muted"], title="Ore", gridwidth=0.5),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        barmode="group",
    ))
    return fig


def mini_gantt(changes: list, date_str: str, tz_offset_min: int = 0) -> go.Figure:
    """
    Grafico Gantt orizzontale per un singolo giorno (tab Attività).

    Mostra le attività del giorno come barre colorate sovrapposte su un asse temporale.
    L'asse X rappresenta l'ora del giorno (00:00 → 24:00) in ora LOCALE.

    Parametri:
        changes:       lista di ActivityChange (o dict equivalenti da dcc.Store)
        date_str:      data del giorno (non usata nel grafico, ma utile per debug)
        tz_offset_min: offset UTC → ora locale in minuti (es. 120 per Italy UTC+2)
                       Traslata l'asse X e le etichette hover all'ora locale corretta

    CONVERSIONE UTC → LOCALE:
      I record ACI sono in minuti dall'inizio del giorno UTC.
      Per mostrare 08:30 locale (invece di 06:30 UTC con offset +2h = 120 min):
        - L'asse X parte da tz_h (es. 2.0) invece di 0
        - Il base delle barre è (t0/60 + tz_h): ogni barra inizia all'ora locale
        - Le etichette del tooltip mostrano (t0 + tz_offset_min) % 1440

    BARMODE="stack": le barre vengono sovrapposte (stacked) per formare il Gantt.
    orientation="h": barre orizzontali (normale in un Gantt).
    """
    from models.card_data import ActivityChange
    # Se i changes sono dizionari (da JSON), convertili in oggetti ActivityChange
    if changes and isinstance(changes[0], dict):
        changes = [ActivityChange(**c) for c in changes]

    # Ordina per tempo di inizio (fondamentale per calcolare la fine di ogni segmento)
    ch   = sorted(changes, key=lambda c: c.time)
    tz_h = tz_offset_min / 60   # offset in ore (es. 120 min → 2.0 ore)

    traces = []
    for i, c in enumerate(ch):
        t0 = c.time   # inizio segmento in minuti UTC dall'inizio del giorno
        # Fine segmento: inizio del segmento successivo, oppure mezzanotte (1440)
        t1 = ch[i + 1].time if i + 1 < len(ch) else 1440
        if t1 <= t0:
            continue   # segmento di durata zero o negativa: skip

        color = ACT_COLORS.get(c.activity, "#888")

        # Converti in minuti LOCALI per il tooltip (% 1440 gestisce il rollover mezzanotte)
        l0 = (t0 + tz_offset_min) % 1440   # inizio in ora locale
        l1 = (t1 + tz_offset_min) % 1440   # fine in ora locale

        traces.append(go.Bar(
            # x: LARGHEZZA della barra in ore (durata del segmento)
            x=[(t1 - t0) / 60],
            y=[""],   # una sola riga (il Gantt è orizzontale su una sola "traccia")
            # base: punto di PARTENZA della barra in ore locali
            base=[t0 / 60 + tz_h],
            orientation="h",   # barre orizzontali
            marker=dict(color=color, line=dict(width=0), cornerradius=3),
            name=c.activity,
            legendgroup=c.activity,   # raggruppa le barre per attività nella legenda
            showlegend=False,          # legenda gestita altrove
            # Tooltip: mostra attività, orario locale inizio→fine e durata
            hovertemplate=(
                f"<b>{c.activity}</b><br>"
                f"{l0//60:02d}:{l0%60:02d}→{l1//60:02d}:{l1%60:02d}"
                f"<br>{(t1-t0)//60}h{(t1-t0)%60:02d}<extra></extra>"
            ),
        ))

    # Asse X in ora locale: va da tz_h (es. 2.0) a tz_h+24 (es. 26.0)
    # I tick ogni 6h mostrano: "02:00", "08:00", "14:00", "20:00", "02:00 (domani)"
    x_start   = tz_h
    tick_vals = [x_start + v for v in range(0, 25, 6)]   # 5 tick da 6h in 6h
    tick_text = [f"{int(v % 24):02d}:00" for v in tick_vals]  # % 24 gestisce rollover

    fig = go.Figure(traces)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",           # sfondo figura trasparente
        plot_bgcolor="rgba(255,255,255,0.04)",   # sfondo grafico leggermente visibile
        barmode="stack",    # barre impilate (stacked) → forma il Gantt
        height=54,          # altezza compatta (è un mini-gantt inline nella card giorno)
        margin=dict(l=0, r=0, t=0, b=22),        # margine minimo, spazio solo per i tick
        xaxis=dict(
            range=[x_start, x_start + 24],   # 24 ore a partire dall'offset locale
            tickvals=tick_vals,
            ticktext=tick_text,
            gridcolor=C["border"], showline=False, zeroline=False,
            tickcolor=C["muted"], tickfont=dict(size=8, color=C["muted"]),
        ),
        yaxis=dict(visible=False),   # asse Y nascosto (una sola riga)
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=C["card"], font=dict(color=C["text"])),
    )
    return fig


def bar_weekly(weekly: list) -> go.Figure:
    """
    Bar chart con guida + lavoro totale per settimana (tab Riepilogo).

    Mostra le ultime 12 settimane in ordine cronologico ([::-1] inverte la lista
    perché weekly è ordinata dalla più recente alla più vecchia).

    Due barre per ogni settimana:
      - Rossa (C["guida"]): ore di guida
      - Giallo-arancio (C["lavoro"]): ore totali lavoro (guida+lavoro+disp.)

    Le linee di riferimento a 56h e 48h permettono di valutare visivamente
    se le settimane rispettano i limiti del Reg. 561/2006 e Dir. 2002/15/CE.

    La funzione _get() gestisce il doppio formato: oggetti WeekSummary o dizionari.
    """
    items  = weekly[:12][::-1]   # ultime 12 settimane, dalla più vecchia alla più recente
    labels = [w.week_label if hasattr(w, "week_label") else w["week_label"] for w in items]

    def _get(w, k):
        """Legge un attributo da un oggetto o da un dizionario (doppio formato)."""
        return getattr(w, k) if hasattr(w, k) else w[k]

    # Ore guida per settimana (converte da minuti a ore)
    g_vals = [_get(w, "guida_min") / 60 for w in items]

    # Ore lavoro totale (guida + lavoro + disponibilità)
    # Gestisce sia il campo `totale_lavoro_min` (oggetto) sia la somma dei campi separati (dict)
    l_vals = [_get(w, "totale_lavoro_min") / 60
              if hasattr(items[0], "totale_lavoro_min")
              else (_get(w, "guida_min") + _get(w, "lavoro_min") + _get(w, "disponibilita_min")) / 60
              for w in items]

    fig = go.Figure()
    # Barra rossa: ore guida
    fig.add_trace(go.Bar(x=labels, y=g_vals, name="Guida",
                         marker=dict(color=C["guida"], opacity=0.9,
                                     line=dict(width=0), cornerradius=4),
                         hovertemplate="<b>%{x}</b><br>Guida: <b>%{y:.1f}h</b><extra></extra>"))
    # Barra arancione: ore lavoro totale
    fig.add_trace(go.Bar(x=labels, y=l_vals, name="Tot. Lavoro",
                         marker=dict(color=C["lavoro"], opacity=0.75,
                                     line=dict(width=0), cornerradius=4),
                         hovertemplate="<b>%{x}</b><br>Lavoro: <b>%{y:.1f}h</b><extra></extra>"))
    # Riferimento normativo guida settimanale: 56h (Art. 6§2)
    fig.add_hline(y=56, line=dict(color=C["guida"], dash="dot", width=1),
                  annotation=dict(text="56h", font_size=9,
                                  font_color=C["guida"], x=0, xanchor="left"))
    # Riferimento normativo lavoro settimanale: 48h (Dir. 2002/15 Art. 4)
    fig.add_hline(y=48, line=dict(color=C["lavoro"], dash="dot", width=1),
                  annotation=dict(text="48h", font_size=9,
                                  font_color=C["lavoro"], x=1, xanchor="right"))
    fig.update_layout(**plotly_base(
        barmode="group",   # barre affiancate (non sovrapposte)
        height=220,
        margin=dict(l=40, r=10, t=20, b=60),
        xaxis=dict(**axis_style()),
        yaxis=dict(**axis_style(), title="Ore"),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", x=0, y=1.1),
    ))
    return fig


def hist_rest(rest_periods: list) -> go.Figure:
    """
    Istogramma della distribuzione delle durate dei periodi di riposo (tab Riposo).

    Sull'asse X: durata del riposo in ore.
    Sull'asse Y: quante volte appare una pausa di quella durata.
    nbinsx=20: raggruppa le durate in 20 bin (es. ogni 30-60 min).

    Le linee verticali tratteggiate segnano le soglie normative:
      - 9h (linea arancione): soglia riposo giornaliero ridotto (Art. 8§1)
      - 11h (linea verde): soglia riposo giornaliero regolare (Art. 8§1)

    Gestisce sia oggetti RestPeriod che dizionari (doppio formato dcc.Store).
    """
    durs = []
    for r in rest_periods:
        # duration_min: attributo di RestPeriod, oppure chiave del dizionario
        m = r.duration_min if hasattr(r, "duration_min") else r["duration_min"]
        durs.append(m / 60)   # converti da minuti a ore

    if not durs:
        return empty_fig("Nessun periodo di riposo")

    fig = go.Figure(go.Histogram(
        x=durs,
        nbinsx=20,   # numero di colonne dell'istogramma
        marker=dict(
            color=C["riposo"],   # colore verde-azzurro (riposo)
            opacity=0.85,
            line=dict(width=0.5, color="rgba(0,0,0,0.3)"),   # bordo sottile tra le barre
            cornerradius=3,
        ),
        hovertemplate="<b>%{x:.1f}h</b><br>%{y} periodi<extra></extra>",
    ))
    # Linea 9h: soglia riposo ridotto
    fig.add_vline(x=9,  line=dict(color=C["disp"],    dash="dot"),
                  annotation=dict(text="9h ridotto", font_size=9, font_color=C["disp"]))
    # Linea 11h: soglia riposo regolare
    fig.add_vline(x=11, line=dict(color=C["success"], dash="dot"),
                  annotation=dict(text="11h regolare", font_size=9, font_color=C["success"]))
    fig.update_layout(**plotly_base(
        height=200, margin=dict(l=40, r=10, t=20, b=40),
        xaxis=dict(**axis_style(), title="Ore"),
        yaxis=dict(**axis_style()),
    ))
    return fig


def pie_countries(places: list) -> go.Figure:
    """
    Grafico a torta dei paesi visitati (tab Luoghi).

    Ogni fetta rappresenta un paese, proporzionale al numero di soste in quel paese.
    Le etichette includono l'emoji della bandiera per riconoscimento immediato.
    hole=0.5: forma a semi-ciambella (donut meno pronunciato del donut_hours).

    Counter(... for p in places): conta le occorrenze di ogni paese.
    Gestisce sia oggetti Place che dizionari (doppio formato dcc.Store).
    """
    from collections import Counter

    # Conta le soste per paese (gestisce oggetti Place e dict)
    counts = Counter(
        p.country if hasattr(p, "country") else p["country"]
        for p in places
    )

    # Mappa codice ISO → emoji bandiera
    FLAG = {"IT":"🇮🇹","DE":"🇩🇪","FR":"🇫🇷","ES":"🇪🇸","PL":"🇵🇱","NL":"🇳🇱",
            "BE":"🇧🇪","AT":"🇦🇹","CH":"🇨🇭","CZ":"🇨🇿","RO":"🇷🇴","SK":"🇸🇰",
            "HU":"🇭🇺","BG":"🇧🇬","HR":"🇭🇷","SI":"🇸🇮","GB":"🇬🇧","SE":"🇸🇪","NO":"🇳🇴"}

    # Etichette con bandiera (es. "🇮🇹 IT")
    labels = [f"{FLAG.get(k,'🏳')} {k}" for k in counts]
    values = list(counts.values())   # numero di soste per paese

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.5,   # ciambella al 50%
        marker=dict(line=dict(color=C["bg"], width=2)),   # bordo scuro tra le fette
        hovertemplate="<b>%{label}</b><br>%{value} soste<extra></extra>",
        textinfo="none",   # etichette solo nel tooltip
    ))
    fig.update_layout(**plotly_base(
        height=220,
        margin=dict(l=0, r=100, t=0, b=0),   # spazio a destra per la legenda
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="v", x=1, y=.5),
    ))
    return fig

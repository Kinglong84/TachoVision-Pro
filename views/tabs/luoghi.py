"""
views/tabs/luoghi.py
=====================
Tab "Luoghi": luoghi registrati dal tachigrafo e mappa GPS.

Il tachigrafo registra il paese in cui si trova il conducente all'inizio
e alla fine di ogni giornata lavorativa (confini di attività).
Per le carte Gen2 con GPS integrato, vengono registrati anche waypoint
GNSS precisi (latitudine/longitudine) con cadenza periodica.

Questa tab mostra:
  1. Un banner informativo se il conducente ha lavorato solo nel paese di base
  2. Riga overview: pie-chart paesi + tabella luoghi filtrabili
  3. (se Gen2 con GPS) Mappa geografica Plotly + tabella waypoint GPS
"""

from collections import defaultdict
from datetime import datetime
from dash import html, dcc
import dash_bootstrap_components as dbc

from views.components import (
    section, empty_state,
    filter_bar, filter_input, filter_select, filter_count_badge,
)
from views.charts import pie_countries   # grafico torta paesi visitati
from views.theme import C, btn_ghost
from models.card_data import CardData


# Mappa codici ISO 3166-1 alpha-2 → emoji bandiera
# Usata per mostrare la bandiera del paese accanto al codice (es. "🇮🇹 IT")
FLAG = {"IT": "🇮🇹", "DE": "🇩🇪", "FR": "🇫🇷", "ES": "🇪🇸", "PL": "🇵🇱",
        "NL": "🇳🇱", "BE": "🇧🇪", "AT": "🇦🇹", "CH": "🇨🇭", "CZ": "🇨🇿",
        "RO": "🇷🇴", "SK": "🇸🇰", "HU": "🇭🇺", "BG": "🇧🇬", "HR": "🇭🇷",
        "SI": "🇸🇮", "GB": "🇬🇧", "SE": "🇸🇪", "NO": "🇳🇴"}

# ID HTML della tabella luoghi (usato dal filtro JavaScript)
_TABLE_ID = "table-luoghi"


def _vrns_for_date(iso_date: str, vehicle_sessions: list) -> list:
    """Restituisce le targhe dei veicoli usati in una data specifica (ISO YYYY-MM-DD)."""
    from datetime import timezone
    try:
        target = datetime.strptime(iso_date, "%Y-%m-%d").date()
        vrns = sorted({
            s.vrn for s in vehicle_sessions
            if (datetime.fromtimestamp(s.first_use_utc, tz=timezone.utc).date() <= target <=
                datetime.fromtimestamp(s.last_use_utc, tz=timezone.utc).date())
        })
        return vrns
    except Exception:
        return []


def _place_iso_date(datetime_str: str) -> str:
    """Converte 'DD/MM/YYYY HH:MM' o 'DD/MM/YYYY' in 'YYYY-MM-DD'."""
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(datetime_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


ESRI_IMAGERY = ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
                "MapServer/tile/{z}/{y}/{x}")


def gnss_points(gnss_records: list) -> list:
    """Punti della mappa (per lo store del navigatore)."""
    return [{"lat": g.lat, "lon": g.lon, "time": g.timestamp,
             "text": (f"<b>{g.timestamp}</b><br>📍 {g.lat:.5f}°N, {g.lon:.5f}°E<br>"
                      f"🎯 Precisione: {g.accuracy_dm/10:.1f} m<br>"
                      f"🚛 Odometro: {g.odometer_km:,} km".replace(",", "."))}
            for g in gnss_records]


def gnss_figure(points: list, selected: int = None, layer: str = "strade"):
    """
    Mappa GPS (OpenStreetMap o satellite Esri, nessuna chiave richiesta).
    Linea del percorso + punti dal più vecchio (grigio) al più recente (ciano),
    partenza verde, ultima posizione arancione.
    con un punto selezionato la mappa si centra su di lui
    (navigazione primo / precedente / successivo / ultimo); senza, mostra tutto.
    """
    import plotly.graph_objects as go
    from views.theme import plotly_base

    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    texts = [p["text"] for p in points]
    n = len(lats)
    colors = [
        f"rgba({int(30 + 170*i/(max(n-1,1)))},{int(220*i/(max(n-1,1)))},{int(130 + 125*i/(max(n-1,1)))},0.85)"
        for i in range(n)
    ]
    fig = go.Figure()
    fig.add_trace(go.Scattermapbox(lat=lats, lon=lons, mode="lines",
                                   line=dict(width=2, color="rgba(0,200,200,0.45)"),
                                   hoverinfo="skip", showlegend=False))
    if n > 2:
        fig.add_trace(go.Scattermapbox(lat=lats[1:-1], lon=lons[1:-1], text=texts[1:-1],
                                       mode="markers", marker=dict(size=8, color=colors[1:-1]),
                                       hovertemplate="%{text}<extra></extra>", name="Waypoint"))
    if n >= 1:
        fig.add_trace(go.Scattermapbox(lat=[lats[0]], lon=[lons[0]], text=[texts[0]],
                                       mode="markers", marker=dict(size=12, color="#10B981"),
                                       hovertemplate="%{text}<extra></extra>", name="Partenza"))
    if n >= 2:
        fig.add_trace(go.Scattermapbox(lat=[lats[-1]], lon=[lons[-1]], text=[texts[-1]],
                                       mode="markers", marker=dict(size=12, color="#F59E0B"),
                                       hovertemplate="%{text}<extra></extra>",
                                       name="Ultima posizione"))
    if selected is not None and 0 <= selected < n:
        fig.add_trace(go.Scattermapbox(lat=[lats[selected]], lon=[lons[selected]],
                                       text=[points[selected]["time"]],
                                       customdata=[texts[selected]], mode="markers+text",
                                       marker=dict(size=18, color="#C1121F"),
                                       textposition="top right",
                                       textfont=dict(size=13, color="#FFFFFF"
                                                     if layer == "satellite" else C["text"]),
                                       hovertemplate="%{customdata}<extra></extra>",
                                       name="Selezionato"))
        center, zoom = dict(lat=lats[selected], lon=lons[selected]), 13
    else:
        center = dict(lat=sum(lats) / n if n else 45, lon=sum(lons) / n if n else 12)
        span = max(max(lats) - min(lats), max(lons) - min(lons), 0.01) if n else 0
        zoom = max(3, min(13, round(8 - span * 0.6))) if n else 6
    mapbox = dict(style="open-street-map", center=center, zoom=zoom)
    if layer == "satellite":
        mapbox.update(style="white-bg", layers=[{
            "below": "traces", "sourcetype": "raster", "source": [ESRI_IMAGERY],
            "sourceattribution": "Tiles © Esri — World Imagery"}])
    fig.update_layout(
        **plotly_base(margin=dict(l=0, r=0, t=0, b=0), height=480,
                      legend=dict(orientation="h", x=0.01, y=0.01,
                                  bgcolor="rgba(246,247,244,0.85)",
                                  font=dict(color=C["text"], size=11))),
        mapbox=mapbox)
    return fig


def _gnss_map(gnss_records: list) -> html.Div:
    """Mappa con navigatore: ⏮ primo, ◀ precedente, ⤢ adatta tutto, ▶ successivo,
    ⏭ ultimo, livello Strade/Satellite (gestito da controllers/gps_controller.py)."""
    points = gnss_points(gnss_records)
    btn = lambda i, label, title: html.Button(label, id=i, n_clicks=0, title=title,
                                              style={**btn_ghost(), "minWidth": "40px",
                                                     "padding": "4px 10px"})
    bar = html.Div([
        btn("gnss-first", "⏮", "Primo punto"), btn("gnss-prev", "◀", "Precedente"),
        btn("gnss-fit", "⤢", "Adatta tutto"), btn("gnss-next", "▶", "Successivo"),
        btn("gnss-last", "⏭", "Ultimo punto"),
        html.Button("Satellite", id="gnss-layer", n_clicks=0,
                    style={**btn_ghost(), "marginLeft": "12px", "padding": "4px 12px"}),
        html.Span(f"{len(points)} punti", id="gnss-caption",
                  style={"marginLeft": "12px", "fontSize": "0.82rem", "color": C["muted"]}),
    ], style={"display": "flex", "gap": "6px", "alignItems": "center", "flexWrap": "wrap",
              "marginBottom": "8px"})
    return html.Div([
        bar,
        dcc.Store(id="gnss-points", data=points),
        dcc.Store(id="gnss-view", data={"idx": None, "layer": "strade"}),
        dcc.Graph(id="gnss-map", figure=gnss_figure(points),
                  config={"displayModeBar": True,
                          "modeBarButtonsToRemove": ["select2d", "lasso2d"]},
                  style={"borderRadius": "10px", "overflow": "hidden"}),
    ])


def _coord(r: dict) -> str:
    return f"{r['lat']:.4f}, {r['lon']:.4f}" if r.get("lat") is not None and         r.get("lon") is not None else "—"


def _gen2_v2_sections(cd: CardData) -> list:
    """Carte Gen2 v2: attraversamenti di frontiera (EF 0528) e carico/scarico (EF 0529)."""
    mono = {"fontFamily": "'Overpass'", "fontSize": "0.8rem", "whiteSpace": "nowrap"}
    km = lambda r: f"{r['odometer_km']:,} km".replace(",", ".")
    out = []
    if cd.border_crossings:
        rows = [html.Tr([html.Td(r["datetime"], style=mono),
                         html.Td(f"{FLAG.get(r['country_left'], '🏳')} {r['country_left']} → "
                                 f"{FLAG.get(r['country_entered'], '🏳')} {r['country_entered']}"),
                         html.Td(km(r), style={**mono, "textAlign": "right"}),
                         html.Td(_coord(r), style={**mono, "color": C["muted"]})])
                for r in cd.border_crossings]
        out.append(section(f"Attraversamenti di frontiera ({len(rows)})", html.Table(
            [html.Thead(html.Tr([html.Th(h) for h in ("Data/Ora", "Frontiera", "Odometro",
                                                      "Coordinate GNSS")])),
             html.Tbody(rows)], className="veh-table")))
    if cd.load_unload:
        rows = [html.Tr([html.Td(r["datetime"], style=mono), html.Td(r["operation"]),
                         html.Td(km(r), style={**mono, "textAlign": "right"}),
                         html.Td(_coord(r), style={**mono, "color": C["muted"]})])
                for r in cd.load_unload]
        out.append(section(f"Operazioni di carico e scarico ({len(rows)})", html.Table(
            [html.Thead(html.Tr([html.Th(h) for h in ("Data/Ora", "Operazione", "Odometro",
                                                      "Coordinate GNSS")])),
             html.Tbody(rows)], className="veh-table")))
    return out


def render(cd: CardData, gnss_date: str = None) -> html.Div:
    """
    Costruisce la tab Luoghi completa.

    gnss_date: se impostato (YYYY-MM-DD), filtra la mappa GPS al solo giorno indicato.
    Se non ci sono luoghi (il file DDD non ha un EF_PLACES_USED), mostra un messaggio.
    """
    if not cd.places:
        return empty_state("Nessun luogo registrato (sezione PLACES_USED assente nel file)")

    # Lista ordinata dei paesi unici visitati (set rimuove i duplicati)
    countries = sorted({p.country for p in cd.places})

    # Banner se il conducente ha lavorato solo nel paese di base (un solo paese)
    no_foreign_banner = html.Div(
        "ℹ️  L'autista non ha lavorato al di fuori del paese di base durante il periodo registrato.",
        style={"background": C["surface"], "border": f"1px solid {C['border']}",
               "borderRadius": "8px", "padding": "10px 16px", "color": C["muted"],
               "fontSize": "0.83rem", "marginBottom": "16px"},
    ) if len(countries) <= 1 else None

    # Controlla se almeno un record Place ha coordinate GPS
    has_gnss_places = any(p.gnss_lat is not None for p in cd.places)

    def _gnss_cell(p):
        """Cella tabella con coordinate lat/lon, oppure "—" se non disponibili."""
        if p.gnss_lat is not None and p.gnss_lon is not None:
            return html.Td(f"{p.gnss_lat:.4f}, {p.gnss_lon:.4f}",
                           style={"fontFamily": "'Overpass'", "fontSize": "0.73rem",
                                  "color": C["muted"], "whiteSpace": "nowrap"})
        return html.Td("—", style={"color": C["muted"], "fontSize": "0.78rem"})

    def _region_cell(p):
        """Cella tabella con codice regione, oppure "—" se non disponibile (region=0)."""
        if p.region and p.region != 0:
            return html.Td(str(p.region),
                           style={"fontFamily": "'Overpass'", "fontSize": "0.78rem",
                                  "textAlign": "center", "color": C["muted"]})
        return html.Td("—", style={"color": C["muted"], "fontSize": "0.78rem", "textAlign": "center"})

    # Colonne della tabella (aggiunge GNSS se i dati sono presenti)
    header_cols = ["Data/Ora", "Paese", "Tipo", "Odometro", "Regione"]
    if has_gnss_places:
        header_cols.append("Coordinate GNSS")

    # Costruisce le righe della tabella (max 100 per performance)
    rows = []
    for i, p in enumerate(cd.places[:100]):
        # ISO date for GPS button id (used by gps_controller)
        p_iso = _place_iso_date(p.datetime)

        cells = [
            html.Td(p.datetime, style={"fontFamily": "'Overpass'", "fontSize": "0.8rem",
                                        "whiteSpace": "nowrap"}),
            # Paese con bandiera emoji (es. "🇮🇹 IT")
            html.Td(f"{FLAG.get(p.country, '🏳')} {p.country}",
                    style={"fontFamily": "'Overpass'", "textAlign": "center"}),
            html.Td(p.entry_type),   # "Inizio" o "Fine"
            # Odometro in formato italiano con punto separatore migliaia
            html.Td(f"{p.odometer_km:,} km".replace(",", "."),
                    style={"fontFamily": "'Overpass'", "textAlign": "right", "fontSize": "0.8rem"}),
            _region_cell(p),
        ]
        if has_gnss_places:
            if p.gnss_lat is not None and p.gnss_lon is not None:
                # Coordinate cliccabili → filtrano la mappa GPS a questa data
                gnss_cell = html.Td([
                    html.Span(
                        f"{p.gnss_lat:.4f}, {p.gnss_lon:.4f}",
                        style={"fontFamily": "'Overpass'", "fontSize": "0.73rem",
                               "color": C["muted"], "whiteSpace": "nowrap",
                               "marginRight": "4px"},
                    ),
                    html.Button(
                        "📍",
                        id={"type": "btn-gps-place", "index": f"{i}|{p_iso}"},
                        n_clicks=0,
                        title="Mostra traccia GPS di questo giorno",
                        style={
                            "background": "transparent", "border": "none",
                            "cursor": "pointer", "fontSize": "0.85rem",
                            "padding": "0 2px", "lineHeight": "1",
                            "verticalAlign": "middle",
                        },
                    ),
                ])
            else:
                gnss_cell = html.Td("—", style={"color": C["muted"], "fontSize": "0.78rem"})
            cells.append(gnss_cell)
        rows.append(html.Tr(cells))

    # Tabella principale dei luoghi
    tbl = html.Table(
        [html.Thead(html.Tr([html.Th(h) for h in header_cols])),
         html.Tbody(rows)],
        id=_TABLE_ID,          # id per il filtro JavaScript
        className="veh-table",
    )

    # Opzioni filtro dropdown paesi (con bandiere)
    country_options = [f"{FLAG.get(c, '🏳')} {c}" for c in countries]

    # Sezione tabella con filtri
    soste_section = section(
        f"Elenco soste ({len(cd.places)})",
        filter_bar(
            filter_input("Cerca data / paese...", _TABLE_ID, width="230px"),
            filter_select("Paese", country_options, _TABLE_ID, col=1),  # filtra colonna 1 (Paese)
            filter_count_badge(_TABLE_ID),
        ),
        tbl,
    )

    # Layout overview: pie-chart (md=4) + tabella (md=8)
    chart_col = dbc.Col(section("Paesi visitati",
        dcc.Graph(figure=pie_countries(cd.places), config={"displayModeBar": False})), md=4)

    overview_row = dbc.Row([chart_col, dbc.Col(soste_section, md=8)], className="g-3")

    # Assemblaggio parti (banner opzionale + overview)
    # in cima, al posto del vecchio banner
    from views.countries import countries_section
    parts = [countries_section(cd), overview_row]
    parts += _gen2_v2_sections(cd)

    # ── Sezione GNSS (solo se la carta ha waypoint GPS) ──────────────────────────
    if cd.gnss_records:
        gr = cd.gnss_records

        # Applica filtro data se impostato da gps_controller
        if gnss_date:
            gr = [g for g in gr if g.date == gnss_date]

        # Nessun waypoint per questa data → sezione vuota con avviso
        if not gr:
            date_disp = datetime.strptime(gnss_date, "%Y-%m-%d").strftime("%d/%m/%Y")
            parts.append(section(
                "🗺️ Mappa GPS",
                html.Div(
                    f"Nessun waypoint GPS trovato per il {date_disp}.",
                    style={"color": C["muted"], "padding": "12px 0", "fontSize": "0.85rem"},
                ),
            ))
            return html.Div(parts)

        map_graph = _gnss_map(gr)

        # Statistiche percorso
        date_from  = gr[0].date
        date_to    = gr[-1].date
        km_from    = gr[0].odometer_km
        km_to      = gr[-1].odometer_km
        km_delta   = km_to - km_from
        acc_values = [g.accuracy_dm for g in gr if g.accuracy_dm and g.accuracy_dm < 255]
        acc_avg    = f"{sum(acc_values)/len(acc_values)/10:.1f} m" if acc_values else "—"

        stat_style = {
            "background": C["surface"], "border": f"1px solid {C['border']}",
            "borderRadius": "8px", "padding": "10px 18px", "textAlign": "center",
        }
        label_style = {"color": C["muted"], "fontSize": "0.72rem", "marginBottom": "2px"}
        value_style = {"color": C["accent"], "fontFamily": "'Overpass'", "fontSize": "1rem",
                       "fontWeight": "600"}

        stats_row = dbc.Row([
            dbc.Col(html.Div([
                html.Div("Punti GPS", style=label_style),
                html.Div(str(len(gr)), style=value_style),
            ], style=stat_style), xs=6, md=3),
            dbc.Col(html.Div([
                html.Div("Periodo registrato", style=label_style),
                html.Div(f"{date_from} → {date_to}",
                         style={**value_style, "fontSize": "0.78rem"}),
            ], style=stat_style), xs=6, md=3),
            dbc.Col(html.Div([
                html.Div("Distanza (odometro)", style=label_style),
                html.Div(f"{km_delta:,} km".replace(",", "."), style=value_style),
            ], style=stat_style), xs=6, md=3),
            dbc.Col(html.Div([
                html.Div("Precisione media", style=label_style),
                html.Div(acc_avg, style=value_style),
            ], style=stat_style), xs=6, md=3),
        ], className="g-2 mb-3")

        # Tabella waypoint (tutti i punti, scorrevole)
        gnss_table_rows = []
        for g in gr:
            acc_m = f"{g.accuracy_dm / 10:.1f} m" if g.accuracy_dm and g.accuracy_dm < 255 else "—"
            gnss_table_rows.append(html.Tr([
                html.Td(g.timestamp, style={"fontFamily": "'Overpass'", "fontSize": "0.78rem",
                                             "whiteSpace": "nowrap"}),
                html.Td(f"{g.lat:.5f}", style={"fontFamily": "'Overpass'", "fontSize": "0.75rem",
                                                 "textAlign": "right"}),
                html.Td(f"{g.lon:.5f}", style={"fontFamily": "'Overpass'", "fontSize": "0.75rem",
                                                 "textAlign": "right"}),
                html.Td(acc_m, style={"fontFamily": "'Overpass'", "fontSize": "0.75rem",
                                       "textAlign": "right", "color": C["muted"]}),
                html.Td(f"{g.odometer_km:,} km".replace(",", "."),
                        style={"fontFamily": "'Overpass'", "fontSize": "0.75rem",
                               "textAlign": "right", "color": C["muted"]}),
            ]))

        gnss_table = html.Div(
            html.Table([
                html.Thead(html.Tr([html.Th(h) for h in
                                    ["Data/Ora", "Latitudine", "Longitudine",
                                     "Precisione", "Odometro"]])),
                html.Tbody(gnss_table_rows),
            ], className="veh-table"),
            style={"maxHeight": "260px", "overflowY": "auto"},
        )

        # Banner contesto (mostrato solo con filtro attivo)
        context_banner = None
        if gnss_date:
            date_disp = datetime.strptime(gnss_date, "%Y-%m-%d").strftime("%d/%m/%Y")
            vrns = _vrns_for_date(gnss_date, cd.vehicle_sessions)
            vrn_text = ("  •  🚛 " + ", ".join(vrns)) if vrns else ""
            context_banner = html.Div([
                html.Span(
                    f"📅 Traccia GPS del {date_disp}{vrn_text}",
                    style={"color": C["accent"], "fontWeight": "500", "fontSize": "0.85rem"},
                ),
                html.Button(
                    "✕ Rimuovi filtro",
                    id="btn-gnss-clear",
                    n_clicks=0,
                    style={
                        "background": C["surface"], "border": f"1px solid {C['border']}",
                        "color": C["muted"], "borderRadius": "4px", "padding": "3px 10px",
                        "cursor": "pointer", "fontSize": "0.75rem",
                        "fontFamily": "'Overpass'", "marginLeft": "auto",
                    },
                ),
            ], style={
                "display": "flex", "alignItems": "center",
                "background": C["accent"] + "12",
                "border": f"1px solid {C['accent']}33",
                "borderRadius": "6px", "padding": "8px 14px",
                "marginBottom": "12px",
            })

        section_title = f"🗺️ Mappa GPS — {len(gr)} waypoint"
        if gnss_date:
            date_disp = datetime.strptime(gnss_date, "%Y-%m-%d").strftime("%d/%m/%Y")
            section_title += f" — {date_disp}"
        else:
            section_title += " registrati"

        gnss_children = []
        if context_banner:
            gnss_children.append(context_banner)
        gnss_children.extend([stats_row, map_graph, html.Div(gnss_table, style={"marginTop": "16px"})])

        gnss_section = section(section_title, *gnss_children)
        parts.append(gnss_section)

    return html.Div(parts)

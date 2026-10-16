"""
views/tabs/infrazioni.py
========================
Tab "Infrazioni": violazioni al Reg. CE 561/2006 e alla Dir. 2002/15/CE.

Schermata:
  - intestazione "Valido: <data scarico>"
  - ogni voce: Fallo + gravità, Periodo, Dettagli "misurato (soglia)"
  - menu: periodo 7 / 28 / 56 giorni / intero periodo (predefinito 56),
    filtro a stelle per gravità, filtro per tipo (6 gruppi), dettagli on/off
In più: contatori per gravità e spiegazione normativa di ogni tipo.

I filtri sono ricordati dal browser (persistence) e applicati dal callback in
controllers/violations_controller.py, che richiama build_list().
"""

from datetime import datetime, timedelta

from dash import dcc, html

from models.card_data import CardData
from models.violations import GROUPS, MI, MSI, SI, VSI, DESCRIPTIONS, violation_summary
from views.components import empty_state, section
from views.export_bar import bar_for
from views.theme import C

WARN_INFO = ("W", 0, "Avvertenza", "#5E666D")
SEV_INFO = [  # (codice, stelle, etichetta app, colore)
    (MSI, 4, "Infrazione più grave", "#991B1B"),
    (VSI, 3, "Infrazione molto grave", "#DC2626"),
    (SI, 2, "Infrazione grave", "#F97316"),
    (MI, 1, "Infrazione minore", "#F59E0B"),
]

PERIOD_OPTIONS = [("7", "Ultimi 7 giorni"), ("28", "Ultimi 28 giorni"),
                  ("56", "Ultimi 56 giorni"), ("all", "Intero periodo")]

# Riferimento normativo e spiegazione breve per ogni tipo (testi nostri)
NORMA = {
    "ContinuousDriving": "Reg. 561/2006 Art. 7 — dopo 4h30 di guida serve una pausa di almeno 45 min, frazionabile in 15 + 30 min.",
    "DayDriving_9": "Reg. 561/2006 Art. 6§1 — guida giornaliera max 9h; 10h al massimo 2 volte a settimana.",
    "DayDriving_10": "Reg. 561/2006 Art. 6§1 — anche nei giorni estesi la guida giornaliera non può superare 10h.",
    "WeekDriving_one": "Reg. 561/2006 Art. 6§2 — guida settimanale max 56h.",
    "WeekDriving_two": "Reg. 561/2006 Art. 6§3 — guida in due settimane consecutive max 90h.",
    "NightDrivingBus": "Reg. 561/2006 Art. 7 (servizi occasionali bus) — tra le 22 e le 6, in multipresenza, pausa dopo 3h di guida.",
    "Rest_DailyNormal_Fine": "Reg. 561/2006 Art. 8§2 — riposo giornaliero regolare di 11h entro 24h dalla fine del riposo precedente.",
    "Rest_DailySplit_Fine": "Reg. 561/2006 Art. 4(g) — riposo frazionato: prima 3h, poi 9h.",
    "Rest_DailyReduced_Fine": "Reg. 561/2006 Art. 8§4 — riposo ridotto almeno 9h, max 3 volte tra due riposi settimanali.",
    "Rest_DailyStaff_Fine": "Reg. 561/2006 Art. 8§5 — in multipresenza 9h di riposo entro 30h.",
    "Weekly_TooShort_45": "Reg. 561/2006 Art. 8§6 — in 2 settimane consecutive servono 2 riposi regolari di 45h, oppure 1 regolare e 1 ridotto (≥ 24h).",
    "Weekly_TooShort_24": "Reg. 561/2006 Art. 8§6 — il riposo settimanale ridotto non può essere inferiore a 24h.",
    "Weekly_TooLate": "Reg. 561/2006 Art. 8§6 — il riposo settimanale deve iniziare entro 6 periodi di 24h dal precedente.",
    "Weekly_TooLate_Bus": "Reg. 561/2006 Art. 8§6a — servizi occasionali bus: deroga fino a 12 periodi di 24h.",
    "Weekly_TooShort_Bus": "Reg. 561/2006 Art. 8§6a — dopo la deroga dei 12 giorni servono riposi più lunghi.",
    "Rest45InVehicle": "Reg. 561/2006 Art. 8§8 (dal 20/08/2020) — il riposo settimanale regolare non può essere trascorso nel veicolo.",
    "WeekWorking_48": "Dir. 2002/15/CE Art. 4 — orario medio settimanale max 48h sul periodo di riposo di riferimento.",
    "WeekWorking_60": "Dir. 2002/15/CE Art. 4 — orario settimanale max 60h.",
    "Working_IsNight_10": "Dir. 2002/15/CE Art. 7 — con lavoro notturno l'orario giornaliero non può superare 10h.",
    "ContinuousWorking_6": "Dir. 2002/15/CE Art. 5 — oltre 6h di lavoro servono almeno 30 min di pausa.",
    "ContinuousWorking_9": "Dir. 2002/15/CE Art. 5 — oltre 9h di lavoro servono almeno 45 min di pausa.",
    "ContinuousWorking_6S": "Dir. 2002/15/CE Art. 5 — non si può lavorare più di 6h consecutive senza pausa.",
    "Missing_CountryCode": "Reg. 165/2014 Art. 34§6(f) — il simbolo del paese va inserito all'inizio e alla fine del periodo di lavoro giornaliero.",
    "Missing_CountryCode_Border": "Reg. 165/2014 Art. 34§7 — dal 02/02/2022 va inserito il paese anche all'attraversamento di frontiera.",
    "Missing_ManualEntry": "Reg. 165/2014 Art. 34§3 — al reinserimento della carta vanno inserite a mano le attività svolte senza carta.",
    "Mode_Incorrect_Use": "Reg. 165/2014 Art. 34§5 — a fine giornata va selezionato il riposo sul tachigrafo.",
    "VirtualTravel": "Spostamento non registrato tra la fine e l'inizio di due periodi di lavoro in paesi diversi.",
    "VehicleCheck": "Controllo del veicolo prima della partenza (durata scelta nelle impostazioni).",
    "Weekly_TooShort_International": "Reg. 561/2006 Art. 8§6 (dal 20/08/2020) — nel trasporto merci internazionale due riposi settimanali ridotti consecutivi all'estero sono ammessi solo se compensati prima del riposo settimanale successivo e con almeno 4 riposi settimanali (2 regolari) in 4 settimane.",
    "FerryButtonInvalid": "Reg. 561/2006 Art. 9 — il riposo su traghetto o treno vale solo se il conducente dispone di una cabina letto o cuccetta.",
    "CardDownload_28": "Reg. UE 581/2010 — i dati della carta del conducente vanno scaricati almeno ogni 28 giorni.",
    "DataGap": "Tra due scarichi del conducente mancano dei dati: il periodo è considerato riposo, quindi le valutazioni vicine sono incerte.",
}

_SHORT = {  # nomi brevi per il filtro per tipo
    "DayDriving_9": "Guida giornaliera 9h", "DayDriving_10": "Guida giornaliera 10h",
    "ContinuousDriving": "Guida continua", "WeekDriving_one": "Guida settimanale",
    "WeekDriving_two": "Guida bisettimanale", "NightDrivingBus": "Guida notturna bus",
    "Rest_DailyNormal_Fine": "Riposo giornaliero regolare",
    "Rest_DailySplit_Fine": "Riposo giornaliero frazionato",
    "Rest_DailyReduced_Fine": "Riposo giornaliero ridotto",
    "Rest_DailyStaff_Fine": "Riposo in multipresenza",
    "Weekly_TooShort_45": "Riposo settimanale < 45h", "Weekly_TooShort_24": "Riposo settimanale < 24h",
    "Weekly_TooLate": "Riposo settimanale in ritardo", "Weekly_TooLate_Bus": "Riposo settimanale in ritardo (bus)",
    "Weekly_TooShort_Bus": "Riposo settimanale breve (bus)", "Rest45InVehicle": "Riposo nel veicolo",
    "WeekWorking_48": "Orario settimanale 48h", "WeekWorking_60": "Orario settimanale 60h",
    "Working_IsNight_10": "Lavoro notturno 10h", "ContinuousWorking_6": "Pause lavoro 6-9h",
    "ContinuousWorking_9": "Pause lavoro > 9h", "ContinuousWorking_6S": "Lavoro continuo > 6h",
    "Missing_CountryCode": "Simbolo paese", "Missing_CountryCode_Border": "Simbolo paese (frontiera)",
    "Missing_ManualEntry": "Inserimento manuale", "VirtualTravel": "Viaggio virtuale",
    "Mode_Incorrect_Use": "Uso del commutatore", "VehicleCheck": "Ispezione veicolo",
    "CardDownload_28": "Scarico carta entro 28 giorni",
    "Weekly_TooShort_International": "Due ridotti all'estero non compensati",
    "FerryButtonInvalid": "Commutatore traghetto/treno", "DataGap": "Dati mancanti",
}

_LABEL = {"fontSize": "0.74rem", "color": C["muted"], "fontWeight": "700", "marginBottom": "4px"}


def _valid_until(cd: CardData) -> datetime:
    """Fine della finestra: data dello scarico o, se assente, ultimo giorno di dati."""
    for txt in (cd.driver.last_download,):
        try:
            return datetime.strptime(txt, "%d/%m/%Y %H:%M")
        except (TypeError, ValueError):
            pass
    last = max((d.date for d in cd.activities), default=None)
    return datetime.fromisoformat(last) + timedelta(days=1) if last else datetime.now()


def _stars(n: int, color: str) -> html.Span:
    return html.Span("★" * n + "☆" * (4 - n), title=f"{n}/4",
                     style={"color": color, "letterSpacing": "1px"})


def _item(v, show_details: bool) -> html.Div:
    sev = next((s for s in SEV_INFO if s[0] == v.severity), WARN_INFO)
    warn = sev is WARN_INFO
    return html.Div([
        html.Div([
            html.Span("Avvertenza" if warn else "Fallo", style=_LABEL),
            html.Span([None if warn else _stars(sev[1], sev[3]),
                       html.Span(f"  {sev[2]}", style={"color": sev[3], "fontSize": "0.76rem",
                                                      "fontWeight": "600"})]),
        ], style={"display": "flex", "justifyContent": "space-between", "gap": "8px",
                  "flexWrap": "wrap"}),
        html.Div(v.description, style={"fontSize": "0.9rem", "fontWeight": "600",
                                       "margin": "2px 0 8px"}),
        html.Div("Periodo", style=_LABEL),
        html.Div(v.period, style={"fontFamily": "'Overpass'", "fontSize": "0.84rem",
                                  "marginBottom": "8px"}),
        html.Div([
            html.Div("Dettagli", style=_LABEL),
            html.Div(v.detail, style={"fontFamily": "'Overpass'", "fontSize": "0.84rem"}),
            html.Details([
                html.Summary("ℹ️ Norma", style={"cursor": "pointer", "color": C["muted"],
                                                "fontSize": "0.76rem", "marginTop": "6px"}),
                html.Div(NORMA.get(v.code, ""), style={"fontSize": "0.8rem",
                                                       "color": C["muted"], "padding": "4px 0"}),
            ]),
        ]) if show_details else None,
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderLeft": f"4px solid {sev[3]}", "borderRadius": "8px",
              "padding": "12px 14px", "marginBottom": "10px"},
        **{"data-code": v.code})


def filter_violations(cd: CardData, period: str, sevs, codes):
    """Applica i filtri del menu alle infrazioni del file."""
    # le infrazioni usano lo storico unito degli scarichi del conducente
    from models.history import violations_with_history
    viols = violations_with_history(cd)
    if period and period != "all":
        since = _valid_until(cd) - timedelta(days=int(period))
        viols = [v for v in viols if v.date >= since.date().isoformat()]
    sevs = set(sevs or [])
    codes = set(codes or [])
    # le avvertenze "Dati mancanti" sono sempre mostrate
    # le avvertenze (senza stelle) seguono solo il filtro per tipo
    return [v for v in viols if v.code == "DataGap"
            or (v.code in codes and (v.severity in sevs or v.severity == "W"))]


def build_list(cd: CardData, period: str, sevs, codes, details) -> html.Div:
    viols = filter_violations(cd, period, sevs, codes)
    vs = violation_summary(viols)
    counters = html.Div([
        html.Div([
            html.Div(str(vs[code]), className="stat-value", style={"color": color}),
            html.Div(label, className="stat-label"),
        ], className="stat-card", style={"borderColor": color + "33", "flex": "1",
                                          "minWidth": "140px"})
        for code, _, label, color in SEV_INFO
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"})

    if not viols:
        body = empty_state("✅ L'elenco dei falli è vuoto")
    else:
        show = bool(details)
        # Contenuto: dalla più recente alla più vecchia
        body = html.Div([_item(v, show) for v in reversed(viols)])
    return html.Div([counters, body])


def render(cd: CardData) -> html.Div:
    valid = _valid_until(cd)
    all_codes = [code for _, group in GROUPS for code in group]
    type_filter = html.Details([
        html.Summary("Filtro per tipo", style={"cursor": "pointer", "fontSize": "0.84rem"}),
        html.Div([
            html.Div([
                html.Div(title, style={**_LABEL, "marginTop": "10px"}),
                dcc.Checklist(
                    id={"type": "viol-code-filter", "group": i},
                    options=[{"label": f" {_SHORT.get(code, code)}", "value": code}
                             for code in group],
                    value=group, persistence=True, persistence_type="local",
                    labelStyle={"display": "block", "fontSize": "0.82rem", "color": C["text"]},
                ),
            ]) for i, (title, group) in enumerate(GROUPS)
        ], style={"display": "grid", "gridTemplateColumns": "repeat(auto-fill, minmax(240px, 1fr))",
                  "gap": "6px 20px"}),
    ], style={"marginTop": "10px"})

    filters = section(
        "Filtri",
        html.Div([
            html.Div([
                html.Div("Periodo", style=_LABEL),
                dcc.RadioItems(
                    id="viol-period", value="56", persistence=True, persistence_type="local",
                    options=[{"label": f" {lbl}", "value": val} for val, lbl in PERIOD_OPTIONS],
                    labelStyle={"display": "block", "fontSize": "0.82rem", "color": C["text"]},
                ),
            ]),
            html.Div([
                html.Div("Gravità", style=_LABEL),
                dcc.Checklist(
                    id="viol-sev", value=[s[0] for s in SEV_INFO], persistence=True,
                    persistence_type="local",
                    options=[{"label": html.Span([" ", _stars(n, col), f"  {lbl}"]),
                              "value": code} for code, n, lbl, col in SEV_INFO],
                    labelStyle={"display": "block", "fontSize": "0.82rem", "color": C["text"]},
                ),
            ]),
            html.Div([
                html.Div("Visualizzazione", style=_LABEL),
                dcc.Checklist(
                    id="viol-details", value=["on"], persistence=True, persistence_type="local",
                    options=[{"label": " Dettagli", "value": "on"}],
                    labelStyle={"fontSize": "0.82rem", "color": C["text"]},
                ),
            ]),
        ], style={"display": "flex", "gap": "40px", "flexWrap": "wrap"}),
        type_filter,
    )

    return html.Div([
        html.Div(f"Valido: {valid.strftime('%d/%m/%Y %H:%M')}",
                 style={"color": C["muted"], "fontSize": "0.84rem", "marginBottom": "12px"}),
        filters,
        bar_for(cd, "infringement", 56),
        html.Div(build_list(cd, "56", [s[0] for s in SEV_INFO], all_codes, ["on"]),
                 id="viol-list"),
    ])

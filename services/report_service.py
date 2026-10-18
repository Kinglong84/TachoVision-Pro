"""
services/report_service.py
==========================
Tutti i report esportabili.

| Report        | Formati                       | Nome file       |
|---------------|-------------------------------|-----------------|
| activities    | pdf, pdf_graph, csv           | ACTIVITIES_     |
| worktime      | pdf, csv                      | WORKTIME_       |
| vehicle       | pdf, csv                      | VEHICLEUSAGE_   |
| gps           | csv                           | VEHICLEGPS_     |
| country       | pdf, csv                      | COUNTRY_        |
| rest          | pdf                           | REST_           |
| infringement  | pdf                           | INFRINGEMENT_   |

Ogni report accetta il periodo Dal/Al (date locali).
L'Excel è un CSV con il separatore scelto nelle impostazioni (UTF-8 con BOM);
formato del CSV delle attività:
  "26/11/22 10:05:20";":";"Card In (AB123CD, 100000km)";"";"";
  "26/11/22 10:06:00";"#";"GUIDA";"";"01:22";
I PDF sono disegnati su pagina (A4, margini 28 pt, stessa intestazione e
piè di pagina): vedi services/pdf_canvas.py.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple

from models.card_data import CardData
from models.settings import Settings, load_settings
from models.timeline import Timeline

PREFIX = {"activities": "ACTIVITIES_", "worktime": "WORKTIME_", "vehicle": "VEHICLEUSAGE_",
          "gps": "VEHICLEGPS_", "country": "COUNTRY_", "rest": "REST_",
          "infringement": "INFRINGEMENT_"}
FORMATS = {"activities": ["pdf", "pdf_graph", "csv"], "worktime": ["pdf", "csv"],
           "vehicle": ["pdf", "csv"], "gps": ["csv"], "country": ["pdf", "csv"],
           "rest": ["pdf"], "infringement": ["pdf", "pdf_grouped"]}
FORMAT_LABEL = {"pdf": "Pdf", "pdf_graph": "Pdf (solo grafico)", "csv": "Excel",
                "pdf_grouped": "Pdf (raggruppato)"}
# opzioni aggiuntive del dialog di esportazione (es. campi firma delle infrazioni)
EXPORT_OPTIONS = {"infringement": [("sign", "Campi per la firma alla fine del rapporto")]}
TITLES = {"activities": "Attività", "worktime": "Riepilogo del tempo di lavoro",
          "vehicle": "Elenco di utilizzo del veicolo", "gps": "Posizioni GPS",
          "country": "Paesi visitati", "rest": "Periodi di riposo",
          "infringement": "Infrazioni"}

# nomi inglesi dei paesi nelle righe "#SYS#COUNTRY_<nome>|"
_COUNTRY_EN = {
    "AT": "Austria", "AL": "Albania", "AD": "Andorra", "AM": "Armenia", "AZ": "Azerbaijan",
    "BE": "Belgium", "BG": "Bulgaria", "BA": "Bosnia", "BY": "Belarus", "CH": "Switzerland",
    "CY": "Cyprus", "CZ": "CzechRep", "DE": "Germany", "DK": "Denmark", "ES": "Spain",
    "EE": "Estonia", "FR": "France", "FI": "Finland", "LI": "Liechtenstein",
    "FO": "FaroeIslands", "GB": "UnitedKingdom", "GE": "Georgia", "GR": "Greece",
    "HU": "Hungary", "HR": "Croatia", "IT": "Italy", "IE": "Ireland", "IS": "Iceland",
    "KZ": "Kazakhstan", "LU": "Luxembourg", "LT": "Lithuania", "LV": "Latvia", "MT": "Malta",
    "MC": "Monaco", "MD": "Moldova", "MK": "Macedonia", "NO": "Norway", "NL": "Netherlands",
    "PT": "Portugal", "PL": "Poland", "RO": "Romania", "SM": "SanMarino", "RU": "Russia",
    "SE": "Sweden", "SK": "Slovakia", "SI": "Slovenia", "TM": "Turkmenistan", "TR": "Turkey",
    "UA": "Ukraine", "VA": "VaticanCity", "YU": "Yugoslavia", "ME": "Montenegro",
    "RS": "Serbia", "UZ": "Uzbekistan", "TJ": "Tajikistan", "EC": "Europe", "EUR": "Europe",
    "WLD": "World",
}
_UPPER = {"Guida": "GUIDA", "Lavoro": "LAVORO", "Disponibilità": "DISPONIBILITÀ",
          "Riposo": "INTERRUZIONE/RIPOSO"}


# ── Utilità ──────────────────────────────────────────────────────────────────

def filename(report: str, fmt: str, cd: CardData) -> str:
    d = cd.driver
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{d.firstname}_{d.surname}".replace(" ", "_")
    ext = "csv" if fmt == "csv" else "pdf"
    return f"{PREFIX[report]}{name}_{d.card_number}_{stamp}.{ext}"


def _bounds(tl: Timeline, d_from: Optional[str], d_to: Optional[str]) -> Tuple[int, int]:
    """Periodo Dal/Al (date locali) → intervallo in minuti UTC."""
    a = tl.day_start(date.fromisoformat(d_from[:10])) if d_from else -10 ** 12
    b = tl.day_start(date.fromisoformat(d_to[:10]) + timedelta(days=1)) if d_to else 10 ** 12
    return a, b


def _csv(rows, s: Settings, header=None) -> str:
    """
    matrice di testi: ogni valore tra virgolette e seguito dal
    separatore delle impostazioni (anche l'ultimo), righe CRLF, UTF-8 con BOM.
    Le virgolette interne vengono tolte.
    """
    sep = s.csv_sep
    out = []
    for r in ([header] if header else []) + list(rows):
        out.append("".join('"' + ("" if c is None else str(c)).replace('"', "") + '"' + sep
                           for c in r) + "\r\n")
    return "﻿" + "".join(out)          # BOM: Excel riconosce l'UTF-8


def _dur(m: int, s: Settings) -> str:
    """"HH:MM" oppure ore decimali "00,00" (locale IT)."""
    m = max(0, int(m))
    if s.intervalformat == "HHHH":
        return f"{m / 60:05.2f}".replace(".", ",")
    return f"{m // 60:02d}:{m % 60:02d}"


def _iso(tl: Timeline, minute: int, with_time: bool = True) -> str:
    """"yyyy-MM-dd HH:mm" / "yyyy-MM-dd" nel fuso scelto."""
    return tl.local(minute).strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


# ── Report ───────────────────────────────────────────────────────────────────

def _activities(cd, s, fmt, d_from, d_to):
    tl = Timeline(cd.activities, s.timezone)
    if fmt == "csv":
        from models.vehicle_report import merged_sessions
        a, b = _bounds(tl, d_from, d_to)
        rows = [["", "", "", "", ""]]
        events = []
        for v in merged_sessions(cd):
            if v.first_use_utc:
                events.append((v.first_use_utc, f"Card In ({v.vrn}, {v.odo_begin_km}km)"))
            if v.last_use_utc:
                events.append((v.last_use_utc, f"Card Out ({v.vrn}, {v.odo_end_km}km)"))
        card_times = [t for t, _ in events]
        for p in cd.places:
            if p.ts_utc:
                txt = f"#SYS#COUNTRY_{_COUNTRY_EN.get(p.country, p.country)}|"
                # i km compaiono quando il paese è stato inserito durante
                # la sessione (non all'inserimento/estrazione della carta)
                if not any(abs(p.ts_utc - t) <= 60 for t in card_times):
                    txt += f" ({p.odometer_km}km)"
                events.append((p.ts_utc, txt))
        # condizioni specifiche: fuori ambito in inglese
        # (testo in inglese), traghetto/treno con i simboli "ǁᴥ" / "ᴥǁ"
        cond_txt = {"Inizio fuori ambito": "Out Of Scope Begin",
                    "Fine fuori ambito": "Out Of Scope End",
                    "Inizio traghetto/treno": "ǁᴥ", "Fine traghetto/treno": "ᴥǁ"}
        for sc in cd.specific_conditions:
            try:
                ts = datetime.strptime(sc.entry_time, "%d/%m/%Y %H:%M").replace(
                    tzinfo=timezone.utc).timestamp()
            except ValueError:
                continue
            if sc.condition_type in cond_txt:
                events.append((int(ts), cond_txt[sc.condition_type]))
        items = [(t / 60, 0, ":", txt, "", "") for t, txt in events if a <= t / 60 < b]
        last_seg = tl.segments[-1] if tl.segments else None
        for x in tl.segments:
            if not a <= x.start < b:
                continue
            # "?" = attività sconosciuta (carta estratta, nulla inserito);
            # ">>" = periodo a carta estratta inserito a mano
            name = "?" if x.unknown else _UPPER.get(x.activity, x.activity)
            flag = ">>" if x.manual and not x.unknown else ""
            dur = "" if x is last_seg else _dur(x.length, s)  # ultimo tratto ancora aperto
            items.append((x.start, 1, "#", name, flag, dur))
        for t, _, sym, txt, flag, dur in sorted(items, key=lambda i: (int(i[0]), i[1])):
            when = datetime.fromtimestamp(t * 60, tz=timezone.utc).astimezone(tl.tz)
            rows.append([when.strftime("%d/%m/%y %H:%M:%S"), sym, txt, flag, dur])
        return _csv(rows, s)
    # disegnato (services/pdf_canvas.py)
    from services.pdf_canvas import activities_pdf
    return activities_pdf(cd, s, d_from, d_to, graph_only=fmt == "pdf_graph")


def _worktime_csv(periods, tl, s, shift: bool, only_headers: bool, wage: bool) -> str:
    """
    Colonne secondo la vista mostrata:
      per giorno     DAY | | GUIDA LAVORO DISPONIBILITÀ INTERRUZIONE | [fascia (●)] | KM
      per turno      START STOP ΔT | | GUIDA LAVORO DISPONIBILITÀ INTERRUZIONE
                     INTERRUZIONE(€) ∑ | [fascia (●) + ∑] | KM
      solo sintesi   una riga per periodo con START/STOP (date) e i totali
    Ogni giorno del periodo ha la sua riga (anche a zero); una riga vuota separa i
    periodi. ∑ = Guida + Lavoro (+ Disponibilità se pagata) (+ interruzione pagata).
    """
    D = lambda m: _dur(m, s)
    km = lambda x: str(int(round(x.km)))
    pay_av, pay_brk = s.payedavailability, s.payedbreaktype != "NO"
    tot = lambda x: x.drive + x.work + (x.avail if pay_av else 0) + (x.brk if pay_brk else 0)
    G, L, DI, I = "GUIDA", "LAVORO", "DISPONIBILITÀ", "INTERRUZIONE"
    wage_h = [G + "(●)", L + "(●)", DI + "(●)", I + "(●)"]

    def wage_cells(w, with_sum):
        if not wage:
            return []
        if w is None:
            from models.worktime import Sums
            w = Sums()
        cells = [D(w.drive), D(w.work), D(w.avail), D(w.brk)]
        return cells + ([D(tot(w))] if with_sum else []) + [""]

    if shift:
        header = ["START", "STOP", "ΔT", "", G, L, DI, I, I + "(€)", "∑", ""] + \
                 (wage_h + ["∑", ""] if wage else []) + ["KM"]
    elif only_headers:
        header = ["START", "STOP", "", G, L, DI, I, "∑", ""] + \
                 (wage_h + ["∑", ""] if wage else []) + ["KM"]
    else:
        header = ["DAY", "", G, L, DI, I, ""] + (wage_h + [""] if wage else []) + ["KM"]
    rows = []
    for p in periods:
        if only_headers:
            start, stop = _iso(tl, p.start, False), _iso(tl, p.end - 1, False)
            sm = p.sums
            if shift:
                dt = sum(r.end - r.start for r in p.rows if r.kind == "shift")
                rows.append([start, stop, D(dt), "", D(sm.drive), D(sm.work), D(sm.avail),
                             D(sm.brk_all), D(sm.brk), D(tot(sm)), ""]
                            + wage_cells(p.wage, True) + [km(sm)])
            else:
                rows.append([start, stop, "", D(sm.drive), D(sm.work), D(sm.avail), D(sm.brk),
                             D(tot(sm)), ""] + wage_cells(p.wage, True) + [km(sm)])
            continue
        rows.append([""] * len(header))                 # riga vuota a inizio periodo
        for r in p.rows:
            sm = r.sums
            if shift and r.kind == "shift":
                rows.append([_iso(tl, r.start), _iso(tl, r.end), D(r.end - r.start), "",
                             D(sm.drive), D(sm.work), D(sm.avail), D(sm.brk_all), D(sm.brk),
                             D(tot(sm)), ""] + wage_cells(r.wage, True) + [km(sm)])
            elif not shift and r.kind == "day":
                rows.append([_iso(tl, r.start, False), "", D(sm.drive), D(sm.work),
                             D(sm.avail), D(sm.brk), ""] + wage_cells(r.wage, False) + [km(sm)])
    while rows and not any(rows[-1]):  # nessuna riga vuota finale
        rows.pop()
    return _csv(rows, s, header)


def _worktime(cd, s, fmt, d_from, d_to, view="monthly_day", options=(), order="inc_inc"):
    from models.worktime import build_worktime
    tl = Timeline(cd.activities, s.timezone)
    a, b = _bounds(tl, d_from, d_to)
    # il periodo scelto si allarga a settimane/mesi interi
    periods = [p for p in build_worktime(cd, view, s, order) if p.start < b and p.end > a]
    if fmt == "csv":
        return _worktime_csv(periods, tl, s, view.endswith("_shift"), "header" in options,
                             "wage" in options and s.wage_period is not None)
    # disegnato (services/pdf_canvas.py)
    from services.pdf_canvas import worktime_pdf
    return worktime_pdf(cd, s, periods, d_from, d_to, options)


def _vehicle(cd, s, fmt, d_from, d_to):
    from models.vehicle_report import vehicle_periods
    tl = Timeline(cd.activities, s.timezone)
    a, b = _bounds(tl, d_from, d_to)
    periods = vehicle_periods(cd, s, "month", "inc_inc")
    if fmt == "csv":
        # una riga per sessione;
        # "ʘ" = ha guidato, "◊" = disponibilità nella sessione
        rows = [[_iso(tl, r.start), _iso(tl, r.end), _dur(r.end - r.start, s), r.vrn,
                 "ʘ" if r.drive > 0 else "", "◊" if r.avail > 0 else "",
                 r.odo_begin, r.odo_end, r.km]
                for p in periods for r in p.rows if r.start < b and r.end >= a]
        return _csv(rows, s, ["BEGIN", "END", "ΔT", "", "GUIDA", "DISPONIBILITÀ",
                              "BEGIN (KM)", "END (KM)", "KM"])
    from services.pdf_canvas import vehicle_pdf
    rows = [r for p in periods for r in p.rows if r.start < b and r.end >= a]
    return vehicle_pdf(cd, s, rows, d_from, d_to)


def _gps(cd, s, fmt, d_from, d_to):
    """
    (VEHICLEGPS_)
    TIME | | VEHICLE | KM | TYPE | | LATITUDE | LONGITUDE | | GOOGLE MAP
    TYPE: WORK BEGIN / WORK END (luoghi), GO (guida accumulata ogni 3 h).
    """
    from models.vehicle_report import merged_sessions, vehicle_at
    tl = Timeline(cd.activities, s.timezone)
    a, b = _bounds(tl, d_from, d_to)
    sessions = merged_sessions(cd)
    points = []
    for g in cd.gnss_records or []:
        points.append((g.timestamp, "GO", g.lat, g.lon, g.odometer_km))
    for p in cd.places:
        if p.gnss_lat is not None:
            points.append((p.datetime, "WORK BEGIN" if p.entry_type == "Inizio" else "WORK END",
                           p.gnss_lat, p.gnss_lon, p.odometer_km))
    rows = []
    for ts, kind, lat, lon, odo in points:
        m = int(datetime.strptime(ts, "%d/%m/%Y %H:%M").replace(tzinfo=timezone.utc)
                .timestamp() // 60)
        if a <= m < b:
            rows.append((m, [_iso(tl, m), "", vehicle_at(cd, m, sessions), odo, kind, "",
                             f"{lat:.6f}", f"{lon:.6f}", "",
                             f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"]))
    rows.sort(key=lambda r: r[0])
    return _csv([r for _, r in rows], s, ["TIME", "", "VEHICLE", "KM", "TYPE", "", "LATITUDE",
                                          "LONGITUDE", "", "GOOGLE MAP"])


def _country(cd, s, fmt, d_from, d_to):
    from models.vehicle_report import country_stays
    tl = Timeline(cd.activities, s.timezone)
    a, b = _bounds(tl, d_from, d_to)
    stays, only_base = country_stays(cd, s)
    stays = [x for x in stays if x.start < b and x.end >= a]
    if fmt == "csv":
        # (COUNTRY_); ΔKM solo se il veicolo
        # all'uscita è lo stesso dell'entrata
        D = lambda m: _dur(m, s)
        rows = [[_iso(tl, x.start), _iso(tl, x.end), D(x.end - x.start), x.name,
                 x.vrn_in, x.km_in, x.vrn_out, x.km_out,
                 x.distance if x.vrn_in and x.vrn_in == x.vrn_out else "",
                 D(x.drive), D(x.work), D(x.avail), D(x.brk)] for x in stays]
        return _csv(rows, s, ["BEGIN", "END", "ΔT", "COUNTRY", "VEHICLE (ENTER)", "KM (ENTER)",
                              "VEHICLE (EXIT)", "KM (EXIT)", "ΔKM", "GUIDA", "LAVORO",
                              "DISPONIBILITÀ", "INTERRUZIONE/RIPOSO"])
    from services.pdf_canvas import country_pdf
    return country_pdf(cd, s, stays, only_base, d_from, d_to)


def _rest(cd, s, fmt, d_from, d_to):
    from models.rest_report import build_report
    from services.pdf_canvas import rest_pdf
    tl = Timeline(cd.activities, s.timezone)
    a, b = _bounds(tl, d_from, d_to)
    items = [it for it in build_report(cd.activities, cd, s).items if a <= it.start < b]
    return rest_pdf(cd, s, items, d_from, d_to)


def _infringement(cd, s, fmt, d_from, d_to, options=()):
    from services.pdf_canvas import infringement_pdf
    from models.history import violations_with_history
    viols = [v for v in violations_with_history(cd, s)
             if (not d_from or v.date >= d_from[:10]) and (not d_to or v.date <= d_to[:10])]
    return infringement_pdf(cd, s, viols, d_from, d_to, grouped=fmt == "pdf_grouped",
                            signature="sign" in (options or ()))


_BUILDERS = {"activities": _activities, "worktime": _worktime, "vehicle": _vehicle,
             "gps": _gps, "country": _country, "rest": _rest, "infringement": _infringement}


def generate(report: str, fmt: str, cd: CardData, d_from: str = None, d_to: str = None,
             settings: Settings = None, view: dict = None, options=None):
    """
    Ritorna (contenuto bytes|str, nome file).
    view: stato della schermata da cui si esporta (per il riepilogo:
    {"view": "monthly_day", "options": ["header", "wage"], "order": "inc_inc"}).
    """
    s = settings or load_settings()
    if fmt not in FORMATS.get(report, []):
        raise ValueError(f"Formato {fmt} non disponibile per {report}")
    extra = {}
    if report == "worktime" and view:
        extra = {k: view[k] for k in ("view", "options", "order") if view.get(k) is not None}
    if report == "infringement":
        extra = {"options": options or []}
    return _BUILDERS[report](cd, s, fmt, d_from, d_to, **extra), filename(report, fmt, cd)

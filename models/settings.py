"""
models/settings.py
==================
Impostazioni utente di TachoVision Pro.

Tutte le impostazioni modificabili del programma
(stessi nomi delle chiavi, per riconoscerle).
Nomi dei campi = chiavi delle impostazioni, con i loro valori predefiniti.

Le impostazioni sono descritte in modo dichiarativo in SPEC: la view
(views/tabs/impostazioni.py) genera la pagina da questa lista, i modelli
(violations, analytics…) leggono i valori con load_settings().

Salvataggio: ~/TachoVision/impostazioni.json (accanto all'archivio).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

SETTINGS_FILE = Path.home() / "TachoVision" / "impostazioni.json"


@dataclass(frozen=True)
class SettingSpec:
    """Descrizione di una singola impostazione."""
    key: str                 # nome del campo (chiave delle impostazioni)
    section: str             # sezione della pagina
    label: str               # etichetta (testo italiano)
    kind: str                # "bool" | "select" | "int" | "text"
    default: Any
    options: Optional[List[tuple]] = None   # [(valore, etichetta)] per "select"
    on_text: str = ""        # descrizione stato acceso (bool)
    off_text: str = ""       # descrizione stato spento (bool)
    help: str = ""
    min: Optional[int] = None
    max: Optional[int] = None


# ── Sezioni (ordine e titoli ──────────────────────────────────
SECTIONS = [
    ("general",     "⚙️", "Impostazioni di base"),
    ("legislation", "⚖️", "Legislazioni"),
    ("worktime",    "⏱",  "Riepilogo del tempo di lavoro"),
    ("accessories", "🔔", "Accessori"),
    ("design",      "🎨", "Aspetto"),
]

# ── Opzioni ──────────────────────────────────────────────────────────────────
# Paesi (codici ISO usati dal parser per i luoghi)
COUNTRY_OPTIONS = [
    ("", "— non impostato —"),
    ("AL", "Albania"), ("AD", "Andorra"), ("AM", "Armenia"), ("AT", "Austria"),
    ("AZ", "Azerbaigian"), ("BY", "Bielorussia"), ("BE", "Belgio"),
    ("BA", "Bosnia-Erzegovina"), ("BG", "Bulgaria"), ("HR", "Croazia"),
    ("CY", "Cipro"), ("CZ", "Repubblica Ceca"), ("DK", "Danimarca"),
    ("EE", "Estonia"), ("FO", "Isole Faroe"), ("FI", "Finlandia"),
    ("FR", "Francia"), ("GE", "Georgia"), ("DE", "Germania"), ("GR", "Grecia"),
    ("HU", "Ungheria"), ("IS", "Islanda"), ("IE", "Irlanda"), ("IT", "Italia"),
    ("KZ", "Kazakistan"), ("KG", "Kirghizistan"), ("LV", "Lettonia"), ("LI", "Liechtenstein"),
    ("LT", "Lituania"), ("LU", "Lussemburgo"), ("MK", "Macedonia del Nord"),
    ("MT", "Malta"), ("MD", "Moldavia"), ("MC", "Monaco"), ("ME", "Montenegro"),
    ("NL", "Paesi Bassi"), ("NO", "Norvegia"), ("PL", "Polonia"),
    ("PT", "Portogallo"), ("RO", "Romania"), ("RU", "Russia"),
    ("SM", "San Marino"), ("RS", "Serbia"), ("SK", "Slovacchia"),
    ("SI", "Slovenia"), ("ES", "Spagna"), ("SE", "Svezia"), ("CH", "Svizzera"),
    ("TJ", "Tagikistan"), ("TR", "Turchia"), ("TM", "Turkmenistan"),
    ("UA", "Ucraina"), ("GB", "Regno Unito"), ("UZ", "Uzbekistan"),
    ("VA", "Città del Vaticano"),
]

# NIGHTPERIOD: valore app 1..10 → (ora inizio, ora fine)
NIGHT_PERIODS = {1: (0, 4), 2: (0, 5), 3: (0, 6), 4: (0, 7), 5: (1, 5),
                 6: (1, 6), 7: (1, 7), 8: (2, 6), 9: (2, 7), 10: (3, 7)}

# WORKINGTIMEFRAME: valore app 0..5 → settimane del periodo di riferimento
WORKING_TIMEFRAMES = {0: 4, 1: 9, 2: 13, 3: 17, 4: 22, 5: 26}
_TIMEFRAME_LABELS = {4: "1 mese", 9: "2 mesi", 13: "3 mesi", 17: "4 mesi",
                     22: "5 mesi", 26: "6 mesi"}

# HIGHERWAGEPERIOD: 0 = off, 1..35 = inizio (20,21,22,23,0,18,19) × fine (4..8)
_WAGE_STARTS = [20, 21, 22, 23, 0, 18, 19]
_WAGE_ENDS = [4, 5, 6, 7, 8]


def higher_wage_period(value: int) -> Optional[tuple]:
    """Ritorna (ora_inizio, ora_fine) della fascia salariale maggiorata o None."""
    if not value or value < 1 or value > 35:
        return None
    return _WAGE_STARTS[(value - 1) // 5], _WAGE_ENDS[(value - 1) % 5]


def _wage_options():
    opts = [(0, "Spento")]
    for v in range(1, 36):
        s, e = higher_wage_period(v)
        opts.append((v, f"{s:02d}:00 - {e:02d}:00"))
    return opts


# PAYEDBREAKTYPE: tipo di pausa retribuita 
_BREAK_MINUTES = [15, 30, 45, 60, 90, 120]
PAYED_BREAK_OPTIONS = (
    [("NO", "Le pause non vengono pagate"),
     ("ALL", "Ogni pausa viene pagata"),
     ("ALL_EXCEPTREQUIRED", "Ogni pausa viene pagata (tranne i 45 min richiesti)")]
    + [(f"SHORT{m}", f"Vengono pagate solo pause brevi (< {m} min)") for m in _BREAK_MINUTES]
    + [(f"ALL_EXCEPTFIRST{m}", f"Ogni pausa viene pagata (tranne i primi {m} min)")
       for m in _BREAK_MINUTES]
)

LANGUAGE_OPTIONS = [
    ("it", "Italiano"), ("en", "English"), ("de", "Deutsch"), ("fr", "Français"),
    ("es", "Español"), ("pt", "Português"), ("nl", "Nederlands"), ("pl", "Polski"),
    ("ro", "Română"), ("hu", "Magyar"), ("cs", "Český"), ("sk", "Slovenčina"),
    ("sl", "Slovenščina"), ("hr", "Hrvatski"), ("sr", "Cрпски"), ("bg", "Български"),
    ("el", "Ελληνικά"), ("tr", "Türk"), ("ru", "Pусский"), ("uk", "Український"),
    ("lt", "Lietuvis"), ("lv", "Latviešu"), ("et", "Eesti"), ("fi", "Suomen"),
    ("sv", "Svenska"), ("da", "Dansk"), ("nb", "Norsk"),
]

# GRAPHCOLORSCHEMA: palette (Guida, Lavoro, Disponibilità, Riposo)
COLOR_SCHEMAS = {
    1: ("Standard", ("#a048a0", "#f8a028", "#787878", "#00a4e8")),
    2: ("Solid",    ("#ff6347", "#6495ed", "#daa520", "#8fbc8b")),
    3: ("Pastel",   ("#da6158", "#ca62db", "#89aa8c", "#3e62a0")),
    4: ("Flower",   ("#ff362c", "#52a347", "#fec047", "#3736f4")),
    5: ("Shrill",   ("#ff0000", "#0000ff", "#f0f000", "#00ff00")),
}

TIMEZONE_OPTIONS = [("", "Predefinito (sistema)"), ("UTC", "UTC")] + [
    (f"Europe/{c}", f"Europe/{c}") for c in (
        "Amsterdam", "Athens", "Belgrade", "Berlin", "Bratislava", "Brussels",
        "Bucharest", "Budapest", "Chisinau", "Copenhagen", "Dublin", "Helsinki",
        "Istanbul", "Kiev", "Lisbon", "Ljubljana", "London", "Luxembourg",
        "Madrid", "Minsk", "Moscow", "Nicosia", "Oslo", "Paris", "Podgorica",
        "Prague", "Riga", "Rome", "Sarajevo", "Skopje", "Sofia", "Stockholm",
        "Tallinn", "Tirane", "Vienna", "Vilnius", "Warsaw", "Zagreb", "Zurich")]


# ── Specifica di tutte le impostazioni ───────────────────────────────────────
SPEC: List[SettingSpec] = [
    # Impostazioni di base
    SettingSpec("language", "general", "Lingua", "select", "it", LANGUAGE_OPTIONS),
    SettingSpec("timezone", "general", "Fuso orario", "select", "Europe/Rome",
                TIMEZONE_OPTIONS, help="Fuso usato per mostrare orari e giorni"),
    SettingSpec("filetype", "general", "Formato del nome del file", "select", "DDD",
                [("DDD", "Digital Download Data (.DDD)"),
                 ("ESM", "External Storage Medium (.esm)"),
                 ("TGD", "Spanish Binary Data (.tgd)"),
                 ("C1B", "Carte Appendix 1 B (.C1B)")]),
    SettingSpec("compatibilitylevel", "general", "Livello di compatibilità della carta",
                "select", 3,
                [(1, "Lettura solo dati di tipo G1"),
                 (2, "Lettura dei dati di tipo G2v1 (incluso G1)"),
                 (3, "Lettura di dati di tipo G2v2 (inclusi G1 e G2v1)")]),
    SettingSpec("cardstamping", "general", "Timestamp della carta", "bool", True,
                on_text="Il timestamp del download sarà scritto sulla scheda",
                off_text="Il timestamp del download non verrà scritto sulla scheda ⚠️"),
    SettingSpec("fastcardreading", "general", "Lettura rapida delle carte", "bool", True,
                on_text="Lettura della carta con impostazioni ottimizzate",
                off_text="Lettura della carta con impostazioni predefinite"),

    # Legislazioni
    SettingSpec("basecountry", "legislation", "Paese base", "select", "IT",
                COUNTRY_OPTIONS,
                help="Serve per paesi esteri, rientro a casa e riposo internazionale"),
    SettingSpec("isbus", "legislation", "Trasporto passeggeri in autobus", "bool", False,
                on_text="Periodo di riposo settimanale non più di ogni 12 giorni",
                off_text="Periodo di riposo settimanale non più di ogni 6 giorni"),
    SettingSpec("workingtimeframe", "legislation", "Cornice di lavoro", "select", 3,
                [(k, f"{_TIMEFRAME_LABELS[w]} ({w} settimane)")
                 for k, w in WORKING_TIMEFRAMES.items()],
                help="Periodo di riferimento per la media di 48 ore settimanali"),
    SettingSpec("holidayhours", "legislation", "Orario di lavoro giornaliero (ferie)",
                "int", 8, min=0, max=24,
                help="Ore di lavoro accreditate per ogni giorno di ferie"),
    SettingSpec("nightperiod", "legislation", "Periodo notturno", "select", 1,
                [(k, f"{s:02d}:00 - {e:02d}:00") for k, (s, e) in NIGHT_PERIODS.items()]),
    SettingSpec("dailyworkinglimitbynightwork", "legislation",
                "Il lavoro notturno non limita l'orario di lavoro giornaliero", "bool", False,
                on_text="L'orario di lavoro può essere superiore a 10 ore ⚠️",
                off_text="L'orario di lavoro massimo è di 10 ore"),
    SettingSpec("worknotbeginatcardin", "legislation",
                "L'inserimento della tessera non influisce sull'inizio dell'orario di lavoro",
                "bool", False,
                on_text="L'orario di lavoro inizia solo con la prima attività ⚠️",
                off_text="L'orario di lavoro inizia quando si inserisce la tessera"),
    SettingSpec("availibilityisbreak", "legislation",
                "La disponibilità può essere considerata una interruzione", "bool", False,
                on_text="La disponibilità può interrompere il lavoro continuo ⚠️",
                off_text="La disponibilità non interrompe il lavoro continuo"),
    SettingSpec("shortbreakisnotwork", "legislation",
                "Brevi pause (<15 min) non sono considerate lavoro", "bool", False,
                on_text="Le pause brevi non sono incluse nell'orario di lavoro ⚠️",
                off_text="Le pause brevi sono incluse nell'orario di lavoro"),
    SettingSpec("vehiclecheck", "legislation", "La durata dell'ispezione del veicolo",
                "select", 0,
                [(0, "Non è previsto un periodo di ispezione"), (1, "5 min"),
                 (2, "10 min"), (3, "15 min")]),

    # Riepilogo del tempo di lavoro
    SettingSpec("firstdayofweek", "worktime", "Primo giorno della settimana", "select", 1,
                [(1, "Settimana: lunedì 00:00 - domenica 23:59"),
                 (0, "Settimana: domenica 00:00 - sabato 23:59")]),
    SettingSpec("firstdayofmonth", "worktime", "Primo giorno del mese", "int", 1,
                min=1, max=28, help="Il periodo mensile va dal giorno N al giorno N-1"),
    SettingSpec("higherwageperiod", "worktime", "Periodo salariale superiore", "select", 0,
                _wage_options()),
    SettingSpec("payedavailability", "worktime", "Disponibilità a pagamento", "bool", False,
                on_text="Tutti i periodi di disponibilità sono pagati",
                off_text="I periodi di disponibilità non sono retribuiti"),
    SettingSpec("payedbreaktype", "worktime", "Interruzione pagata", "select", "SHORT15",
                PAYED_BREAK_OPTIONS),

    # Accessori
    SettingSpec("warning28day", "accessories", "Avviso ogni 28 giorni", "bool", True,
                on_text="Acceso", off_text="Spento"),
    SettingSpec("automaticbackup", "accessories", "Backup automatico", "bool", False,
                on_text="Backup automatico settimanale", off_text="Spento"),
    SettingSpec("automaticread", "accessories",
                "A partire se il lettore di schede è rilevabile", "bool", False,
                on_text="Acceso", off_text="Spento"),
    SettingSpec("email", "accessories", "Destinatario principale delle e-mail", "text", ""),
    SettingSpec("automaticsend", "accessories", "Invio automatico dopo la lettura", "bool",
                False, on_text="Acceso", off_text="Spento"),
    SettingSpec("csvseparator", "accessories", "Separatore di celle di Excel", "select", 0,
                [(0, "Virgola"), (1, "Punto e virgola")]),

    # Aspetto
    SettingSpec("intervalformat", "design", "Formato della durata", "select", "HHMM",
                [("HHMM", "oo:mm  (04:30 = 04.50)"), ("HHHH", "oo.oo  (04.50 = 04:30)")]),
    SettingSpec("distanceunit", "design", "Unità di distanza", "select", "KILOMETER",
                [("KILOMETER", "Chilometro"), ("MILES", "Miglia")]),
    SettingSpec("graphcolorschema", "design", "Colori del grafico", "select", 1,
                [(k, name) for k, (name, _) in COLOR_SCHEMAS.items()]),
]

SPEC_BY_KEY: Dict[str, SettingSpec] = {s.key: s for s in SPEC}


@dataclass
class Settings:
    """Valori correnti di tutte le impostazioni (accesso: s.get('isbus') o s.isbus)."""
    values: Dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name):
        if name == "values":
            raise AttributeError(name)
        if name in SPEC_BY_KEY:
            return self.values.get(name, SPEC_BY_KEY[name].default)
        raise AttributeError(name)

    def get(self, key: str):
        return getattr(self, key)

    # ── Valori derivati, usati dai modelli ──
    @property
    def night_hours(self) -> tuple:
        return NIGHT_PERIODS.get(self.nightperiod, (0, 4))

    @property
    def reference_weeks(self) -> int:
        return WORKING_TIMEFRAMES.get(self.workingtimeframe, 17)

    @property
    def vehicle_check_min(self) -> int:
        return {1: 5, 2: 10, 3: 15}.get(self.vehiclecheck, 0)

    @property
    def wage_period(self) -> Optional[tuple]:
        return higher_wage_period(self.higherwageperiod)

    @property
    def colors(self) -> Dict[str, str]:
        _, (g, l, d, r) = COLOR_SCHEMAS.get(self.graphcolorschema, COLOR_SCHEMAS[1])
        return {"Guida": g, "Lavoro": l, "Disponibilità": d, "Riposo": r}

    @property
    def csv_sep(self) -> str:
        return ";" if self.csvseparator == 1 else ","

    def to_dict(self) -> Dict[str, Any]:
        return {s.key: self.get(s.key) for s in SPEC}


def coerce(key: str, value: Any) -> Any:
    """Converte un valore arrivato dalla UI nel tipo previsto dalla specifica."""
    spec = SPEC_BY_KEY[key]
    if value is None:
        return spec.default
    if spec.kind == "bool":
        if isinstance(value, list):        # dcc.Checklist → lista
            return bool(value)
        return bool(value)
    if spec.kind == "int":
        try:
            v = int(value)
        except (TypeError, ValueError):
            return spec.default
        if spec.min is not None:
            v = max(spec.min, v)
        if spec.max is not None:
            v = min(spec.max, v)
        return v
    if spec.kind == "select":
        allowed = [o[0] for o in spec.options]
        for a in allowed:                  # i valori dalla UI possono arrivare come str
            if str(a) == str(value):
                return a
        return spec.default
    return str(value).strip()


def load_settings(path: Path = None) -> Settings:
    """Legge le impostazioni dal file JSON (valori mancanti/invalidi → default)."""
    path = path or SETTINGS_FILE
    values: Dict[str, Any] = {}
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            values = {k: coerce(k, v) for k, v in raw.items() if k in SPEC_BY_KEY}
    except (OSError, ValueError) as e:
        log.warning("Impostazioni non leggibili (%s): uso i predefiniti", e)
    return Settings(values)


def save_settings(settings: Settings, path: Path = None) -> None:
    path = path or SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8")


def default_settings() -> Settings:
    """"""
    return Settings({})

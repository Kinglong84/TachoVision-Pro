"""
views/i18n.py
=============
Lingua dell'interfaccia.

I testi restano scritti in italiano nel codice. Al momento di inviare i componenti
al browser (vedi `views.theme.install_theme_vars`) i testi visibili — children,
etichette delle opzioni, placeholder, title, testi dei grafici — passano da `tr()`,
che li cerca nel dizionario della lingua scelta (`locales/<lingua>.json`).

Il dizionario ha due parti:
  "texts":     { "testo italiano": "traduzione" }        corrispondenza esatta
  "templates": { "Giornata {} di {}": "Day {} of {}" }    testi con parti variabili

Un testo non trovato resta in italiano. Emoji/simboli iniziali e punteggiatura
finale (":", "…", spazi) sono tenuti da parte e rimessi dopo la traduzione.
"""

import json
import os
import re
from functools import lru_cache

LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "locales")

_LANG = {"code": None, "mtime": None, "forced": None}
JS_TEXTS = ("risultati", "Espandi sidebar", "Comprimi sidebar")   # testi in assets/*.js
RECORD = None          # set() per raccogliere i testi (strumento di sviluppo)


def current_lang() -> str:
    """Lingua delle impostazioni (riletta solo se il file impostazioni cambia)."""
    if _LANG["forced"]:
        return _LANG["forced"]
    from models import settings as _s
    try:
        mtime = os.path.getmtime(_s.SETTINGS_FILE)
    except OSError:
        mtime = None
    if _LANG["code"] is None or mtime != _LANG["mtime"]:
        try:
            _LANG["code"] = _s.load_settings().get("language") or "it"
        except Exception:
            _LANG["code"] = "it"
        _LANG["mtime"] = mtime
    return _LANG["code"]


def set_lang(code: str = None):
    """Fissa la lingua (dopo il salvataggio delle impostazioni, nei test);
    None torna a leggerla dal file delle impostazioni."""
    _LANG["forced"] = code
    _LANG["code"] = None


@lru_cache(maxsize=None)
def _catalog(code: str):
    path = os.path.join(LOCALES_DIR, f"{code}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}, []
    texts = {}
    templates = []
    pairs = {**data.get("texts", {}), **data.get("templates", {})}
    if "ids" in data:                     # dizionario numerato sull'elenco base
        keys = base_keys()
        for n, dst in data["ids"].items():
            i = int(n)
            if 0 <= i < len(keys) and dst:
                pairs[keys[i]] = dst
    pairs.update(_GENERIC)
    for src, dst in pairs.items():
        if "{}" in src:
            parts = [re.escape(p) for p in src.split("{}")]
            rx = re.compile("^" + "(.+?)".join(parts) + "$", re.S)
            # i modelli con più testo fisso (più specifici) vengono provati prima
            templates.append((len(src.replace("{}", "")), rx, dst))
        else:
            texts[src] = dst
            h, core, t = _split(src)
            if core and core != src:
                texts.setdefault(core, _split(dst)[1] or dst)
    templates.sort(key=lambda t: -t[0])
    return texts, [(rx, dst) for _, rx, dst in templates]


# separatori: valgono per tutte le lingue (i pezzi vengono tradotti uno per uno)
_GENERIC = {"{} ({})": "{} ({})", "{} — {}": "{} — {}", "{} - {}": "{} - {}",
            "{}: {}": "{}: {}", "{} · {}": "{} · {}", "{} → {}": "{} → {}"}


@lru_cache(maxsize=1)
def base_keys():
    """Testi italiani numerati (locales/_base.json) a cui si riferiscono i dizionari "ids"."""
    try:
        with open(os.path.join(LOCALES_DIR, "_base.json"), encoding="utf-8") as f:
            return json.load(f)["keys"]
    except (OSError, ValueError, KeyError):
        return []


def reload_catalogs():
    _catalog.cache_clear()
    _translate.cache_clear()


def _is_letter(ch: str) -> bool:
    # "ℹ" e gli altri simboli letterali (U+2100-214F) non sono parole
    return ch.isalpha() and not ("℀" <= ch <= "⅏")


def _split(text: str):
    """(testa, nucleo, coda): il nucleo va dalla prima all'ultima lettera; prima e dopo
    restano emoji, simboli, numeri, orari e punteggiatura."""
    idx = [i for i, ch in enumerate(text) if _is_letter(ch)]
    if not idx:
        return text, "", ""
    return text[:idx[0]], text[idx[0]:idx[-1] + 1], text[idx[-1] + 1:]


def _apply_templates(text, texts, templates, depth):
    for rx, dst in templates:
        m = rx.match(text)
        if not m:
            continue
        hit = False
        vals = []
        for g in m.groups():
            v = _lookup(g, texts, templates, depth + 1)
            hit = hit or v is not None
            vals.append(g if v is None else v)
        # un modello generico ("{} ({})") vale solo se traduce almeno un pezzo
        if not hit and not dst.replace("{}", "").strip(" ()-—:·,/"):
            continue
        out = dst
        for v in vals:
            out = out.replace("{}", v, 1)
        return out
    return None


def _lookup(text, texts, templates, depth=0):
    if depth > 6 or not text:
        return None
    if text in texts:
        return texts[text]
    head, core, tail = _split(text)
    if not core:
        return None
    if core in texts:
        return head + texts[core] + tail
    out = _apply_templates(text, texts, templates, depth)
    if out is None and head:                       # senza emoji/simboli iniziali
        out = _apply_templates(text[len(head):], texts, templates, depth)
        if out is not None:
            out = head + out
    if out is None and core != text:
        out = _apply_templates(core, texts, templates, depth)
        if out is not None:
            out = head + out + tail
    return out


@lru_cache(maxsize=50000)
def _translate(text: str, code: str) -> str:
    texts, templates = _catalog(code)
    if not texts and not templates:
        return text
    hit = _lookup(text, texts, templates)
    return text if hit is None else hit


def tr(text: str, code: str = None) -> str:
    """Traduce un testo dell'interfaccia nella lingua scelta (italiano = invariato)."""
    if not isinstance(text, str) or not text.strip():
        return text
    if RECORD is not None:
        RECORD.add(text)
    code = code or current_lang()
    if code == "it":
        return text
    return _translate(text, code)


# ── Applicazione ai componenti ────────────────────────────────────────────────────
_TEXT_PROPS = {"children", "placeholder", "title", "label", "value_text",
               "children_text", "message", "tooltip"}
_FIG_KEYS = {"text", "name", "title", "ticktext"}


def _tr_options(opts):
    out = []
    for o in opts:
        if isinstance(o, dict) and isinstance(o.get("label"), str):
            o = {**o, "label": tr(o["label"])}
        out.append(o)
    return out


def _tr_figure(obj, key=""):
    if isinstance(obj, dict):
        return {k: _tr_figure(v, k) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        if key in _FIG_KEYS:
            return [tr(v) if isinstance(v, str) else _tr_figure(v) for v in obj]
        return [_tr_figure(v) for v in obj]
    if isinstance(obj, str) and key in _FIG_KEYS:
        return tr(obj)
    return obj


def translate_props(type_name: str, props: dict):
    """Traduce sul posto i testi visibili di un componente serializzato."""
    for k, v in list(props.items()):
        if v is None:
            continue
        if k in _TEXT_PROPS:
            if isinstance(v, str):
                props[k] = tr(v)
            elif isinstance(v, list):
                props[k] = [tr(x) if isinstance(x, str) else x for x in v]
        elif k == "options" and isinstance(v, list):
            props[k] = _tr_options(v)
        elif k == "figure" and v is not None:
            if hasattr(v, "to_plotly_json"):
                v = v.to_plotly_json()
            if isinstance(v, dict):
                props[k] = _tr_figure(v)
        elif k == "columns" and isinstance(v, list):          # DataTable
            props[k] = [{**c, "name": tr(c["name"])} if isinstance(c, dict)
                        and isinstance(c.get("name"), str) else c for c in v]


# ── Valori restituiti dai callback ────────────────────────────────────────────────
# Un callback può restituire una stringa semplice (es. "✔ Impostazioni salvate")
# invece di un componente: non passa da to_plotly_json, quindi va tradotta qui.
def _tr_value(prop: str, value):
    if isinstance(value, str):
        return tr(value) if prop in _TEXT_PROPS else value
    if prop in _TEXT_PROPS and isinstance(value, list):
        return [tr(v) if isinstance(v, str) else v for v in value]
    if prop == "options" and isinstance(value, list):
        if value and all(isinstance(v, list) for v in value):     # uscite ALL
            return [_tr_options(v) for v in value]
        return _tr_options(value)
    if prop == "figure" and value is not None:
        if hasattr(value, "to_plotly_json"):
            value = value.to_plotly_json()
        if isinstance(value, dict):
            return _tr_figure(value)
    return value


def install_callback_translation(app):
    """Avvolge app.callback: i testi restituiti dai callback vengono tradotti."""
    from dash.dependencies import Output

    original = app.callback

    def outputs_of(args, kwargs):
        found = []
        for a in list(args) + [kwargs.get("output")]:
            if isinstance(a, Output):
                found.append(a)
            elif isinstance(a, (list, tuple)):
                found += [x for x in a if isinstance(x, Output)]
        return found

    def callback(*args, **kwargs):
        outs = outputs_of(args, kwargs)
        props = [o.component_property for o in outs]
        single = len(outs) == 1 and not any(isinstance(a, (list, tuple)) and
                                            any(isinstance(x, Output) for x in a)
                                            for a in args)
        decorator = original(*args, **kwargs)
        if not any(p in _TEXT_PROPS or p in ("options", "figure") for p in props):
            return decorator

        def wrap(func):
            import functools

            @functools.wraps(func)
            def inner(*a, **k):
                result = func(*a, **k)
                if current_lang() == "it":
                    return result
                if single:
                    return _tr_value(props[0], result)
                if isinstance(result, (list, tuple)) and len(result) == len(props):
                    return type(result)(_tr_value(p, v) for p, v in zip(props, result))
                return result
            return decorator(inner)
        return wrap

    app.callback = callback

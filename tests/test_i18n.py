"""Lingua dell'interfaccia: traduzione dei testi al momento dell'invio al browser."""

import json

import plotly.utils
from dash import dcc, html

from views import i18n
from views.theme import install_theme_vars


def _send(component):
    return json.loads(json.dumps(component, cls=plotly.utils.PlotlyJSONEncoder))


def test_testi_fissi_e_variabili():
    tr = lambda t: i18n.tr(t, "en")
    assert tr("Infrazioni") == "Infringements"
    assert tr("📄 PDF Attività") == "📄 Activities PDF"                    # emoji davanti
    assert tr("Giornata 46 di 46 con attività") == "Day 46 of 46 with activity"
    assert tr("Venerdì 9 ottobre 2026") == "Friday 9 October 2026"        # modelli annidati
    assert tr("Periodo di riposo troppo breve 08:50 (09:00)") == \
        "Rest period too short 08:50 (09:00)"
    assert tr("GA123BC") == "GA123BC"                                      # dati: invariati
    assert i18n.tr("Infrazioni", "it") == "Infrazioni"


def test_componenti_tradotti_all_invio():
    install_theme_vars()
    i18n.set_lang("en")
    try:
        out = _send(html.Div([html.Span("Veicoli"), dcc.RadioItems(
            options=[{"label": "Ultimi 7 giorni", "value": 7}], value=7)]))
        span, radio = out["props"]["children"]
        assert span["props"]["children"] == "Vehicles"
        assert radio["props"]["options"][0]["label"] == "Last 7 days"
    finally:
        i18n.set_lang(None)


def test_cataloghi_validi():
    import glob, os
    keys = i18n.base_keys()
    assert keys
    for path in glob.glob(os.path.join(i18n.LOCALES_DIR, "[a-z]*.json")):
        data = json.load(open(path, encoding="utf-8"))
        for src, dst in data.get("templates", {}).items():
            assert src.count("{}") == dst.count("{}"), (path, src)
        for n, dst in data.get("ids", {}).items():
            src = keys[int(n)]                                 # numero dentro l'elenco
            assert src.count("{}") == dst.count("{}"), (path, n, src)
            assert dst.strip(), (path, n)
        if "ids" in data:                                      # dizionario completo
            assert len(data["ids"]) == len(keys), (path, len(data["ids"]))


def test_tedesco():
    tr = lambda t: i18n.tr(t, "de")
    assert tr("Infrazioni") == "Verstöße"
    assert tr("Venerdì 9 ottobre 2026") == "Freitag 9. Oktober 2026"
    assert tr("4 infrazioni da verificare") == "4 Verstöße zu prüfen"

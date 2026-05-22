"""
views/tabs/__init__.py
Router: mappa tab_id → funzione render(CardData) → html component
"""
from views.tabs import (panoramica, attivita, riepilogo, riposo,
                         infrazioni, veicoli, luoghi, pianificazione,
                         carta, archivio, condivisione)
from models.card_data import CardData

TAB_RENDERERS = {
    "panoramica":     panoramica.render,
    "attivita":       attivita.render,
    "riepilogo":      riepilogo.render,
    "riposo":         riposo.render,
    "infrazioni":     infrazioni.render,
    "veicoli":        veicoli.render,
    "luoghi":         luoghi.render,
    "pianificazione": pianificazione.render,
    "carta":          carta.render,
    "archivio":       archivio.render,
    "condivisione":   condivisione.render,
}

def render_tab(tab_id: str, cd: CardData, gnss_date: str = None):
    fn = TAB_RENDERERS.get(tab_id, panoramica.render)
    if tab_id == "luoghi":
        return fn(cd, gnss_date=gnss_date)
    return fn(cd)

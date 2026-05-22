"""
controllers/export_controller.py
=================================
Controller per l'esportazione dei dati in CSV e PDF.

Gestisce i click sui 4 bottoni di download nell'header dell'app:
  📥 CSV         → esporta le attività in formato tabellare CSV
  📄 PDF Attività   → genera il PDF con le attività giornaliere
  📄 PDF Infrazioni → genera il PDF con le infrazioni rilevate
  📄 PDF Riepilogo  → genera il PDF con il riepilogo settimanale

Come funziona dcc.Download in Dash:
  Il componente dcc.Download è invisibile nella pagina.
  Quando un callback gli assegna un valore tramite dcc.send_bytes()
  o dcc.send_string(), Dash triggera automaticamente il download
  nel browser dell'utente (come se avesse cliccato un link di download).
"""

import pandas as pd
# pandas è una libreria per la manipolazione di dati tabulari.
# Viene usata per creare il DataFrame delle attività e salvarlo come CSV.

from dash import Input, Output, State, dcc, no_update

from models.card_data import CardData
from services.pdf_service import generate_activities, generate_violations_pdf, generate_weekly
# generate_* sono funzioni che restituiscono bytes (il contenuto del PDF)


def _name(cd: CardData) -> str:
    """
    Costruisce una stringa "CognomeNome" da usare nei nomi dei file scaricati.

    Rimuove gli spazi per evitare nomi di file con spazi (problematici su alcuni OS).

    Esempio:
        _name(cd)  →  "MASOTTIGIOVANNI"
    """
    return f"{cd.driver.surname}{cd.driver.firstname}".replace(" ", "")


def _to_csv(cd: CardData) -> str:
    """
    Converte le attività del conducente in formato CSV.

    Struttura del CSV (separatore ";", decimali con ","):
    Data;Inizio;Fine;Attività;Durata_h;Km;Manuale
    09/05/2026;06:20;07:35;Guida;1.25;192;No

    Le colonne sono:
        Data:      data in formato italiano DD/MM/YYYY
        Inizio:    ora inizio segmento HH:MM (ora locale UTC)
        Fine:      ora fine segmento HH:MM
        Attività:  Guida | Lavoro | Disponibilità | Riposo
        Durata_h:  durata in ore (es. 1.25 = 1h15)
        Km:        km percorsi nel giorno (solo sulla prima riga del giorno)
        Manuale:   "Sì" se l'orario è stato inserito manualmente

    Nota: gli orari sono in UTC (come nel file DDD), non in ora locale.
    Per l'ora locale usare il PDF che applica il fuso orario italiano.
    """
    rows = []
    for day in cd.activities:
        # Ordina i cambi attività per orario crescente
        ch = sorted(day.changes, key=lambda c: c.time)
        for i, c in enumerate(ch):
            t0 = c.time   # inizio segmento in minuti (da mezzanotte UTC)
            # Fine segmento: inizio del prossimo, oppure fine giornata (1440)
            t1 = ch[i + 1].time if i + 1 < len(ch) else 1440
            rows.append({
                "Data":      day.date_display,
                "Inizio":    f"{t0//60:02d}:{t0%60:02d}",   # minuti → HH:MM
                "Fine":      f"{t1//60:02d}:{t1%60:02d}",
                "Attività":  c.activity,
                "Durata_h":  round((t1 - t0) / 60, 2),      # durata in ore decimali
                "Km":        day.distance_km if i == 0 else "",  # km solo sulla prima riga
                "Manuale":   "Sì" if c.manual else "No",
            })

    # Crea un DataFrame pandas dalla lista di dizionari e lo serializza in CSV
    # sep=";" → separatore punto e virgola (standard italiano)
    # decimal="," → decimali con virgola (standard europeo, es. 1,25)
    return pd.DataFrame(rows).to_csv(index=False, sep=";", decimal=",")


def register(app):
    """Registra i callback di esportazione sull'istanza Dash."""

    # ── Download CSV ──────────────────────────────────────────────────────────────
    @app.callback(
        Output("download-csv", "data"),         # aggiorna il componente Download
        Input("btn-csv", "n_clicks"),           # triggera al click del bottone
        State("store-data", "data"),            # legge i dati correnti (non triggera)
        prevent_initial_call=True,
    )
    def dl_csv(n, raw):
        """
        Genera e scarica il CSV delle attività.

        Controlla che ci sia stato un click reale (n > 0) e che ci siano dati.
        Deserializza il CardData dallo Store e genera il CSV.
        """
        if not n or not raw:
            return no_update   # nessun click o nessun dato: non fare nulla

        cd = CardData.from_dict(raw)   # ricostruisce l'oggetto Python dallo Store
        # dcc.send_string() crea il payload per il download di un file testo
        return dcc.send_string(_to_csv(cd), f"TachoVision_{_name(cd)}.csv")

    # ── Download PDF Attività ─────────────────────────────────────────────────────
    @app.callback(
        Output("download-pdf-act", "data"),
        Input("btn-pdf-act", "n_clicks"),
        State("store-data", "data"),
        prevent_initial_call=True,
    )
    def dl_pdf_act(n, raw):
        """
        Genera e scarica il PDF delle attività giornaliere.

        generate_activities() restituisce bytes (il contenuto del file PDF).
        dcc.send_bytes() crea il payload per il download di un file binario.
        """
        if not n or not raw:
            return no_update

        cd = CardData.from_dict(raw)
        # dcc.send_bytes(dati_binari, nome_file)
        return dcc.send_bytes(generate_activities(cd),
                              f"TachoVision_Attivita_{_name(cd)}.pdf")

    # ── Download PDF Infrazioni ───────────────────────────────────────────────────
    @app.callback(
        Output("download-pdf-viol", "data"),
        Input("btn-pdf-viol", "n_clicks"),
        State("store-data", "data"),
        prevent_initial_call=True,
    )
    def dl_pdf_viol(n, raw):
        """
        Genera e scarica il PDF delle infrazioni (Reg. CE 561/2006).
        """
        if not n or not raw:
            return no_update

        cd = CardData.from_dict(raw)
        return dcc.send_bytes(generate_violations_pdf(cd),
                              f"TachoVision_Infrazioni_{_name(cd)}.pdf")

    # ── Download PDF Riepilogo settimanale ────────────────────────────────────────
    @app.callback(
        Output("download-pdf-week", "data"),
        Input("btn-pdf-week", "n_clicks"),
        State("store-data", "data"),
        prevent_initial_call=True,
    )
    def dl_pdf_week(n, raw):
        """
        Genera e scarica il PDF del riepilogo settimanale ore/km.
        """
        if not n or not raw:
            return no_update

        cd = CardData.from_dict(raw)
        return dcc.send_bytes(generate_weekly(cd),
                              f"TachoVision_Riepilogo_{_name(cd)}.pdf")

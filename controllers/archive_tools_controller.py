"""
controllers/archive_tools_controller.py
=======================================
Menu dell'archivio: filtro conducente, backup/ripristino su file, zip, cancella tutto.

"""

import base64
from datetime import datetime

from dash import Input, Output, State, callback_context, dcc, no_update
from dash.exceptions import PreventUpdate

from services.archive_service import (archive_zip, backup_zip, delete_all, get_archive,
                                      restore_zip)
from views.tabs.archivio import build_table


def register(app):

    @app.callback(
        Output("archive-table-container", "children", allow_duplicate=True),
        Input("archive-driver", "value"),
        prevent_initial_call=True,
    )
    def filter_driver(card):
        entries = get_archive().list_entries()
        if card and card != "ALL":
            entries = [e for e in entries if e.card_number == card]
        return build_table(entries)

    @app.callback(
        Output("download-archive-tool", "data"),
        Output("archive-tools-msg", "children"),
        Input("btn-backup-file", "n_clicks"),
        Input("btn-archive-zip", "n_clicks"),
        State("archive-driver", "value"),
        prevent_initial_call=True,
    )
    def download(_b, _z, card):
        trig = callback_context.triggered[0]
        if not trig["value"]:
            raise PreventUpdate
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if trig["prop_id"].startswith("btn-backup-file"):
            return (dcc.send_bytes(backup_zip(), f"TachoVision_backup_{stamp}.zip"),
                    "✔ Backup creato (archivio, dati manuali, impostazioni)")
        sel = None if card in (None, "ALL") else card
        return (dcc.send_bytes(archive_zip(card_number=sel), f"TachoVision_archivio_{stamp}.zip"),
                "✔ Zip dell'archivio creato")

    @app.callback(
        Output("archive-tools-msg", "children", allow_duplicate=True),
        Output("store-archive", "data", allow_duplicate=True),
        Input("upload-backup", "contents"),
        prevent_initial_call=True,
    )
    def restore(contents):
        if not contents:
            raise PreventUpdate
        try:
            data = base64.b64decode(contents.split(",", 1)[1])
            c = restore_zip(data)
        except Exception as e:     # file non valido: messaggio all'utente
            return f"⚠️ Impossibile ripristinare il backup: {e}", no_update
        return (f"✔ Ripristinati {c['file']} file, {c['manuali']} conducenti con dati manuali"
                + (", impostazioni" if c["impostazioni"] else ""),
                {"restored": datetime.now().isoformat()})

    @app.callback(
        Output("confirm-delete-all", "displayed"),
        Output("confirm-delete-all", "message"),
        Input("btn-delete-all", "n_clicks"),
        State("archive-driver", "value"),
        prevent_initial_call=True,
    )
    def ask_delete(n, card):
        if not n:
            raise PreventUpdate
        if card in (None, "ALL"):
            msg = ("Sei sicuro di voler eliminare tutti i file dall'archivio "
                   "(compresi i dati inseriti manualmente: note, ferie, attività)?")
        else:
            msg = ("Sei sicuro di voler eliminare dall'archivio tutti i file della persona "
                   "selezionata (compresi i dati inseriti manualmente: note, ferie, attività)?")
        return True, msg

    @app.callback(
        Output("archive-tools-msg", "children", allow_duplicate=True),
        Output("store-archive", "data", allow_duplicate=True),
        Input("confirm-delete-all", "submit_n_clicks"),
        State("archive-driver", "value"),
        prevent_initial_call=True,
    )
    def do_delete(n, card):
        if not n:
            raise PreventUpdate
        k = delete_all(None if card in (None, "ALL") else card)
        return f"✔ Eliminati {k} file", {"deleted": datetime.now().isoformat()}

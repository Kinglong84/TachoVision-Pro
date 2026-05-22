"""
services/archive_service.py
Gestione dell'archivio locale dei file .DDD scaricati.

Responsabilità:
  - Salvare il file .DDD grezzo su disco dopo ogni lettura (cartella archivio configurabile)
  - Elencare i file archiviati con metadati
  - Fornire i bytes per il download/copia verso supporti esterni
  - Rilevare se la scadenza dei 28 giorni è imminente

Il salvataggio fisico del file .DDD è sufficiente ad adempiere
all'obbligo di legge (Reg. CE 561/2006 Art. 10 §5 e Dir. 2006/22/CE).
"""

from __future__ import annotations

import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict

# ── Cartella archivio di default ──────────────────────────────────────────────
# Modificabile dall'utente tramite settings. Usa la home dell'utente.
DEFAULT_ARCHIVE_DIR = Path.home() / "TachoVision" / "archivio"

METADATA_FILE = ".tachovision_index.json"


# ── Struttura metadati ────────────────────────────────────────────────────────
class ArchiveEntry:
    def __init__(self, **kw):
        self.filename:      str  = kw.get("filename", "")
        self.filepath:      str  = kw.get("filepath", "")
        self.card_number:   str  = kw.get("card_number", "—")
        self.driver_name:   str  = kw.get("driver_name", "—")
        self.download_date: str  = kw.get("download_date", "")
        self.next_due:      str  = kw.get("next_due", "")      # entro 28gg
        self.file_size:     int  = kw.get("file_size", 0)
        self.sha256:        str  = kw.get("sha256", "")
        self.source:        str  = kw.get("source", "upload")  # "upload"|"smartcard"

    @property
    def days_until_due(self) -> Optional[int]:
        if not self.next_due:
            return None
        try:
            due = datetime.strptime(self.next_due, "%d/%m/%Y")
            return (due - datetime.now()).days
        except Exception:
            return None

    @property
    def due_status(self) -> str:
        d = self.days_until_due
        if d is None:      return "unknown"
        if d < 0:          return "scaduto"
        if d <= 5:         return "urgente"
        if d <= 14:        return "attenzione"
        return "ok"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ── Servizio archivio ─────────────────────────────────────────────────────────
class ArchiveService:

    def __init__(self, archive_dir: Optional[str] = None):
        self.archive_dir = Path(archive_dir) if archive_dir else DEFAULT_ARCHIVE_DIR
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._index: List[dict] = self._load_index()

    # ── Indice ────────────────────────────────────────────────────────────────
    def _index_path(self) -> Path:
        return self.archive_dir / METADATA_FILE

    def _load_index(self) -> List[dict]:
        p = self._index_path()
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_index(self):
        with open(self._index_path(), "w", encoding="utf-8") as f:
            json.dump(self._index, f, ensure_ascii=False, indent=2)

    # ── Salvataggio file .DDD ─────────────────────────────────────────────────
    def save_ddd(
        self,
        raw_bytes: bytes,
        card_data,          # CardData (importato a runtime per evitare ciclo)
        source: str = "smartcard",
        custom_filename: Optional[str] = None,
    ) -> ArchiveEntry:
        """
        Salva il file .DDD grezzo nella cartella archivio.
        Restituisce un ArchiveEntry con i metadati.

        Il nome file segue la convenzione standard:
            C_YYYYMMDD_HHMM_<cognome>_<numero_carta>.DDD
        """
        now = datetime.now()
        d   = card_data.driver
        surname  = (d.surname  or "UNKNOWN").replace(" ", "").upper()[:10]
        card_num = (d.card_number or "0000000000000000").replace(" ", "")[:16]

        filename = custom_filename or (
            f"C_{now.strftime('%Y%m%d')}_{now.strftime('%H%M')}"
            f"_{surname}_{card_num}.DDD"
        )
        filepath = self.archive_dir / filename

        # Scrivi file
        with open(filepath, "wb") as f:
            f.write(raw_bytes)

        # Prossima scadenza 28 giorni
        next_due = (now + timedelta(days=28)).strftime("%d/%m/%Y")

        sha = hashlib.sha256(raw_bytes).hexdigest()

        entry = ArchiveEntry(
            filename=filename,
            filepath=str(filepath),
            card_number=card_num,
            driver_name=d.full_name,
            download_date=now.strftime("%d/%m/%Y %H:%M"),
            next_due=next_due,
            file_size=len(raw_bytes),
            sha256=sha,
            source=source,
        )

        # Aggiorna indice (evita duplicati per sha256)
        self._index = [e for e in self._index if e.get("sha256") != sha]
        self._index.insert(0, entry.to_dict())
        self._save_index()

        return entry

    # ── Lettura archivio ──────────────────────────────────────────────────────
    def list_entries(self) -> List[ArchiveEntry]:
        """
        Restituisce tutti i file nell'archivio, verificando che esistano su disco.
        """
        valid = []
        for d in self._index:
            p = Path(d.get("filepath", ""))
            if p.exists():
                valid.append(ArchiveEntry(**d))
        # Sincronizza se ci sono file orfani
        if len(valid) != len(self._index):
            self._index = [e.to_dict() for e in valid]
            self._save_index()
        return valid

    def _safe_path(self, filename: str) -> Optional[Path]:
        """
        Restituisce il path assoluto solo se è dentro archive_dir.
        Previene path traversal: es. filename='../../etc/passwd' verrebbe rifiutato.
        """
        # Usa solo il nome base: elimina qualsiasi directory component
        safe_name = Path(filename).name
        resolved = (self.archive_dir / safe_name).resolve()
        if not str(resolved).startswith(str(self.archive_dir.resolve())):
            return None
        return resolved

    def get_bytes(self, filename: str) -> Optional[bytes]:
        """Restituisce i byte del file .DDD richiesto."""
        p = self._safe_path(filename)
        if p is None or not p.exists():
            return None
        with open(p, "rb") as f:
            return f.read()

    def delete(self, filename: str) -> bool:
        """Elimina un file dall'archivio."""
        p = self._safe_path(filename)
        if p is None:
            return False
        try:
            if p.exists():
                p.unlink()
            self._index = [e for e in self._index
                           if e.get("filename") != Path(filename).name]
            self._save_index()
            return True
        except Exception:
            return False

    # ── Export verso storage esterno ──────────────────────────────────────────
    def export_to_folder(self, filename: str, dest_folder: str) -> bool:
        """
        Copia il file .DDD in una cartella esterna (USB, LAN, NAS).
        dest_folder può essere un path locale o un mount point di rete.
        """
        import shutil
        src = self._safe_path(filename)
        if src is None or not src.exists():
            return False
        # Usa solo il nome base del file anche nella destinazione
        safe_name = Path(filename).name
        dst = Path(dest_folder) / safe_name
        try:
            Path(dest_folder).mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            return True
        except Exception:
            return False

    def export_all_to_folder(self, dest_folder: str) -> Dict[str, bool]:
        """Esporta tutti i file dell'archivio in una cartella esterna."""
        results = {}
        for entry in self.list_entries():
            results[entry.filename] = self.export_to_folder(
                entry.filename, dest_folder
            )
        return results

    # ── Statistiche ───────────────────────────────────────────────────────────
    def due_soon(self, days: int = 14) -> List[ArchiveEntry]:
        """Carte la cui scadenza 28-giorni si avvicina."""
        return [e for e in self.list_entries()
                if e.days_until_due is not None and e.days_until_due <= days]

    @property
    def archive_path_str(self) -> str:
        return str(self.archive_dir)


# ── Singleton (condiviso tra controller e view) ───────────────────────────────
_archive: Optional[ArchiveService] = None

def get_archive(archive_dir: Optional[str] = None) -> ArchiveService:
    global _archive
    if _archive is None:
        _archive = ArchiveService(archive_dir)
    return _archive

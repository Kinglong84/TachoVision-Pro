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
# ── Nome del file di scarico ──────────────────────────────────────────────────────
# Un solo costruttore, come i lettori ufficiali: C_aaaaMMgg_HHmm_I_COGNOME_CARTA.ext
# (ora UTC dello scarico, iniziale del nome, cognome solo A-Z/0-9, numero carta).
_TRANSLIT = str.maketrans({
    "Ł": "L", "Đ": "D", "Ø": "O", "Æ": "AE", "Œ": "OE", "Þ": "TH", "ß": "SS", "Ħ": "H",
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E", "Ж": "ZH",
    "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O",
    "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "KH", "Ц": "TS",
    "Ч": "CH", "Ш": "SH", "Щ": "SHCH", "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "YU",
    "Я": "YA", "Є": "YE", "І": "I", "Ї": "YI", "Ґ": "G", "Ј": "J", "Љ": "LJ", "Њ": "NJ",
    "Ћ": "C", "Џ": "DZ", "Ђ": "DJ",
    "Α": "A", "Β": "V", "Γ": "G", "Δ": "D", "Ε": "E", "Ζ": "Z", "Η": "I", "Θ": "TH",
    "Ι": "I", "Κ": "K", "Λ": "L", "Μ": "M", "Ν": "N", "Ξ": "X", "Ο": "O", "Π": "P",
    "Ρ": "R", "Σ": "S", "Τ": "T", "Υ": "Y", "Φ": "F", "Χ": "CH", "Ψ": "PS", "Ω": "O",
})


def name_part(text: str) -> str:
    """Testo per il nome del file: maiuscolo, senza accenti, spazi → "_", solo A-Z 0-9 _ -."""
    import re
    import unicodedata
    s = (text or "").upper().translate(_TRANSLIT)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", "_", s.strip())
    return re.sub(r"[^A-Z0-9_-]", "", s)


def ddd_filename(driver, when: Optional[datetime] = None, ext: str = ".DDD") -> str:
    """Nome standard dello scarico. when: ora dello scarico (locale se senza fuso)."""
    from datetime import timezone
    when = when or datetime.now()
    utc = when.astimezone(timezone.utc)
    initial = name_part(getattr(driver, "firstname", ""))[:1]
    surname = name_part(getattr(driver, "surname", "")) or "UNKNOWN"
    card = name_part(getattr(driver, "card_number", "")) or "0000000000000000"
    middle = f"{initial}_{surname}" if initial else surname
    return f"C_{utc.strftime('%Y%m%d_%H%M')}_{middle}_{card}{ext}"


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
        try:
            self._rescan()
        except Exception:            # l'archivio deve aprirsi comunque
            pass

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

    def _rescan(self) -> bool:
        """
        Riporta nell'indice i file presenti nella cartella ma usciti dall'elenco
        (es. copie identiche salvate di nuovo: l'indice teneva solo l'ultima).
        Un contenuto = una voce; la data di scarico è la più vecchia tra le copie
        (quella nel nome file C_YYYYMMDD_HHMM_…). Nessun file viene cancellato.
        Ritorna True se l'indice è cambiato.
        """
        import re
        exts = {".ddd", ".esm", ".tgd", ".c1b"}
        indexed = {Path(d.get("filepath", "")).name for d in self._index}
        by_sha = {d.get("sha256"): d for d in self._index if d.get("sha256")}
        changed = False

        def name_date(name: str) -> Optional[datetime]:
            m = re.match(r"C_(\d{8})_(\d{4})", name)
            try:
                return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M") if m else None
            except ValueError:
                return None

        for p in sorted(self.archive_dir.iterdir()):
            if p.suffix.lower() not in exts or not p.is_file():
                continue
            try:
                raw = p.read_bytes()
            except OSError:
                continue
            sha = hashlib.sha256(raw).hexdigest()
            when = name_date(p.name)
            entry = by_sha.get(sha)
            if entry is not None:
                # copia di un file già in elenco: tiene la data di scarico più vecchia
                old = None
                try:
                    old = datetime.strptime(entry.get("download_date", ""), "%d/%m/%Y %H:%M")
                except ValueError:
                    pass
                if when and (old is None or when < old):
                    entry["download_date"] = when.strftime("%d/%m/%Y %H:%M")
                    entry["next_due"] = (when + timedelta(days=28)).strftime("%d/%m/%Y")
                    changed = True
                continue
            if p.name in indexed:
                continue
            try:
                from models.parser import parse_ddd
                d = parse_ddd(raw).driver
                name, card = d.full_name, (d.card_number or "").replace(" ", "")
            except Exception:
                name, card = "—", "—"
            when = when or datetime.fromtimestamp(p.stat().st_mtime)
            entry = ArchiveEntry(
                filename=p.name, filepath=str(p), card_number=card or "—",
                driver_name=name or "—", download_date=when.strftime("%d/%m/%Y %H:%M"),
                next_due=(when + timedelta(days=28)).strftime("%d/%m/%Y"),
                file_size=len(raw), sha256=sha, source="archivio").to_dict()
            self._index.append(entry)
            by_sha[sha] = entry
            changed = True
        if changed:
            self._index.sort(key=lambda d: datetime.strptime(d["download_date"], "%d/%m/%Y %H:%M")
                             if d.get("download_date") else datetime.min, reverse=True)
            self._save_index()
        return changed

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

        Il nome file segue la convenzione standard (vedi ddd_filename):
            C_YYYYMMDD_HHMM_<iniziale>_<cognome>_<numero_carta>.DDD (ora UTC)
        """
        d   = card_data.driver
        # data dello scarico = quella della carta (o del nome file),
        # non l'ora in cui il file viene caricato nell'app
        try:
            now = datetime.strptime(d.last_download, "%d/%m/%Y %H:%M")
        except (TypeError, ValueError):
            now = datetime.now()
        # DDD / ESM / TGD / C1B
        from models.settings import load_settings
        ext = {"DDD": ".DDD", "ESM": ".esm", "TGD": ".tgd", "C1B": ".C1B"}.get(
            load_settings().filetype, ".DDD")

        filename = custom_filename or ddd_filename(d, now, ext)
        filepath = self.archive_dir / filename

        # stesso contenuto già in archivio: non si crea una copia con data nuova
        # (la data di scarico resta quella del primo salvataggio)
        sha_new = hashlib.sha256(raw_bytes).hexdigest()
        for e in self._index:
            if e.get("sha256") == sha_new and Path(e.get("filepath", "")).exists():
                return ArchiveEntry(**e)

        # Scrivi file
        with open(filepath, "wb") as f:
            f.write(raw_bytes)

        # Prossima scadenza 28 giorni
        next_due = (now + timedelta(days=28)).strftime("%d/%m/%Y")

        sha = hashlib.sha256(raw_bytes).hexdigest()

        entry = ArchiveEntry(
            filename=filename,
            filepath=str(filepath),
            card_number=(d.card_number or "0000000000000000").replace(" ", "")[:16],
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

# ── ──────

def _settings_file():
    from models.settings import SETTINGS_FILE
    return SETTINGS_FILE


def _manual_dir():
    from models.manual_data import MANUAL_DIR
    return MANUAL_DIR


def backup_zip(archive: "ArchiveService" = None) -> bytes:
    """Backup completo: file dell'archivio + indice, dati manuali, impostazioni."""
    import io
    import zipfile
    archive = archive or get_archive()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in archive.archive_dir.glob("*"):
            if p.is_file():
                z.write(p, f"archivio/{p.name}")
        md = _manual_dir()
        if md.exists():
            for p in md.glob("*.json"):
                z.write(p, f"manuale/{p.name}")
        sf = _settings_file()
        if sf.exists():
            z.write(sf, "impostazioni.json")
    return buf.getvalue()


def archive_zip(archive: "ArchiveService" = None, card_number: str = None) -> bytes:
    """solo i file tachigrafo (eventualmente di un conducente)."""
    import io
    import zipfile
    archive = archive or get_archive()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for e in archive.list_entries():
            if card_number and e.card_number != card_number:
                continue
            p = Path(e.filepath)
            if p.exists():
                z.write(p, p.name)
    return buf.getvalue()


def restore_zip(data: bytes, archive: "ArchiveService" = None,
                restore_settings: bool = True) -> Dict[str, int]:
    """
    Ripristina un backup creato da backup_zip(): aggiunge i file all'archivio
    (senza cancellare quelli presenti), i dati manuali e le impostazioni.
    I nomi dei file vengono ripuliti (nessun percorso esterno alla cartella).
    """
    import io
    import json
    import zipfile
    archive = archive or get_archive()
    counts = {"file": 0, "manuali": 0, "impostazioni": 0}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        index_data = None
        for info in z.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name                  # niente "../"
            if info.filename.startswith("archivio/"):
                if name == METADATA_FILE:
                    index_data = json.loads(z.read(info).decode("utf-8"))
                    continue
                (archive.archive_dir / name).write_bytes(z.read(info))
                counts["file"] += 1
            elif info.filename.startswith("manuale/") and name.endswith(".json"):
                md = _manual_dir()
                md.mkdir(parents=True, exist_ok=True)
                (md / name).write_bytes(z.read(info))
                counts["manuali"] += 1
            elif name == "impostazioni.json" and restore_settings:
                sf = _settings_file()
                sf.parent.mkdir(parents=True, exist_ok=True)
                sf.write_bytes(z.read(info))
                counts["impostazioni"] = 1
        if index_data:
            known = {e.get("sha256") for e in archive._index}
            for e in index_data:
                if e.get("sha256") not in known:
                    e["filepath"] = str(archive.archive_dir / Path(e.get("filename", "")).name)
                    archive._index.append(e)
            archive._save_index()
    return counts


def delete_all(card_number: str = None, archive: "ArchiveService" = None) -> int:
    """tutti i file (o di un conducente) + dati manuali."""
    from models.manual_data import delete_all as delete_manual
    archive = archive or get_archive()
    n = 0
    for e in list(archive.list_entries()):
        if card_number and e.card_number != card_number:
            continue
        if archive.delete(e.filename):
            n += 1
    delete_manual(card_number)
    return n


def get_archive(archive_dir: Optional[str] = None) -> ArchiveService:
    global _archive
    if _archive is None:
        _archive = ArchiveService(archive_dir)
    return _archive

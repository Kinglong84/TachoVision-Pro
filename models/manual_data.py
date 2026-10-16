"""
models/manual_data.py
=====================
Dati inseriti a mano dall'utente, salvati per conducente.

  - Note: legate a un istante, in un gruppo (predefiniti: Commento, Odometro,
    Rifornimento; l'utente può crearne altri) di tipo Evento / Testo breve /
    Testo lungo / Numero
  - Ferie: periodi di giorni; ogni giorno conta HOLIDAYHOURS ore di lavoro
    nella media settimanale di 48h e nel contatore "Ferie"
  - Attività manuali: Guida / Lavoro / Disponibilità / Interruzione-Riposo in
    un intervallo; sostituiscono quanto registrato dalla carta in quel tratto

File: ~/TachoVision/manuale/<numero carta>.json — il file DDD non viene toccato.
Le modifiche entrano nei calcoli tramite apply_manual(), chiamata da
CardData.from_dict().
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)

MANUAL_DIR = Path.home() / "TachoVision" / "manuale"

NOTE_TYPES = [("event", "Evento"), ("short", "Testo breve"), ("long", "Testo lungo"),
              ("number", "Numero")]
DEFAULT_GROUPS = [("Commento", "long"), ("Odometro", "number"), ("Rifornimento", "number")]
MANUAL_ACTIVITIES = ["Guida", "Lavoro", "Disponibilità", "Riposo"]


@dataclass
class Note:
    minute: int          # minuto UTC
    group: str
    kind: str            # event | short | long | number
    value: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])


@dataclass
class Holiday:
    first: str           # "YYYY-MM-DD"
    last: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def days(self) -> List[date]:
        a, b = date.fromisoformat(self.first), date.fromisoformat(self.last)
        out = []
        while a <= b:
            out.append(a)
            a += timedelta(days=1)
        return out


@dataclass
class ManualActivity:
    start: int           # minuto UTC
    end: int
    activity: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])


@dataclass
class ManualData:
    notes: List[Note] = field(default_factory=list)
    holidays: List[Holiday] = field(default_factory=list)
    activities: List[ManualActivity] = field(default_factory=list)
    groups: List[list] = field(default_factory=lambda: [list(g) for g in DEFAULT_GROUPS])

    def to_dict(self):
        return {"notes": [asdict(n) for n in self.notes],
                "holidays": [asdict(h) for h in self.holidays],
                "activities": [asdict(a) for a in self.activities],
                "groups": self.groups}

    @staticmethod
    def from_dict(d) -> "ManualData":
        return ManualData(
            notes=[Note(**n) for n in d.get("notes", [])],
            holidays=[Holiday(**h) for h in d.get("holidays", [])],
            activities=[ManualActivity(**a) for a in d.get("activities", [])],
            groups=d.get("groups") or [list(g) for g in DEFAULT_GROUPS],
        )

    def delete(self, item_id: str):
        self.notes = [x for x in self.notes if x.id != item_id]
        self.holidays = [x for x in self.holidays if x.id != item_id]
        self.activities = [x for x in self.activities if x.id != item_id]


def _path(card_number: str) -> Path:
    safe = "".join(c for c in (card_number or "") if c.isalnum()) or "sconosciuto"
    return MANUAL_DIR / f"{safe}.json"


def load_manual(card_number: str) -> ManualData:
    p = _path(card_number)
    try:
        if p.exists():
            return ManualData.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as e:
        log.warning("Dati manuali non leggibili (%s): %s", p, e)
    return ManualData()


def save_manual(card_number: str, data: ManualData) -> None:
    p = _path(card_number)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def delete_all(card_number: str = None) -> None:
    """(un conducente o tutti)."""
    targets = [_path(card_number)] if card_number else list(MANUAL_DIR.glob("*.json"))
    for p in targets:
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            log.warning("Impossibile cancellare %s: %s", p, e)


def apply_manual(cd, data: ManualData = None) -> None:
    """
    Applica le attività manuali alle attività della carta (in memoria) e
    collega note e ferie al CardData (cd.notes, cd.holidays).
    """
    from models.card_data import ActivityChange, DayActivity
    data = data or load_manual(cd.driver.card_number)
    cd.notes = list(data.notes)
    cd.holidays = list(data.holidays)
    if not data.activities:
        return
    by_date = {d.date: d for d in cd.activities}
    epoch = date(1970, 1, 1)
    for ma in sorted(data.activities, key=lambda a: a.start):
        day = ma.start // 1440
        while day * 1440 < ma.end:
            iso = (epoch + timedelta(days=day)).isoformat()
            a = max(ma.start - day * 1440, 0)
            b = min(ma.end - day * 1440, 1440)
            d = by_date.get(iso)
            if d is None:
                dd = epoch + timedelta(days=day)
                d = DayActivity(iso, dd.strftime("%d/%m/%Y"), 0.0,
                                [ActivityChange(0, "Riposo")])
                cd.activities.append(d)
                by_date[iso] = d
            segs = d.segments() or [(0, 1440, "Riposo")]
            act_at_b = next((x for x in sorted(d.changes, key=lambda c: c.time)[::-1]
                             if x.time <= b), None) if b < 1440 else None
            kept = [c for c in d.changes if c.time < a or c.time >= b]
            kept.append(ActivityChange(a, ma.activity, manual=True, card_inserted=False))
            if b < 1440 and not any(c.time == b for c in kept):
                prev = act_at_b or ActivityChange(b, segs[-1][2])
                kept.append(ActivityChange(b, prev.activity, prev.manual, prev.crew,
                                           prev.card_inserted))
            d.changes = sorted(kept, key=lambda c: c.time)
            day += 1
    cd.activities.sort(key=lambda d: d.date)

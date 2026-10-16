"""
models/demo_data.py
===================
Dati di esempio completamente inventati (conducente MARIO ROSSI) per provare il
programma senza una carta tachigrafica: 9 settimane di attività, tre veicoli,
un viaggio Italia → Francia → Germania → Austria, posizioni GPS, eventi e
qualche infrazione tipica (guida continua, guida giornaliera, riposo breve).

Nessun dato reale: nomi, carta, targhe e luoghi sono di fantasia.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import List, Tuple

from models.card_data import (ActivityChange, CardData, CardEvent, CardFault, DayActivity,
                              DriverInfo, GNSSRecord, Place, Vehicle, VehicleSession)

G, L, D, R = "Guida", "Lavoro", "Disponibilità", "Riposo"

# città di partenza/arrivo per paese (lat, lon) — punti generici sulle autostrade
CITIES = {
    "IT": [(45.464, 9.190), (45.438, 10.992), (44.494, 11.343)],   # Milano, Verona, Bologna
    "FR": [(45.764, 4.836), (45.188, 5.725)],                        # Lione, Grenoble
    "DE": [(48.137, 11.576), (49.452, 11.077)],                      # Monaco, Norimberga
    "AT": [(47.269, 11.404), (47.809, 13.055)],                      # Innsbruck, Salisburgo
}

# turni tipo: (minuti, attività) dall'inizio del turno
NORMAL = [(15, L), (150, G), (45, R), (120, G), (40, L), (20, D), (110, G), (20, L)]
LONG = [(15, L), (160, G), (45, R), (160, G), (30, L), (45, R), (160, G), (15, L), (100, G),
        (15, L)]
CONTINUOUS = [(15, L), (290, G), (45, R), (150, G), (30, L)]          # guida 4h50 di fila
SHORT = [(15, L), (120, G), (30, L), (90, G), (15, L)]
SATURDAY = [(15, L), (150, G), (40, L), (60, G), (10, L)]


def _shift_minutes(plan) -> Tuple[int, int]:
    return sum(m for m, _ in plan), sum(m for m, a in plan if a == G)


def build_demo(end_day: date = date(2026, 10, 9)) -> CardData:
    """CardData di esempio: 9 settimane che finiscono il venerdì `end_day`."""
    rng = random.Random(7)
    monday = end_day - timedelta(days=end_day.weekday()) - timedelta(weeks=8)

    driver = DriverInfo(
        surname="ROSSI", firstname="MARIO", birth_date="01/01/1980", language="it",
        card_number="I000000000000001", issuing_authority="CCIAA DI ESEMPIO",
        issuing_nation="IT", issue_date="01/02/2022", validity_begin="01/02/2022",
        expiry_date="01/02/2027", licence_number="X000000000",
        licence_authority="AUTORITA' DI ESEMPIO", generation="G2 (v1)",
        renewal_index="1", replacement_index="0",
        last_download=f"{end_day.strftime('%d/%m/%Y')} 17:30",
        prev_download=f"{(end_day - timedelta(days=27)).strftime('%d/%m/%Y')} 17:10",
        filename=f"C_{end_day.strftime('%Y%m%d')}_1530_ROSSI_I000000000000001.DDD",
        file_size="0")

    vrns = ["GA123BC", "GB456DE", "GC789FG"]
    odo = {v: 120000 + i * 85000 for i, v in enumerate(vrns)}

    changes: List[Tuple[datetime, str]] = []
    sessions: List[VehicleSession] = []
    places: List[Place] = []
    gnss: List[GNSSRecord] = []
    km_by_day = {}

    def utc(d: date, minute: int) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=minute)

    def add_place(when: datetime, country: str, kind: str, km: int, pos):
        places.append(Place(
            datetime=when.strftime("%d/%m/%Y %H:%M"), date=when.date().isoformat(),
            country=country, entry_type=kind, odometer_km=km, region=0,
            gnss_lat=round(pos[0], 4), gnss_lon=round(pos[1], 4), gnss_accuracy=20,
            ts_utc=int(when.timestamp())))

    # (giorno della settimana, tipo di turno, paese di partenza → arrivo)
    for week in range(9):
        for wd in range(6):
            day = monday + timedelta(weeks=week, days=wd)
            if day > end_day:
                break
            plan, start_c, end_c = NORMAL, "IT", "IT"
            if wd == 5:
                if week != 3:
                    continue                                   # sabato libero
                plan = SATURDAY                                # riposo settimanale ridotto
            if week == 1 and wd == 2:
                plan = CONTINUOUS
            if week == 2 and wd in (0, 2, 3):
                plan = LONG                                    # 3 estensioni a 10h
            if week == 6 and wd == 1:
                plan = SHORT
            if week == 5:                                      # viaggio all'estero
                start_c, end_c = [("IT", "FR"), ("FR", "FR"), ("FR", "DE"), ("DE", "AT"),
                                  ("AT", "IT")][wd] if wd < 5 else ("IT", "IT")
            start = rng.randint(300, 390) if not (week == 4 and wd == 1) else 150
            if week == 4 and wd == 0:
                start = 420                                    # fine tardi → riposo breve
            dur, drive_min = _shift_minutes(plan)
            vrn = vrns[2] if week == 5 else vrns[(week + (wd >= 3)) % 2]
            t = start
            for minutes, act in plan:
                changes.append((utc(day, t), act))
                t += minutes
            changes.append((utc(day, t), R))
            if week == 4 and wd == 0:
                changes[-1] = (utc(day, t + 120), R)           # resta a lavorare 2h in più
                changes.insert(-1, (utc(day, t), L))
                t += 120
            km = int(drive_min * rng.uniform(1.05, 1.25))
            km_by_day[day.isoformat()] = km
            a_in, a_out = utc(day, start - 2), utc(day, t + 3)
            sessions.append(VehicleSession(
                vrn=vrn, first_use=a_in.strftime("%d/%m/%Y"), last_use=a_out.strftime("%d/%m/%Y"),
                odo_begin_km=odo[vrn], odo_end_km=odo[vrn] + km,
                first_use_utc=int(a_in.timestamp()), last_use_utc=int(a_out.timestamp())))
            p0 = rng.choice(CITIES[start_c])
            p1 = rng.choice(CITIES[end_c])
            add_place(a_in, start_c, "Inizio", odo[vrn], p0)
            add_place(a_out, end_c, "Fine", odo[vrn] + km, p1)
            # posizione GPS ogni 3 ore di guida accumulata (come i tachigrafi Gen2)
            steps = drive_min // 180
            for k in range(1, steps + 1):
                f = k / (steps + 1)
                when = utc(day, start + int(dur * f))
                gnss.append(GNSSRecord(
                    timestamp=when.strftime("%d/%m/%Y %H:%M"), date=day.isoformat(),
                    lat=round(p0[0] + (p1[0] - p0[0]) * f, 4),
                    lon=round(p0[1] + (p1[1] - p0[1]) * f, 4),
                    accuracy_dm=30, odometer_km=odo[vrn] + int(km * f)))
            odo[vrn] += km

    # ── giorni del DDD (UTC) ──
    changes.sort()
    activities: List[DayActivity] = []
    by_day = {}
    for when, act in changes:
        by_day.setdefault(when.date(), []).append(ActivityChange(when.hour * 60 + when.minute,
                                                                 act))
    cur = R
    d = monday - timedelta(days=1)
    while d <= end_day:
        ch = by_day.get(d, [])
        if not ch or ch[0].time > 0:
            ch = [ActivityChange(0, cur)] + ch
        cur = ch[-1].activity
        activities.append(DayActivity(date=d.isoformat(), date_display=d.strftime("%d/%m/%Y"),
                                      distance_km=float(km_by_day.get(d.isoformat(), 0)),
                                      changes=ch))
        d += timedelta(days=1)

    vehicles = []
    for v in vrns:
        mine = [s for s in sessions if s.vrn == v]
        if mine:
            vehicles.append(Vehicle(v, mine[0].first_use, mine[-1].last_use,
                                    total_km=sum(s.odo_end_km - s.odo_begin_km for s in mine)))

    ev_day = monday + timedelta(weeks=6, days=2)
    events = [CardEvent(begin_time=f"{ev_day.strftime('%d/%m/%Y')} 09:12",
                        end_time=f"{ev_day.strftime('%d/%m/%Y')} 09:14", event_type_code=0x07,
                        event_type="Eccesso di velocità", vehicle=vrns[1])]
    faults = [CardFault(begin_time=f"{(ev_day + timedelta(days=8)).strftime('%d/%m/%Y')} 14:02",
                        end_time="", fault_type_code=0x21, fault_type="Guasto della carta",
                        vehicle=vrns[0])]

    return CardData(driver=driver, activities=activities, vehicles=vehicles,
                    vehicle_sessions=sessions, places=sorted(places, key=lambda p: p.ts_utc,
                                                             reverse=True),
                    gnss_records=gnss, events=events, faults=faults, demo=True)

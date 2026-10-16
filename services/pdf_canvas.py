"""
services/pdf_canvas.py
======================
Motore dei PDF (disegno diretto su pagina).

Il PDF non usa tabelle: disegna ogni pagina A4 (595×842 pt) con margini di 28 pt.
Intestazione:  nome (15 pt grassetto), data di nascita, numero carta, data di
               download (10 pt), "Fuso orario: …" (10 pt), "Periodo: a - b" (12 pt,
               centrato).
Piè di pagina: linea grigia a 28 pt dal fondo, poi (7 pt grigio) a sinistra il
               programma, al centro "Pagina N", a destra data e ora di creazione.
Il PDF Attività elenca i giorni dal più recente:
  linea spessa 3 pt + data (12 pt);
  riga dei turni (esagoni color #E8D991 con l'ampiezza), 3 righe di simboli
  (paese, equipaggio), barre alte 40 pt: Guida piena, Disponibilità 5/6,
  Lavoro 2/3, Riposo 1/3 con la durata; carta estratta con attività inserita a
  mano = barra scura #454545; asse con tacche ogni quarto d'ora e ore ogni 4;
  sotto, gli eventi su 3 colonne riempite dall'alto in basso: ora (9 pt),
  simbolo dell'attività a +42 pt, durata a 60 pt dal bordo destro della colonna.
Le icone sono disegnate con semplici tratti.
"""

from __future__ import annotations

import io
import math
from datetime import date, datetime, timedelta
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas

PW, PH = A4
M = 28.0                         # margine su tutti i lati
CW = PW - 2 * M                  # larghezza utile (539 pt)
BOTTOM = PH - M                  # linea del piè di pagina


def _register_fonts():
    """Sans-serif TrueType con "Δ" e "€"; altrimenti Helvetica."""
    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    pairs = [(os.path.join(win, "arial.ttf"), os.path.join(win, "arialbd.ttf")),
             ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
             ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
             ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf")]
    for reg, bold in pairs:
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("AppSans", reg))
                pdfmetrics.registerFont(TTFont("AppSans-Bold", bold))
                return "AppSans", "AppSans-Bold"
            except Exception:
                pass
    return "Helvetica", "Helvetica-Bold"


FONT, BOLD = _register_fonts()
HAS_DELTA = FONT != "Helvetica"
GREY = "#888888"                 # -7829368 (0xFF888888) dei testi secondari
DARK = "#444444"                 # -12303292 (0xFF444444) dei testi a 6 pt
SHIFT = "#E8D991"                # colorShift
MANUAL_BG = "#E0E0E0"            # colorEventDrawerManualBackground
NOCARD = "#454545"               # colorEventNoCard
# linee informative / equipaggio per schema colori (colorEventDrawerInfoLine/StaffLine)
_LINES = {1: ("#F01010", "#74F13F"), 2: ("#404040", "#CA62DB"), 3: ("#404040", "#FFC90E"),
          4: ("#404040", "#CA62DB"), 5: ("#404040", "#CA62DB")}

_MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
         "settembre", "ottobre", "novembre", "dicembre"]
_MESI_BREVI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov",
               "dic"]


def h(size: float) -> float:
    """Altezza della riga (descent - ascent) del carattere sans-serif."""
    return size * 1.172


def asc(size: float) -> float:
    return size * 0.928


def date_medium(d: date) -> str:
    """FormatStyle.MEDIUM in italiano: "26 nov 2022"."""
    return f"{d.day} {_MESI_BREVI[d.month - 1]} {d.year}"


def date_long(d: date) -> str:
    """FormatStyle.LONG in italiano: "26 novembre 2022"."""
    return f"{d.day} {_MESI[d.month - 1]} {d.year}"


def wrap(text: str, width: float, size: float, font: str = FONT) -> List[str]:
    """Spezza il testo in righe che stanno nella larghezza."""
    out, cur = [], ""
    for word in text.split():
        t = f"{cur} {word}".strip()
        if cur and stringWidth(t, font, size) > width:
            out.append(cur)
            cur = word
        else:
            cur = t
    if cur:
        out.append(cur)
    return out or [""]


class AppPdf:
    """Pagina A4 con intestazione e piè di pagina; y misurata dall'alto."""

    def __init__(self, cd, settings, d_from: date, d_to: date, program: str = "TachoVision Pro"):
        self.cd, self.s = cd, settings
        self.d_from, self.d_to = d_from, d_to
        self.program = program
        self.buf = io.BytesIO()
        self.c = rl_canvas.Canvas(self.buf, pagesize=A4)
        self.page = 0
        self.created = datetime.now()

    # ── primitive (coordinate misurate dall'alto) ──
    def text(self, s, x, y, size=9, color="#000000", font=FONT, align="left"):
        c = self.c
        c.setFont(font, size)
        c.setFillColor(colors.HexColor(color))
        if align == "center":
            c.drawCentredString(x, PH - y, s)
        elif align == "right":
            c.drawRightString(x, PH - y, s)
        else:
            c.drawString(x, PH - y, s)

    def line(self, x1, y1, x2, y2, width=1.0, color="#000000"):
        c = self.c
        c.setStrokeColor(colors.HexColor(color))
        c.setLineWidth(width)
        c.line(x1, PH - y1, x2, PH - y2)

    def rect(self, x1, y1, x2, y2, fill):
        """Rettangolo pieno da (x1,y1) in alto a sinistra a (x2,y2)."""
        if x2 <= x1 or y2 <= y1:
            return
        c = self.c
        c.setFillColor(colors.HexColor(fill))
        c.rect(x1, PH - y2, x2 - x1, y2 - y1, stroke=0, fill=1)

    # ── pagina ──
    def new_page(self) -> float:
        if self.page:
            self.c.showPage()
        self.page += 1
        y = self.header()
        self.footer()
        return y

    def header(self) -> float:
        """intestazione; ritorna la y dove inizia il contenuto."""
        d = self.cd.driver
        y = M + h(15)
        self.text(f"{d.firstname} {d.surname}".strip(), M, y, 15, font=BOLD)
        tz = self.s.timezone or "predefinito"
        for ln in (f"Data di nascita: {d.birth_date}" if d.birth_date else "",
                   f"Numero della carta del conducente: {d.card_number}"
                   if d.card_number else "",
                   f"Data di download: {d.last_download}" if d.last_download else "",
                   f"Fuso orario: {tz}"):
            if ln:
                y += h(10)
                self.text(ln, M, y, 10)
        y += h(12)
        self.text(f"Periodo: {date_medium(self.d_from)} - {date_medium(self.d_to)}",
                  CW / 2 + M, y, 12, align="center")
        return y + h(7) / 3

    def footer(self):
        """linea grigia, programma, "Pagina N", data di creazione."""
        self.line(M, BOTTOM, M + CW, BOTTOM, 1, GREY)
        y = BOTTOM + h(7) + 4
        self.text(self.program, M, y, 7, GREY)
        self.text(f"Pagina {self.page}", CW / 2 + M, y, 7, GREY, align="center")
        self.text(f"{date_long(self.created.date())} {self.created:%H:%M}", M + CW, y, 7, GREY,
                  align="right")

    def close(self, y: float) -> bytes:
        """Linea finale spessa e chiusura del documento."""
        if self.page:
            if y + 3 > BOTTOM:
                y = self.new_page()
            self.line(M, y + 3, M + CW, y + 3, 3)
        self.c.save()
        return self.buf.getvalue()


# ── simboli delle attività (disegnati da noi) ────────────────────────────────

def icon(pdf: AppPdf, kind: str, x: float, y_top: float, size: float, color="#000000"):
    """Piccolo pittogramma tachigrafico nel quadrato (x, y_top, size)."""
    c = pdf.c
    col = colors.HexColor(color)
    c.setStrokeColor(col)
    c.setFillColor(col)
    c.setLineWidth(0.6)
    cx, cy = x + size / 2, PH - (y_top + size / 2)
    r = size / 2
    if kind == "Guida":                       # volante
        c.circle(cx, cy, r * 0.9, stroke=1, fill=0)
        c.circle(cx, cy, r * 0.25, stroke=0, fill=1)
        c.line(cx - r * 0.9, cy, cx + r * 0.9, cy)
    elif kind == "Lavoro":                    # martelli incrociati
        c.line(cx - r, cy - r, cx + r, cy + r)
        c.line(cx - r, cy + r, cx + r, cy - r)
    elif kind == "Disponibilità":             # quadrato barrato
        c.rect(cx - r * 0.85, cy - r * 0.85, r * 1.7, r * 1.7, stroke=1, fill=0)
        c.line(cx - r * 0.85, cy - r * 0.85, cx + r * 0.85, cy + r * 0.85)
    elif kind == "Riposo":                    # letto
        c.rect(cx - r, cy - r * 0.5, r * 2, r * 0.45, stroke=0, fill=1)
        c.rect(cx - r, cy - r * 0.5, r * 0.45, r * 1.1, stroke=0, fill=1)
        c.circle(cx - r * 0.3, cy + r * 0.2, r * 0.25, stroke=0, fill=1)
    elif kind == "equipaggio":                # due persone
        for dx in (-r * 0.45, r * 0.45):
            c.circle(cx + dx, cy + r * 0.35, r * 0.28, stroke=0, fill=1)
            c.rect(cx + dx - r * 0.3, cy - r, r * 0.6, r * 0.9, stroke=0, fill=1)
    elif kind == "manuale":                   # mano: palmo + dita
        c.rect(cx - r * 0.6, cy - r, r * 1.2, r, stroke=0, fill=1)
        for i in range(4):
            c.rect(cx - r * 0.6 + i * r * 0.32, cy, r * 0.22, r * 0.9, stroke=0, fill=1)


# ── PDF Attività ────────────────────────────────────────────────────────────

def _dur(m: int, s) -> str:
    m = max(0, int(m))
    if s.intervalformat == "HHHH":
        return f"{m / 60:05.2f}".replace(".", ",")
    return f"{m // 60:02d}:{m % 60:02d}"


def _day_block(pdf: AppPdf, day, segs, shifts, crew, countries, draw: bool, y: float,
               graph: bool, listing: bool, open_end: int) -> float:
    """disegna (o misura, draw=False) un giorno."""
    s = pdf.s
    pal = s.colors
    info_c, staff_c = _LINES.get(s.graphcolorschema, _LINES[1])
    a = day.start
    k = (CW - 1) / 1440.0
    X = lambda m: M + round(min(max(m - a, 0), 1440) * k)

    lines = day.lines if listing else []
    if lines or graph:
        y18 = y + 3
        if draw:
            pdf.line(M, y18, M + CW, y18, 3)
        y = y18 + h(12) + 1
        if draw:
            pdf.text(date_medium(day.date), M, y, 12)
    top = y + 3
    r8 = h(8)
    f21 = top + r8 / 0.7
    f23, f24 = f21 + r8, f21 + r8 + 1
    f25 = f24 + r8
    f26 = f25 + 1
    f27 = f26 + r8 + 1
    base = f27 + 40
    H40 = 40.0
    hw, hr = H40 * 2 / 3, H40 / 3
    ha = (H40 + hw) / 2
    heights = {"Guida": H40, "Lavoro": hw, "Disponibilità": ha, "Riposo": hr}
    y36 = y
    if graph:
        if draw:
            # turni: esagoni con l'ampiezza
            for sa, sb in shifts:
                x1, x2 = M + round((sa - a) * k), M + round((sb - a) * k)
                yt, yb = top, f21 - 2
                hh = yb - yt
                cut = min(hh / 2, (x2 - x1) / 2)
                c = pdf.c
                c.saveState()
                p = c.beginPath()
                p.rect(M, PH - yb, CW, hh)
                c.clipPath(p, stroke=0, fill=0)
                c.setFillColor(colors.HexColor(SHIFT))
                hx = c.beginPath()
                mid = PH - (yt + hh / 2)
                hx.moveTo(x1, mid)
                hx.lineTo(x1 + cut, PH - yt)
                hx.lineTo(x2 - cut, PH - yt)
                hx.lineTo(x2, mid)
                hx.lineTo(x2 - cut, PH - yb)
                hx.lineTo(x1 + cut, PH - yb)
                hx.close()
                c.drawPath(hx, stroke=0, fill=1)
                c.restoreState()
                lab = _dur(sb - sa, s)
                xa, xb = max(x1 + cut, M), min(M + CW, x2 - cut)
                if stringWidth(lab, FONT, 8) <= (xb - xa) * 0.9:
                    pdf.text(lab, (xa + xb) / 2, yt + hh / 2 + asc(8) / 2.6, 8, align="center")
            # barre delle attività: riposo, disponibilità, lavoro, guida
            for act in ("Riposo", "Disponibilità", "Lavoro", "Guida"):
                for x in segs:
                    if x.activity != act or x.unknown:
                        continue
                    x1, x2 = X(x.start), X(x.end)
                    hgt = heights[act]
                    # NOCARD_DRIVING/WORK/AVAILABILITY: attività inserita a mano a carta
                    # estratta; il riposo resta del suo colore
                    nocard = x.manual and act != "Riposo"
                    fill = NOCARD if nocard else pal.get(act, "#888888")
                    pdf.rect(x1, base - hgt, max(x2, x1 + 1), base, fill)
                    if act == "Riposo":
                        lab = _dur(x.length, s)
                        fs = hr * 0.6
                        tw = stringWidth(lab, FONT, fs)
                        if tw <= (x2 - x1) / 2:
                            ih = hr * 0.5
                            tot = ih + 0.4 * ih + tw
                            x0 = (x1 + x2) / 2 - tot / 2
                            icon(pdf, "Riposo", x0, base - hr / 2 - ih / 2, ih)
                            pdf.text(lab, x0 + ih + 0.4 * ih, base - hr / 2 + fs * 0.35, fs)
            # equipaggio: linea sulla base
            for ca, cb in crew:
                pdf.line(X(ca), base + hr / 10, X(cb), base + hr / 10, hr / 5, staff_c)
            # paesi: linea verticale fino alla terza riga e codice
            for m, code in countries:
                xx = X(m)
                pdf.line(xx, base, xx, f26, 1, info_c)
                pdf.text(code, xx + 2, f26 + asc(8), 8, GREY)
            # asse: tacche ogni quarto d'ora, ore ogni 4 tacche
            pdf.line(M, base, M + CW, base, 1)
            for i in range(97):
                xx = M + int(i * CW / 96)
                pdf.line(xx, base, xx, base + (3 if i % 4 == 0 else 2), 0.6)
                if i % 4 == 0:
                    lab = f"{i // 4:02d}"
                    al = "left" if i == 0 else "right" if i == 96 else "center"
                    pdf.text(lab, xx, base + 3 + asc(8), 8, GREY, align=al)
        y36 = base + 3 + asc(8)
    if not listing:
        return y36
    q = h(9)
    n = len(lines)
    cols = 3 if graph else 1
    colw = CW / cols
    rows = math.ceil(n / cols) if n else 0
    if draw:
        for i, ln in enumerate(lines):
            x = M + (i // rows) * colw
            ry = (i % rows) * q + y36
            yb = ry + q
            txt_c = "#000000"
            if ln.kind == "activity" and ln.info == "manuale":
                pdf.rect(x - 1, ry + 2, x + colw - 37, ry + 2 + q, MANUAL_BG)
            if ln.kind == "activity" and ln.info == "sconosciuta":
                pdf.rect(x - 1, ry + 2, x + colw - 37, ry + 2 + q, NOCARD)
                txt_c = "#FFFFFF"
            pdf.text(ln.time, x, yb, 9, txt_c)
            if ln.kind == "activity":
                sz = asc(9) - 2
                if ln.info != "sconosciuta":
                    icon(pdf, ln.activity, x + 42, yb - sz, sz, txt_c)
                if ln.info in ("equipaggio", "manuale"):
                    icon(pdf, ln.info, x + 55, yb - sz, sz, txt_c)
                dur = (("ΔT=" if HAS_DELTA else "--:--") if ln.minute == open_end
                       else ln.length.replace("ΔT=", ""))
                if s.intervalformat == "HHHH" and ":" in dur and "-" not in dur:
                    hh_, mm_ = dur.split(":")
                    dur = _dur(int(hh_) * 60 + int(mm_), s)
                pdf.text(dur, x + colw - 60, yb, 9, txt_c)
            elif ln.kind == "place":
                pdf.text(ln.text, x + 42, yb, 9)
            else:
                parts = wrap(ln.text, (colw - 42) * 0.95, 6)
                if len(parts) > 1:
                    pdf.text(parts[0], x + 42, ry + q / 2 + 2, 6, DARK)
                    pdf.text(" ".join(parts[1:]), x + 42, yb + 2, 6, DARK)
                else:
                    pdf.text(parts[0], x + 42, yb - 1, 6, DARK)
    if rows:
        return rows * q + q + y36
    if draw:
        pdf.text("Non ci sono attività in questo giorno", M, y36 + q, 9)
    return y36 + 2 * q


def activities_pdf(cd, s, d_from: Optional[str], d_to: Optional[str], graph_only=False) -> bytes:
    """(ACTIVITIES_…pdf)."""
    from models.day_events import build_days
    from models.timeline import Timeline, build_shifts, classify_rests
    tl = Timeline(cd.activities, s.timezone)
    if not tl.segments:
        pdf = AppPdf(cd, s, date.today(), date.today())
        y = pdf.new_page()
        pdf.text("Non ci sono attività in questo giorno", M, y + h(9), 9)
        return pdf.close(y + 2 * h(9))
    first = date.fromisoformat(d_from[:10]) if d_from else tl.local(tl.start).date()
    last = date.fromisoformat(d_to[:10]) if d_to else tl.local(tl.end - 1).date()
    days = build_days(cd, s, None, first, last)
    rests = [r for r in classify_rests(tl) if r.length > 0]
    shifts = [(x.start, x.end) for x in build_shifts(tl, rests)]
    places = []
    for p in cd.places:
        if p.ts_utc:
            places.append((p.ts_utc // 60, p.country))
    open_end = tl.segments[-1].start
    pdf = AppPdf(cd, s, first, last)
    y = pdf.new_page()
    for day in reversed(days):  # dal giorno più recente
        a, b = day.start, day.start + 1440
        segs = tl.between(a, b)
        day_shifts = [(sa, sb) for sa, sb in shifts if sb > a and sa < b]
        crew = [(x.start, x.end) for x in segs if x.crew]
        ctry = [(m, code) for m, code in places if a <= m < b]
        args = (day, segs, day_shifts, crew, ctry)
        if _day_block(pdf, *args, False, y, True, not graph_only, open_end) > BOTTOM:
            y = pdf.new_page()
        y = _day_block(pdf, *args, True, y, True, not graph_only, open_end)
    return pdf.close(y)


# ── telaio comune degli altri PDF ────────────────────────────────────────────

def _run(pdf: AppPdf, blocks) -> float:
    """
    Disegna i blocchi (funzioni f(draw, y) -> y): prima misura, se il
    blocco esce dalla pagina ne apre una nuova, poi disegna.
    """
    y = pdf.new_page()
    for blk in blocks:
        if blk(False, y) > BOTTOM:
            y = pdf.new_page()
        y = blk(True, y)
    return y


def _period(cd, s, d_from, d_to):
    from models.timeline import Timeline
    tl = Timeline(cd.activities, s.timezone)
    if not tl.segments:
        return tl, date.today(), date.today()
    first = date.fromisoformat(d_from[:10]) if d_from else tl.local(tl.start).date()
    last = date.fromisoformat(d_to[:10]) if d_to else tl.local(tl.end - 1).date()
    return tl, first, last


def _band(pdf: AppPdf, draw: bool, y: float, label: str) -> float:
    """fascia grigia #CCCCCC tra due linee."""
    y += 15
    r10 = h(10)
    if draw:
        pdf.rect(M, y, M + CW, y + r10 + 3, "#CCCCCC")
        pdf.line(M, y, M + CW, y, 1, GREY)
    y += r10
    if draw:
        pdf.text(label, M, y, 10)
    y += 3
    if draw:
        pdf.line(M, y, M + CW, y, 1, GREY)
    return y


def _label_between_lines(pdf: AppPdf, draw: bool, y: float, label: str) -> float:
    """Riga di sessione: linea grigia, testo 10 pt, linea grigia (veicoli, paesi)."""
    y += 15
    if draw:
        pdf.line(M, y, M + CW, y, 1, GREY)
    y += h(10)
    if draw:
        pdf.text(label, M, y, 10)
    y += 3
    if draw:
        pdf.line(M, y, M + CW, y, 1, GREY)
    return y


def _grey_line(pdf, draw, y, text):
    y += h(10)
    if draw:
        pdf.text(text, M + 12, y, 10, GREY)
    return y


def _nothing(pdf, draw, y, text):
    y += h(10) * 2
    if draw:
        pdf.text(text, M, y, 10)
    return y


# ── Riepilogo del tempo di lavoro (WORKTIME_) ────────────────────────────────

_WT_COLS = (("Guida", 51), ("Lavoro", 109), ("Disponibilità", 167), ("Riposo", 225))


def _wt_values(pdf, draw, y, sums, s, label="", km=True, x0=0):
    """etichetta a 28, simboli a 51/109/167/225, valori
    12 pt più a destra, km a 339."""
    y += h(10)
    if draw:
        if label:
            pdf.text(label, M, y, 10)
        sz = asc(10) - 2
        vals = (sums.drive, sums.work, sums.avail, sums.brk)
        for (kind, x), v in zip(_WT_COLS, vals):
            icon(pdf, kind, x + x0, y - sz, sz)
            pdf.text(_dur(v, s), x + x0 + 12, y, 10)
        if km:
            pdf.text(f"{int(round(sums.km))}km", 339 + x0, y, 10)
    return y


def worktime_pdf(cd, s, periods, d_from, d_to, options=()) -> bytes:
    """
    periodo in fascia grigia, una riga per giorno (o turno) con i simboli e le
    durate, riga IN TOTALE, somma retribuita e contatori del periodo."""
    tl, first, last = _period(cd, s, d_from, d_to)
    pdf = AppPdf(cd, s, first, last)
    only_headers = "header" in options
    show_rests = "rests" in options
    wage = "wage" in options and s.wage_period is not None
    pay_av, pay_brk = s.payedavailability, s.payedbreaktype != "NO"
    blocks = []
    for p in periods:
        blocks.append(lambda draw, y, p=p: _band(pdf, draw, y, p.label))
        if not only_headers:
            for r in p.rows:
                if r.kind == "rest":
                    if show_rests:
                        blocks.append(lambda draw, y, r=r: _grey_line(pdf, draw, y, r.label))
                    continue
                if r.kind == "shift":
                    def blk(draw, y, r=r):
                        y += h(10)
                        if draw:
                            pdf.text(f"{tl.fmt(r.start)} - {tl.fmt(r.end)}", M, y, 10)
                        y = _wt_values(pdf, draw, y, r.sums, s, _dur(r.end - r.start, s))
                        if wage and r.wage:
                            y = _wt_values(pdf, draw, y, r.wage, s, "", km=False)
                        return y
                else:
                    def blk(draw, y, r=r):
                        y = _wt_values(pdf, draw, y, r.sums, s, tl.local(r.start).strftime("%d"))
                        if wage and r.wage:
                            y = _wt_values(pdf, draw, y, r.wage, s, "", km=False)
                        return y
                blocks.append(blk)

        def summary(draw, y, p=p):
            y += 4
            if draw:
                pdf.line(M, y, M + CW, y, 2, GREY)
            y = _wt_values(pdf, draw, y, p.sums, s, "IN TOTALE", x0=40)
            sm = p.sums
            parts = [sm.drive, sm.work]
            if pay_av:
                parts.append(sm.avail)
            if pay_brk:
                parts.append(sm.brk)
            y += h(10)
            if draw:
                pdf.text(" + ".join(_dur(v, s) for v in parts) + f" = {_dur(sum(parts), s)}",
                         M + CW, y, 10, align="right")
            if wage and p.wage:
                w0, w1 = s.wage_period
                y = _wt_values(pdf, draw, y, p.wage, s, f"{w0:02d}-{w1:02d}", km=False, x0=40)
            y += h(10)
            if draw:
                pdf.text(f"Giorni lavorati: {p.work_days}   Turni con lavoro notturno: "
                         f"{p.night_shifts}   Notti fuori dal paese di base: {p.nights_abroad}"
                         + (f"   Ferie: {p.holidays}" if p.holidays else ""), M, y, 10, GREY)
            return y
        blocks.append(summary)
    if not periods:
        blocks.append(lambda draw, y: _nothing(pdf, draw, y, "L'elenco dei lavori è vuoto"))
    return pdf.close(_run(pdf, blocks))


# ── Utilizzo del veicolo (VEHICLEUSAGE_) ─────────────────────────────────────

def vehicle_pdf(cd, s, rows, d_from, d_to) -> bytes:
    """
    sessione tra due linee grigie, poi targa a 28, simboli guida/disponibilità a
    98, km inizio, fine e differenza allineati a destra a 178/228/278."""
    tl, first, last = _period(cd, s, d_from, d_to)
    pdf = AppPdf(cd, s, first, last)
    blocks = []
    for r in rows:
        blocks.append(lambda draw, y, r=r: _label_between_lines(pdf, draw, y, r.period))

        def veh(draw, y, r=r):
            y += h(10)
            if draw:
                pdf.text(r.vrn, M, y, 10)
                sz = asc(10) - 2
                if r.drive > 0:
                    icon(pdf, "Guida", 98, y - sz, sz)
                if r.avail > 0:
                    icon(pdf, "Disponibilità", 98 + asc(10), y - sz, sz)
                pdf.text(str(r.odo_begin), 178, y, 10, align="right")
                pdf.text(str(r.odo_end), 228, y, 10, align="right")
                pdf.text(f"{r.km}km", 278, y, 10, align="right")
            return y
        blocks.append(veh)
    if not rows:
        blocks.append(lambda draw, y: _nothing(pdf, draw, y, "Nessun veicolo nel periodo"))
    return pdf.close(_run(pdf, blocks))


# ── Paesi visitati (COUNTRY_) ────────────────────────────────────────────────

def country_pdf(cd, s, stays, only_base, d_from, d_to) -> bytes:
    """periodo tra due
    linee, paese a 28 con Guida/Lavoro/Disponibilità/Riposo (valori a 160/218/276/
    350), poi entrata, uscita e distanza rientrate a 38."""
    tl, first, last = _period(cd, s, d_from, d_to)
    pdf = AppPdf(cd, s, first, last)
    blocks = []
    if only_base:
        blocks.append(lambda draw, y: _nothing(
            pdf, draw, y, "L'autista non ha lavorato al di fuori del paese di base"))
    for x in [] if only_base else stays:
        blocks.append(lambda draw, y, x=x: _label_between_lines(pdf, draw, y, x.period))

        def row(draw, y, x=x):
            y += h(10)
            if draw:
                base = x.country == s.basecountry
                pdf.text(x.name, M, y, 10, font=BOLD if base else FONT)
                sz = asc(10) - 2
                for kind, ix, vx, v in (("Guida", 148, 160, x.drive),
                                        ("Lavoro", 206, 218, x.work),
                                        ("Disponibilità", 264, 276, x.avail),
                                        ("Riposo", 322, 350, x.brk)):
                    icon(pdf, kind, ix, y - sz, sz)
                    pdf.text(_dur(v, s), vx, y, 10)
            y += h(10)
            if draw:
                pdf.text(f"{x.entered}: {x.vrn_in} ({x.km_in}km)" if x.vrn_in
                         else f"{x.entered}:", 38, y, 10)
            y += h(10)
            if draw:
                pdf.text(f"{x.left}: {x.vrn_out} ({x.km_out}km)" if x.vrn_out
                         else f"{x.left}:", 38, y, 10)
            if x.vrn_in and x.vrn_in == x.vrn_out:
                y += h(10)
                if draw:
                    pdf.text(f"Distanza: {x.distance}km", 38, y, 10)
            return y
        blocks.append(row)
    if not stays and not only_base:
        blocks.append(lambda draw, y: _nothing(pdf, draw, y, "Nessun paese nel periodo"))
    return pdf.close(_run(pdf, blocks))


# ── Infrazioni (INFRINGEMENT_) ───────────────────────────────────────────────

_STARS = {"MI": "*", "SI": "**", "VSI": "***", "MSI": "****"}


def _split80(text, width, size=10, font=FONT):
    """al massimo 2 righe: la prima entro la larghezza."""
    parts = wrap(text or "", width, size, font)
    return parts[0], " ".join(parts[1:])


def infringement_pdf(cd, s, viols, d_from, d_to, grouped=False, signature=True) -> bytes:
    """per ogni infrazione
    linea grigia, descrizione (80% della larghezza) con la gravità in stelle
    allineata a destra (* MI, ** SI, *** VSI, **** MSI), periodo, dettagli in
    grigio; "raggruppato" = intestazione "descrizione (n)" in grassetto e voci
    rientrate. Alla fine, i campi per la firma."""
    tl, first, last = _period(cd, s, d_from, d_to)
    pdf = AppPdf(cd, s, first, last)
    r10 = h(10)
    blocks = []

    def entry(v, indent):
        def blk(draw, y):
            stars = _STARS.get(v.severity, "")
            if indent:
                y += r10 / 2 + r10
                if draw:
                    pdf.text(v.period, M + r10, y, 10)
                    pdf.text(stars, M + CW, y, 10, align="right")
                x = M + r10
            else:
                y += r10
                if draw:
                    pdf.line(M, y, M + CW, y, 1, GREY)
                a, b = _split80(v.description, CW * 0.8)
                y += r10
                if draw:
                    pdf.text(a, M, y, 10)
                    pdf.text(stars, M + CW, y, 10, align="right")
                if b:
                    y += r10
                    if draw:
                        pdf.text(b, M, y, 10)
                y += r10
                if draw:
                    pdf.text(v.period, M, y, 10)
                x = M
            a, b = _split80(v.detail, CW * 0.8)
            y += r10
            if draw:
                pdf.text(a, x, y, 10, GREY)
            if b:
                y += r10
                if draw:
                    pdf.text(b, x, y, 10, GREY)
            return y
        return blk

    if not viols:
        def none(draw, y):
            y += r10
            if draw:
                pdf.line(M, y, M + CW, y, 1, GREY)
            y += r10
            if draw:
                pdf.text("Non ci sono infrazioni", M, y, 10)
            return y
        blocks.append(none)
    elif grouped:
        groups = {}
        for v in viols:
            groups.setdefault(v.description, []).append(v)
        for desc, items in groups.items():
            def head(draw, y, desc=desc, n=len(items)):
                a, b = _split80(f"{desc} ({n})", CW * 0.8, font=BOLD)
                y += r10
                if draw:
                    pdf.line(M, y, M + CW, y, 1, GREY)
                y += r10
                if draw:
                    pdf.text(a, M, y, 10, font=BOLD)
                if b:
                    y += r10
                    if draw:
                        pdf.text(b, M, y, 10, font=BOLD)
                return y
            blocks.append(head)
            blocks += [entry(v, True) for v in items]
    else:
        blocks += [entry(v, False) for v in viols]

    if signature:
        def sign(draw, y):
            w = 0.42 * CW
            x2 = CW + M - w
            y += 3 * r10
            lab = "Data: "
            if draw:
                pdf.text(lab, M, y, 10)
                pdf.line(M + stringWidth(lab, FONT, 10), y, M + w, y, 1, GREY)
            y += 6 * r10
            if draw:
                pdf.line(M, y, M + w, y, 1, GREY)
                pdf.line(x2, y, x2 + w, y, 1, GREY)
            a1, b1 = _split80("Firma di chi ha verificato (responsabile)", w)
            a2, b2 = _split80("Firma del conducente", w)
            y += r10
            if draw:
                pdf.text(a1, M + w / 2, y, 10, GREY, align="center")
                pdf.text(a2, x2 + w / 2, y, 10, GREY, align="center")
            if b1 or b2:
                y += r10
                if draw:
                    pdf.text(b1, M + w / 2, y, 10, GREY, align="center")
                    pdf.text(b2, x2 + w / 2, y, 10, GREY, align="center")
            return y
        blocks.append(sign)
    return pdf.close(_run(pdf, blocks))


# ── Periodi di riposo (REST_) ────────────────────────────────────────────────

def rest_pdf(cd, s, items, d_from, d_to) -> bytes:
    """settimane in
    fascia grigia, turni (guida con continuo, lavoro, disponibilità a 28/113/167)
    e riposi con tipo, compensazioni e paese."""
    from models.rest_report import RestEntry, ShiftEntry, WeekEntry
    tl, first, last = _period(cd, s, d_from, d_to)
    pdf = AppPdf(cd, s, first, last)
    r10 = h(10)
    blocks = []
    for it in items:
        if isinstance(it, WeekEntry):
            blocks.append(lambda draw, y, it=it: _band(
                pdf, draw, y, f"Settimana {it.week}: guida settimanale {_dur(it.one_week, s)}, "
                              f"quindicinale {_dur(it.two_week, s)}"))
        elif isinstance(it, ShiftEntry):
            def sh(draw, y, it=it):
                y += r10
                if draw:
                    pdf.text(it.period, M, y, 10)
                y += r10
                if draw:
                    sz = asc(10) - 2
                    for kind, x, txt in (("Guida", 28, f"{_dur(it.drive, s)} "
                                                       f"({_dur(it.drive_cont, s)})"),
                                         ("Lavoro", 113, _dur(it.work, s)),
                                         ("Disponibilità", 167, _dur(it.avail, s))):
                        icon(pdf, kind, x, y - sz, sz)
                        pdf.text(txt, x + sz + 4, y, 10)
                return y
            blocks.append(sh)
        elif isinstance(it, RestEntry):
            def rs(draw, y, it=it):
                y += 4
                if draw:
                    pdf.line(M, y, M + CW, y, 1, GREY)
                y += r10
                sz = asc(10) - 2
                if draw:
                    icon(pdf, "Riposo", M, y - sz, sz)
                    pdf.text(it.period, M + sz + 6, y, 10)
                    if it.country:
                        pdf.text(it.country, M + CW, y, 10, align="right")
                y += r10
                if draw:
                    pdf.text(it.text, M + 12, y, 10, font=BOLD)
                extra = " ".join(x for x in (it.weeks, it.compensation) if x)
                for part in (wrap(extra, CW - 12, 10) if extra else []):
                    y += r10
                    if draw:
                        pdf.text(part, M + 12, y, 10, GREY)
                return y
            blocks.append(rs)
    if not items:
        blocks.append(lambda draw, y: _nothing(pdf, draw, y, "Nessun periodo di riposo"))
    return pdf.close(_run(pdf, blocks))

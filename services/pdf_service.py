"""
services/pdf_service.py
========================
Generazione di report PDF: attività, infrazioni, riepilogo settimanale.

Questo servizio usa la libreria ReportLab per costruire documenti PDF professionali
da zero, senza template HTML → immagine. ReportLab costruisce il PDF direttamente
come vettore, garantendo qualità perfetta a qualsiasi zoom.

STRUTTURA DEL MODULO:
  _C             → palette colori per il PDF (HexColor ReportLab)
  _ACT, _SEV     → mappe attività→colore e severità→colore
  DayGantt       → classe Flowable personalizzata: disegna il Gantt giornaliero
  _HF            → classe Header/Footer: intestazione su ogni pagina
  _cum_rest()    → helper: calcola il riposo cumulativo fino a una data
  generate_activities()     → PDF attività giornaliere
  generate_violations_pdf() → PDF infrazioni
  generate_weekly()         → PDF riepilogo settimanale

CONCETTI REPORTLAB:
  Story:      lista di Flowable (elementi del documento) da inserire in ordine
  Flowable:   qualsiasi cosa che può essere messa in una storia: Paragraph,
              Table, Spacer, HRFlowable, o classe personalizzata
  SimpleDocTemplate: costruisce il PDF dato una story + template di pagina
  onFirstPage / onLaterPages: callback chiamati su ogni pagina per disegnare
                              intestazione e piè di pagina
  canvas:     oggetto di disegno di basso livello (coordinate in punti PostScript)
  Table:      griglia di celle con colWidths, setStyle(TableStyle([...]))
  KeepTogether: mantiene un blocco sulla stessa pagina (evita il salto pagina a metà)

UNITÀ DI MISURA:
  ReportLab usa "punti PostScript" (1 punto = 1/72 pollice ≈ 0.353 mm).
  mm: costante di ReportLab che converte millimetri → punti (es. 15*mm = 42.5pt)
  A4: costante che definisce le dimensioni della pagina A4 in punti (595×842)

DIPENDENZE:
  - Non dipende da Dash (nessun html.*, dcc.*)
  - Usa utils/time_utils.py per la conversione UTC → ora locale
  - Usa models/violations.py per rilevare le infrazioni nel PDF infrazioni
"""

from __future__ import annotations
import io                    # io.BytesIO: buffer in memoria (simula un file)
from datetime import datetime
from typing import List

# Import funzioni UTC→locale e nomi mesi italiani da utils/time_utils.py
# (refactoring: eliminate duplicazioni con views/tabs/attivita.py)
from utils.time_utils import (
    tz_offset_min as _tz_off,          # offset UTC→locale per una data specifica
    local_time_str as _local_time_str,  # timestamp Unix → "HH:MM" ora locale
    sessions_for_day as _sessions_for_day,  # filtra sessioni veicolo per giorno
    MESI_IT, MESI_IT_BREVI,            # nomi mesi italiani (indice 1=gennaio, …, 12=dicembre)
)

# Importazioni ReportLab
from reportlab.lib import colors           # gestione colori (HexColor, rgb, predefiniti)
from reportlab.lib.pagesizes import A4     # dimensioni foglio A4 in punti PostScript
from reportlab.lib.units import mm         # fattore di conversione: mm → punti
from reportlab.lib.styles import ParagraphStyle  # stile testo (font, dimensione, colore)
from reportlab.lib.enums import TA_CENTER, TA_LEFT  # allineamento testo
from reportlab.platypus import (
    SimpleDocTemplate,  # template PDF: gestisce layout pagine
    Paragraph,          # testo con stile (supporta HTML limitato con <b>, <br/>, ecc.)
    Spacer,             # spazio verticale vuoto
    Table,              # griglia di celle
    TableStyle,         # stile visivo di una tabella (colori, padding, bordi)
    HRFlowable,         # linea orizzontale separatrice
    KeepTogether,       # raggruppa flowable per evitare interruzione di pagina nel mezzo
)
from reportlab.platypus.flowables import Flowable  # classe base per elementi personalizzati

from models.card_data import CardData, DayActivity
from models.violations import detect_violations, violation_summary, SEV_VERY, SEV_HIGH, SEV_LOW


# ── Palette colori PDF ────────────────────────────────────────────────────────
# Versione "chiara" per stampa (sfondo bianco), diversa dal tema dark della UI.
# HexColor(str): crea un colore da una stringa esadecimale CSS.
_C = {
    "guida":  colors.HexColor("#8B3DBF"),  # viola: attività Guida
    "lavoro": colors.HexColor("#E8A000"),  # arancione: attività Lavoro
    "disp":   colors.HexColor("#F0C040"),  # giallo: attività Disponibilità
    "riposo": colors.HexColor("#1EAAE0"),  # blu: attività Riposo
    "header": colors.HexColor("#2C2C2C"),  # grigio scuro: intestazioni tabella
    "grid":   colors.HexColor("#DDDDDD"),  # grigio chiaro: linee griglia
    "axis":   colors.HexColor("#999999"),  # grigio medio: etichette assi
    "bg":     colors.HexColor("#F8F8F8"),  # quasi bianco: sfondo barre Gantt
    "sev_mg": colors.HexColor("#D32F2F"),  # rosso: infrazione Molto Grave
    "sev_g":  colors.HexColor("#E65100"),  # arancione scuro: infrazione Grave
    "sev_l":  colors.HexColor("#F57F17"),  # arancione: infrazione Lieve
}

# Mappa attività → colore ReportLab (usata nel Gantt PDF)
_ACT = {
    "Guida":         _C["guida"],
    "Lavoro":        _C["lavoro"],
    "Disponibilità": _C["disp"],
    "Riposo":        _C["riposo"],
}

# Mappa severità infrazione → colore (usata nella tabella infrazioni)
_SEV = {
    SEV_VERY: _C["sev_mg"],   # Molto Grave → rosso
    SEV_HIGH: _C["sev_g"],    # Grave → arancione scuro
    SEV_LOW:  _C["sev_l"],    # Lieve → arancione
}

# Dimensioni pagina e margini (in punti PostScript)
PAGE_W, PAGE_H = A4   # A4: 595 × 842 punti (≈ 210 × 297 mm)
MARGIN    = 15*mm      # margine laterale: 15 mm
CONTENT_W = PAGE_W - 2*MARGIN  # larghezza area stampabile


# ── Stili testo (ParagraphStyle) ─────────────────────────────────────────────
# ParagraphStyle: definisce font, dimensione, colore, interlinea per un tipo di testo.
# "leading": interlinea (distanza tra le baseline di due righe consecutive).
_ST = {
    "day":   ParagraphStyle("day",  fontName="Helvetica-Bold", fontSize=12, spaceAfter=1*mm),
    # "day": intestazione giorno (es. "15 mag 2024 (mercoledì)")
    "empty": ParagraphStyle("emp",  fontName="Helvetica-Oblique", fontSize=8, textColor=_C["axis"]),
    # "empty": messaggio "nessuna attività" in corsivo grigio
    "log":   ParagraphStyle("log",  fontName="Courier", fontSize=7, leading=9),
    # "log": righe di log attività (font monospace per allineamento colonne)
    "th":    ParagraphStyle("th",   fontName="Helvetica-Bold", fontSize=8, textColor=colors.white),
    # "th": intestazione colonna tabella (bianco su sfondo scuro)
    "td":    ParagraphStyle("td",   fontName="Helvetica", fontSize=8, leading=11),
    # "td": cella tabella normale
    "tdm":   ParagraphStyle("tdm",  fontName="Courier",   fontSize=8, leading=11),
    # "tdm": cella tabella con font monospace (es. orari, durate)
    "foot":  ParagraphStyle("foot", fontName="Helvetica", fontSize=7, textColor=_C["axis"]),
    # "foot": testo piè di pagina
}


def _fmth(m: int) -> str:
    """
    Formatta una durata in minuti come stringa "HH:MM".
    abs(m): gestisce durate negative (es. calcoli con segni misti).
    Esempio: 95 → "01:35"
    """
    h, mn = divmod(abs(m), 60)
    return f"{h:02d}:{mn:02d}"


def _period(activities: list) -> str:
    """
    Calcola e formatta il periodo coperto dalle attività (data inizio — data fine).

    Usata nell'intestazione del PDF per mostrare l'intervallo di date.
    Esempio: "25 ott 2022 — 5 lug 2024"

    Gestisce sia oggetti DayActivity (attributo .date) sia dizionari Python
    (chiave "date"), perché dcc.Store serializza gli oggetti in JSON.
    """
    if not activities:
        return "—"
    dates = [a.date if hasattr(a, "date") else a["date"] for a in activities]

    def _fmt(s):
        """Converte 'YYYY-MM-DD' in '5 lug 2024' usando i mesi italiani abbreviati."""
        dt = datetime.strptime(s, "%Y-%m-%d")
        return f"{dt.day} {MESI_IT_BREVI[dt.month]} {dt.year}"

    return f"{_fmt(min(dates))} — {_fmt(max(dates))}"


# ── Flowable personalizzato: Gantt giornaliero ────────────────────────────────
class DayGantt(Flowable):
    """
    Disegna il grafico Gantt orizzontale per un singolo giorno nel PDF.

    Classe Flowable (elemento ReportLab personalizzato):
      - Estende Flowable: ReportLab la tratta come un blocco rettangolare
      - wrap(aw, ah): dice a ReportLab quanto spazio occupa (width × HEIGHT)
      - draw(): disegna il contenuto sul canvas a coordinate locali (0,0 = angolo in basso a sinistra)

    STRUTTURA VISIVA del Gantt (dall'alto al basso nel PDF, ma coordinate canvas
    crescono dal basso verso l'alto):
      [AREA GANTT: 8mm di altezza]   ← barre colorate delle attività
      [ASSE X: etichette orarie]     ← "00", "02", "04", ..., "22"
      [BARRA RIPOSO CUMULATIVO: 4mm] ← blu con ore riposo accumulate fino a quel giorno

    COORDINATE CANVAS:
      Il canvas ha origine (0,0) in basso a sinistra. L'asse Y cresce verso l'alto.
      REST_H=4mm: la barra riposo occupa y=0..4mm
      AXIS_Y=REST_H+1mm=5mm: la griglia Gantt inizia a y=5mm
      BAR_H=8mm: le barre attività occupano y=5mm..13mm

    ORA LOCALE:
      I tempi ACI sono in minuti UTC. L'offset tz (in minuti) viene aggiunto
      per ottenere la posizione orizzontale corretta nell'ora locale.
      t0_loc = (t0 + tz) % 1440 → minuti locali dall'inizio della giornata locale
    """
    HEIGHT = 22*mm   # altezza totale del Gantt (barre + asse + riposo)

    def __init__(self, changes, rest_cumul: int = 0, width: float = CONTENT_W, tz_offset_min: int = 0):
        """
        Parametri:
            changes:       lista di ActivityChange (o dict da JSON) con i cambi attività del giorno
            rest_cumul:    minuti totali di riposo accumulati fino a questo giorno
            width:         larghezza del Gantt in punti (default = larghezza contenuto pagina)
            tz_offset_min: offset UTC→locale in minuti (es. 120 per UTC+2)
        """
        super().__init__()
        from models.card_data import ActivityChange
        # Gestisce il doppio formato: oggetti ActivityChange o dict (da dcc.Store JSON)
        if changes and isinstance(changes[0], dict):
            changes = [ActivityChange(**c) for c in changes]
        self.changes       = sorted(changes, key=lambda c: c.time)
        self.rest_cumul    = rest_cumul
        self.width         = width
        self.tz_offset_min = tz_offset_min
        self._height       = self.HEIGHT

    def wrap(self, aw, ah):
        """
        Metodo obbligatorio di Flowable: ritorna (larghezza, altezza) del componente.
        ReportLab chiama wrap() per sapere quanto spazio riservare prima di disegnare.
        """
        return self.width, self._height

    def draw(self):
        """
        Disegna il Gantt sul canvas ReportLab.
        Tutti i metodi canvas (setFillColor, rect, line, drawString) operano
        in coordinate locali (0,0 = angolo in basso a sinistra del Flowable).
        """
        c = self.canv       # canvas ReportLab per il disegno
        w = self.width      # larghezza totale in punti

        tz    = self.tz_offset_min
        BAR_H = 8*mm    # altezza barre attività
        REST_H = 4*mm   # altezza barra riposo cumulativo
        AXIS_Y = REST_H + 1*mm   # coordinata Y della base delle barre attività
        TICK_H = 1.5*mm  # altezza dei tick sull'asse X

        # ── Sfondo grigio chiaro per la zona Gantt ──────────────────────────────
        c.setFillColor(_C["bg"])
        c.rect(0, AXIS_Y, w, BAR_H, fill=1, stroke=0)

        # ── Griglia verticale: 24 linee (una ogni ora) ─────────────────────────
        c.setStrokeColor(_C["grid"])
        c.setLineWidth(0.3)
        for ht in range(0, 25):
            c.line(w * ht / 24, AXIS_Y, w * ht / 24, AXIS_Y + BAR_H)

        # ── Barre colorate delle attività ───────────────────────────────────────
        for i, ch in enumerate(self.changes):
            t0 = ch.time
            # Fine del segmento: inizio del successivo, oppure mezzanotte (1440)
            t1 = self.changes[i + 1].time if i + 1 < len(self.changes) else 1440
            if t1 <= t0:
                continue   # segmento di durata nulla: skip

            # Converti in minuti locali per la posizione X della barra
            t0_loc = (t0 + tz) % 1440
            t1_loc = (t1 + tz) % 1440

            # Gestisci il rollover mezzanotte locale (es. segmento che va oltre le 24:00 locali)
            if t1_loc < t0_loc:
                t1_loc = 1440   # la barra arriva fino al bordo destro

            c.setFillColor(_ACT.get(ch.activity, colors.grey))
            c.setStrokeColor(colors.white)
            c.setLineWidth(0.3)
            # rect(x, y, width, height): disegna rettangolo con fill e stroke
            c.rect(
                w * t0_loc / 1440,          # x di inizio (proporzione del giorno)
                AXIS_Y,                      # y di base
                w * (t1_loc - t0_loc) / 1440,  # larghezza proporzionale alla durata
                BAR_H,                       # altezza fissa
                fill=1, stroke=1,
            )

        # ── Barra riposo cumulativo (in basso, blu) ─────────────────────────────
        h_str = f"{self.rest_cumul // 60}:{self.rest_cumul % 60:02d}"
        c.setFillColor(_C["riposo"])
        c.rect(0, 0, w, REST_H, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(w / 2, REST_H * 0.25, f"  {h_str}")

        # ── Etichette asse X (ore locali, ogni 2h) ─────────────────────────────
        c.setFont("Helvetica", 6)
        c.setFillColor(_C["axis"])
        tz_h = tz // 60   # offset in ore intere (es. 120 min → 2h)
        for ht in range(0, 25, 2):
            x = w * ht / 24
            c.line(x, AXIS_Y - TICK_H, x, AXIS_Y)   # tick verticale sull'asse
            # Etichetta oraria locale: (ht + offset_ore) % 24
            label = str((ht + tz_h) % 24).zfill(2)
            c.drawCentredString(x, AXIS_Y - TICK_H - 2.5*mm, label)


# ── Classe Header/Footer (intestazione e piè di pagina) ─────────────────────
class _HF:
    """
    Callable usata come onFirstPage e onLaterPages nel SimpleDocTemplate.

    ReportLab chiama __call__(canvas, doc) su ogni pagina del documento.
    Il canvas è in modalità "pagina intera" (coordinate assolute A4).
    saveState() / restoreState(): salva/ripristina lo stato grafico del canvas
    (evita che le impostazioni dell'header interferiscano col corpo della pagina).

    STRUTTURA INTESTAZIONE (dall'alto al basso):
      - Nome conducente in grassetto (14pt)
      - 4 righe dati anagrafici (8pt)
      - Linea separatrice orizzontale
      - Titolo periodo (11pt, centrato)

    PIÈ DI PAGINA:
      - "Powered by TachoVision Pro" (sinistra)
      - "Pagina N" (centro)
      - Data/ora generazione PDF (destra)
    """
    def __init__(self, cd: CardData, period: str, title: str):
        """
        Parametri:
            cd:     CardData con i dati del conducente
            period: stringa periodo (es. "25 ott 2022 — 5 lug 2024")
            title:  titolo del documento (es. "Attività", "Infrazioni")
        """
        self.cd      = cd
        self.period  = period
        self.title   = title
        # Genera la data/ora di creazione del PDF in italiano
        now = datetime.now()
        self.generated = f"{now.day} {MESI_IT[now.month]} {now.year} {now.strftime('%H:%M')}"

    def __call__(self, canvas, doc):
        """
        Disegna header e footer su ogni pagina.
        doc.page: numero di pagina corrente (da 1).
        Tutte le coordinate sono assolute sulla pagina A4.
        """
        canvas.saveState()   # salva stato grafico per non contaminare il corpo
        d = self.cd.driver

        # ── Titolo: nome conducente ─────────────────────────────────────────────
        canvas.setFont("Helvetica-Bold", 14)
        canvas.setFillColor(_C["header"])
        canvas.drawString(MARGIN, PAGE_H - 18*mm, d.full_name)

        # ── Dati anagrafici (4 righe) ───────────────────────────────────────────
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#555555"))
        y = PAGE_H - 24*mm   # posizione Y iniziale (scende di 4mm per ogni riga)
        for line in [
            f"Data di nascita: {d.birth_date}",
            f"Numero carta conducente: {d.card_number}",
            f"Lettura carta: {d.last_download or '—'}",
            "Fuso orario: Europe/Rome",
        ]:
            canvas.drawString(MARGIN, y, line)
            y -= 4*mm

        # ── Linea separatrice ───────────────────────────────────────────────────
        canvas.setStrokeColor(_C["header"])
        canvas.setLineWidth(1)
        canvas.line(MARGIN, PAGE_H - 42*mm, PAGE_W - MARGIN, PAGE_H - 42*mm)

        # ── Titolo periodo (centrato) ───────────────────────────────────────────
        canvas.setFont("Helvetica-Bold", 11)
        canvas.setFillColor(_C["header"])
        canvas.drawCentredString(PAGE_W / 2, PAGE_H - 48*mm, f"Periodo: {self.period}")

        # ── Piè di pagina ───────────────────────────────────────────────────────
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_C["axis"])
        canvas.drawString(MARGIN, 8*mm, "Powered by TachoVision Pro")
        canvas.drawCentredString(PAGE_W / 2, 8*mm, f"Pagina {doc.page}")
        canvas.drawRightString(PAGE_W - MARGIN, 8*mm, self.generated)

        canvas.restoreState()   # ripristina stato grafico


# ── Helper: calcola riposo cumulativo fino a una data ────────────────────────
def _cum_rest(activities, current_date: str) -> int:
    """
    Calcola i minuti totali di Riposo registrati fino alla data corrente (inclusa).

    Usato per mostrare nella barra blu del Gantt PDF quante ore di riposo
    il conducente ha accumulato dall'inizio della registrazione.

    Algoritmo:
      - Ordina i giorni cronologicamente
      - Interrompe non appena trova un giorno SUCCESSIVO a current_date
      - Somma tutti i segmenti di Riposo (e - s in minuti)
    """
    total = 0
    for day in sorted(activities, key=lambda d: d.date):
        if day.date > current_date:
            break   # non considerare giorni futuri
        for s, e, a in day.segments():
            if a == "Riposo":
                total += max(0, e - s)
    return total


# ── Generazione PDF Attività ──────────────────────────────────────────────────
def generate_activities(cd: CardData) -> bytes:
    """
    Genera il PDF con tutte le attività giornaliere del conducente.

    OUTPUT:
      bytes del PDF completo, pronti per essere scritti su file o inviati via email.

    STRUTTURA DEL PDF:
      Per ogni giorno (dal più recente al più vecchio):
        1. Intestazione giorno (data + giorno della settimana)
        2. Linea separatrice
        3. DayGantt: Gantt grafico delle attività + barra riposo cumulativo
        4. Log testuale delle attività in due colonne:
           - Riga "ENTRATA  HH:MM  TARGA  km" (carta inserita)
           - Righe "HH:MM  >> Guida  01:30" per ogni segmento
           - Riga "USCITA  HH:MM  TARGA  km  (+X km)" (carta disinserita)
        5. Spacer di 4mm

    COLONNE LOG:
      Il log testuale viene diviso in due metà e mostrato affiancato
      per ottimizzare lo spazio verticale.
      half = len(lines)//2 + len(lines)%2 → metà arrotondata per eccesso

    KeepTogether: raggruppa il blocco di un giorno per evitare che si spezzi
      tra due pagine. Se il giorno ha > 15 righe, KeepTogether non viene usato
      (troppo lungo da tenere insieme → si lascia spezzare).

    io.BytesIO: buffer in memoria che si comporta come un file.
      doc.build() scrive il PDF nel buffer.
      buf.getvalue() restituisce i bytes scritti.
    """
    buf  = io.BytesIO()
    acts = sorted(cd.activities, key=lambda d: d.date, reverse=True)  # dal più recente
    period = _period(acts)

    # Crea il documento PDF con l'intestazione su ogni pagina
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=52*mm,   # spazio per l'intestazione (52mm dall'alto)
        bottomMargin=18*mm,
        onFirstPage=_HF(cd, period, "Attività"),
        onLaterPages=_HF(cd, period, "Attività"),
    )

    WDAYS = ["lunedì","martedì","mercoledì","giovedì","venerdì","sabato","domenica"]
    story = []
    # Icone testuali per ogni attività nel log (Courier monospace per allineamento)
    ACT_ICON = {"Guida": ">>", "Lavoro": "**", "Disponibilità": "--", "Riposo": "  "}

    for day in acts:
        dt    = datetime.strptime(day.date, "%Y-%m-%d")
        # Intestazione giorno: "15 mag 2024 (mercoledì)"
        label = f"{dt.day} {MESI_IT_BREVI[dt.month]} {dt.year} ({WDAYS[dt.weekday()]})"
        cum   = _cum_rest(acts, day.date)   # minuti riposo cumulativi
        tz    = _tz_off(day.date)           # offset fuso orario per questo giorno

        # Sessioni veicolo del giorno (inserimento/disinserimento carta)
        day_sess = _sessions_for_day(cd.vehicle_sessions, day.date)

        # Blocco flowable per questo giorno
        block = [
            Paragraph(label, _ST["day"]),
            HRFlowable(width="100%", thickness=0.5, color=_C["grid"], spaceAfter=1*mm),
        ]

        if not day.changes:
            # Giorno senza attività: mostra solo il Gantt vuoto e un messaggio
            block.append(DayGantt([], cum, tz_offset_min=tz))
            block.append(Paragraph("Non ci sono attività in questo giorno", _ST["empty"]))
        else:
            block.append(DayGantt(day.changes, cum, tz_offset_min=tz))
            ch = sorted(day.changes, key=lambda c: c.time)
            lines = []

            # Riga "ENTRATA": prima sessione del giorno
            if day_sess:
                s     = day_sess[0]
                km_in = f"{s.odo_begin_km:,}".replace(",", ".")
                lines.append(f"ENTRATA  {_local_time_str(s.first_use_utc)}  {s.vrn:<10}  {km_in} km")

            # Righe di ogni segmento di attività
            for i, c in enumerate(ch):
                t0  = c.time
                t1  = ch[i + 1].time if i + 1 < len(ch) else 1440
                dur = max(0, t1 - t0)
                # Converti t0 in ora locale per il log
                loc0 = (t0 + tz) % 1440
                lines.append(
                    f"      {loc0//60:02d}:{loc0%60:02d}:00  {ACT_ICON.get(c.activity,'•')}  "
                    f"{c.activity:<14}  {_fmth(dur)}"
                    f"{'  [M]' if c.manual else ''}"   # [M] se inserimento manuale
                )

            # Riga "USCITA": ultima sessione del giorno
            if day_sess:
                s      = day_sess[-1]
                km_out = f"{s.odo_end_km:,}".replace(",", ".")
                delta  = s.odo_end_km - s.odo_begin_km
                delta_str = f"  (+{delta} km)" if 0 < delta <= 5000 else ""
                lines.append(f"USCITA   {_local_time_str(s.last_use_utc)}  {s.vrn:<10}  {km_out} km{delta_str}")

            # Riga distanza giornaliera
            if day.distance_km:
                lines.append(f"{'':>30}  Dist. {day.distance_km:.0f} km")

            # Divide il log in due colonne affiancate per risparmiare spazio verticale
            half     = len(lines) // 2 + len(lines) % 2   # metà arrotondata per eccesso
            col_a, col_b = lines[:half], lines[half:]
            while len(col_b) < len(col_a):
                col_b.append("")   # padding per allineare le colonne

            # Costruisce la tabella a due colonne per le righe di log
            rows = [[Paragraph(a, _ST["log"]), Paragraph(b, _ST["log"])]
                    for a, b in zip(col_a, col_b)]
            if rows:
                t = Table(rows, colWidths=[CONTENT_W * 0.5 - 2*mm] * 2, hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("TOPPADDING",    (0,0), (-1,-1), 0.5),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 0.5),
                    ("LEFTPADDING",   (0,0), (-1,-1), 0),
                    ("RIGHTPADDING",  (0,0), (-1,-1), 2),
                    ("VALIGN",        (0,0), (-1,-1), "TOP"),
                    ("LINEAFTER",     (0,0), (0,-1),  0.3, _C["grid"]),  # linea divisoria tra le 2 col
                ]))
                block.append(t)

        block.append(Spacer(1, 4*mm))   # spazio dopo ogni giorno

        # KeepTogether: tiene il blocco sulla stessa pagina se ha ≤ 15 segmenti
        # Con > 15 segmenti il blocco è troppo lungo → si lascia spezzare naturalmente
        story.append(KeepTogether(block) if len(day.changes) <= 15 else block[0])
        if len(day.changes) > 15:
            story.extend(block[1:])

    if not story:
        story.append(Paragraph("Nessuna attività.", _ST["empty"]))

    doc.build(story)         # costruisce il PDF e lo scrive in buf
    return buf.getvalue()    # ritorna i bytes del PDF


# ── Generazione PDF Infrazioni ────────────────────────────────────────────────
def generate_violations_pdf(cd: CardData) -> bytes:
    """
    Genera il PDF con tutte le infrazioni rilevate.

    STRUTTURA DEL PDF:
      1. Tabella riepilogo: 4 celle con conteggio per severità (MG, G, L, Tot)
      2. Se nessuna infrazione: messaggio verde "Nessuna infrazione rilevata"
      3. Tabella infrazioni con colonne:
         Data | Infrazione + dettaglio | Rilevato | Limite | Eccesso | Severità

    STILE TABELLA INFRAZIONI:
      - Intestazione scura su sfondo _C["header"]
      - Righe alternate bianco/grigio chiarissimo (ROWBACKGROUNDS)
      - Colonna Severità colorata con il colore della gravità
      - repeatRows=1: ripete l'intestazione su ogni pagina

    STILE TABELLA RIEPILOGO:
      - 4 celle colorate per severità + totale
      - Colore cella = colore della severità corrispondente
    """
    buf   = io.BytesIO()
    viols = detect_violations(cd.activities)   # lista Violation
    vs    = violation_summary(viols)            # {SEV_VERY: N, SEV_HIGH: N, SEV_LOW: N, "total": N}
    period = _period(cd.activities)

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=52*mm, bottomMargin=18*mm,
        onFirstPage=_HF(cd, period, "Infrazioni"),
        onLaterPages=_HF(cd, period, "Infrazioni"),
    )
    story = []

    # ── Tabella riepilogo conteggi (4 celle colorate) ─────────────────────────
    cnt_data = [[Paragraph(f"{ic}  {vs[s]}\n{s}",
                           ParagraphStyle("cn", fontName="Helvetica-Bold", fontSize=10,
                                          textColor=colors.white))
                 for ic, s in [("🚨", SEV_VERY), ("🔴", SEV_HIGH), ("🟡", SEV_LOW), ("⚠️", "total")]]]
    cnt = Table(cnt_data, colWidths=[CONTENT_W / 4] * 4)
    cnt.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (0,0), _C["sev_mg"]),   # Molto Grave → rosso
        ("BACKGROUND",    (1,0), (1,0), _C["sev_g"]),    # Grave → arancione scuro
        ("BACKGROUND",    (2,0), (2,0), _C["sev_l"]),    # Lieve → arancione
        ("BACKGROUND",    (3,0), (3,0), colors.HexColor("#555")),  # Totale → grigio
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("BOX",           (0,0), (-1,-1), 0.5, colors.white),
        ("INNERGRID",     (0,0), (-1,-1), 0.5, colors.white),
    ]))
    story.append(cnt)
    story.append(Spacer(1, 6*mm))

    # ── Caso nessuna infrazione ────────────────────────────────────────────────
    if not viols:
        story.append(Paragraph("✅  Nessuna infrazione rilevata.",
            ParagraphStyle("ok", fontName="Helvetica", fontSize=11,
                           textColor=colors.HexColor("#2E7D32"))))
        doc.build(story)
        return buf.getvalue()

    # ── Tabella infrazioni ────────────────────────────────────────────────────
    header = [Paragraph(t, _ST["th"]) for t in
              ["Data", "Infrazione", "Rilevato", "Limite", "Eccesso", "Severità"]]
    rows = [header]

    for v in viols:
        sc = _SEV.get(v.severity, colors.grey)   # colore della severità
        rows.append([
            Paragraph(v.date_display, _ST["tdm"]),
            # Cella "Infrazione": titolo in grassetto + dettaglio in piccolo grigio
            Paragraph(f"<b>{v.description}</b><br/>"
                      f"<font size='7' color='#666'>{v.detail}</font>", _ST["td"]),
            Paragraph(v.value_h,             _ST["tdm"]),   # valore rilevato (es. "10h30")
            Paragraph(v.limit_h,             _ST["tdm"]),   # limite normativo
            Paragraph(f"<b>{v.excess_h}</b>", _ST["tdm"]), # eccesso in grassetto
            # Cella Severità: testo bianco su sfondo colorato (applicato con setStyle)
            Paragraph(f"{v.icon} {v.severity}",
                ParagraphStyle("sv", fontName="Helvetica-Bold", fontSize=8,
                               alignment=TA_CENTER, textColor=colors.white)),
        ])

    # Larghezze colonne: Data(22mm) + Infrazione(residuo) + 3×18mm + Severità(25mm)
    cws = [22*mm, CONTENT_W - 22*mm - 18*3*mm - 25*mm] + [18*mm] * 3 + [25*mm]
    tbl = Table(rows, colWidths=cws, repeatRows=1)

    # Stile base della tabella
    sty = [
        ("BACKGROUND",    (0,0),  (-1,0), _C["header"]),   # intestazione scura
        ("TEXTCOLOR",     (0,0),  (-1,0), colors.white),
        ("FONTNAME",      (0,0),  (-1,0), "Helvetica-Bold"),
        ("ALIGN",         (0,0),  (-1,-1), "LEFT"),
        ("VALIGN",        (0,0),  (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0),  (-1,-1), 3),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 3),
        ("INNERGRID",     (0,0),  (-1,-1), 0.3, _C["grid"]),
        ("BOX",           (0,0),  (-1,-1), 0.5, colors.HexColor("#AAA")),
        # Righe alternate: bianco / grigio chiarissimo
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9F9F9")]),
    ]
    # Colorazione cella Severità (colonna 5) per ogni riga di infrazione
    for i, v in enumerate(viols, 1):  # enumerate da 1: la riga 0 è l'intestazione
        sty.append(("BACKGROUND", (5,i), (5,i), _SEV.get(v.severity, colors.grey)))

    tbl.setStyle(TableStyle(sty))
    story.append(tbl)
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_C["grid"]))
    story.append(Spacer(1, 2*mm))
    # Nota normativa in corsivo a piè di tabella
    story.append(Paragraph("<i>Reg. (CE) n. 561/2006 + Direttiva 2002/15/CE</i>",
        ParagraphStyle("ref", fontName="Helvetica-Oblique", fontSize=7, textColor=_C["axis"])))

    doc.build(story)
    return buf.getvalue()


# ── Generazione PDF Riepilogo settimanale ─────────────────────────────────────
def generate_weekly(cd: CardData) -> bytes:
    """
    Genera il PDF con il riepilogo delle ore per settimana.

    STRUTTURA:
      Una singola tabella con una riga per ogni settimana nel file DDD.
      Colonne: Settimana | Gg | Guida | Lavoro | Dispon. | Riposo | Tot.Lavoro | Km | ⚠

    Colonna ⚠: mostra "⚠️" se la settimana supera il limite 56h guida
              o 48h lavoro, "✅" se tutto in regola.

    La tabella usa repeatRows=1 per ripetere l'intestazione su ogni pagina.

    doc.build([tbl]): storia di un solo elemento (la tabella).
    """
    buf    = io.BytesIO()
    period = _period(cd.activities)

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=52*mm, bottomMargin=18*mm,
        onFirstPage=_HF(cd, period, "Riepilogo"),
        onLaterPages=_HF(cd, period, "Riepilogo"),
    )

    # Intestazione tabella
    header = [Paragraph(t, _ST["th"]) for t in
              ["Settimana", "Gg", "Guida", "Lavoro", "Dispon.", "Riposo",
               "Tot.Lavoro", "Km", "⚠"]]
    rows = [header]

    for w in cd.weekly_summary:
        rows.append([
            Paragraph(f"Sett. {w.week_label}",
                ParagraphStyle("wl", fontName="Courier", fontSize=8)),
            Paragraph(str(w.days),      _ST["tdm"]),
            Paragraph(w.guida,          _ST["tdm"]),   # es. "56h00"
            Paragraph(w.lavoro,         _ST["tdm"]),
            Paragraph(w.disponibilita,  _ST["tdm"]),
            Paragraph(w.riposo,         _ST["tdm"]),
            Paragraph(w.totale_lavoro,  _ST["tdm"]),
            Paragraph(f"{w.km:.0f}",    _ST["tdm"]),
            # Indicatore visivo: ⚠️ se supera limiti, ✅ se conforme
            Paragraph("⚠️" if w.over56h or w.over48h_work else "✅", _ST["tdm"]),
        ])

    # Larghezze colonne (totale = CONTENT_W)
    cws = [30*mm, 10*mm] + [20*mm] * 5 + [18*mm, 10*mm]
    tbl = Table(rows, colWidths=cws, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),  (-1,0), _C["header"]),
        ("TEXTCOLOR",     (0,0),  (-1,0), colors.white),
        ("FONTNAME",      (0,0),  (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),  (-1,-1), 8),
        ("ALIGN",         (0,0),  (-1,-1), "CENTER"),
        ("VALIGN",        (0,0),  (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),  (-1,-1), 3),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 3),
        ("INNERGRID",     (0,0),  (-1,-1), 0.3, _C["grid"]),
        ("BOX",           (0,0),  (-1,-1), 0.5, colors.HexColor("#AAA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9F9F9")]),
    ]))

    doc.build([tbl])
    return buf.getvalue()

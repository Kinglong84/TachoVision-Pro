# TachoVision Pro

![Beta](https://img.shields.io/badge/versione-beta-orange)
![Python](https://img.shields.io/badge/python-3.10--3.13-blue)
![License](https://img.shields.io/badge/licenza-uso%20personale-lightgrey)

Applicazione web locale per analizzare le **carte tachigrafo digitali** (file `.DDD`).  
Supporta la lettura da lettore USB smartcard e il caricamento diretto del file.

> ⚠️ **Versione Beta** — Prima release pubblica. Il software è funzionante ma potrebbero
> essere presenti bug. Per segnalazioni apri una [Issue](../../issues) su GitHub.

---

## Funzionalità

| Tab | Cosa mostra |
|---|---|
| **Panoramica** | Riepilogo rapido: ore guida, lavoro, disponibilità, riposo |
| **Attività** | Calendario giornaliero con timeline attività e icone GPS |
| **Riepilogo ore** | Totali per settimana e mese con grafici Plotly |
| **Riposo** | Analisi periodi di riposo giornalieri e settimanali |
| **Infrazioni** | Rilevamento automatico violazioni Reg. CE 561/2006 + Dir. 2002/15/CE |
| **Veicoli** | Lista veicoli usati con targa, date, km percorsi e VIN (Gen2) |
| **Luoghi** | Registro luoghi con nazione, data/ora, coordinate GNSS |
| **Carta** | Dati anagrafici conducente, numero carta, patente, scadenze |
| **Archivio** | Gestione file `.DDD` salvati localmente con alert scadenza 28 giorni |
| **Condivisione** | Invio via email e upload su Google Drive / OneDrive / Dropbox |

**Formati supportati:**
- Gen1 (Reg. CE 1360/2002 / Reg. 3821/85)
- Gen2 V1 (Reg. UE 2016/799) — con dati GNSS
- Gen2 V2 — con buffer attività a coppia UTC/locale

---

## Requisiti

- **Python 3.9+**
- **Windows** (testato su Win 10/11) — macOS e Linux supportati

---

## Installazione

### Windows — metodo rapido

Doppio clic su **`installa_windows.bat`** oppure, da PowerShell:

```powershell
.\installa_windows.ps1
```

Lo script installa automaticamente tutte le dipendenze Python.

### Manuale (Windows / macOS / Linux)

```bash
pip install -r requirements.txt
```

### Lettore smartcard USB (opzionale)

Per leggere la carta direttamente dal lettore fisico USB è necessario **pyscard**.

#### Python 3.10 – 3.13 (Windows, macOS) — installazione diretta ✅

pyscard distribuisce wheel pre-compilati su PyPI per Python 3.10, 3.11, 3.12 e 3.13.
**Nessun compilatore necessario**, basta:

```bash
pip install pyscard
```

#### Python 3.9 o 3.14+ su Windows — Build Tools richiesti ⚠️

Per Python 3.9 su Windows e per Python 3.14 o superiore (wheel non ancora disponibili),
è necessario installare prima i **Microsoft C++ Build Tools**:

1. Scarica da: [visualstudio.microsoft.com/visual-cpp-build-tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
2. Installa il workload **"Sviluppo di applicazioni desktop con C++"**
3. Poi esegui:
   ```bash
   pip install pyscard
   ```

#### Linux — pacchetti di sistema richiesti

```bash
# Debian / Ubuntu
sudo apt-get install swig libpcsclite-dev
pip install pyscard

# Fedora / RHEL
sudo dnf install pcsc-lite-devel swig
pip install pyscard
```

> Senza pyscard l'applicazione funziona normalmente caricando file `.DDD` dal disco.  
> Gli script di installazione Windows (`installa_windows.bat` / `.ps1`) gestiscono  
> automaticamente entrambi i casi: provano prima il wheel, poi mostrano le istruzioni  
> Build Tools solo se necessario.

---

## Avvio

```bash
python app.py
```

Apri il browser su: **http://localhost:8050**

L'app è accessibile anche dagli altri dispositivi sulla stessa rete locale
(`http://<ip-del-pc>:8050`).

### Avvio rapido su Windows

Doppio clic su **`start_app.bat`**

---

## Utilizzo

### Caricamento da file

1. Clicca **"Carica .DDD"** nella barra in alto (o trascina il file)
2. Seleziona il file `.DDD` dalla carta tachigrafo
3. I dati vengono caricati e visualizzati automaticamente

### Lettura da lettore USB

1. Inserisci la carta nel lettore USB collegato al PC
2. Clicca **"Leggi Carta"**
3. Attendi il completamento della lettura (10-30 secondi)

Il file viene salvato automaticamente nell'archivio locale.

### Navigazione

Usa la **sidebar** a sinistra per passare tra le tab.  
La barra di ricerca in alto filtra il contenuto della tab corrente.

### Export

| Pulsante | Output |
|---|---|
| **CSV** | Tutte le attività in formato tabellare |
| **PDF Attività** | Resoconto giornaliero completo |
| **PDF Infrazioni** | Solo le infrazioni rilevate |
| **PDF Riepilogo** | Riepilogo settimanale ore |

### Archivio locale

La tab **Archivio** conserva tutti i file `.DDD` letti o caricati.  
Mostra un avviso quando la scadenza dei 28 giorni (obbligo di legge) si avvicina.

---

## Infrazioni rilevate

Implementate secondo **Reg. CE 561/2006** e **Dir. 2002/15/CE**:

| Codice | Norma | Soglia |
|---|---|---|
| Guida continua | Art. 7 | > 4h 30min senza pausa 45min |
| Guida giornaliera | Art. 6 §1 | > 9h (o > 10h max 2×/settimana) |
| Guida settimanale | Art. 6 §2 | > 56h |
| Guida bisettimanale | Art. 6 §3 | > 90h |
| Riposo giornaliero | Art. 8 §1 | < 11h (ridotto: < 9h) |
| Riposo settimanale | Art. 8 §6 | < 45h (ridotto: < 24h) |
| Ore lavoro settimanale | Dir. 2002/15 Art. 4 | > 48h / > 60h |
| Lavoro continuo | Dir. 2002/15 Art. 5 | > 6h senza pausa |
| Turno notturno | Dir. 2002/15 Art. 7 | > 10h/24h |

---

## Configurazione cloud (opzionale)

### Google Drive

1. Vai su [console.cloud.google.com](https://console.cloud.google.com)
2. Crea un progetto → Abilita **Google Drive API**
3. Credenziali → OAuth 2.0 → App desktop → Scarica JSON
4. Salva il file come: `~/TachoVision/config/gdrive_credentials.json`

### OneDrive

Richiede la registrazione di un'app su [portal.azure.com](https://portal.azure.com):

1. Azure Active Directory → App registrations → New registration
2. Copia il **Client ID** dell'app
3. Imposta la variabile d'ambiente:
   ```bash
   # Windows
   set TACHOVISION_MSAL_CLIENT_ID=<il-tuo-client-id>
   
   # macOS / Linux
   export TACHOVISION_MSAL_CLIENT_ID=<il-tuo-client-id>
   ```

### Dropbox

Genera un **Personal Access Token** su [dropbox.com/developers/apps](https://www.dropbox.com/developers/apps)
e incollalo nella tab Condivisione.

---

## Struttura del progetto

```
tachovision-pro/
├── app.py                      ← entry point: avvio server + layout
├── requirements.txt
├── installa_windows.bat        ← installazione automatica Windows
├── installa_windows.ps1
├── start_app.bat               ← avvio rapido Windows
├── models/
│   ├── parser.py               ← parser binario .DDD (Gen1 + Gen2)
│   ├── card_data.py            ← dataclass: CardData, Vehicle, Place…
│   ├── analytics.py            ← statistiche e aggregazioni
│   └── violations.py           ← rilevamento infrazioni CE 561/2006
├── views/
│   ├── theme.py                ← palette colori dark
│   ├── components.py           ← componenti Dash riutilizzabili
│   ├── charts.py               ← grafici Plotly
│   └── tabs/                   ← una tab = un file Python
├── controllers/
│   ├── render_controller.py    ← rendering + upload file
│   ├── nav_controller.py       ← navigazione sidebar
│   ├── export_controller.py    ← PDF e CSV
│   ├── archive_controller.py   ← archivio locale
│   ├── share_controller.py     ← email + cloud
│   └── gps_controller.py       ← mappa GPS interattiva
├── services/
│   ├── card_service.py         ← lettura smartcard USB (pyscard)
│   ├── pdf_service.py          ← generazione PDF (ReportLab)
│   ├── email_service.py        ← apertura client email locale
│   ├── cloud_service.py        ← Google Drive / OneDrive / Dropbox
│   └── archive_service.py      ← gestione archivio .DDD locale
└── assets/
    ├── style.css               ← tema dark
    ├── filter.js               ← ricerca globale
    └── sidebar.js              ← navigazione
```

---

## Privacy

I file `.DDD` contengono **dati personali sensibili** del conducente (identità, spostamenti, orari).

- L'app gira **interamente in locale**: nessun dato viene trasmesso a server esterni
- I file vengono salvati solo nella cartella `~/TachoVision/archivio/` del PC
- L'upload cloud (Drive / OneDrive / Dropbox) avviene solo se configurato manualmente dall'utente
- Il trattamento dei dati tachigrafi è regolato dal **Reg. CE 561/2006** e dal **GDPR (Reg. UE 2016/679)**

---

## Dipendenze principali

| Libreria | Versione | Uso |
|---|---|---|
| [Dash](https://dash.plotly.com/) | ≥ 2.17 | Framework web reattivo |
| [Plotly](https://plotly.com/python/) | ≥ 5.22 | Grafici interattivi |
| [Dash Bootstrap Components](https://dash-bootstrap-components.opensource.faculty.ai/) | ≥ 1.6 | Layout e componenti UI |
| [pandas](https://pandas.pydata.org/) | ≥ 2.0 | Elaborazione dati tabellari |
| [ReportLab](https://www.reportlab.com/) | ≥ 4.0 | Generazione PDF |
| [pyscard](https://pyscard.sourceforge.io/) | opzionale | Lettura smartcard USB |

---

## Licenza

Distribuito per uso personale e professionale nel rispetto delle normative sul trattamento
dei dati tachigrafo (Reg. CE 561/2006, Dir. 2006/22/CE, Reg. UE 2016/679).

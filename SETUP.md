# Garmin Prissporingssystem — Oppsettsguide

Dette systemet skraper brukte Garmin-klokker fra **finn.no** og **Facebook Marketplace**, 
beregner potensiell fortjeneste, og viser et dashboard med kjøps-/salgsanalyse.

---

## Metode A: GitHub Codespaces (anbefalt — ingen installasjon)

Alt kjører i nettleseren. Du trenger bare en GitHub-konto.

### Steg 1 — Opprett repo og start Codespace

1. Gå til https://github.com/new
2. Lag et nytt **privat** repo, f.eks. `garmin-prissporing`
3. Last opp alle filene fra dette prosjektet (dra og slipp inn i GitHub)
4. Klikk den grønne **"<> Code"**-knappen → **"Codespaces"** → **"Create codespace on main"**
5. Vent 2–3 minutter mens alt installeres automatisk (Python, pakker, nettleser)

### Steg 2 — Kjør Finn-scraperen

Når Codespace er klart, åpnes en editor i nettleseren. Nede til høyre er en terminal.
Skriv:

```
python finn_scraper.py
```

Data lagres i `data/finn_historikk.xlsx`.

### Steg 3 — Kjør Facebook-scraperen

**Merk:** Facebook-scraperen trenger en nettleser med innlogging. I Codespaces
kan den ikke åpne et vindu for deg. Du har to valg:

**Alternativ A — Kjør kun Finn (enklest)**  
Hopp over Facebook. Finn alene gir deg god nok data.

**Alternativ B — Eksporter cookies selv**  
1. Logg inn på Facebook i din vanlige nettleser
2. Bruk et browser-tillegg til å eksportere cookies (f.eks. "EditThisCookie")
3. Legg dem i `fb_session/`-mappen i Codespace

### Steg 4 — Start dashbordet

```
streamlit run dashboard.py
```

Codespaces åpner automatisk dashbordet i en ny nettleserfane. Du kan trykke 
"Open in Browser" i popup-meldingen som dukker opp.

### Steg 5 — Last ned Excel-filene (valgfritt)

Høyreklikk på `data/finn_historikk.xlsx` i filutforskeren til venstre → **Download**.

### Kostnader

GitHub gir **60 timer gratis** Codespaces per måned. En scrape-kjøring tar 
5–10 minutter. Det er mer enn nok til daglig bruk. Husk å **stoppe** 
Codespace når du er ferdig (den stopper også automatisk etter 30 min).

---

## Metode B: Lokal installasjon (hvis du vil kjøre på egen PC)

### 1. Installere Python

**Windows:**
1. Gå til https://www.python.org/downloads/
2. Last ned siste versjon av Python 3 (f.eks. 3.12)
3. Kjør installasjonsprogrammet — **huk av for "Add Python to PATH"**
4. Klikk "Install Now"

**Mac:**
1. Åpne Terminal (Cmd+Mellomrom → "Terminal")
2. Kjør: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
3. Deretter: `brew install python`

### 2. Installere pakker

```
cd "C:\Users\RobinRakvåg\OneDrive - Aquaship AS\Privat\App"
pip install -r requirements.txt
playwright install chromium
```

### 3. Daglig bruk

```
python finn_scraper.py
python facebook_scraper.py
streamlit run dashboard.py
```

---

## Mappestruktur

```
App/
├── .devcontainer/
│   └── devcontainer.json    # Codespaces-oppsett (automatisk)
├── finn_scraper.py          # Skraper finn.no
├── facebook_scraper.py      # Skraper Facebook Marketplace
├── dashboard.py             # Streamlit-dashboard
├── fortjeneste.py           # Fortjenesteberegner
├── requirements.txt         # Pakkeliste
├── .gitignore               # Filer som ikke lastes opp til GitHub
├── SETUP.md                 # Denne filen
├── fb_session/              # Lagret Facebook-innlogging (privat, ikke i Git)
└── data/
    ├── finn_historikk.xlsx
    └── facebook_historikk.xlsx
```

---

## Feilsøking

| Problem | Løsning |
|---|---|
| Codespace starter ikke | Sjekk at `.devcontainer/devcontainer.json` finnes i repoet |
| Dashbordet åpnes ikke i Codespace | Klikk "Ports"-fanen i terminalen → port 8501 → "Open in Browser" |
| Tomt Excel-ark | Finn kan ha endret HTML-strukturen. Sjekk feilmeldinger i terminalen |
| Facebook blokkerer | Vent 24 timer, eller slett `fb_session/` og logg inn på nytt |
| `ModuleNotFoundError` | Kjør `pip install -r requirements.txt` på nytt |

---

## Kjøpssignal

Dashbordet markerer annonser med **🟢 KJØPSignal** når antatt ROI > 40%.
Det betyr at klokken (etter kjøp + fiks 150 kr + frakt 80 kr) kan selges 
videre med minst 40% fortjeneste basert på typiske finn.no-priser.

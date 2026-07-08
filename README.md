# Garmin-pristracker 🏷️⌚

Et selvgående system som overvåker prisene på brukte Garmin-klokker på
finn.no, finner kupp, og viser alt i et mobilvennlig dashbord — helt gratis
hostet på GitHub.

## Slik henger det sammen

```
GitHub Actions (kl. 07, 13 og 20)          GitHub Pages
        │                                       │
        ▼                                       ▼
   scraper.py  ──► data/listings.json      docs/index.html  ◄── du, fra mobilen
   (Python)    ──► data/history.json       (dashbordet)
               ──► docs/data/data.js  ─────────┘
```

1. **Scraperen** ([scraper.py](scraper.py)) søker på finn.no/torget etter
   søkeordene i [config.json](config.json), gjenkjenner Garmin-modellen fra
   tittelen, og fører prishistorikk per annonse. Kjente annonser som
   forsvinner fra søket markeres «borte fra FINN» (typisk = solgt).
2. **GitHub Actions** ([.github/workflows/scraper.yml](.github/workflows/scraper.yml))
   kjører scraperen automatisk tre ganger daglig og committer oppdaterte
   datafiler tilbake til repoet. Feiler scrapingen (f.eks. fordi finn.no har
   endret siden sin), blir kjøringen **rød** — det lagres aldri tomme data.
3. **Dashbordet** ([docs/index.html](docs/index.html)) er én enkelt HTML-fil
   som GitHub Pages serverer. Den leser dataene fra `docs/data/data.js` og
   regner ut alt i nettleseren. Ingen server, ingenting å drifte.

### De fire fanene

| Fane | Hva den gjør |
|---|---|
| **💰 Kupp** | Aktive annonser priset under 10.-persentilen for sin modell, sortert etter estimert margin. Margin = medianpris − annonsepris − frakt (80 kr) − fiks (150 kr). Viser også ROI. |
| **📋 Alle** | Alle annonser med søk og filter på modell og prisintervall. Kan også vise solgte/fjernede. |
| **📈 Historikk** | Graf over medianpris per modell over tid. Trykk på modell-knappene for å velge hvilke som vises. |
| **💼 Mine kjøp** | Manuell føring av egne kjøp og salg (også fra Facebook Marketplace). Lagres **kun i nettleseren på din enhet** — ta sikkerhetskopi med knappen nederst innimellom. |

---

## Oppsett — steg for steg

Du trenger en gratis konto på [github.com](https://github.com). Alt gjøres i
nettleseren og tar ca. 10 minutter.

### 1. Opprett repoet på GitHub

1. Gå til <https://github.com/new>
2. Gi repoet et navn, f.eks. `garmin-priser`
3. Velg **Public** (kreves for gratis GitHub Pages) og trykk **Create repository**

### 2. Last opp koden

Fra denne mappen på PC-en, i et terminalvindu (PowerShell):

```powershell
git branch -M main
git remote add origin https://github.com/DITT-BRUKERNAVN/garmin-priser.git
git push -u origin main
```

(Bytt ut `DITT-BRUKERNAVN` med GitHub-brukernavnet ditt. Første gang blir du
bedt om å logge inn.)

### 3. Slå på GitHub Pages (dashbordet)

1. På repo-siden: **Settings** → **Pages** (venstremenyen)
2. Under «Build and deployment»: Source = **Deploy from a branch**
3. Branch = **main**, mappe = **/docs** → trykk **Save**
4. Etter et par minutter er dashbordet live på
   `https://DITT-BRUKERNAVN.github.io/garmin-priser/`
   — **legg denne til på hjemskjermen på telefonen**, så oppfører den seg som en app.

### 4. Slå på automatikken (Actions)

1. På repo-siden: fanen **Actions**
2. Trykk **«I understand my workflows, go ahead and enable them»** hvis du blir spurt
3. Test med en manuell kjøring: velg **«Skrap finn.no»** i venstremenyen →
   **Run workflow** → grønn knapp. Etter 1–2 minutter skal kjøringen bli grønn ✅
   og dashbordet oppdateres kort tid etter.

Deretter går alt av seg selv: scraperen kjører kl. **07, 13 og 20**
(norsk sommertid — én time tidligere på klokka om vinteren, fordi GitHub
bruker UTC).

> **Tips:** GitHub skrur av tidsplanen i repoer uten aktivitet i 60 dager.
> Du får en e-post først — trykk på lenken i den, så fortsetter alt som før.

---

## Vanlige endringer

### Endre eller legge til søkeord

Åpne [config.json](config.json) (kan gjøres rett i GitHub: trykk på filen →
blyant-ikonet), rediger listen `sokeord`, og trykk **Commit changes**:

```json
"sokeord": [
  "Garmin klokke",
  "Garmin Fenix",
  "Garmin Forerunner",
  "Garmin Instinct"
]
```

Neste kjøring bruker de nye søkeordene automatisk.

### Justere kostnader i kupp-beregningen

Samme fil: `frakt_kr` og `fikskostnad_kr`.

### Legge til en ny modellserie i gjenkjenningen

Åpne [scraper.py](scraper.py) og finn listen `SERIER` (ca. linje 90). Kopier
en linje og tilpass — mønsteret til venstre er serienavnet som vises, det til
høyre er teksten som gjenkjennes. Modellene beregnes på nytt for *alle*
annonser ved hver kjøring, så forbedringer virker med tilbakevirkende kraft.

### Hvor dypt søkes det?

`maks_sider_per_sok` i config.json (4 sider ≈ 200 annonser per søkeord).
Systemet følger altså de nyeste annonsene — en annonse som blir eldre enn
dette vinduet markeres «borte fra FINN» selv om den teknisk sett fortsatt
ligger ute. For kuppjakt er det de ferske annonsene som teller.

---

## Feilsøking

| Symptom | Årsak og løsning |
|---|---|
| Rød kjøring i Actions med «Ingen annonser funnet» eller «manglet datablokken» | finn.no har endret sidestrukturen. Dataene dine er urørt. `scraper.py` må oppdateres — be gjerne en AI-assistent om å se på `parse_sokeside()`. |
| Rød kjøring med HTTP-feil (403/429) | finn.no avviser forespørslene. Vent til neste kjøring; vurder å øke `pause_sekunder` eller redusere `maks_sider_per_sok`. |
| Dashbordet viser «Venter på første datainnsamling» | `docs/data/data.js` mangler — kjør workflowen manuelt (se steg 4). |
| Dashbordet oppdaterer seg ikke | Sjekk at siste Actions-kjøring er grønn, og hard-oppdater siden (dra ned for å laste på nytt). GitHub Pages kan bruke noen minutter på å publisere. |
| «Mine kjøp» er tomme etter bytte av telefon | De lagres lokalt per enhet. Bruk «Kopier sikkerhetskopi» på gammel enhet og «Lim inn sikkerhetskopi» på ny. |

## Verdt å vite

- **Vilkår:** finn.no sine vilkår sier at systematisk/automatisert innhenting
  krever samtykke fra FINN, selv om robots.txt ikke blokkerer søkesidene
  maskinelt. Dette oppsettet er bevisst svært skånsomt (36 sidevisninger
  spredt over tre korte økter per dag, med pauser og ærlig User-Agent som
  identifiserer formålet), men bruken skjer på eget ansvar. Scraperen sjekker
  robots.txt før hver kjøring og stopper selv hvis reglene strammes inn.
- **Facebook Marketplace** kan ikke scrapes (krever innlogging og er mot
  vilkårene deres på en mer håndhevet måte) — derfor føres kjøp derfra manuelt
  i «Mine kjøp»-fanen.
- Prisene i «Kupp» er *estimater* basert på medianen av det som ligger ute
  akkurat nå. Sjekk alltid tilstand, modellvariant (Sapphire/Solar/størrelse)
  og selger før du slår til.

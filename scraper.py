"""
Prisovervåking av brukte Garmin-klokker på finn.no.

Slik virker den:
  1. Leser innstillinger fra config.json (søkeord, antall sider, pauser, kostnader).
  2. Sjekker at robots.txt fortsatt tillater søkesiden.
  3. Henter søkeresultater fra finn.no/torget for hvert søkeord.
     Dataene leses primært fra siden sin innebygde schema.org-JSON
     (tittel, pris, URL) - det er mye mer robust enn å tolke HTML-klasser.
     Sted og alder ("3 t.", "2 d.") plukkes fra annonsekortene i tillegg.
  4. Slår sammen med eksisterende data/listings.json:
     - nye annonser legges til
     - kjente annonser oppdateres (prisendringer tas vare på i prishistorikk)
     - annonser som ikke lenger finnes i søket markeres som inaktive
  5. Skriver dagens snapshot av medianpris per modell til data/history.json.
  6. Skriver docs/data/data.js som dashbordet (GitHub Pages) leser.

Feilhåndtering: Hvis finn.no har endret struktur slik at ingen annonser
kan leses, avslutter scriptet med feilkode 1 UTEN å røre dataene.
Da blir kjøringen rød i GitHub Actions, og du ser at noe må fikses.

Kjøres med:  python scraper.py
"""

import json
import re
import sys
import time
import urllib.robotparser
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Oppsett og konstanter
# ---------------------------------------------------------------------------

ROT = Path(__file__).parent
OSLO = ZoneInfo("Europe/Oslo")

SOKE_URL = "https://www.finn.no/recommerce/forsale/search"
ROBOTS_URL = "https://www.finn.no/robots.txt"

# Ærlig User-Agent slik at finn.no kan se hvem som spør og hvorfor
HEADERS = {
    "User-Agent": (
        "GarminPristracker/1.0 "
        "(personlig prisovervaaking av brukte Garmin-klokker; "
        "kjoeres 3 ganger daglig med lange pauser mellom forespoersler)"
    ),
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.5",
}

# Innstillinger fra config.json
KONFIG = json.loads((ROT / "config.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Modellgjenkjenning
# ---------------------------------------------------------------------------

# Annonser der noen vil KJØPE (ikke selge) en klokke. Disse merkes "Kjøpes"
# og holdes utenfor prisstatistikken - det er ikke reelle salgspriser.
KJOPES_MONSTER = re.compile(
    r"\b(ønske(s|r)?\s*(å\s*)?kjøpe?|kjøpes|søkes)\b",
    re.IGNORECASE,
)

# Ord som tyder på at annonsen er tilbehør (reim, lader osv.) og ikke en klokke.
# Disse merkes "Tilbehør" og holdes utenfor prisstatistikken.
# "til garmin" fanger opp mønsteret "Reim/Lader/Glass til Garmin ...".
TILBEHOR_MONSTER = re.compile(
    r"\b(reim|reimer|klokkereim|armb[åa]nd|strop|strap|watch\s*band"
    r"|lader|ladekabel|ladere|charger|charging|dokk|dockingstasjon"
    r"|skjermbeskytter|beskyttelsesglass|herdet\s*glass|panserglass"
    r"|screen\s*(part|protector)|bezel|protector"
    r"|deksel|etui|case|cover|hylster|holder|brakett|sykkelfeste|styrefeste|feste"
    r"|verkt[øo]y|pulsbelte|brystbelte|pulssensor|hrm[\s-]?(dual|pro|run|tri)"
    r"|fotsensor|footpod|cadence|speedsensor|varia|edge\s*\d|tempe"
    r"|til\s+garmin)\b",
    re.IGNORECASE,
)

# Garmin-serier vi kjenner igjen. Rekkefølgen har betydning: mer spesifikke
# mønstre må stå først. Gruppen (\d...) fanger modellnummeret hvis det finnes,
# slik at "Garmin Fenix 7X Pro Solar" blir "Fenix 7".
# Vil du legge til en ny serie? Kopier en linje og bytt navn/mønster.
SERIER = [
    ("Forerunner", r"(?:forerunner|(?<![a-z])fr)\s*[-]?\s*(\d{2,3})"),
    ("Forerunner", r"forerunner"),
    ("Fenix", r"f[eé]nix\s*[-]?\s*e?\s*(\d)"),
    ("Fenix", r"f[eé]nix"),
    ("Epix", r"epix(?:.{0,8}gen\s*(\d))?"),
    ("Enduro", r"enduro\s*(\d)?"),
    ("Venu", r"venu\s*(sq\s*2|sq|x1|\d)?"),
    ("Vivoactive", r"v[ií]vo\s*active\s*(\d)?"),
    ("Vivomove", r"v[ií]vo\s*move"),
    ("Vivosmart", r"v[ií]vo\s*smart\s*(\d)?"),
    ("Vivofit", r"v[ií]vo\s*fit\s*(\d)?"),
    ("Vivosport", r"v[ií]vo\s*sport"),
    ("Instinct", r"instinct\s*(\d)?"),
    ("Lily", r"\blily\b\s*(\d)?"),
    ("Swim", r"\bswim\b\s*(\d)?"),
    ("Descent", r"descent"),
    ("Approach", r"approach"),
    ("Tactix", r"tactix\s*(\d)?"),
    ("MARQ", r"\bmarq\b"),
    ("Quatix", r"quatix\s*(\d)?"),
]


def klassifiser_modell(tittel: str) -> str:
    """Gjetter Garmin-modell ut fra annonsetittelen.

    Returnerer f.eks. "Forerunner 255", "Fenix 7", "Venu SQ 2",
    "Kjøpes" for ønskes kjøpt-annonser, "Tilbehør" for remmer/ladere osv.,
    eller "Annet" hvis ukjent.
    """
    tekst = tittel.lower()

    if KJOPES_MONSTER.search(tekst):
        return "Kjøpes"
    if TILBEHOR_MONSTER.search(tekst):
        return "Tilbehør"

    for serie, monster in SERIER:
        treff = re.search(monster, tekst)
        if treff:
            nummer = ""
            # Noen mønstre har en gruppe for modellnummer, andre ikke
            if treff.groups() and treff.group(1):
                nummer = re.sub(r"\s+", " ", treff.group(1).strip()).upper()
            return f"{serie} {nummer}".strip()

    return "Annet"


# ---------------------------------------------------------------------------
# Henting og parsing av søkesider
# ---------------------------------------------------------------------------

def sjekk_robots() -> None:
    """Stopper kjøringen hvis robots.txt-reglene ikke lenger tillater søkesiden.

    Viktig detalj: Pythons innebygde robotparser tolker feilkoder (403/500)
    som «alt er forbudt». Det ville stoppet oss selv når reglene faktisk
    tillater søket. Derfor henter vi filen selv og håndhever kun regler vi
    faktisk får lest (HTTP 200). Får vi ikke lest den, sier vi fra i loggen
    og fortsetter forsiktig - selve søket feiler uansett tydelig hvis
    finn.no avviser oss.
    """
    try:
        respons = requests.get(ROBOTS_URL, headers=HEADERS, timeout=30)
    except Exception as feil:
        print(f"Advarsel: fikk ikke hentet robots.txt ({feil}) - fortsetter forsiktig.")
        return

    if respons.status_code != 200:
        print(f"Advarsel: robots.txt svarte HTTP {respons.status_code} - "
              "kan ikke verifisere reglene, fortsetter forsiktig.")
        return

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(respons.text.splitlines())
    if not parser.can_fetch(HEADERS["User-Agent"], SOKE_URL + "?q=garmin"):
        sys.exit("STOPP: robots.txt tillater ikke lenger søkesiden. Ingen data hentet.")
    print("robots.txt lest - søkesiden er fortsatt tillatt.")


def hent_side(sokeord: str, side: int) -> str:
    """Henter én søkeresultatside (HTML) fra finn.no. Kaster feil ved HTTP-problemer."""
    respons = requests.get(
        SOKE_URL,
        params={"q": sokeord, "sort": "PUBLISHED_DESC", "page": side},
        headers=HEADERS,
        timeout=30,
    )
    respons.raise_for_status()
    return respons.text


def tolk_alder(tekst: str, naa: datetime) -> str | None:
    """Gjør om finn sin alders-tekst til en ISO-dato.

    Finn viser alder som "3 min.", "14 t.", "6 dg." for ferske annonser
    og "24. juni" for eldre. Returnerer None hvis teksten ikke kan tolkes.
    Dette er et estimat - godt nok til å se hvor ferske annonsene er.
    """
    tekst = tekst.strip().lower().rstrip(".")

    treff = re.fullmatch(r"(\d+)\s*(min|t|dg|d|mnd)", tekst)
    if treff:
        antall = int(treff.group(1))
        enhet = treff.group(2)
        delta = {
            "min": timedelta(minutes=antall),
            "t": timedelta(hours=antall),
            "dg": timedelta(days=antall),
            "d": timedelta(days=antall),
            "mnd": timedelta(days=30 * antall),
        }[enhet]
        return (naa - delta).strftime("%Y-%m-%d")

    # Datoformat som "24. juni" (eldre annonser). Vi kjenner igjen måneden
    # på de tre første bokstavene - de er unike på norsk.
    maaneder = ["jan", "feb", "mar", "apr", "mai", "jun",
                "jul", "aug", "sep", "okt", "nov", "des"]
    treff = re.fullmatch(r"(\d{1,2})\.?\s*([a-zæøå]{3,9})", tekst)
    if treff and treff.group(2)[:3] in maaneder:
        dag = int(treff.group(1))
        maaned = maaneder.index(treff.group(2)[:3]) + 1
        aar = naa.year
        try:
            dato = datetime(aar, maaned, dag, tzinfo=OSLO)
        except ValueError:
            return None
        if dato > naa:  # f.eks. "28. des" sett i januar -> i fjor
            dato = dato.replace(year=aar - 1)
        return dato.strftime("%Y-%m-%d")

    return None


def parse_sokeside(html: str, naa: datetime) -> list[dict] | None:
    """Leser annonsene ut av én søkeresultatside.

    Primærkilde er schema.org-JSON-en finn legger i siden (stabil struktur).
    Sted og publiseringsestimat hentes fra annonsekortene der det er mulig.

    Returnerer None hvis siden ikke lenger inneholder JSON-blokken i det hele
    tatt (= finn har endret strukturen), og tom liste hvis det bare er tomt
    for resultater.
    """
    soup = BeautifulSoup(html, "html.parser")

    json_tag = soup.find("script", id="seoStructuredData")
    if json_tag is None or not json_tag.string:
        return None  # Strukturendring - må fanges opp som feil

    try:
        data = json.loads(json_tag.string)
    except json.JSONDecodeError:
        return None

    elementer = data.get("mainEntity", {}).get("itemListElement", [])

    annonser = []
    for element in elementer:
        item = element.get("item", {})
        url = item.get("url", "")
        kode_treff = re.search(r"/item/(\d+)", url)
        if not kode_treff:
            continue

        pris = None
        pris_raa = item.get("offers", {}).get("price")
        if pris_raa is not None:
            try:
                pris = int(float(pris_raa))
            except (TypeError, ValueError):
                pris = None

        annonser.append({
            "finnkode": kode_treff.group(1),
            "tittel": (item.get("name") or "").strip(),
            "pris": pris,
            "url": url,
            "sted": "",
            "publisert": None,
        })

    # Berik med sted og alder fra de synlige annonsekortene.
    # Kortene er <article>-elementer med en lenke som inneholder finnkoden.
    per_kode = {a["finnkode"]: a for a in annonser}
    for kort in soup.find_all("article"):
        lenke = kort.find("a", href=re.compile(r"/item/(\d+)"))
        if not lenke:
            continue
        kode_treff = re.search(r"/item/(\d+)", lenke["href"])
        if not kode_treff or kode_treff.group(1) not in per_kode:
            continue
        annonse = per_kode[kode_treff.group(1)]

        # Tekstbitene i kortet: stedet står rett før alders-teksten ("3 t.")
        biter = [s.strip() for s in kort.stripped_strings if s.strip()]
        for i, bit in enumerate(biter):
            publisert = tolk_alder(bit, naa)
            if publisert:
                annonse["publisert"] = publisert
                if i > 0 and len(biter[i - 1]) <= 40 and not biter[i - 1].endswith("kr"):
                    annonse["sted"] = biter[i - 1]
                break

    return annonser


def skrap_alle_sok(naa: datetime) -> dict[str, dict]:
    """Kjører alle søkeordene fra config.json og returnerer annonser per finnkode."""
    funnet: dict[str, dict] = {}
    strukturfeil = 0

    for sokeord in KONFIG["sokeord"]:
        print(f"\nSøker: '{sokeord}'")
        for side in range(1, KONFIG["maks_sider_per_sok"] + 1):
            html = hent_side(sokeord, side)
            annonser = parse_sokeside(html, naa)

            if annonser is None:
                print(f"  Side {side}: fant ikke JSON-datablokken - strukturen kan være endret!")
                strukturfeil += 1
                break

            print(f"  Side {side}: {len(annonser)} annonser")
            if not annonser:
                break  # Ikke flere resultater for dette søkeordet

            for annonse in annonser:
                funnet[annonse["finnkode"]] = annonse

            # Vær skånsom mot finn.no: pause mellom hver forespørsel
            time.sleep(KONFIG["pause_sekunder"])

    # Feil høyt og tydelig hvis vi ikke fikk noe som helst - da skal
    # GitHub Actions bli rød i stedet for å lagre tomme data.
    if not funnet:
        sys.exit(
            "STOPP: Ingen annonser funnet i noen av søkene. "
            "Finn.no har trolig endret sidestrukturen - scraper.py må oppdateres. "
            "Eksisterende data er IKKE endret."
        )
    if strukturfeil > 0:
        sys.exit(
            f"STOPP: {strukturfeil} søk manglet datablokken i siden. "
            "Finn.no har trolig endret strukturen. Eksisterende data er IKKE endret."
        )

    print(f"\nTotalt {len(funnet)} unike annonser funnet.")
    return funnet


# ---------------------------------------------------------------------------
# Sammenslåing med eksisterende data
# ---------------------------------------------------------------------------

def les_json(sti: Path, standard):
    """Leser en JSON-fil, eller returnerer standardverdien hvis den ikke finnes."""
    if sti.exists():
        return json.loads(sti.read_text(encoding="utf-8"))
    return standard


def oppdater_annonser(gamle: dict, nye: dict[str, dict], naa: datetime) -> dict:
    """Fletter dagens skrap inn i eksisterende annonsedata.

    - Nye finnkoder legges til med prishistorikk.
    - Kjente finnkoder får oppdatert pris (endringer logges i prishistorikk).
    - Annonser som ikke ble sett i dag markeres aktiv=false (solgt/fjernet).
    """
    dato = naa.strftime("%Y-%m-%d")
    tidspunkt = naa.strftime("%Y-%m-%d %H:%M")

    nye_antall = 0
    prisendringer = 0

    for finnkode, fersk in nye.items():
        eksisterende = gamle.get(finnkode)

        if eksisterende is None:
            # Helt ny annonse
            gamle[finnkode] = {
                "finnkode": finnkode,
                "tittel": fersk["tittel"],
                "modell": klassifiser_modell(fersk["tittel"]),
                "pris": fersk["pris"],
                "sted": fersk["sted"],
                "url": fersk["url"],
                "publisert": fersk["publisert"],
                "forst_sett": tidspunkt,
                "sist_sett": tidspunkt,
                "aktiv": True,
                "prishistorikk": (
                    [{"dato": dato, "pris": fersk["pris"]}] if fersk["pris"] is not None else []
                ),
            }
            nye_antall += 1
        else:
            # Kjent annonse - oppdater
            eksisterende["sist_sett"] = tidspunkt
            eksisterende["aktiv"] = True
            eksisterende["tittel"] = fersk["tittel"]
            # Modellen beregnes på nytt hver gang, slik at forbedringer i
            # gjenkjenningen automatisk gjelder gamle annonser også
            eksisterende["modell"] = klassifiser_modell(fersk["tittel"])
            if fersk["sted"]:
                eksisterende["sted"] = fersk["sted"]
            if fersk["publisert"] and not eksisterende.get("publisert"):
                eksisterende["publisert"] = fersk["publisert"]

            if fersk["pris"] is not None and fersk["pris"] != eksisterende.get("pris"):
                eksisterende["pris"] = fersk["pris"]
                eksisterende.setdefault("prishistorikk", []).append(
                    {"dato": dato, "pris": fersk["pris"]}
                )
                prisendringer += 1

    # Annonser vi IKKE så i dag er trolig solgt eller fjernet
    inaktivert = 0
    for finnkode, annonse in gamle.items():
        if finnkode not in nye and annonse.get("aktiv"):
            annonse["aktiv"] = False
            inaktivert += 1

    print(f"Nye annonser: {nye_antall}, prisendringer: {prisendringer}, "
          f"markert inaktive: {inaktivert}")
    return gamle


def persentil(sorterte_priser: list[int], andel: float) -> int:
    """Enkel persentil med lineær interpolasjon. Lista må være sortert."""
    if not sorterte_priser:
        return 0
    posisjon = (len(sorterte_priser) - 1) * andel
    lav = int(posisjon)
    hoy = min(lav + 1, len(sorterte_priser) - 1)
    vekt = posisjon - lav
    return round(sorterte_priser[lav] * (1 - vekt) + sorterte_priser[hoy] * vekt)


def lag_dagens_snapshot(annonser: dict, naa: datetime) -> dict:
    """Beregner medianpris, 10.-persentil og antall per modell (kun aktive annonser).

    Tilbehør, ukjente modeller og mistenkelig billige oppføringer holdes utenfor,
    slik at statistikken speiler faktiske klokkepriser.
    """
    minstepris = KONFIG.get("minste_troverdige_pris_kr", 500)

    priser_per_modell: dict[str, list[int]] = {}
    for annonse in annonser.values():
        if not annonse.get("aktiv") or annonse.get("pris") is None:
            continue
        if annonse["modell"] in ("Tilbehør", "Annet", "Kjøpes"):
            continue
        if annonse["pris"] < minstepris:
            continue
        priser_per_modell.setdefault(annonse["modell"], []).append(annonse["pris"])

    snapshot = {}
    for modell, priser in sorted(priser_per_modell.items()):
        priser.sort()
        snapshot[modell] = {
            "median": persentil(priser, 0.5),
            "p10": persentil(priser, 0.1),
            "antall": len(priser),
        }
    return snapshot


# ---------------------------------------------------------------------------
# Lagring
# ---------------------------------------------------------------------------

def lagre_alt(annonser: dict, historikk: dict, naa: datetime) -> None:
    """Skriver data/listings.json, data/history.json og docs/data/data.js."""
    (ROT / "data").mkdir(exist_ok=True)
    (ROT / "docs" / "data").mkdir(parents=True, exist_ok=True)

    listings = {
        "oppdatert": naa.strftime("%Y-%m-%d %H:%M"),
        "kostnader": {
            "frakt_kr": KONFIG["frakt_kr"],
            "fikskostnad_kr": KONFIG["fikskostnad_kr"],
            "minste_troverdige_pris_kr": KONFIG.get("minste_troverdige_pris_kr", 500),
        },
        "annonser": annonser,
    }

    # Rådata i data/-mappen (fine å se på direkte i GitHub)
    (ROT / "data" / "listings.json").write_text(
        json.dumps(listings, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (ROT / "data" / "history.json").write_text(
        json.dumps(historikk, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # Samme data pakket som JavaScript for dashbordet. Grunnen til at vi gjør
    # dette er at en <script>-fil kan leses uten webserver-triksing (CORS),
    # så dashbordet virker både på GitHub Pages og lokalt på PC-en.
    data_js = (
        "// Denne filen genereres automatisk av scraper.py - ikke rediger den.\n"
        f"window.FINN_DATA = {json.dumps(listings, ensure_ascii=False)};\n"
        f"window.FINN_HISTORIKK = {json.dumps(historikk, ensure_ascii=False)};\n"
    )
    (ROT / "docs" / "data" / "data.js").write_text(data_js, encoding="utf-8")

    print(f"\nLagret {len(annonser)} annonser og historikk for {len(historikk)} dager.")


def main() -> None:
    naa = datetime.now(OSLO)
    print(f"Garmin-pristracker - kjøring {naa.strftime('%Y-%m-%d %H:%M')} (norsk tid)")

    sjekk_robots()

    # 1) Hent dagens annonser fra finn.no
    dagens = skrap_alle_sok(naa)

    # 2) Flett inn i eksisterende data
    listings = les_json(ROT / "data" / "listings.json", {"annonser": {}})
    annonser = oppdater_annonser(listings.get("annonser", {}), dagens, naa)

    # 3) Oppdater historikken med dagens snapshot (overskriver dagens dato
    #    hvis scriptet kjører flere ganger samme dag)
    historikk = les_json(ROT / "data" / "history.json", {})
    historikk[naa.strftime("%Y-%m-%d")] = lag_dagens_snapshot(annonser, naa)

    # 4) Lagre alt
    lagre_alt(annonser, historikk, naa)
    print("Ferdig!")


if __name__ == "__main__":
    main()

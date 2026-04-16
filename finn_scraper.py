"""
Finn.no-skraper for Garmin-klokker.

Henter annonser fra finn.no/torget, beriker dem med omtrentlig butikkpris
fra prisjakt.no, beregner fortjeneste, og lagrer alt i Excel.

Kjøres med:  python finn_scraper.py
"""

import os
import sys
import time
import re
from datetime import datetime
from urllib.parse import urlencode, quote_plus

import requests
from bs4 import BeautifulSoup
import pandas as pd

from fortjeneste import beregn_fortjeneste, skriv_ut_oppsummering, normaliser_modell

# Konfigurasjon
SOKEORD = "Garmin klokke"
DATA_MAPPE = "data"
EXCEL_FIL = os.path.join(DATA_MAPPE, "finn_historikk.xlsx")
FINN_BASE = "https://www.finn.no/recommerce/forsale/search.html"
PRISJAKT_BASE = "https://www.prisjakt.no/search"

# Nettleser-headers for å ikke bli blokkert
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.7",
}


def hent_finn_side(sidenummer: int = 1) -> str:
    """Henter én søkeresultatside fra finn.no. Returnerer HTML."""
    params = {
        "q": SOKEORD,
        "sort": "PUBLISHED_DESC",
        "page": sidenummer,
    }
    url = f"{FINN_BASE}?{urlencode(params)}"
    print(f"Henter: {url}")

    try:
        respons = requests.get(url, headers=HEADERS, timeout=30)
        respons.raise_for_status()
        return respons.text
    except Exception as feil:
        print(f"  ⚠️  Feil ved henting av side {sidenummer}: {feil}")
        return ""


def parse_pris(tekst: str) -> float:
    """Plukker ut tall fra en prisstreng som '2 499 kr'. Returnerer 0 hvis ikke funnet."""
    if not tekst:
        return 0.0
    # Fjern alt som ikke er tall
    tall = re.sub(r"[^\d]", "", tekst)
    return float(tall) if tall else 0.0


def parse_annonser(html: str) -> list[dict]:
    """Plukker ut annonser fra finn-søkeresultat-HTML."""
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    annonser = []

    # Finn bruker articles med data-testid for søkeresultater
    # Vi prøver flere selektorer fordi finn endrer strukturen av og til
    artikler = soup.find_all("article")

    for art in artikler:
        try:
            # Lenke til annonsen
            lenke_tag = art.find("a", href=True)
            if not lenke_tag:
                continue
            url = lenke_tag["href"]
            if not url.startswith("http"):
                url = "https://www.finn.no" + url

            # Filtrer ut annet enn torget-annonser
            if "/recommerce/" not in url and "/bap/" not in url:
                continue

            # Tittel
            tittel_tag = art.find(["h2", "h3"])
            tittel = tittel_tag.get_text(strip=True) if tittel_tag else ""

            # Tekst-skrap for pris, sted og dato
            tekst = art.get_text(" | ", strip=True)

            # Pris — typisk formatert som "1 234 kr" eller "1.234 kr"
            pris_match = re.search(r"(\d[\d\s\.]{1,10})\s*kr", tekst)
            pris = parse_pris(pris_match.group(1)) if pris_match else 0.0

            # Sted — ofte etter prisen, vanskelig å plukke ut konsekvent
            # Vi henter beste gjetning
            sted = ""
            sted_tag = art.find(attrs={"data-testid": re.compile(".*location.*", re.I)})
            if sted_tag:
                sted = sted_tag.get_text(strip=True)

            # Tilstand — står ofte i tittel eller beskrivelse
            tilstand = ""
            for nokkel in ["Brukt", "Som ny", "Ny", "Pent brukt", "Defekt"]:
                if nokkel.lower() in tekst.lower():
                    tilstand = nokkel
                    break

            # Dato postet — ofte vist som "i dag", "i går" eller dato
            dato_match = re.search(r"(\d{1,2}\.\s*\w+\s*\d{4}|\d{1,2}\.\d{1,2}\.\d{4}|i dag|i går)", tekst, re.IGNORECASE)
            dato_postet = dato_match.group(1) if dato_match else ""

            if tittel and pris > 0:
                annonser.append({
                    "tittel": tittel,
                    "pris": pris,
                    "sted": sted,
                    "dato_postet": dato_postet,
                    "tilstand": tilstand,
                    "url": url,
                })
        except Exception as feil:
            print(f"  ⚠️  Kunne ikke parse annonse: {feil}")
            continue

    return annonser


def hent_prisjakt_retail(modell: str) -> float:
    """
    Henter omtrentlig butikkpris (ny-pris) fra prisjakt.no for en Garmin-modell.
    Returnerer 0 hvis ingen pris finnes.
    """
    if not modell or modell == "ukjent":
        return 0.0

    sokestreng = f"garmin {modell}"
    url = f"{PRISJAKT_BASE}?search_query={quote_plus(sokestreng)}"

    try:
        respons = requests.get(url, headers=HEADERS, timeout=20)
        if respons.status_code != 200:
            return 0.0

        soup = BeautifulSoup(respons.text, "lxml")
        tekst = soup.get_text(" ", strip=True)

        # Prisjakt viser priser som "fra 2 499 kr" eller "2 499,-"
        priser = re.findall(r"(\d[\d\s]{2,8})\s*(?:kr|,-)", tekst)

        if not priser:
            return 0.0

        # Ta første fornuftige pris (mellom 500 og 20000 kr)
        for p in priser:
            verdi = parse_pris(p)
            if 500 <= verdi <= 20000:
                return verdi

        return 0.0
    except Exception as feil:
        print(f"  ⚠️  Kunne ikke hente prisjakt for '{modell}': {feil}")
        return 0.0


def berik_med_retail_pris(df: pd.DataFrame) -> pd.DataFrame:
    """Legger til en kolonne 'retail_pris' basert på prisjakt.no per unike modell."""
    if df.empty:
        return df

    df = df.copy()
    unike_modeller = df["modell"].unique()

    print(f"\nHenter butikkpriser fra prisjakt.no for {len(unike_modeller)} modeller...")
    retail_cache = {}
    for modell in unike_modeller:
        if modell == "ukjent":
            retail_cache[modell] = 0.0
            continue
        retail_cache[modell] = hent_prisjakt_retail(modell)
        print(f"  • {modell}: {retail_cache[modell]:.0f} kr")
        time.sleep(1.5)  # Vær snill med prisjakt

    df["retail_pris"] = df["modell"].map(retail_cache)
    return df


def les_historikk() -> pd.DataFrame:
    """Leser eksisterende historikk-fil. Returnerer tom DataFrame hvis filen ikke finnes."""
    if os.path.exists(EXCEL_FIL):
        try:
            return pd.read_excel(EXCEL_FIL)
        except Exception as feil:
            print(f"⚠️  Kunne ikke lese eksisterende fil: {feil}")
    return pd.DataFrame()


def lagre_excel(nye_data: pd.DataFrame, historisk: pd.DataFrame):
    """Slår sammen nye og gamle data, og lagrer til Excel."""
    os.makedirs(DATA_MAPPE, exist_ok=True)

    if historisk.empty:
        kombinert = nye_data
    else:
        kombinert = pd.concat([historisk, nye_data], ignore_index=True)

    # Fjern eksakte duplikater (samme URL samme dag)
    if "url" in kombinert.columns and "dato_scrapet" in kombinert.columns:
        kombinert = kombinert.drop_duplicates(subset=["url", "dato_scrapet"], keep="last")

    try:
        kombinert.to_excel(EXCEL_FIL, index=False)
        print(f"\n✅ Lagret {len(nye_data)} nye annonser til {EXCEL_FIL}")
        print(f"   Total historikk: {len(kombinert)} rader")
    except Exception as feil:
        print(f"❌ Kunne ikke lagre Excel: {feil}")
        # Fallback — lagre som CSV slik at data ikke går tapt
        csv_fil = EXCEL_FIL.replace(".xlsx", f"_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        kombinert.to_csv(csv_fil, index=False)
        print(f"   Data lagret som CSV: {csv_fil}")


def kjor_scraper(antall_sider: int = 5):
    """Hovedfunksjon — skraper, beriker og lagrer."""
    print(f"\n🔍 Starter Finn.no-skraping for '{SOKEORD}'")
    print(f"   Henter opptil {antall_sider} sider\n")

    alle_annonser = []
    for side in range(1, antall_sider + 1):
        html = hent_finn_side(side)
        if not html:
            print(f"   Side {side} tom eller blokkert — stopper.")
            break

        annonser = parse_annonser(html)
        print(f"  Fant {len(annonser)} annonser på side {side}")

        if not annonser:
            # Ingen flere resultater
            break

        alle_annonser.extend(annonser)
        time.sleep(2)  # Vær snill med finn.no

    if not alle_annonser:
        print("\n❌ Ingen annonser funnet. Finn kan ha endret HTML-strukturen.")
        sys.exit(1)

    # Lag DataFrame
    df = pd.DataFrame(alle_annonser)
    df["dato_scrapet"] = datetime.now().strftime("%Y-%m-%d")
    df["kilde"] = "Finn"

    # Les historikk for å forbedre salgspris-estimat
    historisk = les_historikk()

    # Beregn modell og fortjeneste (bruker historisk data som referanse hvis tilgjengelig)
    df = beregn_fortjeneste(df, historisk_df=historisk if not historisk.empty else df)

    # Berik med retail-priser fra prisjakt
    df = berik_med_retail_pris(df)

    # Skriv oppsummering til terminal
    skriv_ut_oppsummering(df, kilde="Finn.no")

    # Lagre til Excel
    lagre_excel(df, historisk)


if __name__ == "__main__":
    try:
        kjor_scraper(antall_sider=5)
    except KeyboardInterrupt:
        print("\n\n⛔ Avbrutt av bruker.")
        sys.exit(0)

"""
Facebook Marketplace-skraper for Garmin-klokker.

Bruker Playwright (nettleserautomatisering) fordi Facebook krever innlogging.
Første gang scriptet kjøres: åpner nettleser slik at du kan logge inn manuelt.
Etterpå lagres økten og fremtidige kjøringer trenger ikke innlogging.

Kjøres med:  python facebook_scraper.py
"""

import os
import sys
import re
import time
from datetime import datetime

import pandas as pd

from fortjeneste import beregn_fortjeneste, skriv_ut_oppsummering

# Konfigurasjon
SOKEORD = "Garmin klokke"
DATA_MAPPE = "data"
EXCEL_FIL = os.path.join(DATA_MAPPE, "facebook_historikk.xlsx")
SESSION_MAPPE = "fb_session"              # Her lagres cookies/innlogging
FB_URL = "https://www.facebook.com/marketplace/norway/search?query=" + SOKEORD.replace(" ", "%20")
MAX_ANNONSER = 80                          # Stopper når vi har sett så mange
MAX_SCROLL = 15                            # Maks antall ganger vi scroller ned


def parse_pris(tekst: str) -> float:
    """Plukker ut tall fra prisstreng som 'kr 2 499' eller '2.499 kr'."""
    if not tekst:
        return 0.0
    tall = re.sub(r"[^\d]", "", tekst)
    return float(tall) if tall else 0.0


def lagre_innsamlede_data(annonser: list[dict], grunn: str = ""):
    """
    Lagrer det vi har klart å samle inn — brukes også hvis Facebook blokkerer oss,
    slik at data ikke går tapt.
    """
    if not annonser:
        print(f"\n⚠️  {grunn} Ingen data å lagre.")
        return

    df = pd.DataFrame(annonser)
    df["dato_scrapet"] = datetime.now().strftime("%Y-%m-%d")
    df["kilde"] = "Facebook"

    # Prøv å lese historikk fra Finn for bedre salgspris-estimat
    finn_fil = os.path.join(DATA_MAPPE, "finn_historikk.xlsx")
    finn_hist = None
    if os.path.exists(finn_fil):
        try:
            finn_hist = pd.read_excel(finn_fil)
        except Exception:
            finn_hist = None

    # Beregn fortjeneste (referanse = Finn hvis tilgjengelig, ellers Facebook selv)
    df = beregn_fortjeneste(df, historisk_df=finn_hist)

    # Les eksisterende Facebook-historikk
    historisk = pd.DataFrame()
    if os.path.exists(EXCEL_FIL):
        try:
            historisk = pd.read_excel(EXCEL_FIL)
        except Exception as feil:
            print(f"⚠️  Kunne ikke lese eksisterende fil: {feil}")

    kombinert = pd.concat([historisk, df], ignore_index=True) if not historisk.empty else df

    if "url" in kombinert.columns and "dato_scrapet" in kombinert.columns:
        kombinert = kombinert.drop_duplicates(subset=["url", "dato_scrapet"], keep="last")

    os.makedirs(DATA_MAPPE, exist_ok=True)
    try:
        kombinert.to_excel(EXCEL_FIL, index=False)
        print(f"\n✅ Lagret {len(df)} annonser til {EXCEL_FIL}")
        print(f"   Total historikk: {len(kombinert)} rader")
    except Exception as feil:
        csv_fil = EXCEL_FIL.replace(".xlsx", f"_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        kombinert.to_csv(csv_fil, index=False)
        print(f"   Lagret som CSV i stedet: {csv_fil}")

    # Skriv oppsummering
    skriv_ut_oppsummering(df, kilde="Facebook Marketplace")


def forste_gangs_innlogging(playwright_modul):
    """
    Kjøres kun hvis SESSION_MAPPE ikke finnes.
    Åpner nettleser slik at brukeren kan logge inn manuelt.
    """
    print("\n" + "=" * 60)
    print("  FØRSTE GANGS OPPSETT — FACEBOOK-INNLOGGING")
    print("=" * 60)
    print("""
En nettleser åpnes nå. Gjør følgende:
  1. Logg inn på Facebook med brukernavn og passord
  2. Når du er inne, kom tilbake til denne terminalen
  3. Trykk ENTER her

Passordet ditt lagres ALDRI — bare en øktcookie lagres lokalt.
""")
    input("Trykk ENTER for å åpne nettleseren...")

    browser = playwright_modul.chromium.launch_persistent_context(
        user_data_dir=SESSION_MAPPE,
        headless=False,
        viewport={"width": 1280, "height": 900},
    )

    side = browser.new_page()
    side.goto("https://www.facebook.com/login")

    print("\n🔐 Logg inn i nettleseren som nå er åpnet.")
    input("Når du ER logget inn, trykk ENTER her...")

    browser.close()
    print("\n✅ Innlogging lagret. Scriptet fortsetter nå.\n")


def skrap_facebook():
    """Hovedfunksjon for Facebook-skraping."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("""
❌ Playwright er ikke installert.

Kjør først:
    pip install playwright
    playwright install chromium
""")
        sys.exit(1)

    annonser: list[dict] = []

    with sync_playwright() as p:
        # Første gangs oppsett
        if not os.path.exists(SESSION_MAPPE):
            forste_gangs_innlogging(p)

        print(f"\n🔍 Starter Facebook-skraping for '{SOKEORD}'")

        try:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=SESSION_MAPPE,
                headless=False,  # La brukeren se hva som skjer
                viewport={"width": 1280, "height": 900},
            )
            side = browser.new_page()

            print(f"   Åpner: {FB_URL}")
            side.goto(FB_URL, timeout=60000)
            side.wait_for_timeout(3000)

            # Sjekk om vi ble kastet ut til login
            if "login" in side.url.lower():
                print("\n❌ Facebook krever innlogging på nytt.")
                print("   Slett 'fb_session'-mappen og kjør scriptet igjen.")
                browser.close()
                lagre_innsamlede_data(annonser, "Ikke innlogget.")
                return

            # Scroll ned flere ganger for å laste flere annonser
            print("   Scroller for å laste annonser...")
            sett_urler = set()

            for scroll_n in range(MAX_SCROLL):
                # Hent alle annonse-lenker på siden
                lenker = side.query_selector_all('a[href*="/marketplace/item/"]')

                for lenke in lenker:
                    try:
                        url = lenke.get_attribute("href") or ""
                        if not url.startswith("http"):
                            url = "https://www.facebook.com" + url
                        # Fjern query-parametre for entydig ID
                        ren_url = url.split("?")[0]
                        if ren_url in sett_urler:
                            continue
                        sett_urler.add(ren_url)

                        # All tekst i lenken — inneholder typisk pris, tittel og sted
                        tekst = lenke.inner_text() or ""
                        linjer = [l.strip() for l in tekst.split("\n") if l.strip()]

                        if len(linjer) < 2:
                            continue

                        # Første linje er vanligvis pris, andre tittel, tredje sted
                        pris_linje = linjer[0]
                        tittel = linjer[1] if len(linjer) > 1 else ""
                        sted = linjer[2] if len(linjer) > 2 else ""

                        pris = parse_pris(pris_linje)

                        # Hopp over irrelevante annonser
                        if not tittel or "garmin" not in tittel.lower():
                            continue
                        if pris <= 0:
                            continue

                        annonser.append({
                            "tittel": tittel,
                            "pris": pris,
                            "sted": sted,
                            "dato_postet": "",   # Facebook viser ikke dato i søkeresultat
                            "tilstand": "",      # Må evt. hentes fra detaljside
                            "url": ren_url,
                        })
                    except Exception:
                        continue

                print(f"   Scroll {scroll_n + 1}/{MAX_SCROLL}: {len(annonser)} unike annonser funnet")

                if len(annonser) >= MAX_ANNONSER:
                    break

                # Scroll ned
                side.mouse.wheel(0, 3000)
                side.wait_for_timeout(2000)

            browser.close()

        except Exception as feil:
            melding = str(feil).lower()
            if any(nokkel in melding for nokkel in ["blocked", "timeout", "detected", "checkpoint"]):
                print(f"\n❌ Facebook ser ut til å ha blokkert scraperen: {feil}")
            else:
                print(f"\n❌ Uventet feil: {feil}")
            lagre_innsamlede_data(annonser, "Feil under skraping.")
            return

    lagre_innsamlede_data(annonser)


if __name__ == "__main__":
    try:
        skrap_facebook()
    except KeyboardInterrupt:
        print("\n\n⛔ Avbrutt av bruker.")
        sys.exit(0)

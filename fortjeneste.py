"""
Fortjenesteberegner for Garmin-klokker.

Brukes av både finn_scraper.py og facebook_scraper.py.
Beregner forventet salgspris, kostnader og netto fortjeneste per annonse.
"""

import pandas as pd
import numpy as np
import re

# Faste kostnader (i NOK)
FIKSKOSTNAD = 150          # Ny rem + lader fra AliExpress (estimat)
HELTHJEM_FRAKT = 80        # Frakt-buffer (kjøper betaler typisk, men vi inkluderer som sikkerhet)
FINN_ANNONSE = 0           # Finn Torget er gratis
ROI_KJOPSSIGNAL = 40       # Prosent — over denne er det et kjøpssignal


def normaliser_modell(tittel: str) -> str:
    """
    Plukker ut Garmin-modellnavn fra tittel slik at vi kan sammenligne like klokker.
    Returnerer f.eks. "fenix 7", "forerunner 255", "venu 2" osv.
    Hvis ingen modell gjenkjennes, returneres "ukjent".
    """
    if not isinstance(tittel, str):
        return "ukjent"

    t = tittel.lower()

    # Vanlige Garmin-serier vi ser etter
    modeller = [
        r"fenix\s*\d+[a-z]*",
        r"forerunner\s*\d+[a-z]*",
        r"venu\s*\d*[a-z]*",
        r"vivoactive\s*\d+",
        r"vivomove\s*\w*",
        r"instinct\s*\d*[a-z]*",
        r"epix\s*\d*",
        r"enduro\s*\d*",
        r"tactix\s*\d*",
        r"marq\s*\w*",
        r"swim\s*\d*",
        r"descent\s*\w*",
    ]

    for regex in modeller:
        match = re.search(regex, t)
        if match:
            # Rydd opp — fjern ekstra mellomrom
            return re.sub(r"\s+", " ", match.group(0)).strip()

    return "ukjent"


def beregn_salgspris_estimat(df: pd.DataFrame, modell: str) -> float:
    """
    Beregner forventet salgspris for en gitt modell basert på toppen 40% av finn.no-prisene.
    Dette representerer hva selgere som prises "godt" faktisk tar.

    Hvis det er for få data, brukes median av alle priser for modellen.
    Hvis modellen ikke finnes i data, returneres NaN.
    """
    if df is None or df.empty or "modell" not in df.columns or "pris" not in df.columns:
        return np.nan

    # Bare samme modell, og bare gyldige priser
    modell_df = df[(df["modell"] == modell) & (df["pris"] > 0)]

    if modell_df.empty:
        return np.nan

    priser = modell_df["pris"].dropna().sort_values()

    if len(priser) < 3:
        # For lite data — bruk median
        return float(priser.median())

    # Median av topp 40% (dvs. 60. til 100. persentil)
    top_40 = priser[priser >= priser.quantile(0.60)]
    return float(top_40.median())


def beregn_fortjeneste(df: pd.DataFrame, historisk_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Legger til fortjeneste-kolonner til et DataFrame med annonser.

    Argumenter:
        df: Nye annonser som skal analyseres (må ha "tittel" og "pris")
        historisk_df: Historiske finn.no-data for å beregne salgsprisestimat.
                      Hvis None, brukes df selv som referanse.

    Returnerer DataFrame med nye kolonner:
        modell, salgspris_estimat, fikskostnad, helthjem_frakt,
        netto_fortjeneste, roi_prosent, kjopssignal
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # Standardiser priskolonne — sørg for at det er tall
    df["pris"] = pd.to_numeric(df["pris"], errors="coerce")

    # Finn modell fra tittel
    df["modell"] = df["tittel"].apply(normaliser_modell)

    # Referanse-DataFrame for salgspris (bruk historisk hvis tilgjengelig)
    referanse = historisk_df if historisk_df is not None and not historisk_df.empty else df

    # Sørg for at referansen har modell-kolonne
    if "modell" not in referanse.columns and "tittel" in referanse.columns:
        referanse = referanse.copy()
        referanse["modell"] = referanse["tittel"].apply(normaliser_modell)

    # Beregn salgspris per modell (cache for effektivitet)
    salgspris_cache = {}
    for modell in df["modell"].unique():
        salgspris_cache[modell] = beregn_salgspris_estimat(referanse, modell)

    df["salgspris_estimat"] = df["modell"].map(salgspris_cache)
    df["fikskostnad"] = FIKSKOSTNAD
    df["helthjem_frakt"] = HELTHJEM_FRAKT

    # Netto fortjeneste = salgspris - kjøpspris - fiks - frakt
    df["netto_fortjeneste"] = (
        df["salgspris_estimat"]
        - df["pris"]
        - FIKSKOSTNAD
        - HELTHJEM_FRAKT
    )

    # ROI i prosent
    df["roi_prosent"] = np.where(
        df["pris"] > 0,
        (df["netto_fortjeneste"] / df["pris"]) * 100,
        np.nan,
    )

    # Kjøpssignal
    df["kjopssignal"] = np.where(
        df["roi_prosent"] > ROI_KJOPSSIGNAL,
        "🟢 KJØPSignal",
        "",
    )

    return df


def skriv_ut_oppsummering(df: pd.DataFrame, kilde: str = "Finn"):
    """Skriver en enkel oppsummering til terminalen."""
    if df is None or df.empty:
        print(f"Ingen annonser funnet fra {kilde}.")
        return

    print(f"\n{'=' * 60}")
    print(f"  OPPSUMMERING — {kilde}")
    print(f"{'=' * 60}")
    print(f"Totalt antall annonser:     {len(df)}")

    if "pris" in df.columns:
        gyldige = df[df["pris"] > 0]
        if not gyldige.empty:
            print(f"Gjennomsnittlig pris:       {gyldige['pris'].mean():.0f} kr")
            print(f"Median pris:                {gyldige['pris'].median():.0f} kr")

    if "kjopssignal" in df.columns:
        kjop = df[df["kjopssignal"] == "🟢 KJØPSignal"]
        print(f"Kjøpssignaler (ROI > {ROI_KJOPSSIGNAL}%):  {len(kjop)}")

        if not kjop.empty:
            print(f"\n🟢 BESTE KJØPSMULIGHETER:")
            topp = kjop.nlargest(5, "netto_fortjeneste")
            for _, rad in topp.iterrows():
                tittel = str(rad.get("tittel", ""))[:50]
                pris = rad.get("pris", 0)
                netto = rad.get("netto_fortjeneste", 0)
                roi = rad.get("roi_prosent", 0)
                print(f"  • {tittel}")
                print(f"    Pris: {pris:.0f} kr  →  Netto: {netto:.0f} kr  (ROI: {roi:.1f}%)")
    print(f"{'=' * 60}\n")

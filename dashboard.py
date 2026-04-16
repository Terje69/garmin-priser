"""
Dashboard for Garmin-prissporing.

Viser sammenslåtte data fra Finn.no og Facebook Marketplace.
Kjøres med:  streamlit run dashboard.py
"""

import os
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from fortjeneste import FIKSKOSTNAD, HELTHJEM_FRAKT, ROI_KJOPSSIGNAL

# Konfigurasjon
DATA_MAPPE = "data"
FINN_FIL = os.path.join(DATA_MAPPE, "finn_historikk.xlsx")
FB_FIL = os.path.join(DATA_MAPPE, "facebook_historikk.xlsx")

# Sideoppsett
st.set_page_config(
    page_title="Garmin Prissporing",
    page_icon="⌚",
    layout="wide",
)

st.title("⌚ Garmin Prissporing & Fortjenesteanalyse")


# --------------------- Datainnlasting ---------------------
@st.cache_data(ttl=300)  # Cacher i 5 minutter
def last_data():
    """Laster inn data fra begge Excel-filer."""
    finn_df = pd.DataFrame()
    fb_df = pd.DataFrame()

    if os.path.exists(FINN_FIL):
        try:
            finn_df = pd.read_excel(FINN_FIL)
            finn_df["kilde"] = "Finn"
        except Exception as feil:
            st.error(f"Kunne ikke lese Finn-data: {feil}")

    if os.path.exists(FB_FIL):
        try:
            fb_df = pd.read_excel(FB_FIL)
            fb_df["kilde"] = "Facebook"
        except Exception as feil:
            st.error(f"Kunne ikke lese Facebook-data: {feil}")

    # Sørg for at dato_scrapet er datetime
    for df in (finn_df, fb_df):
        if "dato_scrapet" in df.columns:
            df["dato_scrapet"] = pd.to_datetime(df["dato_scrapet"], errors="coerce")

    return finn_df, fb_df


finn_df, fb_df = last_data()

# Sjekk om vi har noe data i det hele tatt
if finn_df.empty and fb_df.empty:
    st.warning("""
    ### Ingen data funnet ennå

    Kjør først scraperne for å samle inn data:
    ```
    python finn_scraper.py
    python facebook_scraper.py
    ```
    """)
    st.stop()

# Sammenslått DataFrame med begge kilder
if not finn_df.empty and not fb_df.empty:
    kombinert_df = pd.concat([finn_df, fb_df], ignore_index=True)
elif not finn_df.empty:
    kombinert_df = finn_df.copy()
else:
    kombinert_df = fb_df.copy()

# Siste dato per kilde+URL (nyeste annonse-status)
if "dato_scrapet" in kombinert_df.columns and "url" in kombinert_df.columns:
    siste_df = kombinert_df.sort_values("dato_scrapet").drop_duplicates(
        subset=["url"], keep="last"
    )
else:
    siste_df = kombinert_df

# Dagens data (siste dato for hver kilde)
if "dato_scrapet" in siste_df.columns:
    siste_dato = siste_df["dato_scrapet"].max()
    dagens_df = siste_df[siste_df["dato_scrapet"] == siste_dato]
else:
    dagens_df = siste_df

# --------------------- Sidebar ---------------------
st.sidebar.header("ℹ️ Om dataene")
st.sidebar.write(f"**Finn-annonser (totalt):** {len(finn_df)}")
st.sidebar.write(f"**Facebook-annonser (totalt):** {len(fb_df)}")
st.sidebar.write(f"**Sist oppdatert:** {siste_df['dato_scrapet'].max().strftime('%Y-%m-%d') if 'dato_scrapet' in siste_df.columns and not siste_df.empty else 'Ukjent'}")

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Faste kostnader per salg:**")
st.sidebar.write(f"• Fiks (rem + lader): {FIKSKOSTNAD} kr")
st.sidebar.write(f"• Helthjem frakt: {HELTHJEM_FRAKT} kr")
st.sidebar.write(f"• Kjøpssignal: ROI > {ROI_KJOPSSIGNAL}%")

# --------------------- Faner ---------------------
fane1, fane2, fane3, fane4 = st.tabs([
    "📊 Dagens marked",
    "📈 Prishistorikk",
    "💰 Kjøp/Selg-analyse",
    "⚔️ Facebook vs Finn",
])

# ============================================================
# FANE 1 — DAGENS MARKED
# ============================================================
with fane1:
    st.header("📊 Dagens marked — alle kilder")

    if dagens_df.empty:
        st.info("Ingen annonser i dagens data.")
    else:
        # Filtreringsvalg
        kol1, kol2, kol3 = st.columns(3)
        with kol1:
            valgt_kilde = st.multiselect(
                "Kilde",
                options=["Finn", "Facebook"],
                default=["Finn", "Facebook"],
            )
        with kol2:
            min_roi = st.slider("Minimum ROI %", -100, 200, -50)
        with kol3:
            maks_pris = st.number_input("Maks pris (kr)", min_value=0, value=10000, step=500)

        # Bruk filter
        vis_df = dagens_df[dagens_df["kilde"].isin(valgt_kilde)]
        if "roi_prosent" in vis_df.columns:
            vis_df = vis_df[vis_df["roi_prosent"].fillna(-999) >= min_roi]
        if "pris" in vis_df.columns and maks_pris > 0:
            vis_df = vis_df[vis_df["pris"] <= maks_pris]

        # Sorter
        if "netto_fortjeneste" in vis_df.columns:
            vis_df = vis_df.sort_values("netto_fortjeneste", ascending=False)

        st.write(f"**{len(vis_df)} annonser vises**")

        # Visningskolonner
        kolonner = [
            "kilde", "tittel", "modell", "pris", "salgspris_estimat",
            "fikskostnad", "helthjem_frakt", "netto_fortjeneste",
            "roi_prosent", "kjopssignal", "sted", "url",
        ]
        kolonner = [k for k in kolonner if k in vis_df.columns]

        # Fargelegg rader basert på ROI
        def farge_for_roi(rad):
            roi = rad.get("roi_prosent", np.nan)
            if pd.isna(roi):
                return [""] * len(rad)
            if roi > 40:
                farge = "background-color: #d4edda"  # grønn
            elif roi >= 20:
                farge = "background-color: #fff3cd"  # gul
            else:
                farge = "background-color: #f8d7da"  # rød
            return [farge] * len(rad)

        styled = vis_df[kolonner].style.apply(farge_for_roi, axis=1).format({
            "pris": "{:.0f} kr",
            "salgspris_estimat": "{:.0f} kr",
            "fikskostnad": "{:.0f} kr",
            "helthjem_frakt": "{:.0f} kr",
            "netto_fortjeneste": "{:.0f} kr",
            "roi_prosent": "{:.1f}%",
        }, na_rep="-")

        st.dataframe(styled, use_container_width=True, height=600)

        # Nedlasting
        csv = vis_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Last ned som CSV", csv, "dagens_marked.csv", "text/csv")


# ============================================================
# FANE 2 — PRISHISTORIKK
# ============================================================
with fane2:
    st.header("📈 Prishistorikk over tid")

    if "dato_scrapet" not in kombinert_df.columns:
        st.warning("Mangler datokolonne i dataene.")
    else:
        # Gjennomsnittspris per dag per kilde
        daglig = kombinert_df.dropna(subset=["pris"]).groupby(
            ["dato_scrapet", "kilde"]
        )["pris"].mean().reset_index()
        daglig.columns = ["Dato", "Kilde", "Gj.snitt pris"]

        st.subheader("Gjennomsnittlig bruktpris per dag")
        if not daglig.empty:
            fig1 = px.line(daglig, x="Dato", y="Gj.snitt pris", color="Kilde",
                           markers=True, labels={"Gj.snitt pris": "Pris (kr)"})
            st.plotly_chart(fig1, use_container_width=True)
        else:
            st.info("Trenger mer data over tid for å vise trend.")

        # Retail-pris fra prisjakt
        if "retail_pris" in kombinert_df.columns:
            st.subheader("Gjennomsnittlig butikkpris (Prisjakt)")
            retail = kombinert_df[kombinert_df["retail_pris"] > 0].groupby(
                "dato_scrapet"
            )["retail_pris"].mean().reset_index()
            retail.columns = ["Dato", "Butikkpris"]
            if not retail.empty:
                fig2 = px.line(retail, x="Dato", y="Butikkpris", markers=True,
                               labels={"Butikkpris": "Pris (kr)"})
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Ingen retail-priser registrert ennå.")

        # Netto fortjeneste over tid
        if "netto_fortjeneste" in kombinert_df.columns:
            st.subheader("Gjennomsnittlig netto fortjeneste per dag")
            fortjeneste_daglig = kombinert_df.dropna(subset=["netto_fortjeneste"]).groupby(
                ["dato_scrapet", "kilde"]
            )["netto_fortjeneste"].mean().reset_index()
            fortjeneste_daglig.columns = ["Dato", "Kilde", "Netto fortjeneste"]
            if not fortjeneste_daglig.empty:
                fig3 = px.line(fortjeneste_daglig, x="Dato", y="Netto fortjeneste",
                               color="Kilde", markers=True,
                               labels={"Netto fortjeneste": "NOK"})
                fig3.add_hline(y=0, line_dash="dash", line_color="gray")
                st.plotly_chart(fig3, use_container_width=True)


# ============================================================
# FANE 3 — KJØP/SELG-ANALYSE
# ============================================================
with fane3:
    st.header("💰 Kjøp/Selg-analyse")

    if "pris" not in siste_df.columns:
        st.warning("Mangler prisdata.")
    else:
        col1, col2, col3 = st.columns(3)

        # Beste kjøpspris — 15. persentil av alle annonser
        alle_priser = siste_df[siste_df["pris"] > 0]["pris"]
        finn_priser = siste_df[(siste_df["kilde"] == "Finn") & (siste_df["pris"] > 0)]["pris"]
        fb_priser = siste_df[(siste_df["kilde"] == "Facebook") & (siste_df["pris"] > 0)]["pris"]

        with col1:
            st.metric("🟢 Beste kjøpspris Finn (15. persentil)",
                      f"{finn_priser.quantile(0.15):.0f} kr" if not finn_priser.empty else "—")
            st.metric("🟢 Beste kjøpspris Facebook (15. persentil)",
                      f"{fb_priser.quantile(0.15):.0f} kr" if not fb_priser.empty else "—")

        with col2:
            # Salgspris — 75. persentil, kun finn
            salgspris_75 = finn_priser.quantile(0.75) if not finn_priser.empty else 0
            st.metric("💸 Estimert salgspris (75. persentil, Finn)",
                      f"{salgspris_75:.0f} kr" if salgspris_75 > 0 else "—")

        with col3:
            # Netto per handel
            beste_kjop = min(
                finn_priser.quantile(0.15) if not finn_priser.empty else 1e9,
                fb_priser.quantile(0.15) if not fb_priser.empty else 1e9,
            )
            netto_per_handel = salgspris_75 - beste_kjop - FIKSKOSTNAD - HELTHJEM_FRAKT
            st.metric("💰 Netto per handel",
                      f"{netto_per_handel:.0f} kr" if beste_kjop < 1e9 else "—")

        st.markdown("---")

        # Scenariotabell
        st.subheader("📅 Månedlig inntektsscenario")

        if beste_kjop < 1e9 and netto_per_handel > 0:
            scenarier = pd.DataFrame({
                "Antall handler per måned": [3, 5, 10],
                "Netto per handel (kr)": [f"{netto_per_handel:.0f}"] * 3,
                "Månedlig netto (kr)": [
                    f"{netto_per_handel * n:.0f}" for n in [3, 5, 10]
                ],
                "Årlig netto (kr)": [
                    f"{netto_per_handel * n * 12:.0f}" for n in [3, 5, 10]
                ],
            })
            st.dataframe(scenarier, use_container_width=True, hide_index=True)

            st.info(f"""
            **Forutsetninger:**
            - Kjøpspris: {beste_kjop:.0f} kr (15. persentil)
            - Salgspris: {salgspris_75:.0f} kr (75. persentil på Finn)
            - Fikskostnad: {FIKSKOSTNAD} kr per klokke
            - Fraktbuffer: {HELTHJEM_FRAKT} kr per klokke
            """)
        else:
            st.warning("Ikke nok data for å beregne scenarier ennå.")


# ============================================================
# FANE 4 — FACEBOOK VS FINN
# ============================================================
with fane4:
    st.header("⚔️ Facebook vs Finn — prissammenligning")

    if finn_df.empty or fb_df.empty:
        st.warning("Trenger data fra BEGGE kilder for sammenligning. "
                   "Kjør både `finn_scraper.py` og `facebook_scraper.py`.")
    else:
        # Siste snitt per kilde
        finn_snitt = finn_df[finn_df["pris"] > 0]["pris"].mean()
        fb_snitt = fb_df[fb_df["pris"] > 0]["pris"].mean()
        diff_kr = finn_snitt - fb_snitt
        diff_prosent = (diff_kr / fb_snitt * 100) if fb_snitt > 0 else 0

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🔵 Snitt Finn", f"{finn_snitt:.0f} kr")
        with col2:
            st.metric("🟣 Snitt Facebook", f"{fb_snitt:.0f} kr")
        with col3:
            st.metric("📊 Prisgap (Finn − Facebook)",
                      f"{diff_kr:.0f} kr",
                      f"{diff_prosent:+.1f}%")

        st.markdown("---")

        # Per-modell sammenligning
        if "modell" in finn_df.columns and "modell" in fb_df.columns:
            st.subheader("Sammenligning per modell")

            finn_modell = finn_df[finn_df["pris"] > 0].groupby("modell")["pris"].mean().reset_index()
            finn_modell.columns = ["modell", "Finn snittpris"]

            fb_modell = fb_df[fb_df["pris"] > 0].groupby("modell")["pris"].mean().reset_index()
            fb_modell.columns = ["modell", "Facebook snittpris"]

            sammenligning = pd.merge(finn_modell, fb_modell, on="modell", how="inner")
            sammenligning["Differanse (kr)"] = (
                sammenligning["Finn snittpris"] - sammenligning["Facebook snittpris"]
            )
            sammenligning["Differanse (%)"] = (
                sammenligning["Differanse (kr)"] / sammenligning["Facebook snittpris"] * 100
            )

            if not sammenligning.empty:
                sammenligning = sammenligning.sort_values("Differanse (kr)", ascending=False)
                st.dataframe(
                    sammenligning.style.format({
                        "Finn snittpris": "{:.0f} kr",
                        "Facebook snittpris": "{:.0f} kr",
                        "Differanse (kr)": "{:+.0f} kr",
                        "Differanse (%)": "{:+.1f}%",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )

                # Søylediagram
                fig = go.Figure()
                fig.add_trace(go.Bar(name="Finn", x=sammenligning["modell"],
                                     y=sammenligning["Finn snittpris"],
                                     marker_color="#1f77b4"))
                fig.add_trace(go.Bar(name="Facebook", x=sammenligning["modell"],
                                     y=sammenligning["Facebook snittpris"],
                                     marker_color="#9467bd"))
                fig.update_layout(barmode="group", yaxis_title="Gj.snitt pris (kr)",
                                  xaxis_title="Modell")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Ingen overlappende modeller mellom kildene ennå.")

        st.markdown("---")

        # Anbefaling
        st.subheader("🎯 Anbefaling")
        if diff_kr > 0:
            st.success(
                f"**Kjøp på Facebook, selg på Finn — "
                f"typisk prisfordel: {diff_kr:.0f} kr** ({diff_prosent:+.1f}%)\n\n"
                f"Gjennomsnittlig er Finn-priser {diff_kr:.0f} kr høyere enn Facebook. "
                f"Kjøp billig på Facebook, videresolg til Finn-nivå."
            )
        elif diff_kr < 0:
            st.warning(
                f"**Facebook er dyrere enn Finn akkurat nå** ({abs(diff_kr):.0f} kr, "
                f"{abs(diff_prosent):.1f}%). "
                f"Det er mer attraktivt å kjøpe direkte på Finn."
            )
        else:
            st.info("Priser er omtrent like mellom kildene.")

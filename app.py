# app.py — Property Hunt v2 (link collector)
import streamlit as st
import pandas as pd
from utils.links import collect_rightmove_links
from utils.details import scrape_details_batch


st.set_page_config(page_title="Property Hunt v2", page_icon="🏠", layout="wide")
st.title("🏠 Property Hunt v2")

# Default Rightmove search (SSTC excluded). You can paste any URL into the box.
DEFAULT_URL = (
    "https://www.rightmove.co.uk/property-for-sale/find.html?"
    "searchLocation=Norwich%2C+Norfolk&useLocationIdentifier=true&"
    "locationIdentifier=REGION%5E1018&radius=0.0&maxPrice=140000&minBedrooms=2&"
    "_includeSSTC=off&dontShow=retirement%2CsharedOwnership%2Cauction&sortType=2&"
    "channel=BUY&transactionType=BUY&displayLocationIdentifier=Norwich.html&"
    "maxDaysSinceAdded=14&index=0"
)

# ---- Controls at the top (as requested) ----
c1, c2, c3 = st.columns([4, 1, 1])
with c1:
    url = st.text_input("Rightmove search URL", value=DEFAULT_URL)
with c2:
    max_pages = st.number_input("Pages", min_value=1, max_value=50, value=10,
                                help="How many result pages to walk (≈24 results per page).")
with c3:
    run = st.button("Scrape listings", type="primary")

st.divider()

# Page focus: show tiles later; for now, just count + collapsed list.
if run:
    # Ensure variables exist before we use them
    links = []
    err = None

    # 1) Collect listing URLs
    with st.status("Collecting links…", expanded=True) as status:
        try:
            links = collect_rightmove_links(url, max_pages=int(max_pages))
            status.update(label=f"Found {len(links)} listing links.", state="complete")
        except Exception as e:
            err = str(e)
            status.update(label="Failed", state="error")

    # 2) Show summary (outside status)
    if err:
        st.error(err)
    st.metric("Listings found", len(links))

    # 3) If we have links, fetch property details (HTTP-only)
    if links:
        with st.status("Fetching details…", expanded=False) as s2:
            rows = scrape_details_batch(links, max_concurrency=8)
            s2.update(label=f"Parsed {len(rows)} pages.", state="complete")

        df = pd.DataFrame(rows)
        show_cols = [
            "url","price_gbp","bedrooms","postcode","tenure","lease_years",
            "service_charge","ground_rent","availability","added_on","reduced_on",
            "image_url","error"
        ]
        show_cols = [c for c in show_cols if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

        with st.expander("Show links (debug)", expanded=False):
            st.dataframe(pd.DataFrame({"url": links}), use_container_width=True, hide_index=True)

        st.success("Detail scraping complete. Next step: build tiles.")
    else:
        st.info("No links found. Try Pages=2 and verify the Rightmove URL.")
else:
    st.info("Paste your Rightmove search and press **Scrape listings** to collect property links.")

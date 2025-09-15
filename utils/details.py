# utils/details.py
from __future__ import annotations
import re
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup

# ---------- small parsers (regex-first, cheap CPU) ----------

_PRICE_RE = re.compile(r"£\s*([\d,]+)", re.I)
_BEDS_RE = re.compile(r"(\d+)\s*bed(?:room)?", re.I)
_POSTCODE_RE = re.compile(
    r"\b([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})\b", re.I
)  # UK postcode (loose)
_TENURE_RE = re.compile(r"\b(leasehold|freehold|share of freehold)\b", re.I)
_LEASE_YEARS_RE = re.compile(
    r"(\d{2,4})\s*(?:years?|yrs?)\s*(?:remaining|left|lease|unexpired)?", re.I
)

_SERVICE_CHARGE_LINE = re.compile(r"service\s*charge[^£\n]*£\s*[\d,]+(?:\.\d{1,2})?\s*(?:per\s*(?:annum|year)|p\.?a\.?|pa|per\s*month|pcm)?", re.I)
_GROUND_RENT_LINE = re.compile(r"ground\s*rent[^£\n]*£\s*[\d,]+(?:\.\d{1,2})?\s*(?:per\s*(?:annum|year)|p\.?a\.?|pa|per\s*month|pcm)?", re.I)

_OFF_MARKET_RE = re.compile(
    r"(sold\s+stc|sstc|sold\s+subject\s+to\s+contract|under\s+offer|offer\s+agreed|sale\s+agreed)",
    re.I,
)

_ADDED_DATE = re.compile(r"Added on[^0-9]{0,10}(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
_REDUCED_DATE = re.compile(r"Reduced on[^0-9]{0,10}(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
_ADDED_REL = re.compile(r"added\s+(\d+)\s+days?\s+ago", re.I)
_REDUCED_REL = re.compile(r"reduced\s+(\d+)\s+days?\s+ago", re.I)

def _gather_focus_text(html: str) -> str:
    """Collect just the meaningful text blocks: description, key features, tenure/charges."""
    soup = BeautifulSoup(html, "lxml")
    chunks = []

    # grab blocks whose id/class hints they contain details
    for tag in soup.find_all(True):
        idc = ((tag.get("id") or "") + " " + " ".join(tag.get("class", []))).lower()
        if any(k in idc for k in ["description", "key", "feature", "tenure", "lease", "leasehold", "charges"]):
            chunks.append(tag.get_text(" ", strip=True))

    # meta description as a fallback
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        chunks.append(meta["content"])

    return " \n ".join(chunks)


def _extract_charges(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Return (service_charge_text, ground_rent_text).
    If advert states a *combined* amount, we return it in service_charge and leave ground_rent None.
    """
    t = text or ""

    # Combined, e.g. "Service Charge And Ground Rent Approx £95PCM"
    comb = re.search(
        r"(?:service\s*charge\s*and\s*ground\s*rent|ground\s*rent\s*and\s*service\s*charge)[^£]{0,40}"
        r"£\s*([\d,]+(?:\.\d{1,2})?)\s*(pcm|per month|per\s*annum|per year|p\.?a\.?|pa)?",
        t, re.I,
    )
    if comb:
        val = comb.group(1)
        per = comb.group(2) or "per year"
        return (f"£{val} {per} (combined)", None)

    # Individual lines
    sc = re.search(
        r"service\s*(?:/maintenance)?\s*charge[^£]{0,40}£\s*([\d,]+(?:\.\d{1,2})?)\s*"
        r"(pcm|per month|per\s*annum|per year|p\.?a\.?|pa)?", t, re.I,
    )
    gr = re.search(
        r"ground\s*rent[^£]{0,40}£\s*([\d,]+(?:\.\d{1,2})?)\s*"
        r"(pcm|per month|per\s*annum|per year|p\.?a\.?|pa)?", t, re.I,
    )

    def fmt(m):
        if not m:
            return None
        return f"£{m.group(1)} {(m.group(2) or 'per year')}"

    return fmt(sc), fmt(gr)


def _norm_date_dmy(dmy: str) -> Optional[str]:
    try:
        d, m, y = dmy.strip().split("/")
        if len(y) == 2:
            y = "20" + y
        return datetime.strptime(f"{d}/{m}/{y}", "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        return None

def parse_added_reduced(text: str) -> tuple[Optional[str], Optional[str]]:
    t = text or ""
    ma = _ADDED_DATE.search(t)
    mr = _REDUCED_DATE.search(t)
    added = _norm_date_dmy(ma.group(1)) if ma else None
    reduced = _norm_date_dmy(mr.group(1)) if mr else None

    low = t.lower()
    today = datetime.today().date()

    if added is None:
        md = _ADDED_REL.search(low)
        if "added yesterday" in low:
            added = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        elif "added today" in low:
            added = today.strftime("%Y-%m-%d")
        elif md:
            added = (today - timedelta(days=int(md.group(1)))).strftime("%Y-%m-%d")

    if reduced is None:
        rd = _REDUCED_REL.search(low)
        if "reduced yesterday" in low:
            reduced = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        elif "reduced today" in low:
            reduced = today.strftime("%Y-%m-%d")
        elif rd:
            reduced = (today - timedelta(days=int(rd.group(1)))).strftime("%Y-%m-%d")

    return added, reduced

def parse_og_image(html: str) -> Optional[str]:
    try:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("meta", attrs={"property": "og:image"})
        return tag["content"] if tag and tag.has_attr("content") else None
    except Exception:
        return None

def parse_text_fields(html: str) -> Dict[str, Any]:
    """Scan the whole HTML text for simple tokens (cheap & resilient)."""
    t = html or ""
    price = None
    m = _PRICE_RE.search(t)
    if m:
        try:
            price = int(m.group(1).replace(",", ""))
        except Exception:
            price = None

    beds = None
    bm = _BEDS_RE.search(t)
    if bm:
        try:
            beds = int(bm.group(1))
        except Exception:
            beds = None

    postcode = None
    pm = _POSTCODE_RE.search(t)
    if pm:
        postcode = pm.group(1).upper().replace("  ", " ").strip()

    tenure = None
    tm = _TENURE_RE.search(t)
    if tm:
        tenure = tm.group(1).title()

    lease_years = None
    lm = _LEASE_YEARS_RE.search(t)
    if lm:
        try:
            lease_years = int(lm.group(1))
        except Exception:
            lease_years = None

    # keep the original matched lines for review (don’t over-normalise yet)

    # Prefer focused blocks (description/key features/leasehold) to avoid noise.
    focus = _gather_focus_text(html)
    service_charge, ground_rent = _extract_charges(focus)


    availability = "on_market"
    if _OFF_MARKET_RE.search(t):
        availability = "off_market"

    added_on, reduced_on = parse_added_reduced(t)
    image_url = parse_og_image(html)

    return {
        "price_gbp": price,
        "bedrooms": beds,
        "postcode": postcode,
        "tenure": tenure,
        "lease_years": lease_years,
        "service_charge": service_charge,
        "ground_rent": ground_rent,
        "availability": availability,
        "added_on": added_on,
        "reduced_on": reduced_on,
        "image_url": image_url,
    }

# ---------- async batch fetch ----------

async def _fetch_one(url: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    try:
        r = await client.get(url)
        if r.status_code != 200:
            return {"url": url, "error": f"HTTP {r.status_code}"}
        data = parse_text_fields(r.text)
        data["url"] = url
        return data
    except Exception as e:
        return {"url": url, "error": str(e)}

async def scrape_details_async(urls: List[str], max_concurrency: int = 8) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(max_concurrency)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    limits = httpx.Limits(max_connections=max_concurrency, max_keepalive_connections=max_concurrency)
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, limits=limits, timeout=timeout) as client:
        async def bound(url: str):
            async with sem:
                return await _fetch_one(url, client)
        tasks = [bound(u) for u in urls]
        return await asyncio.gather(*tasks)

def scrape_details_batch(urls: List[str], max_concurrency: int = 8) -> List[Dict[str, Any]]:
    """Sync wrapper you can call from Streamlit; returns list of dicts."""
    if not urls:
        return []
    try:
        return asyncio.run(scrape_details_async(urls, max_concurrency=max_concurrency))
    except RuntimeError:
        # Streamlit can already have a running loop; create a new one
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(scrape_details_async(urls, max_concurrency=max_concurrency))
        finally:
            loop.close()

# utils/links.py
from __future__ import annotations
import re
import time
from typing import List, Set
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import httpx
from bs4 import BeautifulSoup

RIGHTMOVE_HOST = "www.rightmove.co.uk"
CARD_LINK_RE = re.compile(r"/properties/\d+", re.I)

def _normalize_search_url(url: str) -> str:
    """Ensure ?index=0 exists; keep all your filters intact."""
    u = urlparse(url)
    q = parse_qs(u.query, keep_blank_values=True)
    if "index" not in q:
        q["index"] = ["0"]
    new_query = urlencode({k: v[-1] for k, v in q.items()}, doseq=False)
    return urlunparse((u.scheme or "https", u.netloc or RIGHTMOVE_HOST, u.path, u.params, new_query, u.fragment))

def _absolute(href: str) -> str:
    return href if href.startswith("http") else f"https://{RIGHTMOVE_HOST}{href}"

def _extract_links(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    links: Set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        href = href.split("?", 1)[0]
        href = href.split("#", 1)[0]

        if CARD_LINK_RE.search(href):
            links.add(_absolute(href))
    return sorted(links)

def collect_rightmove_links(search_url: str, max_pages: int = 20, pause_s: float = 0.2) -> List[str]:
    """
    Walk Rightmove pagination via ?index=0,24,48,… and return unique property URLs.
    Lightweight: httpx + BeautifulSoup only (no headless browser).
    """
    start_url = _normalize_search_url(search_url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    all_links: Set[str] = set()
    index_step = 24
    try:
        index = int(parse_qs(urlparse(start_url).query).get("index", ["0"])[0])
    except Exception:
        index = 0

    with httpx.Client(headers=headers, follow_redirects=True, timeout=20) as client:
        for _ in range(max_pages):
            u = urlparse(start_url)
            q = parse_qs(u.query, keep_blank_values=True)
            q["index"] = [str(index)]
            url_this = urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode({k: v[-1] for k, v in q.items()}), u.fragment))

            resp = client.get(url_this)
            if resp.status_code != 200:
                break

            before = len(all_links)
            all_links.update(_extract_links(resp.text))
            if len(all_links) == before:  # nothing new → stop
                break

            index += index_step
            time.sleep(pause_s)  # polite + smooth CPU

    return sorted(all_links)

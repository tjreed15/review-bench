"""Nature Human Behaviour fetcher.

Scrapes nature.com for Open Access research articles that have linked
peer review reports.  Downloads article metadata (JSON-LD), the article
body text, and extracts text from the peer-review PDF.  Everything is
stored as JSONB in raw_venue_data with venue_id='nhb'.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from src.db.queries import upsert_raw_venue_data, get_raw_source_ids

BASE_URL = "https://www.nature.com"
LISTING_URL = BASE_URL + "/nathumbehav/research-articles"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DELAY_BETWEEN_REQUESTS = 1.5  # seconds — be polite


def _get(client: httpx.Client, url: str, retries: int = 3) -> httpx.Response:
    """GET with retries and 429 back-off."""
    for attempt in range(1, retries + 1):
        if attempt > 1:
            time.sleep(DELAY_BETWEEN_REQUESTS * attempt)
        resp = client.get(url, follow_redirects=True)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 10))
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        return resp
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def _extract_jsonld(soup: BeautifulSoup) -> dict | None:
    """Pull the ScholarlyArticle JSON-LD blob from the article page.
    """
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string)
            if isinstance(data, dict):
                if data.get("@type") == "ScholarlyArticle":
                    return data
                # Nature nests ScholarlyArticle inside WebPage.mainEntity
                main = data.get("mainEntity")
                if isinstance(main, dict) and main.get("@type") == "ScholarlyArticle":
                    return main
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "ScholarlyArticle":
                        return item
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_article_body(soup: BeautifulSoup) -> str:
    """Extract the main article body text."""
    body = soup.find("div", class_="c-article-body")
    if not body:
        return ""
    for tag in body.find_all(["figure", "table", "div"], class_=re.compile(r"ref-list|c-article-table")):
        tag.decompose()
    return body.get_text(separator="\n", strip=True)


def _extract_peer_review_pdf_url(soup: BeautifulSoup) -> str | None:
    """Find the peer review PDF download link."""
    link = soup.find("a", attrs={"data-track-label": "peer review file"})
    if link and link.get("href"):
        href = link["href"]
        if href.startswith("http"):
            return href
        return BASE_URL + href
    return None


def _pdf_to_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF using PyMuPDF (fitz)."""
    import fitz  # PyMuPDF

    text_parts = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text_parts.append(page.get_text())
    text = "\n".join(text_parts)
    # Strip null bytes — Postgres JSONB cannot store \u0000
    return text.replace("\x00", "")


class NatureHumanBehaviourFetcher:
    venue = "nhb"

    async def fetch(self, limit: int = 50, **kwargs) -> int:
        existing_ids = get_raw_source_ids(self.venue)
        total_collected = 0
        page = int(kwargs.get("start_page", 1))

        with httpx.Client(timeout=30, headers=HEADERS) as client:
            while total_collected < limit:
                # --- Step 1: get listing page ---
                list_url = f"{LISTING_URL}?searchType=journalSearch&sort=PubDate&page={page}"
                print(f"Fetching listing page {page}...", flush=True)
                resp = _get(client, list_url)
                if resp.status_code != 200:
                    print(f"  Listing page returned {resp.status_code}, stopping.")
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                articles = soup.find_all("article", itemtype="http://schema.org/ScholarlyArticle")
                if not articles:
                    print("  No more articles found, stopping.")
                    break

                for article in articles:
                    if total_collected >= limit:
                        break

                    # Check for Open Access badge
                    oa_badge = article.find("span", attrs={"data-test": "open-access"})
                    if not oa_badge:
                        continue

                    # Get article URL
                    title_link = article.find("a", class_="c-card__link")
                    if not title_link or not title_link.get("href"):
                        continue

                    article_path = title_link["href"]
                    article_url = BASE_URL + article_path

                    # Derive source_id from the article path (e.g. "s41562-026-02413-8")
                    source_id = article_path.rstrip("/").split("/")[-1]
                    if source_id in existing_ids:
                        continue

                    # --- Step 2: fetch article page ---
                    time.sleep(DELAY_BETWEEN_REQUESTS)
                    try:
                        art_resp = _get(client, article_url)
                    except RuntimeError as e:
                        print(f"  [skip] {source_id}: {e}")
                        continue

                    if art_resp.status_code != 200:
                        print(f"  [skip] {source_id}: HTTP {art_resp.status_code}")
                        continue

                    art_soup = BeautifulSoup(art_resp.text, "html.parser")

                    # Must have a peer review PDF
                    pr_pdf_url = _extract_peer_review_pdf_url(art_soup)
                    if not pr_pdf_url:
                        title_preview = (title_link.get_text(strip=True) or source_id)[:50]
                        print(f"  [skip] {title_preview}... — no peer review PDF")
                        continue

                    # Extract JSON-LD metadata
                    jsonld = _extract_jsonld(art_soup)
                    if not jsonld:
                        print(f"  [skip] {source_id}: no JSON-LD metadata")
                        continue

                    # Extract article body text
                    body_text = _extract_article_body(art_soup)

                    # --- Step 3: download peer review PDF ---
                    time.sleep(DELAY_BETWEEN_REQUESTS)
                    try:
                        pdf_resp = _get(client, pr_pdf_url)
                        if pdf_resp.status_code != 200:
                            print(f"  [skip] {source_id}: PDF download returned {pdf_resp.status_code}")
                            continue
                        pr_text = _pdf_to_text(pdf_resp.content)
                    except Exception as e:
                        print(f"  [skip] {source_id}: PDF extraction failed: {e}")
                        continue

                    if not pr_text.strip():
                        print(f"  [skip] {source_id}: peer review PDF was empty")
                        continue

                    # --- Step 4: store raw payload ---
                    raw_payload = {
                        "jsonld": jsonld,
                        "article_body": body_text,
                        "peer_review_text": pr_text,
                        "peer_review_url": pr_pdf_url,
                        "article_url": article_url,
                        "source_id": source_id,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }

                    upsert_raw_venue_data(self.venue, source_id, raw_payload)
                    existing_ids.add(source_id)
                    total_collected += 1

                    title = jsonld.get("headline", source_id)[:60]
                    print(f"[{total_collected}] {title}...", flush=True)

                page += 1
                time.sleep(DELAY_BETWEEN_REQUESTS)

        print(f"\nFetched {total_collected} papers for {self.venue}")
        return total_collected

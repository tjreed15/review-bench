"""Claim extraction.

Uses Gemini's API to extract 3-7 major claims from a paper's PDF or manuscript text.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import httpx

from src.db.queries import (
    get_papers,
    get_papers_with_claims,
    insert_claims_batch,
    delete_claims,
    delete_assessments,
)
from src.lib.gemini import generate_with_pdf, generate_with_pdf_url, generate_with_text
from src.lib.json_repair import parse_json_array

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extract_claims.md"
MODEL = "gemini-3-pro-preview"
CONCURRENCY = 5


async def extract_claims_for_paper(
    paper_id: str,
    pdf_url: str | None = None,
    manuscript_text: str | None = None,
    force: bool = False,
) -> int:
    """Extract claims for a single paper. Returns claim count."""
    existing = set(get_papers_with_claims())
    if not force and paper_id in existing:
        return 0

    prompt = PROMPT_PATH.read_text()

    if pdf_url:
        raw_output = await _generate_with_fallback(
            pdf_url=pdf_url,
            prompt=prompt,
            paper_id=paper_id,
        )
    elif manuscript_text:
        raw_output = await generate_with_text(
            text=manuscript_text,
            prompt=prompt,
            model=MODEL,
            temperature=0,
        )
    else:
        raise ValueError(f"{paper_id}: No PDF URL or manuscript text available")

    claims_raw = parse_json_array(raw_output)

    if force:
        delete_assessments(paper_id)
        delete_claims(paper_id)

    batch = []
    for i, r in enumerate(claims_raw):
        if isinstance(r, dict):
            summary = r.get("summary", "")
            source_excerpt = r.get("source_excerpt")
        else:
            summary = str(r)
            source_excerpt = None
        batch.append({
            "id": f"{paper_id}:claim-{i + 1}",
            "paper_id": paper_id,
            "summary": summary,
            "source_excerpt": source_excerpt,
        })

    insert_claims_batch(batch)
    return len(claims_raw)


async def extract_claims_for_venue(
    venue_id: str,
    limit: int | None = None,
    force: bool = False,
) -> None:
    """Extract claims for all papers in a venue with concurrency."""
    papers = get_papers(venue_id=venue_id, limit=limit)
    existing = set(get_papers_with_claims())

    to_process = []
    skipped = 0

    for paper in papers:
        paper_id = paper["id"]
        pdf_url = paper.get("pdf_url")

        if not force and paper_id in existing:
            skipped += 1
            continue

        if not pdf_url:
            if paper.get("manuscript_text"):
                paper["_manuscript_text"] = paper["manuscript_text"]
            else:
                print(f"  {paper_id}: No PDF URL or manuscript text, skipping")
                skipped += 1
                continue

        to_process.append(paper)

    print(f"Papers to process: {len(to_process)}, already done: {skipped}")

    sem = asyncio.Semaphore(CONCURRENCY)
    processed = 0
    errors = 0

    async def _process_one(paper: dict, idx: int) -> None:
        nonlocal processed, errors
        paper_id = paper["id"]
        title = paper.get("title", paper_id)[:60]

        async with sem:
            print(f"\n[{idx + 1}/{len(to_process)}] {paper_id}: {title}...")
            try:
                claim_count = await extract_claims_for_paper(
                    paper_id,
                    pdf_url=paper.get("pdf_url"),
                    manuscript_text=paper.get("_manuscript_text"),
                    force=force,
                )
                processed += 1
                print(f"  {claim_count} claims")
            except Exception as e:
                errors += 1
                print(f"  Error: {e}")

    await asyncio.gather(*[
        _process_one(p, i) for i, p in enumerate(to_process)
    ])

    print(f"\nDone. Processed: {processed}, Skipped: {skipped}, Errors: {errors}")


async def _generate_with_fallback(
    pdf_url: str,
    prompt: str,
    paper_id: str,
) -> str:
    """Try URL first, fall back to downloading the PDF locally."""
    try:
        return await generate_with_pdf_url(
            pdf_url=pdf_url, prompt=prompt, model=MODEL, temperature=0,
        )
    except Exception as e:
        err = str(e).lower()
        url_errors = ("invalid_argument", "400", "bad request", "403", "forbidden", "url", "fetch")
        if not any(tok in err for tok in url_errors):
            raise
        print(f"  {paper_id}: URL failed ({type(e).__name__}), downloading PDF locally...")

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        resp = await client.get(pdf_url)
        resp.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(resp.content)
        tmp_path = f.name

    try:
        return await generate_with_pdf(
            pdf_path=tmp_path, prompt=prompt, model=MODEL, temperature=0,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

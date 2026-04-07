"""Assess comments using a 3-prompt orchestration pipeline with Gemini context caching.

For each paper, uploads the PDF once and creates a context cache, then runs 3 prompts per source:
  1. comment_parser    — extract anchor, specification, justification, remedy
  2. claim_mapping     — map each comment to a claim, stance (supportive, critical, neutral), is_consequential flag
  3. critique_typing   — classify each comment as one of: validity, sufficiency, contribution, clarity, transparency
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import httpx

from src.db.queries import (
    get_paper,
    get_papers_with_claims,
    get_claims,
    get_comments,
    get_assessed_comment_ids,
    insert_assessment,
    delete_assessments,
)
from src.lib.gemini import (
    create_pdf_cache,
    create_pdf_cache_from_url,
    create_text_cache,
    generate_with_cached_context,
    delete_cache,
)
from src.lib.json_repair import parse_json_array
from src.processor.types import SOURCES, VALID_STANCES, VALID_CRITIQUE_TYPES

PROMPT_DIR = Path(__file__).parent.parent / "prompts"
MODEL = "gemini-3-pro-preview"
CONCURRENCY = 15


def _format_comments(comments: list[dict]) -> str:
    if not comments:
        return "None."
    return "\n\n".join(f"{i + 1}. {c['content']}" for i, c in enumerate(comments))


async def _run_prompt(
    cache_name: str,
    prompt_file: str,
    user_message: str,
    retries: int = 2,
) -> list[dict]:
    """Run a prompt against the cached PDF context and parse JSON array output.

    Retries on empty results or parse failures.
    """
    for attempt in range(1, retries + 1):
        try:
            raw = await generate_with_cached_context(
                cache_name=cache_name,
                prompt=user_message,
                model=MODEL,
                temperature=0,
            )
            results = parse_json_array(raw)

            if not results:
                raise ValueError(f"{prompt_file}: model returned no results")

            return results
        except Exception as e:
            if attempt < retries:
                print(f"  Warning: {prompt_file} attempt {attempt} failed, retrying...")
                await asyncio.sleep(1)
            else:
                raise


async def _step1_comment_parser(
    cache_name: str,
    comments: list[dict],
) -> list[dict]:
    """Step 1: Extract per-comment structure (anchor, specification, justification, remedy)."""
    prompt_text = (PROMPT_DIR / "comment_parser.md").read_text()
    user_message = f"""{prompt_text}

### Reviewer Comments
{_format_comments(comments)}

Return ONLY valid JSON."""
    return await _run_prompt(cache_name, "comment_parser", user_message)


async def _step2_claim_mapping(
    cache_name: str,
    comments: list[dict],
    claims: list[dict],
) -> list[dict]:
    """Step 2: Map each comment to a claim, stance, is_consequential."""
    prompt_text = (PROMPT_DIR / "claim_mapping.md").read_text()
    claims_json = [{"id": c["id"], "summary": c["summary"]} for c in claims]

    user_message = f"""{prompt_text}

### Reviewer Comments
{_format_comments(comments)}

### Claims
{json.dumps(claims_json, indent=2)}

Return ONLY valid JSON."""
    return await _run_prompt(cache_name, "claim_mapping", user_message)


async def _step3_critique_typing(
    cache_name: str,
    comments: list[dict],
) -> list[dict]:
    """Step 3: Classify each comment's critique type."""
    prompt_text = (PROMPT_DIR / "critique_typing.md").read_text()

    user_message = f"""{prompt_text}

### Reviewer Comments
{_format_comments(comments)}

Return ONLY valid JSON."""
    return await _run_prompt(cache_name, "critique_typing", user_message)


async def _create_pdf_cache(
    paper_id: str,
    pdf_url: str,
    prompt_text: str,
    model: str | None = None,
) -> str:
    """Create a Gemini context cache for a paper PDF.

    Tries three approaches in order:
    1. URL-based cache (Gemini fetches the PDF server-side — bypasses 403s)
    2. Direct download with browser headers → local upload
    3. Direct download without headers → local upload
    """
    import time as _time
    _model = model or MODEL

    # Attempt 1: URL-based cache (Gemini fetches server-side)
    try:
        print(f"  {paper_id}: Creating cache from URL...")
        t0 = _time.time()
        cache_name = await create_pdf_cache_from_url(pdf_url, prompt_text, _model)
        print(f"  {paper_id}: Cache created from URL in {_time.time() - t0:.1f}s")
        return cache_name
    except Exception as e:
        print(f"  {paper_id}: URL cache failed ({type(e).__name__}), trying download...")

    # Attempt 2: Download PDF
    try:
        t0 = _time.time()
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            resp = await client.get(pdf_url)
            resp.raise_for_status()
        print(f"  {paper_id}: PDF downloaded in {_time.time() - t0:.1f}s ({len(resp.content)} bytes)")
    except Exception as e:
        # Attempt 3: Download without custom headers (some servers reject spoofed UA)
        print(f"  {paper_id}: Download with headers failed, trying plain...")
        t0 = _time.time()
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            resp = await client.get(pdf_url)
            resp.raise_for_status()
        print(f"  {paper_id}: PDF downloaded in {_time.time() - t0:.1f}s ({len(resp.content)} bytes)")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(resp.content)
        tmp_path = f.name

    try:
        print(f"  {paper_id}: Uploading to Gemini cache...")
        t1 = _time.time()
        cache_name = await create_pdf_cache(tmp_path, prompt_text, _model)
        print(f"  {paper_id}: Cache created in {_time.time() - t1:.1f}s")
        return cache_name
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def assess_comments_for_venue(
    venue_id: str,
    limit: int | None = None,
    force: bool = False,
    source_filter: str | None = None,
) -> None:
    """Assess comments for all papers in a venue that have claims."""
    paper_ids = get_papers_with_claims()
    # Filter to the requested venue
    if venue_id:
        from src.db.queries import get_papers
        venue_paper_ids = {p["id"] for p in get_papers(venue_id=venue_id)}
        paper_ids = [pid for pid in paper_ids if pid in venue_paper_ids]
    if limit:
        paper_ids = paper_ids[:limit]

    sources_to_process = [source_filter] if source_filter else SOURCES

    print(f"Found {len(paper_ids)} papers with claims")
    print(f"Processing sources: {', '.join(sources_to_process)}")

    # Pre-filter: skip papers where every comment is already assessed
    if not force:
        from src.db.queries import get_fully_assessed_paper_ids
        fully_done = get_fully_assessed_paper_ids(sources_to_process)
        before = len(paper_ids)
        paper_ids = [pid for pid in paper_ids if pid not in fully_done]
        pre_skipped = before - len(paper_ids)
        print(f"Pre-filtered: {pre_skipped} fully assessed, {len(paper_ids)} remaining")
    processed = 0
    skipped = 0
    errors = 0
    total_by_source: dict[str, int] = {}

    # System prompt for the cache (shared across all 3 prompts)
    system_prompt = "You are an expert scientific reviewer analyzing a paper and its peer reviews."

    sem = asyncio.Semaphore(CONCURRENCY)

    async def _process_one(paper_id: str, idx: int) -> None:
        nonlocal processed, skipped, errors

        async with sem:
            claims = get_claims(paper_id)
            if not claims:
                skipped += 1
                return

            # Collect comments per source
            unprocessed_by_source: dict[str, list[dict]] = {}
            sources_needed: list[str] = []

            for source in sources_to_process:
                all_comments = get_comments(paper_id, source)
                if not all_comments:
                    continue

                if force:
                    unprocessed_by_source[source] = all_comments
                    sources_needed.append(source)
                else:
                    assessed_ids = get_assessed_comment_ids(paper_id, source)
                    unprocessed = [c for c in all_comments if c["id"] not in assessed_ids]
                    if not unprocessed:
                        continue
                    unprocessed_by_source[source] = unprocessed
                    sources_needed.append(source)

            if not sources_needed:
                skipped += 1
                return

            paper = get_paper(paper_id)
            pdf_url = paper.get("pdf_url") if paper else None

            print(f"\n[{idx + 1}/{len(paper_ids)}] {paper_id} "
                  f"({len(claims)} claims, sources: {', '.join(sources_needed)})")

            # Create context cache (PDF or manuscript text)
            try:
                if pdf_url:
                    cache_name = await _create_pdf_cache(paper_id, pdf_url, system_prompt)
                else:
                    manuscript_text = paper.get("manuscript_text") if paper else None
                    if not manuscript_text:
                        print(f"  {paper_id}: No PDF or manuscript text, skipping")
                        skipped += 1
                        return
                    print(f"  {paper_id}: Creating cache from manuscript text...")
                    cache_name = await create_text_cache(
                        manuscript_text, system_prompt
                    )
            except Exception as e:
                print(f"  Cache creation failed: {e}")
                errors += 1
                return

            try:
                if force and not source_filter:
                    delete_assessments(paper_id)

                # Process each source
                async def _assess_source(source: str) -> None:
                    nonlocal errors
                    comments = unprocessed_by_source[source]
                    import time as _time
                    print(f"  {source}: assessing {len(comments)} comments (3 prompts)...")
                    t_src = _time.time()

                    try:
                        # Run steps 1, 2, 3 sequentially to limit concurrent Gemini connections
                        parsed_results = await _step1_comment_parser(cache_name, comments)
                        mapping_results = await _step2_claim_mapping(cache_name, comments, claims)
                        typing_results = await _step3_critique_typing(cache_name, comments)

                        print(f"  {source}: got results in {_time.time() - t_src:.1f}s")

                        if force:
                            delete_assessments(paper_id, source)

                        # Index results by comment_index (validated by _run_prompt)
                        parsed_by_idx = {a["comment_index"]: a for a in parsed_results if "comment_index" in a}
                        mapping_by_idx = {a["comment_index"]: a for a in mapping_results if "comment_index" in a}
                        typing_by_idx = {a["comment_index"]: a for a in typing_results if "comment_index" in a}

                        claim_ids = {c["id"] for c in claims}
                        inserted = 0

                        for ci in range(1, len(comments) + 1):
                            comment = comments[ci - 1]
                            parsed = parsed_by_idx.get(ci, {})
                            mapped = mapping_by_idx.get(ci, {})
                            typed = typing_by_idx.get(ci, {})

                            # Validate claim_id
                            claim_id = mapped.get("claim_id")
                            if claim_id and claim_id not in claim_ids:
                                claim_id = None

                            # Validate stance
                            stance = mapped.get("stance")
                            if stance not in VALID_STANCES:
                                stance = None

                            # is_consequential only if mapped to a claim
                            is_consequential = None
                            if claim_id:
                                is_consequential = bool(mapped.get("is_consequential", False))

                            # Validate critique_type
                            critique_type = typed.get("critique_type")
                            if critique_type not in VALID_CRITIQUE_TYPES:
                                critique_type = None

                            insert_assessment(
                                paper_id=paper_id,
                                comment_id=comment["id"],
                                source=source,
                                claim_id=claim_id,
                                stance=stance,
                                is_consequential=is_consequential,
                                anchor=parsed.get("anchor"),
                                specification=parsed.get("specification"),
                                justification=parsed.get("justification"),
                                remedy=parsed.get("remedy"),
                                critique_type=critique_type,
                            )
                            inserted += 1

                        total_by_source[source] = total_by_source.get(source, 0) + inserted
                        print(f"  {source}: {inserted}/{len(comments)} saved")

                    except Exception as e:
                        print(f"  {source}: Error - {type(e).__name__}: {e!r}")
                        errors += 1

                await asyncio.gather(*[_assess_source(s) for s in sources_needed])
            finally:
                await delete_cache(cache_name)

            processed += 1

    await asyncio.gather(*[
        _process_one(pid, i) for i, pid in enumerate(paper_ids)
    ])

    print(f"\nDone. Processed: {processed}, Skipped: {skipped}, Errors: {errors}")
    for source, count in total_by_source.items():
        print(f"  {source}: {count} assessments")

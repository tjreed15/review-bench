"""Gemini 3 Pro generator.

Uses Gemini's API to generate reviews for a paper with prompts/control_review.md.
Falls back to downloading and uploading the PDF if Gemini rejects the URL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx

from src.db.queries import insert_comments_batch, delete_comments, count_comments, get_paper
from src.lib.gemini import generate_with_pdf_url, generate_with_pdf, generate_with_text
from src.lib.json_repair import parse_json_array

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
PROMPT_FILE = PROMPTS_DIR / "control_review.md"
MODEL = "gemini-3-pro-preview"


class ControlGeminiGenerator:
    source = "gemini-3-pro"

    async def generate(self, paper_id: str, force: bool = False, **kwargs) -> int:
        """Generate Gemini 3 Pro review with minimal prompt."""
        if not force and count_comments(paper_id, "gemini-3-pro") > 0:
            print(f"  {paper_id}: Gemini 3 Pro comments already exist, skipping (use --force)")
            return 0

        paper = get_paper(paper_id)
        if not paper:
            return 0

        if force:
            delete_comments(paper_id, "gemini-3-pro")

        prompt = PROMPT_FILE.read_text()

        pdf_url = paper.get("pdf_url")
        if pdf_url:
            raw_output = await self._generate_with_fallback(
                pdf_url=pdf_url,
                prompt=prompt,
                paper_id=paper_id,
            )
        else:
            manuscript_text = paper.get("manuscript_text")
            if not manuscript_text:
                print(f"  {paper_id}: No PDF URL or manuscript text, skipping")
                return 0
            raw_output = await generate_with_text(
                text=manuscript_text,
                prompt=prompt,
                model=MODEL,
                temperature=0,
            )

        comments = parse_json_array(raw_output)
        if not isinstance(comments, list):
            raise ValueError(f"Expected JSON array, got {type(comments)}")

        batch = []
        for comment in comments:
            text = comment if isinstance(comment, str) else str(comment)
            if len(text.strip()) < 20:
                continue
            batch.append({
                "id": f"{paper_id}:gemini-3-pro-{len(batch) + 1}",
                "paper_id": paper_id,
                "source": "gemini-3-pro",
                "content": text.strip(),
            })

        insert_comments_batch(batch)
        return len(batch)

    async def _generate_with_fallback(self, pdf_url: str, prompt: str, paper_id: str) -> str:
        """Try URL first, fall back to downloading the PDF locally."""
        try:
            return await generate_with_pdf_url(
                pdf_url=pdf_url, prompt=prompt, model=MODEL, temperature=0,
            )
        except Exception as e:
            if "INVALID_ARGUMENT" not in str(e):
                raise
            print(f"  {paper_id}: URL failed, downloading PDF locally...")

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

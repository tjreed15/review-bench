"""GPT-5.2 generator.

Uses OpenAI's API to generate reviews for a paper with prompts/control_review.md.
Falls back through base64 upload, URL reference, and page images for PDF delivery.
"""

from __future__ import annotations

from pathlib import Path

from src.db.queries import insert_comments_batch, delete_comments, count_comments, get_paper
from src.lib.openai import (
    assess_with_pdf,
    assess_with_pdf_url,
    assess_with_pdf_images,
    assess_with_text,
    download_pdf,
)
from src.lib.json_repair import parse_json_array

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
PROMPT_FILE = PROMPTS_DIR / "control_review.md"
MODEL = "gpt-5.2"


class ControlGPTGenerator:
    source = "gpt-5.2"

    async def generate(self, paper_id: str, force: bool = False, **kwargs) -> int:
        """Generate GPT-5.2 review with minimal prompt."""
        if not force and count_comments(paper_id, "gpt-5.2") > 0:
            print(f"  {paper_id}: GPT-5.2 comments already exist, skipping (use --force)")
            return 0

        paper = get_paper(paper_id)
        if not paper:
            return 0

        if force:
            delete_comments(paper_id, "gpt-5.2")

        prompt = PROMPT_FILE.read_text()

        pdf_url = paper.get("pdf_url")
        raw_output = None

        if pdf_url:
            pdf_bytes = await download_pdf(pdf_url)

            # Try 1: base64 upload
            try:
                raw_output = await assess_with_pdf(
                    pdf_bytes=pdf_bytes,
                    system_prompt="",
                    user_prompt=prompt,
                    model=MODEL,
                    temperature=0,
                )
            except Exception as e:
                print(f"  {paper_id}: base64 failed ({type(e).__name__}), trying URL fallback...")

            # Try 2: Responses API with PDF URL
            if raw_output is None:
                try:
                    raw_output = await assess_with_pdf_url(
                        pdf_url=pdf_url,
                        system_prompt="",
                        user_prompt=prompt,
                        model=MODEL,
                        temperature=0,
                    )
                except Exception as e:
                    print(f"  {paper_id}: URL fallback failed ({type(e).__name__}), trying image fallback...")

            # Try 3: render pages as images
            if raw_output is None:
                raw_output = await assess_with_pdf_images(
                    pdf_bytes=pdf_bytes,
                    system_prompt="",
                    user_prompt=prompt,
                    model=MODEL,
                    temperature=0,
                )
        else:
            manuscript_text = paper.get("manuscript_text")
            if not manuscript_text:
                print(f"  {paper_id}: No PDF URL or manuscript text, skipping")
                return 0
            raw_output = await assess_with_text(
                text=manuscript_text,
                system_prompt="",
                user_prompt=prompt,
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
                "id": f"{paper_id}:gpt-5.2-{len(batch) + 1}",
                "paper_id": paper_id,
                "source": "gpt-5.2",
                "content": text.strip(),
            })

        insert_comments_batch(batch)
        return len(batch)

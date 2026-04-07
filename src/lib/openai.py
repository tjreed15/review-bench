"""OpenAI API client wrapper for cross-model evaluation."""

from __future__ import annotations

import base64
import os

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

_client: AsyncOpenAI | None = None

DEFAULT_MODEL = "gpt-5.2"


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable not set")
        _client = AsyncOpenAI(api_key=api_key)
    return _client


async def assess_with_text(
    text: str,
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
    max_tokens: int = 65536,
) -> str:
    """Send an assessment request with manuscript text (no PDF) to OpenAI."""
    client = get_client()

    response = await client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"<manuscript>\n{text}\n</manuscript>\n\n{user_prompt}",
            },
        ],
    )
    return response.choices[0].message.content or ""


async def download_pdf(pdf_url: str) -> bytes:
    """Download a PDF from a URL and return raw bytes."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        resp = await client.get(pdf_url)
        resp.raise_for_status()
    return resp.content


async def assess_with_pdf(
    pdf_bytes: bytes,
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
    max_tokens: int = 65536,
) -> str:
    """Send an assessment request with a PDF attachment to OpenAI.

    Uses base64-encoded PDF as a file content part in the messages API.
    Returns the raw text response.
    """
    client = get_client()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")

    response = await client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "file",
                        "file": {
                            "filename": "paper.pdf",
                            "file_data": f"data:application/pdf;base64,{pdf_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": user_prompt,
                    },
                ],
            },
        ],
    )
    return response.choices[0].message.content or ""


async def assess_with_pdf_url(
    pdf_url: str,
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
    max_tokens: int = 65536,
) -> str:
    """Send an assessment request with a PDF URL to OpenAI Responses API.

    Uses file_url instead of base64, bypassing the upload size limit.
    Returns the raw text response.
    """
    client = get_client()

    input_messages = []
    if system_prompt:
        input_messages.append({"role": "system", "content": system_prompt})
    input_messages.append({
        "role": "user",
        "content": [
            {
                "type": "input_file",
                "file_url": pdf_url,
            },
            {
                "type": "input_text",
                "text": user_prompt,
            },
        ],
    })

    response = await client.responses.create(
        model=model,
        temperature=temperature,
        max_output_tokens=max_tokens,
        input=input_messages,
    )
    return response.output_text or ""


async def assess_with_pdf_images(
    pdf_bytes: bytes,
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
    max_tokens: int = 65536,
) -> str:
    """Send a PDF as page images to OpenAI, bypassing text token limits.

    Renders each page as a PNG with PyMuPDF and sends as image_url parts.
    Each image costs ~1k tokens regardless of text content.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    # Cap at 50 pages to stay within API limits; skip trailing appendix pages
    max_pages = min(len(doc), 50)
    image_parts = []
    for i in range(max_pages):
        page = doc[i]
        pix = page.get_pixmap(dpi=150)
        png_bytes = pix.tobytes("png")
        img_b64 = base64.standard_b64encode(png_bytes).decode("ascii")
        image_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high",
            },
        })
    doc.close()

    client = get_client()
    content = image_parts + [{"type": "text", "text": user_prompt}]

    response = await client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    )
    return response.choices[0].message.content or ""

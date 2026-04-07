"""Gemini API client wrapper using google-genai."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

_client: genai.Client | None = None

DEFAULT_MODEL = "gemini-3-pro-preview"


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable not set")
        _client = genai.Client(api_key=api_key)
    return _client


async def generate_with_pdf(
    pdf_path: str | Path,
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
    max_tokens: int = 65536,
) -> str:
    """Generate text with a PDF file as context."""
    client = get_client()
    pdf_bytes = Path(pdf_path).read_bytes()

    response = await client.aio.models.generate_content(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=prompt),
                    types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                ],
            ),
        ],
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


async def generate_with_pdf_url(
    pdf_url: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
    max_tokens: int = 65536,
) -> str:
    """Generate text with a PDF URL as context (no download needed)."""
    client = get_client()

    response = await client.aio.models.generate_content(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=prompt),
                    types.Part.from_uri(file_uri=pdf_url, mime_type="application/pdf"),
                ],
            ),
        ],
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


async def generate_with_cached_context(
    cache_name: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
    max_tokens: int = 65536,
    timeout: float = 300,
) -> str:
    """Generate text using a previously created context cache."""
    client = get_client()

    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                cached_content=cache_name,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        ),
        timeout=timeout,
    )
    return response.text or ""


async def create_pdf_cache(
    pdf_path: str | Path,
    system_prompt: str,
    model: str = DEFAULT_MODEL,
    ttl_seconds: int = 3600,
) -> str:
    """Create a context cache with a PDF file and system prompt. Returns cache name."""
    client = get_client()
    pdf_bytes = Path(pdf_path).read_bytes()

    cache = await client.aio.caches.create(
        model=model,
        config=types.CreateCachedContentConfig(
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                    ],
                ),
            ],
            system_instruction=system_prompt,
            ttl=f"{ttl_seconds}s",
        ),
    )
    return cache.name


async def create_pdf_cache_from_url(
    pdf_url: str,
    system_prompt: str,
    model: str = DEFAULT_MODEL,
    ttl_seconds: int = 3600,
) -> str:
    """Create a context cache with a PDF URL and system prompt. Returns cache name."""
    client = get_client()

    cache = await client.aio.caches.create(
        model=model,
        config=types.CreateCachedContentConfig(
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_uri(file_uri=pdf_url, mime_type="application/pdf"),
                    ],
                ),
            ],
            system_instruction=system_prompt,
            ttl=f"{ttl_seconds}s",
        ),
    )
    return cache.name


async def generate_with_text(
    text: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
    max_tokens: int = 65536,
) -> str:
    """Generate text with a long text document as context (instead of PDF)."""
    client = get_client()

    response = await client.aio.models.generate_content(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=f"<manuscript>\n{text}\n</manuscript>"),
                    types.Part.from_text(text=prompt),
                ],
            ),
        ],
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


async def create_text_cache(
    text: str,
    system_prompt: str,
    model: str = DEFAULT_MODEL,
    ttl_seconds: int = 3600,
) -> str:
    """Create a context cache with a text document and system prompt. Returns cache name."""
    client = get_client()

    cache = await client.aio.caches.create(
        model=model,
        config=types.CreateCachedContentConfig(
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=f"<manuscript>\n{text}\n</manuscript>"),
                    ],
                ),
            ],
            system_instruction=system_prompt,
            ttl=f"{ttl_seconds}s",
        ),
    )
    return cache.name


async def delete_cache(cache_name: str) -> None:
    """Delete a context cache."""
    client = get_client()
    try:
        await client.aio.caches.delete(name=cache_name)
    except Exception:
        pass  # Cache may have already expired

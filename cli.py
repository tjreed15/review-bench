"""CLI entry point for the review-bench suite."""

from __future__ import annotations

import asyncio

import click


@click.group()
def cli():
    """Review-bench suite for AI peer review evaluation."""
    pass


# ---------------------------------------------------------------------------
# Database commands
# ---------------------------------------------------------------------------

@cli.group()
def db():
    """Database management commands."""
    pass


@db.command()
def migrate():
    """Create all database tables."""
    from src.db.schema import migrate
    migrate()


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--venue", required=True, help="Venue ID (e.g. iclr-2025)")
@click.option("--limit", default=50, help="Max papers to fetch")
def fetch(venue: str, limit: int):
    """Fetch raw data from a venue into raw_venue_data."""
    from src.fetchers.registry import get_fetcher
    fetcher = get_fetcher(venue)
    count = asyncio.run(fetcher.fetch(limit=limit))
    click.echo(f"\nFetched {count} papers.")


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--venue", required=True, help="Venue ID (e.g. iclr-2025)")
@click.option("--limit", default=None, type=int, help="Max papers to parse")
def parse(venue: str, limit: int | None):
    """Parse raw venue data into papers + comments."""
    from src.parsers.registry import get_parser
    parser = get_parser(venue)
    count = parser.parse(limit=limit)
    click.echo(f"\nParsed {count} papers.")


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--venue", required=True, help="Venue ID (e.g. iclr-2025)")
@click.option("--source", default="all", type=click.Choice(["all", "r3", "gemini-3-pro", "gpt-5.2"]),
              help="Which source to generate")
@click.option("--limit", default=None, type=int, help="Max papers to process")
@click.option("--concurrency", default=10, type=int, help="Max concurrent API calls")
@click.option("--force", is_flag=True, help="Re-generate existing comments")
def generate(venue: str, source: str, limit: int | None, concurrency: int, force: bool):
    """Generate AI reviews (R3 + Gemini 3 Pro + GPT-5.2) for papers in a venue."""
    from src.db.queries import get_papers
    from src.generators.r3 import R3Generator
    from src.generators.control_gemini import ControlGeminiGenerator
    from src.generators.control_gpt import ControlGPTGenerator

    papers = get_papers(venue_id=venue, limit=limit)
    if not papers:
        click.echo("No papers found for this venue. Run fetch + parse first.")
        return

    generators = []
    if source in ("all", "r3"):
        generators.append(R3Generator())
    if source in ("all", "gemini-3-pro"):
        generators.append(ControlGeminiGenerator())
    if source in ("all", "gpt-5.2"):
        generators.append(ControlGPTGenerator())

    click.echo(f"Generating for {len(papers)} papers (concurrency={concurrency})...")

    async def process_paper(sem, paper, gen, progress):
        paper_id = paper["id"]
        async with sem:
            try:
                count = await gen.generate(paper_id, force=force)
                progress[0] += 1
                title = paper.get("title", paper_id)[:60]
                click.echo(f"[{progress[0]}/{len(papers)}] {paper_id}: {title}... ({count} comments)")
                return count
            except Exception as e:
                progress[0] += 1
                click.echo(f"[{progress[0]}/{len(papers)}] {paper_id}: Error - {e}")
                return 0

    async def run():
        sem = asyncio.Semaphore(concurrency)
        for gen in generators:
            click.echo(f"\n=== Generating {gen.source} reviews ===")
            progress = [0]
            tasks = [process_paper(sem, paper, gen, progress) for paper in papers]
            results = await asyncio.gather(*tasks)
            total = sum(results)
            click.echo(f"\n{gen.source}: {total} comments across {len(papers)} papers")

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--venue", required=True, help="Venue ID (e.g. iclr-2025)")
@click.option("--limit", default=None, type=int, help="Max papers to process")
@click.option("--force", is_flag=True, help="Re-process existing data")
@click.option("--source", default=None, help="Filter to specific source for assessment")
def process(venue: str, limit: int | None, force: bool, source: str | None):
    """Run full benchmark: extract claims, assess comments, score."""
    from src.processor.extract_claims import extract_claims_for_venue
    from src.processor.assess_comments import assess_comments_for_venue
    from src.processor.score import score_all_venues

    async def run():
        click.echo("=== Step 1: Extract claims ===")
        await extract_claims_for_venue(venue, limit=limit, force=force)

        click.echo("\n=== Step 2: Assess comments ===")
        await assess_comments_for_venue(venue, limit=limit, force=force, source_filter=source)

        click.echo("\n=== Step 3: Score ===")
        score_all_venues()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Run (all steps)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--venue", required=True, help="Venue ID (e.g. iclr-2025)")
@click.option("--limit", default=50, help="Max papers")
@click.option("--force", is_flag=True, help="Re-process everything")
def run(venue: str, limit: int, force: bool):
    """Run the full pipeline: fetch → parse → generate → process."""
    from src.fetchers.registry import get_fetcher
    from src.parsers.registry import get_parser
    from src.db.queries import get_papers
    from src.generators.r3 import R3Generator
    from src.generators.control_gemini import ControlGeminiGenerator
    from src.generators.control_gpt import ControlGPTGenerator
    from src.processor.extract_claims import extract_claims_for_venue
    from src.processor.assess_comments import assess_comments_for_venue
    from src.processor.score import score_all_venues

    async def pipeline():
        click.echo("=== Step 1: Fetch raw data ===")
        fetcher = get_fetcher(venue)
        await fetcher.fetch(limit=limit)

        click.echo("\n=== Step 2: Parse into papers + comments ===")
        parser = get_parser(venue)
        parser.parse(limit=limit)

        click.echo("\n=== Step 3: Generate AI reviews ===")
        papers = get_papers(venue_id=venue, limit=limit)
        generators = [R3Generator(), ControlGeminiGenerator(), ControlGPTGenerator()]
        sem = asyncio.Semaphore(10)
        for gen in generators:
            click.echo(f"\n--- Generating {gen.source} reviews ---")
            async def _gen(paper, g=gen):
                async with sem:
                    try:
                        return await g.generate(paper["id"], force=force)
                    except Exception as e:
                        click.echo(f"  {paper['id']} {g.source}: Error - {e}")
                        return 0
            results = await asyncio.gather(*[_gen(p) for p in papers])
            click.echo(f"  {gen.source}: {sum(results)} comments")

        click.echo("\n=== Step 4: Extract claims ===")
        await extract_claims_for_venue(venue, limit=limit, force=force)

        click.echo("\n=== Step 5: Assess comments ===")
        await assess_comments_for_venue(venue, limit=limit, force=force)

        click.echo("\n=== Step 6: Score ===")
        score_all_venues()

    asyncio.run(pipeline())


if __name__ == "__main__":
    cli()

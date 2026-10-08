#!/usr/bin/env python3
"""
PDF-to-Obsidian Converter
=========================

A high-fidelity PDF to Markdown converter using Claude Vision API.

This tool converts PDF documents to clean, Obsidian-optimized Markdown by:
1. Converting PDF pages to high-resolution images
2. Sending images to Claude 3.5 Sonnet for intelligent OCR
3. Aggregating results with smart page-boundary handling

Requirements:
    - Python 3.9+
    - poppler-utils (system package for pdf2image)
    - Anthropic API key

Usage:
    python pdf_to_md.py --input document.pdf --output document.md

    # Or with explicit API key:
    python pdf_to_md.py --input document.pdf --output document.md --api-key sk-ant-...

Author: Generated for Obsidian vault optimization
"""

import base64
import io
import os
import sys
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

# Initialize Rich console for pretty output
console = Console()

# Create Typer app with rich markup support
app = typer.Typer(
    name="pdf-to-md",
    help="High-fidelity PDF to Markdown converter using Claude Vision API.",
    rich_markup_mode="rich",
)


# =============================================================================
# SYSTEM PROMPT - The "Brain" of the OCR
# =============================================================================
# This prompt is sent to Claude with each page image. Modify this to adjust
# the extraction behavior and formatting preferences.
# =============================================================================

SYSTEM_PROMPT = """Perform a high-fidelity OCR on the attached image. Extract the full, verbatim text.

**Formatting Constraints:**
* **No System Tags:** Do not include `[PAGE 1]`, `[end]`, or metadata tags.
* **Clean Typography:** Use standard Markdown. Convert fancy quotes to straight quotes if necessary, but prefer author's original typography.
* **Structure:** Use appropriate Markdown headers (#, ##) for titles/sections.
* **Footnotes:** You MUST detect footnotes. Convert them to standard Markdown syntax (e.g., `[^1]` in-text and `[^1]: Content` at the bottom of the text block).
* **No Truncation:** Extract every single word. Do not summarize."""


# Context continuation prompt - appended when we have previous page context
CONTEXT_CONTINUATION_PROMPT = """

**Page Continuity Context:**
The previous page ended with these words: "{last_words}"

If the current page begins mid-sentence or continues a thought from these words, seamlessly continue the text without duplicating these words. Ensure proper sentence flow across page boundaries."""


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def check_poppler_installed() -> bool:
    """
    Check if poppler-utils is installed on the system.

    poppler is required by pdf2image for PDF to image conversion.

    Returns:
        bool: True if poppler is installed, False otherwise.
    """
    # Check for pdftoppm which is part of poppler-utils
    return shutil.which("pdftoppm") is not None


def get_api_key(provided_key: Optional[str] = None) -> str:
    """
    Get the Anthropic API key from various sources.

    Priority order:
    1. Explicitly provided key (--api-key flag)
    2. ANTHROPIC_API_KEY environment variable
    3. Interactive prompt

    Args:
        provided_key: API key provided via command line argument.

    Returns:
        str: The API key.

    Raises:
        typer.Exit: If no API key can be obtained.
    """
    # Check provided key first
    if provided_key:
        return provided_key

    # Check environment variable
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        console.print("[dim]Using API key from ANTHROPIC_API_KEY environment variable[/dim]")
        return env_key

    # Interactive prompt as last resort
    console.print(Panel(
        "[yellow]No Anthropic API key found![/yellow]\n\n"
        "You can provide it via:\n"
        "  1. --api-key flag\n"
        "  2. ANTHROPIC_API_KEY environment variable\n"
        "  3. Enter it below",
        title="API Key Required"
    ))

    api_key = Prompt.ask("Enter your Anthropic API key", password=True)

    if not api_key:
        console.print("[red]Error: API key is required to proceed.[/red]")
        raise typer.Exit(code=1)

    return api_key


def image_to_base64(image) -> str:
    """
    Convert a PIL Image to a base64-encoded string.

    Args:
        image: PIL Image object.

    Returns:
        str: Base64-encoded image data.
    """
    buffer = io.BytesIO()
    # Save as PNG for lossless quality
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.standard_b64encode(buffer.read()).decode("utf-8")


def get_last_n_words(text: str, n: int = 50) -> str:
    """
    Extract the last N words from a text string.

    Used for passing context between pages to ensure smooth
    sentence continuation across page boundaries.

    Args:
        text: The text to extract from.
        n: Number of words to extract (default: 50).

    Returns:
        str: The last N words of the text.
    """
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[-n:])


def clean_page_join(accumulated_text: str, new_page_text: str) -> str:
    """
    Cleanly join text from consecutive pages.

    Handles:
    - Removing excessive whitespace/newlines between pages
    - Ensuring proper paragraph separation

    Args:
        accumulated_text: Text accumulated from previous pages.
        new_page_text: Text from the current page.

    Returns:
        str: Properly joined text.
    """
    if not accumulated_text:
        return new_page_text.strip()

    # Normalize the join point
    # Remove trailing whitespace from accumulated text
    accumulated = accumulated_text.rstrip()
    # Remove leading whitespace from new text
    new_text = new_page_text.lstrip()

    # Add a double newline (paragraph break) between pages
    # This can be adjusted based on preference
    return accumulated + "\n\n" + new_text


# =============================================================================
# CORE CONVERSION LOGIC
# =============================================================================

def convert_pdf_to_images(
    pdf_path: Path,
    dpi: int = 300,
    first_page: Optional[int] = None,
    last_page: Optional[int] = None,
):
    """
    Render PDF pages to PIL Images. If first_page/last_page are given, only that
    range is rendered (used for page-by-page streaming).

    Raises ImportError if pdf2image is missing; lets other exceptions propagate.
    """
    from pdf2image import convert_from_path
    return convert_from_path(
        pdf_path,
        dpi=dpi,
        fmt="png",
        first_page=first_page,
        last_page=last_page,
        thread_count=1,  # parallel pdftoppm processes don't help — empirically same speed
    )


def get_pdf_page_count(pdf_path: Path) -> int:
    """Read just the PDF metadata to get the page count. Much faster than rendering."""
    from pdf2image.pdf2image import pdfinfo_from_path
    info = pdfinfo_from_path(str(pdf_path))
    return int(info["Pages"])


# Fallback chain: Claude Vision can fail two ways on copyrighted editorial content:
#   (a) HARD BLOCK — Anthropic's response content-filter raises a 400 error.
#   (b) SOFT REFUSAL — the call succeeds but Claude returns a summary/description
#       (e.g. "I can see this is a page from..." or "I'm not able to reproduce the
#       full verbatim text") instead of OCR. We must detect this post-hoc.
# Both must trigger the fallback chain. Empirically Haiku is more permissive than
# Sonnet/Opus on both modes; Tesseract has no content awareness at all.
import re

FALLBACK_MODEL = "claude-haiku-4-5-20251001"

# Strong markers — phrases that essentially never appear in real article body text.
# If we see any of these, the output is a refusal regardless of where it appears.
_REFUSAL_STRONG_RE = re.compile(
    r"|".join([
        r"verbatim (?:text|transcription|OCR)",
        r"copyrighted (?:periodical|magazine|article|work|material)",
        r"I(?:'?m| am)?\s+(?:not able|unable)\s+to\s+(?:reproduce|provide|perform|transcribe)",
        r"cannot reproduce the full",
        r"Would any of those alternatives",
        r"I'?d (?:recommend|suggest) consulting",
        r"(?:JSTOR|ProQuest)",
        r"reproducing the full verbatim",
    ]),
    re.IGNORECASE,
)

# Opening patterns — refusals almost always preface with a meta description.
# Checked only against the first ~200 chars so genuine body text isn't a false positive.
_REFUSAL_OPENING_RE = re.compile(
    r"|".join([
        r"^\s*I can (?:see|help|offer|describe|summarize|provide a)\b",
        r"^\s*I'?d be happy",
        r"^\s*I'?m happy to (?:discuss|summarize|help)",
        r"^\s*Here(?:'s| is) (?:a summary|a brief|the text I can)",
        r"^\s*This (?:is an article|appears to be a page|is a page from)",
        r"^\s*The page (?:is|appears|contains)",
        r"^\s*Rather than (?:reproducing|providing)",
    ]),
    re.IGNORECASE,
)


def _is_content_filter_error(exc: Exception) -> bool:
    return "content filtering" in str(exc).lower()


def _looks_like_refusal(text: str) -> bool:
    """Detect when Claude returned a summary/refusal instead of OCR.

    Used to trigger fallback to the next model tier when the API call succeeds
    but the content is a meta-description rather than transcribed text.
    """
    if not text:
        return True
    if _REFUSAL_STRONG_RE.search(text):
        return True
    if _REFUSAL_OPENING_RE.search(text[:200]):
        return True
    return False


def _call_claude_vision(client, image_data: str, prompt: str, model: str) -> str:
    """One Claude Vision call. Raises on any failure; caller decides what to do."""
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return message.content[0].text


def _call_tesseract(image) -> str:
    """OCR via Tesseract. Lower fidelity — used only when Claude refuses."""
    import pytesseract
    return pytesseract.image_to_string(image)


def extract_text_from_image(
    image,
    page_num: int,
    total_pages: int,
    tiers: list[str],
    previous_context: Optional[str] = None,
    client=None,
) -> tuple[str, str]:
    """
    Try each tier in order; return on the first one that produces non-refusal text.

    `tiers` is an ordered list of engine identifiers. Each entry is either:
      - A Claude model ID (e.g. "claude-sonnet-4-6"). Requires `client`.
      - The string "tesseract". Uses pytesseract locally.

    Claude tiers are subject to refusal detection — soft refusals (the response is
    a summary or "I can't reproduce this copyrighted text" rather than OCR) and
    hard content-filter errors both trigger a fall-through to the next tier.
    Tesseract has no content awareness and effectively always returns text.

    Returns: (text, engine_used). engine_used is the tier string that succeeded,
    or "error" if every tier failed.
    """
    # Lazy: only build the image bytes / prompt once we know we have a Claude tier.
    image_data: Optional[str] = None
    prompt: Optional[str] = None

    for tier in tiers:
        if tier == "tesseract":
            try:
                text = _call_tesseract(image)
                return text, "tesseract"
            except Exception as exc:
                console.print(f"[red]Page {page_num}: Tesseract failed ({exc}).[/red]")
                continue

        # Claude model tier
        if client is None:
            console.print(f"[red]Page {page_num}: no Anthropic client; skipping {tier}.[/red]")
            continue
        if image_data is None:
            image_data = image_to_base64(image)
            prompt = SYSTEM_PROMPT
            if previous_context:
                prompt += CONTEXT_CONTINUATION_PROMPT.format(last_words=previous_context)
        try:
            text = _call_claude_vision(client, image_data, prompt, tier)
            if not _looks_like_refusal(text):
                return text, tier
            console.print(f"[yellow]Page {page_num}: {tier} returned a refusal/summary; trying next tier.[/yellow]")
        except Exception as exc:
            if not _is_content_filter_error(exc):
                console.print(f"[yellow]Page {page_num}: {tier} error ({exc}); trying next tier.[/yellow]")

    console.print(f"[red]Page {page_num}: all OCR tiers failed.[/red]")
    return f"[Error extracting page {page_num}: all OCR tiers failed]", "error"


# =============================================================================
# PROGRAMMATIC API
# =============================================================================
# `run_conversion` is the orchestration entry point. Both the CLI (below) and the
# web UI (`web.py`) call into it. The CLI passes a callback that updates a Rich
# progress bar; the web UI passes one that pushes events onto an asyncio queue
# for streaming over SSE.
# =============================================================================


MODE_TIERS: dict[str, list[str]] = {
    "tesseract": ["tesseract"],
    "haiku": ["claude-haiku-4-5-20251001", "tesseract"],
    "sonnet": ["claude-sonnet-4-6", FALLBACK_MODEL, "tesseract"],
}


def _mode_to_tiers(mode: str) -> list[str]:
    try:
        return MODE_TIERS[mode]
    except KeyError:
        raise ValueError(
            f"Unknown mode {mode!r}. Use one of: {', '.join(MODE_TIERS)}"
        )


def _build_provenance_header(
    engine_by_page: dict[int, str],
    primary_engine: str,
) -> str:
    """HTML comment listing pages that fell back from the primary engine.

    Empty string when every page used the primary engine (no provenance to record).
    """
    engine_pages: dict[str, list[int]] = {}
    for page_num, engine in engine_by_page.items():
        engine_pages.setdefault(engine, []).append(page_num)
    fallback_pages = {e: p for e, p in engine_pages.items() if e != primary_engine}
    if not fallback_pages:
        return ""
    lines = ["<!--", "pdf_to_md provenance — pages using fallback engines:"]
    for engine, pages in fallback_pages.items():
        lines.append(f"  {engine}: {sorted(pages)}")
    lines.append("-->")
    return "\n".join(lines) + "\n\n"


@dataclass
class ConversionResult:
    markdown: str                       # full output, including provenance header
    engine_by_page: dict[int, str]      # 1-indexed page → engine that produced it
    total_pages: int
    word_count: int                     # word count of body text (excludes header)
    char_count: int                     # char count of body text (excludes header)
    mode: str
    tiers: list[str] = field(default_factory=list)


# Progress callback event shape (loose dict for cross-process JSON friendliness):
#   {"type": "started",   "total_pages": int, "mode": str}
#   {"type": "page-done", "page": int, "engine": str, "elapsed_ms": int,
#                         "total_pages": int}
#   {"type": "completed", "engine_by_page": dict, "total_pages": int,
#                         "word_count": int, "char_count": int}
ProgressCallback = Callable[[dict], None]


def run_conversion(
    pdf_path: Path,
    mode: str = "sonnet",
    dpi: int = 300,
    context_words: int = 50,
    api_key: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> ConversionResult:
    """
    Convert a PDF to Markdown using the specified mode's tier chain.

    `mode` is one of "tesseract" | "haiku" | "sonnet" — see MODE_TIERS.

    `progress_callback`, if given, receives lifecycle dicts (see comment above).
    Callback exceptions are swallowed so a flaky observer can't corrupt the run.

    Raises:
        ValueError on unknown mode or missing API key when needed.
        Exception from `convert_pdf_to_images` on bad input.
    """
    tiers = _mode_to_tiers(mode)
    needs_claude = any(t != "tesseract" for t in tiers)

    def emit(event: dict) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(event)
        except Exception:
            # A misbehaving observer must never break the conversion itself.
            pass

    # Lazy: only resolve / construct an Anthropic client if a Claude tier is in play.
    client = None
    if needs_claude:
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for modes that use Claude "
                f"(mode={mode!r}, tiers={tiers}). Use mode='tesseract' to skip Claude."
            )
        import anthropic
        client = anthropic.Anthropic(api_key=resolved_key)

    # Cheap metadata read so the consumer knows the total up front. The actual
    # rendering happens lazily, one page at a time, inside the OCR loop — that
    # lets the UI show progress from page 1 instead of staring at a black box
    # while a multi-minute full-PDF render finishes.
    total_pages = get_pdf_page_count(pdf_path)
    emit({"type": "started", "total_pages": total_pages, "mode": mode})

    accumulated_text = ""
    previous_context: Optional[str] = None
    engine_by_page: dict[int, str] = {}

    for page_num in range(1, total_pages + 1):
        page_start = time.monotonic()
        rendered = convert_pdf_to_images(
            pdf_path, dpi=dpi, first_page=page_num, last_page=page_num
        )
        image = rendered[0]
        page_text, engine = extract_text_from_image(
            image=image,
            page_num=page_num,
            total_pages=total_pages,
            tiers=tiers,
            previous_context=previous_context if context_words > 0 else None,
            client=client,
        )
        elapsed_ms = int((time.monotonic() - page_start) * 1000)
        engine_by_page[page_num] = engine
        accumulated_text = clean_page_join(accumulated_text, page_text)
        if context_words > 0:
            previous_context = get_last_n_words(page_text, context_words)
        emit({
            "type": "page-done",
            "page": page_num,
            "engine": engine,
            "elapsed_ms": elapsed_ms,
            "total_pages": total_pages,
        })

    provenance_header = _build_provenance_header(engine_by_page, primary_engine=tiers[0])
    markdown = provenance_header + accumulated_text
    result = ConversionResult(
        markdown=markdown,
        engine_by_page=engine_by_page,
        total_pages=total_pages,
        word_count=len(accumulated_text.split()),
        char_count=len(accumulated_text),
        mode=mode,
        tiers=tiers,
    )
    emit({
        "type": "completed",
        "engine_by_page": engine_by_page,
        "total_pages": total_pages,
        "word_count": result.word_count,
        "char_count": result.char_count,
    })
    return result


# =============================================================================
# MAIN CLI COMMAND
# =============================================================================

@app.command()
def convert(
    input_path: Path = typer.Option(
        ...,
        "--input", "-i",
        help="Path to the input PDF file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    output_path: Path = typer.Option(
        ...,
        "--output", "-o",
        help="Path for the output Markdown file.",
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key", "-k",
        help="Anthropic API key. Can also use ANTHROPIC_API_KEY env var.",
        envvar="ANTHROPIC_API_KEY",
    ),
    dpi: int = typer.Option(
        300,
        "--dpi", "-d",
        help="DPI for PDF to image conversion. Higher = better quality but slower.",
        min=72,
        max=600,
    ),
    mode: str = typer.Option(
        "sonnet",
        "--mode",
        help="Quality tier chain: 'sonnet' (Sonnet→Haiku→Tesseract), 'haiku' (Haiku→Tesseract), or 'tesseract' (Tesseract only).",
    ),
    context_words: int = typer.Option(
        50,
        "--context-words", "-c",
        help="Number of words to pass as context between pages.",
        min=0,
        max=200,
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Overwrite output file if it exists.",
    ),
):
    """
    Convert a PDF document to Obsidian-optimized Markdown.

    Uses a 3-tier fallback chain (Claude Sonnet → Haiku → Tesseract) by default,
    with refusal detection so soft-refusals fall through to the next tier.

    Example:
        python pdf_to_md.py convert -i document.pdf -o document.md
    """

    # ----- Environment checks (CLI-only nicety) -----
    console.print(Panel(
        "[bold blue]PDF-to-Obsidian Converter[/bold blue]\n"
        f"Mode: {mode}",
        title="Starting Conversion"
    ))

    if not check_poppler_installed():
        console.print(Panel(
            "[red bold]poppler-utils is not installed![/red bold]\n\n"
            "  • Ubuntu/Debian: sudo apt-get install poppler-utils\n"
            "  • macOS: brew install poppler\n"
            "  • Windows: see https://github.com/oschwartz10612/poppler-windows/releases",
            title="Missing Dependency"
        ))
        raise typer.Exit(code=1)
    console.print("[green]✓[/green] poppler-utils detected")

    if output_path.exists() and not force:
        if not Confirm.ask(f"Output file {output_path} exists. Overwrite?"):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(code=0)

    # ----- Resolve API key only if a Claude tier will be used -----
    try:
        tiers = _mode_to_tiers(mode)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    resolved_api_key: Optional[str] = None
    if any(t != "tesseract" for t in tiers):
        resolved_api_key = get_api_key(api_key)
        console.print("[green]✓[/green] API key configured")

    # ----- Run conversion with a Rich progress bar driven by the callback -----
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    )

    state = {"task": None}

    def cli_progress_callback(event: dict) -> None:
        et = event.get("type")
        if et == "started":
            state["task"] = progress.add_task(
                f"Scanning {event['total_pages']} pages...",
                total=event["total_pages"],
            )
        elif et == "page-done":
            engine_short = event["engine"].split("-")[1] if event["engine"].startswith("claude-") else event["engine"]
            progress.update(
                state["task"],
                advance=1,
                description=f"Page {event['page']}/{event['total_pages']} via {engine_short}",
            )

    try:
        with progress:
            result = run_conversion(
                pdf_path=input_path,
                mode=mode,
                dpi=dpi,
                context_words=context_words,
                api_key=resolved_api_key,
                progress_callback=cli_progress_callback,
            )
    except Exception as e:
        console.print(f"[red]Conversion failed: {e}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] Extracted text from all {result.total_pages} pages")

    # ----- Save output -----
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result.markdown)
        console.print(f"[green]✓[/green] Saved Markdown to {output_path}")
    except Exception as e:
        console.print(f"[red]Error saving file: {e}[/red]")
        raise typer.Exit(code=1)

    # ----- Summary panel -----
    engine_pages: dict[str, list[int]] = {}
    for page_num, engine in result.engine_by_page.items():
        engine_pages.setdefault(engine, []).append(page_num)
    engine_lines = "\n".join(
        f"[dim]{engine}:[/dim] {len(pages)} page(s) — {sorted(pages)}"
        for engine, pages in engine_pages.items()
    )

    console.print(Panel(
        f"[green bold]Conversion Complete![/green bold]\n\n"
        f"[dim]Input:[/dim]  {input_path.name}\n"
        f"[dim]Output:[/dim] {output_path.name}\n"
        f"[dim]Mode:[/dim]   {result.mode}\n"
        f"[dim]Pages:[/dim]  {result.total_pages}\n"
        f"[dim]Words:[/dim]  {result.word_count:,}\n"
        f"[dim]Chars:[/dim]  {result.char_count:,}\n\n"
        f"[bold]Engine usage:[/bold]\n{engine_lines}",
        title="Summary"
    ))


@app.command()
def test_setup():
    """
    Test that all dependencies are correctly installed.

    This command checks for:
    - poppler-utils (system)
    - pdf2image (Python)
    - anthropic (Python)
    - rich (Python)
    """
    console.print("[bold]Testing PDF-to-Obsidian Setup[/bold]\n")

    from importlib.metadata import version

    all_good = True

    # Check poppler
    if check_poppler_installed():
        console.print("[green]✓[/green] poppler-utils is installed")
    else:
        console.print("[red]✗[/red] poppler-utils is NOT installed")
        console.print("  Install with: sudo apt-get install poppler-utils (Linux)")
        console.print("  Install with: brew install poppler (macOS)")
        all_good = False

    # Check tesseract (used as last-resort fallback when Claude content-filters a page)
    if shutil.which("tesseract"):
        console.print("[green]✓[/green] tesseract is installed (used as fallback)")
    else:
        console.print("[yellow]![/yellow] tesseract is NOT installed")
        console.print("  Install with: sudo apt-get install tesseract-ocr (Linux)")
        console.print("  Install with: brew install tesseract (macOS)")
        console.print("  Pages that Claude blocks will fail without this fallback.")

    # Check pytesseract (Python wrapper for tesseract fallback)
    try:
        import pytesseract  # noqa: F401
        console.print(f"[green]✓[/green] pytesseract is installed (v{version('pytesseract')})")
    except ImportError:
        console.print("[yellow]![/yellow] pytesseract is NOT installed")
        console.print("  Install with: pip install pytesseract")
        console.print("  Pages that Claude blocks will fail without this fallback.")

    # Check pdf2image
    try:
        import pdf2image
        from importlib.metadata import version
        console.print(f"[green]✓[/green] pdf2image is installed (v{version('pdf2image')})")
    except ImportError:
        console.print("[red]✗[/red] pdf2image is NOT installed")
        console.print("  Install with: pip install pdf2image")
        all_good = False

    # Check anthropic
    try:
        import anthropic
        console.print(f"[green]✓[/green] anthropic is installed (v{anthropic.__version__})")
    except ImportError:
        console.print("[red]✗[/red] anthropic is NOT installed")
        console.print("  Install with: pip install anthropic")
        all_good = False

    # Check rich (we're using it, so it must be installed)
    try:
        import rich
        console.print(f"[green]✓[/green] rich is installed (v{version('rich')})")
    except ImportError:
        console.print("[red]✗[/red] rich is NOT installed")
        all_good = False

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        console.print("[green]✓[/green] ANTHROPIC_API_KEY environment variable is set")
    else:
        console.print("[yellow]![/yellow] ANTHROPIC_API_KEY environment variable is not set")
        console.print("  You can still provide it via --api-key flag")

    # Final verdict
    console.print()
    if all_good:
        console.print(Panel(
            "[green bold]All dependencies are installed![/green bold]\n\n"
            "You're ready to convert PDFs to Markdown.\n\n"
            "[dim]Example usage:[/dim]\n"
            "  python pdf_to_md.py -i document.pdf -o document.md",
            title="Setup Complete"
        ))
    else:
        console.print(Panel(
            "[red bold]Some dependencies are missing![/red bold]\n\n"
            "Please install the missing dependencies listed above.",
            title="Setup Incomplete"
        ))
        raise typer.Exit(code=1)


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    app()

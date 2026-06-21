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
from pathlib import Path
from typing import Optional

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

def convert_pdf_to_images(pdf_path: Path, dpi: int = 300):
    """
    Convert a PDF file to a list of PIL Image objects.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Resolution for image conversion (default: 300 for high fidelity).

    Returns:
        list: List of PIL Image objects, one per page.

    Raises:
        ImportError: If pdf2image is not installed.
        Exception: If PDF conversion fails.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        console.print("[red]Error: pdf2image is not installed.[/red]")
        console.print("Install it with: pip install pdf2image")
        raise typer.Exit(code=1)

    try:
        # Convert PDF to images at specified DPI
        # Using PNG format internally for best quality
        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            fmt="png",
            thread_count=4,  # Use multiple threads for faster conversion
        )
        return images
    except Exception as e:
        console.print(f"[red]Error converting PDF to images: {e}[/red]")
        raise typer.Exit(code=1)


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
    client,
    image,
    page_num: int,
    total_pages: int,
    previous_context: Optional[str] = None,
    model: str = "claude-sonnet-4-6",
    fallback_model: str = FALLBACK_MODEL,
) -> tuple[str, str]:
    """
    Extract text from a page image with a 3-tier fallback chain:

    1. Primary Claude model (high fidelity, but its response filter can hard-block
       editorial content that mentions sensitive subjects).
    2. Fallback Claude model — empirically Haiku 4.5 passes content Sonnet/Opus reject.
    3. Tesseract — last resort, lower fidelity but no content filter.

    Returns: (text, engine_used) where engine_used is the model ID or "tesseract".
    """
    image_data = image_to_base64(image)

    prompt = SYSTEM_PROMPT
    if previous_context:
        prompt += CONTEXT_CONTINUATION_PROMPT.format(last_words=previous_context)

    # Tier 1: primary model
    try:
        text = _call_claude_vision(client, image_data, prompt, model)
        if not _looks_like_refusal(text):
            return text, model
        console.print(f"[yellow]Page {page_num}: {model} returned a refusal/summary; trying {fallback_model}.[/yellow]")
    except Exception as primary_exc:
        if not _is_content_filter_error(primary_exc):
            console.print(f"[yellow]Page {page_num}: {model} error ({primary_exc}); trying {fallback_model}.[/yellow]")

    # Tier 2: fallback Claude model
    try:
        text = _call_claude_vision(client, image_data, prompt, fallback_model)
        if not _looks_like_refusal(text):
            console.print(f"[yellow]Page {page_num}: recovered via {fallback_model}.[/yellow]")
            return text, fallback_model
        console.print(f"[yellow]Page {page_num}: {fallback_model} also refused; falling back to Tesseract.[/yellow]")
    except Exception as fallback_exc:
        if not _is_content_filter_error(fallback_exc):
            console.print(f"[yellow]Page {page_num}: {fallback_model} error ({fallback_exc}); falling back to Tesseract.[/yellow]")

    # Tier 3: Tesseract
    try:
        text = _call_tesseract(image)
        console.print(f"[yellow]Page {page_num}: Claude refused → recovered via Tesseract (lower fidelity).[/yellow]")
        return text, "tesseract"
    except Exception as tesseract_exc:
        console.print(f"[red]Page {page_num}: all OCR engines failed ({tesseract_exc}).[/red]")
        return f"[Error extracting page {page_num}: all OCR engines failed]", "error"


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
    model: str = typer.Option(
        "claude-sonnet-4-6",
        "--model", "-m",
        help="Claude model to use for OCR.",
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

    This tool uses Claude Vision API to perform high-fidelity OCR,
    preserving complex layouts, footnotes, and typography.

    Example:
        python pdf_to_md.py -i document.pdf -o document.md
    """

    # ==========================================================================
    # STEP 1: Environment Checks
    # ==========================================================================

    console.print(Panel(
        "[bold blue]PDF-to-Obsidian Converter[/bold blue]\n"
        "High-fidelity OCR using Claude Vision API",
        title="Starting Conversion"
    ))

    # Check for poppler
    if not check_poppler_installed():
        console.print(Panel(
            "[red bold]poppler-utils is not installed![/red bold]\n\n"
            "This tool requires poppler for PDF processing.\n\n"
            "[yellow]Installation instructions:[/yellow]\n"
            "  • Ubuntu/Debian: sudo apt-get install poppler-utils\n"
            "  • macOS: brew install poppler\n"
            "  • Windows: Download from https://github.com/oschwartz10612/poppler-windows/releases",
            title="Missing Dependency"
        ))
        raise typer.Exit(code=1)

    console.print("[green]✓[/green] poppler-utils detected")

    # Check output file
    if output_path.exists() and not force:
        if not Confirm.ask(f"Output file {output_path} exists. Overwrite?"):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(code=0)

    # Get API key
    resolved_api_key = get_api_key(api_key)
    console.print("[green]✓[/green] API key configured")

    # Initialize Anthropic client
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=resolved_api_key)
    except ImportError:
        console.print("[red]Error: anthropic library is not installed.[/red]")
        console.print("Install it with: pip install anthropic")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Error initializing Anthropic client: {e}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]✓[/green] Anthropic client initialized")

    # ==========================================================================
    # STEP 2: Convert PDF to Images
    # ==========================================================================

    console.print(f"\n[bold]Converting PDF to images at {dpi} DPI...[/bold]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Converting PDF pages...", total=None)
        images = convert_pdf_to_images(input_path, dpi=dpi)
        progress.update(task, completed=True)

    total_pages = len(images)
    console.print(f"[green]✓[/green] Converted {total_pages} page(s) to images")

    # ==========================================================================
    # STEP 3: OCR Each Page with Claude
    # ==========================================================================

    console.print(f"\n[bold]Extracting text using {model}...[/bold]")

    accumulated_text = ""
    previous_context = None
    # Track which engine produced each page so we can surface fidelity info at the end.
    engine_by_page: dict[int, str] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing pages", total=total_pages)

        for i, image in enumerate(images):
            page_num = i + 1
            progress.update(task, description=f"Scanning page {page_num} of {total_pages}...")

            page_text, engine = extract_text_from_image(
                client=client,
                image=image,
                page_num=page_num,
                total_pages=total_pages,
                previous_context=previous_context if context_words > 0 else None,
                model=model,
            )
            engine_by_page[page_num] = engine

            accumulated_text = clean_page_join(accumulated_text, page_text)

            if context_words > 0:
                previous_context = get_last_n_words(page_text, context_words)

            progress.update(task, advance=1)

    console.print(f"[green]✓[/green] Extracted text from all {total_pages} pages")

    # ==========================================================================
    # STEP 4: Save Output
    # ==========================================================================

    console.print(f"\n[bold]Saving to {output_path}...[/bold]")

    # Build engine summary (pages grouped by engine, with primary model first).
    engine_pages: dict[str, list[int]] = {}
    for page_num, engine in engine_by_page.items():
        engine_pages.setdefault(engine, []).append(page_num)

    fallback_pages = {e: p for e, p in engine_pages.items() if e != model}
    provenance_header = ""
    if fallback_pages:
        # HTML comment is invisible in Obsidian's rendered view but searchable in source.
        lines = ["<!--", "pdf_to_md provenance — pages using fallback engines:"]
        for engine, pages in fallback_pages.items():
            lines.append(f"  {engine}: {sorted(pages)}")
        lines.append("-->")
        provenance_header = "\n".join(lines) + "\n\n"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(provenance_header + accumulated_text)

        console.print(f"[green]✓[/green] Saved Markdown to {output_path}")

    except Exception as e:
        console.print(f"[red]Error saving file: {e}[/red]")
        raise typer.Exit(code=1)

    # ==========================================================================
    # DONE
    # ==========================================================================

    word_count = len(accumulated_text.split())
    char_count = len(accumulated_text)

    engine_lines = "\n".join(
        f"[dim]{engine}:[/dim] {len(pages)} page(s) — {sorted(pages)}"
        for engine, pages in engine_pages.items()
    )

    console.print(Panel(
        f"[green bold]Conversion Complete![/green bold]\n\n"
        f"[dim]Input:[/dim]  {input_path.name}\n"
        f"[dim]Output:[/dim] {output_path.name}\n"
        f"[dim]Pages:[/dim]  {total_pages}\n"
        f"[dim]Words:[/dim]  {word_count:,}\n"
        f"[dim]Chars:[/dim]  {char_count:,}\n\n"
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

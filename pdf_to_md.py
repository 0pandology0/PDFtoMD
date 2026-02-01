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


def extract_text_from_image(
    client,
    image,
    page_num: int,
    total_pages: int,
    previous_context: Optional[str] = None,
    model: str = "claude-sonnet-4-20250514"
) -> str:
    """
    Send an image to Claude Vision API and extract text.

    Args:
        client: Anthropic client instance.
        image: PIL Image object.
        page_num: Current page number (1-indexed).
        total_pages: Total number of pages.
        previous_context: Last ~50 words from previous page for continuity.
        model: Claude model to use.

    Returns:
        str: Extracted text from the image.
    """
    # Convert image to base64
    image_data = image_to_base64(image)

    # Build the prompt
    prompt = SYSTEM_PROMPT
    if previous_context:
        prompt += CONTEXT_CONTINUATION_PROMPT.format(last_words=previous_context)

    # Create the message with image
    try:
        message = client.messages.create(
            model=model,
            max_tokens=8192,  # Allow for long pages
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
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )

        # Extract the text response
        return message.content[0].text

    except Exception as e:
        console.print(f"[red]Error on page {page_num}: {e}[/red]")
        return f"[Error extracting page {page_num}: {str(e)}]"


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
        "claude-sonnet-4-20250514",
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

            # Extract text from this page
            page_text = extract_text_from_image(
                client=client,
                image=image,
                page_num=page_num,
                total_pages=total_pages,
                previous_context=previous_context if context_words > 0 else None,
                model=model,
            )

            # Join with accumulated text
            accumulated_text = clean_page_join(accumulated_text, page_text)

            # Update context for next page
            if context_words > 0:
                previous_context = get_last_n_words(page_text, context_words)

            progress.update(task, advance=1)

    console.print(f"[green]✓[/green] Extracted text from all {total_pages} pages")

    # ==========================================================================
    # STEP 4: Save Output
    # ==========================================================================

    console.print(f"\n[bold]Saving to {output_path}...[/bold]")

    try:
        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the markdown file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(accumulated_text)

        console.print(f"[green]✓[/green] Saved Markdown to {output_path}")

    except Exception as e:
        console.print(f"[red]Error saving file: {e}[/red]")
        raise typer.Exit(code=1)

    # ==========================================================================
    # DONE
    # ==========================================================================

    # Calculate some stats
    word_count = len(accumulated_text.split())
    char_count = len(accumulated_text)

    console.print(Panel(
        f"[green bold]Conversion Complete![/green bold]\n\n"
        f"[dim]Input:[/dim]  {input_path.name}\n"
        f"[dim]Output:[/dim] {output_path.name}\n"
        f"[dim]Pages:[/dim]  {total_pages}\n"
        f"[dim]Words:[/dim]  {word_count:,}\n"
        f"[dim]Chars:[/dim]  {char_count:,}",
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

    all_good = True

    # Check poppler
    if check_poppler_installed():
        console.print("[green]✓[/green] poppler-utils is installed")
    else:
        console.print("[red]✗[/red] poppler-utils is NOT installed")
        console.print("  Install with: sudo apt-get install poppler-utils (Linux)")
        console.print("  Install with: brew install poppler (macOS)")
        all_good = False

    # Check pdf2image
    try:
        import pdf2image
        console.print(f"[green]✓[/green] pdf2image is installed (v{pdf2image.__version__})")
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
        console.print(f"[green]✓[/green] rich is installed (v{rich.__version__})")
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

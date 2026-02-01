#!/usr/bin/env python3
"""
PDF-to-Obsidian Converter
=========================

A PDF to Markdown converter using Tesseract OCR.

This tool converts PDF documents to clean, Obsidian-optimized Markdown by:
1. Converting PDF pages to high-resolution images
2. Running Tesseract OCR on each page
3. Aggregating results into a single Markdown file

Requirements:
    - Python 3.9+
    - poppler-utils (system package for pdf2image)
    - tesseract (system package for OCR)
    - pytesseract (Python wrapper)

Usage:
    python pdf_to_md.py --input document.pdf --output document.md

Author: Generated for Obsidian vault optimization
"""

import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.prompt import Confirm

# Initialize Rich console for pretty output
console = Console()

# Create Typer app with rich markup support
app = typer.Typer(
    name="pdf-to-md",
    help="PDF to Markdown converter using Tesseract OCR.",
    rich_markup_mode="rich",
)


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


def check_tesseract_installed() -> bool:
    """
    Check if tesseract is installed on the system.

    Returns:
        bool: True if tesseract is installed, False otherwise.
    """
    return shutil.which("tesseract") is not None


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


def extract_text_from_image(image, page_num: int, lang: str = "eng") -> str:
    """
    Extract text from an image using Tesseract OCR.

    Args:
        image: PIL Image object.
        page_num: Current page number (1-indexed, for error messages).
        lang: Tesseract language code (default: "eng").

    Returns:
        str: Extracted text from the image.
    """
    try:
        import pytesseract
    except ImportError:
        console.print("[red]Error: pytesseract is not installed.[/red]")
        console.print("Install it with: pip install pytesseract")
        raise typer.Exit(code=1)

    try:
        # Run Tesseract OCR on the image
        text = pytesseract.image_to_string(image, lang=lang)
        return text.strip()
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
    dpi: int = typer.Option(
        300,
        "--dpi", "-d",
        help="DPI for PDF to image conversion. Higher = better quality but slower.",
        min=72,
        max=600,
    ),
    lang: str = typer.Option(
        "eng",
        "--lang", "-l",
        help="Tesseract language code (e.g., 'eng', 'deu', 'fra'). Use 'tesseract --list-langs' to see available.",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Overwrite output file if it exists.",
    ),
):
    """
    Convert a PDF document to Obsidian-optimized Markdown.

    This tool uses Tesseract OCR to extract text from PDF pages.

    Example:
        python pdf_to_md.py -i document.pdf -o document.md
    """

    # ==========================================================================
    # STEP 1: Environment Checks
    # ==========================================================================

    console.print(Panel(
        "[bold blue]PDF-to-Obsidian Converter[/bold blue]\n"
        "OCR using Tesseract",
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

    # Check for tesseract
    if not check_tesseract_installed():
        console.print(Panel(
            "[red bold]tesseract is not installed![/red bold]\n\n"
            "This tool requires Tesseract for OCR.\n\n"
            "[yellow]Installation instructions:[/yellow]\n"
            "  • Ubuntu/Debian: sudo apt-get install tesseract-ocr\n"
            "  • macOS: brew install tesseract\n"
            "  • Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki",
            title="Missing Dependency"
        ))
        raise typer.Exit(code=1)

    console.print("[green]✓[/green] tesseract detected")

    # Check output file
    if output_path.exists() and not force:
        if not Confirm.ask(f"Output file {output_path} exists. Overwrite?"):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(code=0)

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
    # STEP 3: OCR Each Page with Tesseract
    # ==========================================================================

    console.print(f"\n[bold]Extracting text using Tesseract (lang={lang})...[/bold]")

    accumulated_text = ""

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
                image=image,
                page_num=page_num,
                lang=lang,
            )

            # Join with accumulated text
            accumulated_text = clean_page_join(accumulated_text, page_text)

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
    - tesseract (system)
    - pdf2image (Python)
    - pytesseract (Python)
    - rich (Python)
    """
    console.print("[bold]Testing PDF-to-Obsidian Setup[/bold]\n")

    all_good = True
    from importlib.metadata import version

    # Check poppler
    if check_poppler_installed():
        console.print("[green]✓[/green] poppler-utils is installed")
    else:
        console.print("[red]✗[/red] poppler-utils is NOT installed")
        console.print("  Install with: sudo apt-get install poppler-utils (Linux)")
        console.print("  Install with: brew install poppler (macOS)")
        all_good = False

    # Check tesseract
    if check_tesseract_installed():
        console.print("[green]✓[/green] tesseract is installed")
    else:
        console.print("[red]✗[/red] tesseract is NOT installed")
        console.print("  Install with: sudo apt-get install tesseract-ocr (Linux)")
        console.print("  Install with: brew install tesseract (macOS)")
        all_good = False

    # Check pdf2image
    try:
        import pdf2image
        console.print(f"[green]✓[/green] pdf2image is installed (v{version('pdf2image')})")
    except ImportError:
        console.print("[red]✗[/red] pdf2image is NOT installed")
        console.print("  Install with: pip install pdf2image")
        all_good = False

    # Check pytesseract
    try:
        import pytesseract
        console.print(f"[green]✓[/green] pytesseract is installed (v{version('pytesseract')})")
    except ImportError:
        console.print("[red]✗[/red] pytesseract is NOT installed")
        console.print("  Install with: pip install pytesseract")
        all_good = False

    # Check rich (we're using it, so it must be installed)
    try:
        import rich
        console.print(f"[green]✓[/green] rich is installed (v{version('rich')})")
    except ImportError:
        console.print("[red]✗[/red] rich is NOT installed")
        all_good = False

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

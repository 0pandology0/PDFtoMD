# PDF-to-Obsidian Converter

A high-fidelity PDF to Markdown converter using Claude Vision API, optimized for Obsidian vaults.

## Why This Tool?

Standard OCR libraries (like Tesseract) often struggle with:
- Complex layouts and multi-column text
- Footnotes and references
- Preserving typography and formatting
- Handling page boundaries gracefully

This tool uses Claude's Vision capabilities to perform intelligent OCR that understands document structure, properly formats footnotes, and maintains high fidelity to the original text.

## Features

- **High-Fidelity OCR**: Uses Claude Vision API for intelligent text extraction
- **Obsidian-Optimized**: Outputs clean Markdown with proper headers and footnote syntax
- **Smart Page Boundaries**: Passes context between pages to handle sentences that cross page breaks
- **Progress Tracking**: Visual progress bar showing conversion status
- **Configurable**: Adjust DPI, context window, and model parameters

## Prerequisites

### System Dependencies

**poppler-utils** is required for PDF to image conversion:

```bash
# Ubuntu/Debian
sudo apt-get install poppler-utils

# macOS
brew install poppler

# Windows
# Download from: https://github.com/oschwartz10612/poppler-windows/releases
# Add the bin/ directory to your PATH
```

### Python Dependencies

```bash
pip install -r requirements.txt
```

### Anthropic API Key

You'll need an Anthropic API key. Get one at: https://console.anthropic.com/

Set it as an environment variable:

```bash
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
```

Or provide it via the `--api-key` flag when running the tool.

## Installation

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd PDFtoMD
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Verify setup:
   ```bash
   python pdf_to_md.py test-setup
   ```

## Usage

### Basic Conversion

```bash
python pdf_to_md.py --input document.pdf --output document.md
```

Or using short flags:

```bash
python pdf_to_md.py -i document.pdf -o document.md
```

### With Explicit API Key

```bash
python pdf_to_md.py -i document.pdf -o document.md --api-key sk-ant-your-key
```

### All Options

```bash
python pdf_to_md.py --help
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--input` | `-i` | Required | Path to input PDF file |
| `--output` | `-o` | Required | Path for output Markdown file |
| `--api-key` | `-k` | env var | Anthropic API key |
| `--dpi` | `-d` | 300 | Image resolution (72-600) |
| `--model` | `-m` | claude-sonnet-4-20250514 | Claude model to use |
| `--context-words` | `-c` | 50 | Words passed between pages for continuity |
| `--force` | `-f` | False | Overwrite existing output file |

### Test Setup

Verify all dependencies are correctly installed:

```bash
python pdf_to_md.py test-setup
```

## How It Works

1. **PDF to Images**: Each page is converted to a high-resolution PNG image using `pdf2image` (which wraps `poppler`).

2. **Vision API OCR**: Each image is sent to Claude with a specialized prompt that:
   - Extracts verbatim text without summarization
   - Detects and formats footnotes as `[^1]` syntax
   - Preserves document structure with proper Markdown headers
   - Maintains clean typography

3. **Smart Page Joining**: The last 50 words of each page are passed as context to the next page, ensuring sentences that cross page boundaries are handled smoothly without duplication.

4. **Output Assembly**: All pages are combined into a single Markdown file optimized for Obsidian.

## Customizing the OCR Prompt

The extraction behavior is controlled by the `SYSTEM_PROMPT` variable in `pdf_to_md.py` (around line 45). You can modify this to adjust:

- Footnote formatting preferences
- Header detection rules
- Typography handling
- Any other extraction behavior

## Example Output

Input: A PDF with academic text, footnotes, and section headers.

Output:
```markdown
# Chapter 1: Introduction

The study of natural language processing has evolved significantly over the past decade[^1].
This transformation has been driven by advances in deep learning architectures...

## 1.1 Background

Early approaches to text analysis relied heavily on rule-based systems...

[^1]: See Smith et al. (2020) for a comprehensive review of the field's history.
```

## Troubleshooting

### "poppler-utils is not installed"

Install poppler for your operating system (see Prerequisites above).

### "Error converting PDF to images"

- Ensure the PDF file is not corrupted
- Try a lower DPI setting: `--dpi 150`
- Check that you have sufficient disk space for temporary image files

### "Error initializing Anthropic client"

- Verify your API key is correct
- Check your internet connection
- Ensure you have API credits available

### Rate Limits

For large PDFs, you may hit API rate limits. The tool processes pages sequentially, so large documents will take time. Consider:
- Processing in batches
- Using a higher rate limit tier

## Cost Estimation

Each page requires one API call with an image. Approximate costs depend on:
- Image resolution (higher DPI = more tokens)
- Page content density
- Current Anthropic pricing

A typical 300 DPI page might use 1,000-3,000 input tokens plus output tokens for the extracted text.

## License

MIT License - See LICENSE file for details.

# PDF-to-Obsidian Converter

A PDF to Markdown converter using Tesseract OCR, optimized for Obsidian vaults.

## Features

- **Free & Local**: Uses Tesseract OCR - no API keys or cloud services required
- **Obsidian-Optimized**: Outputs clean Markdown files
- **Multi-Language**: Supports any language Tesseract supports
- **Progress Tracking**: Visual progress bar showing conversion status
- **Configurable**: Adjust DPI and language settings

## Prerequisites

### System Dependencies

**poppler-utils** (for PDF to image conversion):

```bash
# Ubuntu/Debian
sudo apt-get install poppler-utils

# macOS
brew install poppler

# Windows
# Download from: https://github.com/oschwartz10612/poppler-windows/releases
```

**tesseract** (for OCR):

```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# macOS
brew install tesseract

# Windows
# Download from: https://github.com/UB-Mannheim/tesseract/wiki
```

### Python Dependencies

```bash
pip install -r requirements.txt
```

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
python pdf_to_md.py convert --input document.pdf --output document.md
```

Or using short flags:

```bash
python pdf_to_md.py convert -i document.pdf -o document.md
```

### With Different Language

```bash
# German
python pdf_to_md.py convert -i document.pdf -o document.md --lang deu

# French
python pdf_to_md.py convert -i document.pdf -o document.md --lang fra
```

To see available languages:
```bash
tesseract --list-langs
```

For additional languages:
```bash
# macOS
brew install tesseract-lang

# Ubuntu/Debian
sudo apt-get install tesseract-ocr-<lang>  # e.g., tesseract-ocr-deu
```

### All Options

```bash
python pdf_to_md.py convert --help
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--input` | `-i` | Required | Path to input PDF file |
| `--output` | `-o` | Required | Path for output Markdown file |
| `--dpi` | `-d` | 300 | Image resolution (72-600) |
| `--lang` | `-l` | eng | Tesseract language code |
| `--force` | `-f` | False | Overwrite existing output file |

### Test Setup

Verify all dependencies are correctly installed:

```bash
python pdf_to_md.py test-setup
```

## How It Works

1. **PDF to Images**: Each page is converted to a high-resolution PNG image using `pdf2image` (which wraps `poppler`).

2. **Tesseract OCR**: Each image is processed by Tesseract to extract text.

3. **Output Assembly**: All pages are combined into a single Markdown file.

## Tips for Better Results

- **Higher DPI**: Use `--dpi 400` for documents with small text
- **Clean scans**: Tesseract works best with high-contrast, deskewed images
- **Language packs**: Install the correct language pack for non-English documents

## Troubleshooting

### "poppler-utils is not installed"

Install poppler for your operating system (see Prerequisites above).

### "tesseract is not installed"

Install Tesseract for your operating system (see Prerequisites above).

### "Error converting PDF to images"

- Ensure the PDF file is not corrupted
- Try a lower DPI setting: `--dpi 150`
- Check that you have sufficient disk space for temporary image files

### Poor OCR Quality

- Increase DPI: `--dpi 400`
- Ensure correct language is set: `--lang <code>`
- Check if the source PDF is a scanned image vs. text-based

## License

MIT License - See LICENSE file for details.

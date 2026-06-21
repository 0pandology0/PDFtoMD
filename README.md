# PDF-to-Obsidian Converter

A high-fidelity PDF → Markdown converter using Claude Vision, with a 3-tier fallback chain (Sonnet → Haiku → Tesseract) so no pages are silently lost. Output is optimized for Obsidian vaults.

## Why This Tool?

Standard OCR libraries (like Tesseract alone) struggle with:
- Complex layouts and multi-column text
- Footnotes and references
- Preserving typography and formatting
- Handling page boundaries gracefully

Claude Vision handles all of those well — *most* of the time. On copyrighted editorial material it has two distinct failure modes that this tool explicitly handles (see [Why the fallback chain](#why-the-fallback-chain) below).

## Features

- **3-tier fallback chain.** Sonnet 4.6 → Haiku 4.5 → Tesseract. Every page produces text.
- **Refusal detection.** Catches cases where Claude returns a summary/description instead of OCR ("I can see this is a page from...", "I'm not able to reproduce the full verbatim text...") and falls through to the next tier.
- **Content-filter awareness.** Catches Anthropic's API-level safety blocks and falls through cleanly.
- **Per-page provenance.** The summary panel shows which engine produced each page, and an HTML comment at the top of the output file preserves this for later reference (invisible in Obsidian's rendered view, searchable in source).
- **Obsidian-optimized output.** Standard Markdown headers, `[^1]` footnote syntax, clean typography.
- **Smart page boundaries.** The last ~50 words of each page are passed as context to the next, so cross-page sentences don't break or duplicate.
- **Configurable.** DPI, primary model, context window, output overwrite.

## Prerequisites

### System dependencies

Two system packages are required:

| Package | Purpose | macOS | Ubuntu/Debian |
|---|---|---|---|
| **poppler-utils** | PDF → image conversion | `brew install poppler` | `sudo apt-get install poppler-utils` |
| **tesseract-ocr** | Last-resort OCR fallback | `brew install tesseract` | `sudo apt-get install tesseract-ocr` |

For Windows, download poppler from <https://github.com/oschwartz10612/poppler-windows/releases> and tesseract from <https://github.com/UB-Mannheim/tesseract/wiki>; add both to PATH.

### Python dependencies

Use a virtual environment (most modern Pythons are externally-managed and will refuse a system-wide `pip install`):

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

### Anthropic API key

Get one at <https://console.anthropic.com/> and set:

```bash
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
```

Or pass it explicitly via `--api-key`.

## Installation

```bash
git clone https://github.com/0pandology0/PDFtoMD.git
cd PDFtoMD
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python pdf_to_md.py test-setup       # verifies all deps
```

## Usage

The CLI uses **subcommands** — `convert` for the main operation, `test-setup` to verify your environment.

### Basic conversion

```bash
python pdf_to_md.py convert --input document.pdf --output document.md
```

Or short flags:

```bash
python pdf_to_md.py convert -i document.pdf -o document.md
```

### Overwrite existing output

```bash
python pdf_to_md.py convert -i document.pdf -o document.md --force
```

### CLI options (for `convert`)

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--input` | `-i` | Required | Path to input PDF file |
| `--output` | `-o` | Required | Path for output Markdown file |
| `--api-key` | `-k` | env var | Anthropic API key |
| `--dpi` | `-d` | 300 | Image resolution (72–600). Higher = better OCR, slower |
| `--model` | `-m` | `claude-sonnet-4-6` | Primary Claude model. Fallback model is hardcoded at the top of `pdf_to_md.py` |
| `--context-words` | `-c` | 50 | Words passed between pages for sentence-continuity hints |
| `--force` | `-f` | False | Overwrite existing output without prompting |

### Verify setup

```bash
python pdf_to_md.py test-setup
```

## How It Works

1. **PDF → images.** Each page is rendered to a PNG at the configured DPI (300 by default) using `pdf2image` / poppler.
2. **Three-tier extraction per page**:
   - **Tier 1 — Primary Claude model** (default Sonnet 4.6). Highest fidelity. If the call succeeds AND the output passes refusal detection, this is the final result.
   - **Tier 2 — Fallback Claude model** (Haiku 4.5). Tried when the primary either errors with a content-filter block OR returns refusal-shaped text. Still high-quality OCR, just empirically more permissive on copyrighted material.
   - **Tier 3 — Tesseract.** Used when both Claude models fail. No content awareness so it always returns *something*, but the output is plain text without intelligent formatting (no Markdown structure, no `[^n]` footnotes).
3. **Cross-page context.** The last `--context-words` words of each accepted page are appended to the next page's prompt so sentences spanning the page break don't duplicate or truncate.
4. **Output assembly.** Pages are joined cleanly, prefixed with an HTML provenance comment listing any fallback engines used, and written to disk.

## Why the fallback chain?

Claude Vision can fail two ways on copyrighted editorial content:

- **Hard block.** The API returns a 400 error: `Output blocked by content filtering policy`. This is the response-side classifier and is deterministic-ish but not perfectly so.
- **Soft refusal.** The API call succeeds, but Claude returns a description or summary ("This appears to be a page from Harper's Magazine...", "I'm not able to reproduce the full verbatim text as it's a copyrighted periodical...") instead of OCR. Without detection this silently corrupts your output — the script can't tell from the API response that anything went wrong.

Empirical behavior on a 24-page Harper's Magazine article during development:

| Engine | Pages | Notes |
|---|---|---|
| Claude Sonnet 4.6 (primary) | 6 / 24 | Refused ~75% of pages as soft refusals |
| Claude Haiku 4.5 (fallback) | 12 / 24 | Recovered most of Sonnet's refusals |
| Tesseract (last resort) | 6 / 24 | Pages where both Claude models refused |

The per-page mix will vary per document — refusals are non-deterministic. The summary panel at the end of every run shows the exact breakdown, and an HTML provenance comment at the top of the output file preserves it for later reference:

```markdown
<!--
pdf_to_md provenance — pages using fallback engines:
  claude-haiku-4-5-20251001: [2, 3, 4, 10, 11, 12, 13, 14, 16, 21, 23, 24]
  tesseract: [5, 8, 9, 18, 20, 22]
-->
```

### Refusal detection heuristics

The script flags Claude's output as a refusal if it matches either of two pattern sets (see `_REFUSAL_STRONG_RE` and `_REFUSAL_OPENING_RE` in `pdf_to_md.py`):

- **Strong markers** anywhere in the text: phrases like `verbatim text`, `copyrighted periodical`, `Would any of those alternatives`, `JSTOR`/`ProQuest`, `I'd recommend consulting`. These essentially never appear in real article body text.
- **Refusal openings** in the first ~200 chars: `^I can see/help/offer/describe...`, `^Here is a summary`, `^This is an article`, `^The page appears to be`, etc.

False positives are possible (e.g. an article that legitimately opens with "I can see..."), but the cost is one extra fallback call — Tesseract output is still preserved, just at lower fidelity.

## Customizing the OCR prompt

The extraction prompt lives in the `SYSTEM_PROMPT` constant near the top of `pdf_to_md.py`. The cross-page context addition is `CONTEXT_CONTINUATION_PROMPT`. Both are heavily commented.

**Note:** During development we tried a "stronger" prompt that included instructions like *"Do not refuse. Output only the transcribed text."* — this *increased* hard-block errors significantly, likely because directive language about not refusing trips the safety classifier. The current prompt deliberately stays neutral.

## Example output

Input: a PDF with editorial text, footnotes, and section headers.

```markdown
<!--
pdf_to_md provenance — pages using fallback engines:
  claude-haiku-4-5-20251001: [2, 4]
-->

# Chapter 1: Introduction

The study of natural language processing has evolved significantly over the past decade[^1].

## 1.1 Background

Early approaches relied heavily on rule-based systems...

[^1]: See Smith et al. (2020) for a comprehensive review.
```

## Troubleshooting

### "No such option: --input"

You forgot the `convert` subcommand. Use `python pdf_to_md.py convert --input ...`, not `python pdf_to_md.py --input ...`.

### Most pages are coming back as summaries or refusals

This is the soft-refusal failure mode on copyrighted material. Check the engine usage panel at the end of the run — if many pages show `claude-haiku` or `tesseract`, the fallback chain did its job. If the *output content* still looks like summaries, the refusal detection patterns may not be catching them; add patterns to `_REFUSAL_STRONG_RE` / `_REFUSAL_OPENING_RE` in `pdf_to_md.py` and rerun.

### `"Output blocked by content filtering policy"` for many pages

Same root cause as above (Anthropic safety filters on certain editorial content), just the hard-block variant. The fallback chain handles this automatically.

### "poppler-utils is not installed" / "tesseract is NOT installed"

Install the missing system package — see Prerequisites. `pip install` alone is not enough; both poppler and tesseract are binaries.

### "Error converting PDF to images"

- Confirm the PDF isn't corrupted (try opening in a normal PDF viewer)
- Lower DPI: `--dpi 150`
- Check available disk space for temp images

### "Error initializing Anthropic client"

- Verify the API key (`echo $ANTHROPIC_API_KEY`)
- Check your internet connection and that you have API credits

### Rate limits

Pages are processed sequentially. For a long PDF you may hit per-minute rate limits. The script doesn't currently retry-with-backoff on rate limit errors — those errors will cascade through the fallback chain and end up in Tesseract.

## Cost estimation

Each page is at minimum one Claude Vision call. Pages that trigger the fallback chain incur:
- **2 calls** (Sonnet refused → Haiku succeeded)
- **2 calls + Tesseract** (Sonnet refused → Haiku refused → Tesseract; Tesseract is local/free)

On heavily-flagged copyrighted material total Claude cost can be 1.5–2× a clean run. The Sonnet ratio is the bigger cost lever (input image tokens dominate); switching the primary to Haiku via `--model claude-haiku-4-5-20251001` would be cheaper *and* would likely skip the fallback for many pages — at the cost of slightly lower OCR fidelity on Sonnet-friendly pages.

A typical 300 DPI page uses roughly 1,000–3,000 input tokens for the image, plus a few hundred output tokens for the extracted text.

## License

MIT License — see LICENSE file.

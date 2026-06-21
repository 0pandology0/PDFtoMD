# Instructions for Claude Code: Build "PDF-to-Obsidian" Tool

## Goal
Create a robust Python CLI utility (`pdf_to_md.py`) that performs high-fidelity OCR on PDF documents and outputs formatted Markdown specifically optimized for an Obsidian vault.

**Crucial Context:** Standard OCR libraries (like Tesseract) are not sufficient. The user requires "high fidelity," meaning the tool must preserve complex layouts, verbatim text, footnotes, and clean typography without truncation.

## Architecture Strategy
To achieve the requested fidelity, the tool should use a **Vision-Language Model (VLM)** approach rather than raw OCR. 
* **Step 1:** Convert PDF pages into high-resolution images.
* **Step 2:** Send images to the Anthropic API (Claude 3.5 Sonnet) with a specialized system prompt to extract text.
* **Step 3:** Aggregate the responses into a single clean Markdown file.

## Requirements

### 1. Dependencies
The script should use:
* `typer` or `argparse` for a clean CLI interface.
* `pdf2image` (wrapping poppler) to convert PDF pages to base64-encoded images.
* `anthropic` library to handle the API calls.
* `rich` for a nice progress bar (scanning page 1 of X...).

### 2. The Extraction Logic (The "Brain")
The script must function as follows:
* Accept a `--input` (PDF path) and `--output` (MD path).
* Iterate through the PDF page by page.
* For each page, send an API request with the image and the specific "System Prompt" defined below.
* **Smart Context:** If possible, pass the last 50 words of the *previous* page's output to the *current* page's prompt prompt to ensure sentences crossing page boundaries are not broken or duplicated.

### 3. The System Prompt
Embed the following prompt strictly into the Python script. This is the exact instruction set the user requires for the extraction:

> "Perform a high-fidelity OCR on the attached image. Extract the full, verbatim text.
>
> **Formatting Constraints:**
> * **No System Tags:** Do not include `[PAGE 1]`, `[end]`, or metadata tags.
> * **Clean Typography:** Use standard Markdown. Convert fancy quotes to straight quotes if necessary, but prefer author's original typography.
> * **Structure:** Use appropriate Markdown headers (#, ##) for titles/sections.
> * **Footnotes:** You MUST detect footnotes. Convert them to standard Markdown syntax (e.g., `[^1]` in-text and `[^1]: Content` at the bottom of the text block).
> * **No Truncation:** Extract every single word. Do not summarize."

### 4. Output Handling
* The script should append each page's text to a buffer.
* It should handle the "join" between pages cleanly (ensure there are no massive gaps or double newlines).
* Save the final result to a `.md` file.

## Execution Plan
1.  **Check environment:** Verify `poppler` is installed (warn the user if not).
2.  **Scaffold:** Create the `pdf_to_md.py` file with necessary imports.
3.  **Implement:** Write the conversion and API logic.
4.  **Test:** Create a dummy test function or instructions on how the user can test it.

## User Interaction
* Ask the user for their Anthropic API Key (or check if it's in the environment variables) before running.
* Ensure the code is heavily commented so the user can adjust the "System Prompt" later if they want to tweak formatting.

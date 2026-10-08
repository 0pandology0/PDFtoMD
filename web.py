"""
PDFtoMD web UI — a local-only FastAPI app that wraps the CLI tool.

  $ python web.py
  # → http://127.0.0.1:8000

Reads the same ANTHROPIC_API_KEY env var the CLI uses. Tesseract-only mode runs
without a key. Uploaded PDFs and generated Markdown live in
$TMPDIR/pdftomd-jobs/<job_id>/ and are not cleaned up automatically — your OS's
temp policy handles eventual reaping.

Architecture: single-process FastAPI. Each upload spawns a background worker via
run_in_executor (the underlying conversion is sync/blocking). The worker pushes
lifecycle events through an asyncio.Queue that the SSE handler streams to the
browser. Job state is in-memory only — server restart loses everything.
"""
import asyncio
import json
import os
import queue as stdqueue
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from pdf_to_md import (
    MODE_TIERS,
    check_poppler_installed,
    run_conversion,
)

WEB_DIR = Path(__file__).parent / "web"
JOBS_DIR = Path(tempfile.gettempdir()) / "pdftomd-jobs"
JOBS_DIR.mkdir(exist_ok=True)


@dataclass
class JobState:
    job_id: str
    original_filename: str
    # stdlib thread-safe Queue. The worker thread `put()`s; the SSE handler
    # `get()`s via run_in_executor so the event loop is not blocked.
    queue: "stdqueue.Queue[dict]"
    result_path: Optional[Path] = None
    error: Optional[str] = None


JOBS: dict[str, JobState] = {}

app = FastAPI(title="PDFtoMD")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (WEB_DIR / "index.html").read_text()


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "claude_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "tesseract_present": shutil.which("tesseract") is not None,
        "poppler_present": check_poppler_installed(),
        "modes": list(MODE_TIERS),
    }


@app.post("/api/convert")
async def convert_endpoint(
    file: UploadFile = File(...),
    mode: str = Form("sonnet"),
    dpi: int = Form(300),
    context_words: int = Form(50),
) -> dict:
    if mode not in MODE_TIERS:
        raise HTTPException(status_code=400, detail=f"Unknown mode {mode!r}")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are accepted")

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / "input.pdf"

    with pdf_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    loop = asyncio.get_running_loop()
    event_queue: "stdqueue.Queue[dict]" = stdqueue.Queue()

    state = JobState(
        job_id=job_id,
        original_filename=file.filename,
        queue=event_queue,
    )
    JOBS[job_id] = state

    def worker() -> None:
        # Run conversion's "completed" event is held until after the file is on disk,
        # so the frontend can fetch /result immediately on receiving completion.
        def callback_filter(event: dict) -> None:
            if event.get("type") != "completed":
                state.queue.put(event)

        try:
            result = run_conversion(
                pdf_path=pdf_path,
                mode=mode,
                dpi=dpi,
                context_words=context_words,
                progress_callback=callback_filter,
            )
            md_path = job_dir / "output.md"
            md_path.write_text(result.markdown, encoding="utf-8")
            state.result_path = md_path
            state.queue.put({
                "type": "completed",
                "engine_by_page": result.engine_by_page,
                "total_pages": result.total_pages,
                "word_count": result.word_count,
                "char_count": result.char_count,
                "preview": result.markdown[:2048],
            })
        except Exception as e:
            state.error = str(e)
            state.queue.put({"type": "error", "message": str(e)})

    loop.run_in_executor(None, worker)

    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str) -> EventSourceResponse:
    state = JOBS.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown job")

    async def stream():
        # Poll the thread-safe queue without blocking the event loop. 50 ms gives
        # near-instant event delivery without burning CPU.
        while True:
            try:
                event = state.queue.get_nowait()
            except stdqueue.Empty:
                await asyncio.sleep(0.05)
                continue
            event_type = event.get("type", "message")
            yield {"event": event_type, "data": json.dumps(event)}
            if event_type in ("completed", "error"):
                return

    return EventSourceResponse(stream())


@app.get("/api/jobs/{job_id}/result")
async def result_endpoint(job_id: str) -> FileResponse:
    state = JOBS.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    if state.error:
        raise HTTPException(status_code=500, detail=state.error)
    if state.result_path is None or not state.result_path.exists():
        raise HTTPException(status_code=425, detail="Conversion not complete")

    download_name = state.original_filename.rsplit(".", 1)[0] + ".md"
    return FileResponse(
        state.result_path,
        media_type="text/markdown",
        filename=download_name,
    )


if __name__ == "__main__":
    import uvicorn
    print("PDFtoMD web UI → http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

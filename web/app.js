"use strict";

const $ = (id) => document.getElementById(id);

const views = {
  idle: $("view-idle"),
  processing: $("view-processing"),
  done: $("view-done"),
  error: $("view-error"),
};

const state = {
  file: null,
  mode: "haiku",
  jobId: null,
  source: null,           // EventSource
  startTimeMs: null,
};

function showView(name) {
  for (const k of Object.keys(views)) {
    views[k].classList.toggle("hidden", k !== name);
  }
}

// ============================================================
// Health check — disable Claude modes if no API key on server
// ============================================================
async function checkHealth() {
  try {
    const r = await fetch("/api/health");
    if (!r.ok) return;
    const h = await r.json();
    if (!h.claude_key_present) {
      const banner = $("health-banner");
      banner.textContent =
        "no ANTHROPIC_API_KEY on the server — only Tesseract mode is available. Set the env var and restart to enable Claude modes.";
      banner.classList.remove("hidden");
      for (const m of ["haiku", "sonnet"]) {
        const card = document.querySelector(`[data-mode-card="${m}"]`);
        card.classList.add("mode-card-disabled");
        card.querySelector("input[type=radio]").disabled = true;
      }
      // Default-select tesseract
      const tesseract = document.querySelector('[data-mode-card="tesseract"]');
      tesseract.click();
    }
    if (!h.tesseract_present) {
      const banner = $("health-banner");
      banner.textContent =
        (banner.textContent ? banner.textContent + " · " : "") +
        "tesseract binary missing — Tesseract fallback will fail.";
      banner.classList.remove("hidden");
    }
  } catch (e) {
    /* ignore — server alive enough to serve the page is good enough */
  }
}

// ============================================================
// File selection (drop + click + clear)
// ============================================================
function setFile(file) {
  state.file = file;
  if (file) {
    $("file-name").textContent = file.name;
    const kb = (file.size / 1024).toFixed(0);
    $("file-meta").textContent = `${kb} KB · ${file.type || "application/pdf"}`;
    $("drop-empty").classList.add("hidden");
    $("drop-filled").classList.remove("hidden");
  } else {
    $("file-input").value = "";
    $("drop-empty").classList.remove("hidden");
    $("drop-filled").classList.add("hidden");
  }
  updateSubmitEnabled();
}

function updateSubmitEnabled() {
  const enabled = state.file && state.mode;
  $("convert-btn").disabled = !enabled;
}

(function wireFileSelection() {
  const dropZone = $("drop-zone");
  const fileInput = $("file-input");

  fileInput.addEventListener("change", (e) => {
    const f = e.target.files?.[0];
    if (f && f.type === "application/pdf") setFile(f);
  });

  dropZone.addEventListener("click", (e) => {
    if (e.target.tagName !== "BUTTON") fileInput.click();
  });
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  ["dragenter", "dragover"].forEach((ev) =>
    dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropZone.classList.add("drop-zone-hover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropZone.classList.remove("drop-zone-hover");
    })
  );
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    const f = e.dataTransfer?.files?.[0];
    if (!f) return;
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      alert("Only PDF files are accepted.");
      return;
    }
    setFile(f);
  });

  $("file-clear").addEventListener("click", (e) => {
    e.stopPropagation();
    setFile(null);
  });
})();

// ============================================================
// Mode selection
// ============================================================
(function wireModeSelection() {
  const cards = document.querySelectorAll(".mode-card");
  for (const card of cards) {
    card.addEventListener("click", (e) => {
      e.preventDefault();
      if (card.classList.contains("mode-card-disabled")) return;
      for (const c of cards) c.classList.remove("mode-card-selected");
      card.classList.add("mode-card-selected");
      card.querySelector("input[type=radio]").checked = true;
      state.mode = card.dataset.modeCard;
      updateSubmitEnabled();
    });
  }
})();

// ============================================================
// Advanced range readouts
// ============================================================
(function wireRanges() {
  $("dpi").addEventListener("input", (e) => ($("dpi-value").textContent = e.target.value));
  $("context_words").addEventListener("input", (e) => ($("context-value").textContent = e.target.value));
})();

// ============================================================
// Submit + SSE
// ============================================================
function engineShort(engine) {
  if (engine === "tesseract") return "tesseract";
  if (engine === "error") return "error";
  if (engine.startsWith("claude-sonnet")) return "sonnet";
  if (engine.startsWith("claude-haiku")) return "haiku";
  if (engine.startsWith("claude-opus")) return "opus";
  return engine;
}

function engineClass(engine) {
  return "engine-" + engineShort(engine);
}

function startConversion() {
  if (!state.file || !state.mode) return;

  const fd = new FormData();
  fd.append("file", state.file);
  fd.append("mode", state.mode);
  fd.append("dpi", $("dpi").value);
  fd.append("context_words", $("context_words").value);

  // Reset processing UI
  $("processing-filename").textContent = state.file.name;
  $("processing-mode").textContent = state.mode;
  $("progress-fill").style.width = "0%";
  $("progress-count").textContent = "0 / 0";
  $("progress-eta").textContent = "starting…";
  $("page-log").innerHTML = "";
  state.startTimeMs = performance.now();
  showView("processing");

  fetch("/api/convert", { method: "POST", body: fd })
    .then(async (r) => {
      if (!r.ok) {
        const detail = await r.text().catch(() => r.statusText);
        throw new Error(`upload failed: ${detail}`);
      }
      const { job_id } = await r.json();
      state.jobId = job_id;
      attachEventSource(job_id);
    })
    .catch((err) => showError(err.message));
}

function attachEventSource(jobId) {
  if (state.source) state.source.close();
  const src = new EventSource(`/api/jobs/${jobId}/events`);
  state.source = src;
  let totalPages = 0;
  let donePages = 0;

  src.addEventListener("started", (ev) => {
    const d = JSON.parse(ev.data);
    totalPages = d.total_pages;
    $("progress-count").textContent = `0 / ${totalPages}`;
    $("progress-eta").textContent = "—";
  });

  src.addEventListener("page-done", (ev) => {
    const d = JSON.parse(ev.data);
    donePages = d.page;
    totalPages = d.total_pages || totalPages;
    const pct = totalPages ? Math.round((donePages / totalPages) * 100) : 0;
    $("progress-fill").style.width = pct + "%";
    $("progress-count").textContent = `${donePages} / ${totalPages}`;
    // ETA: based on elapsed time
    const elapsedSec = (performance.now() - state.startTimeMs) / 1000;
    const remaining = totalPages > donePages ? Math.round((elapsedSec / donePages) * (totalPages - donePages)) : 0;
    $("progress-eta").textContent = remaining > 0 ? `~${remaining}s left` : "finishing…";

    const li = document.createElement("li");
    li.className = "page-log-item";
    const short = engineShort(d.engine);
    li.innerHTML = `
      <span class="page-log-num">page ${d.page}</span>
      <span class="page-log-engine ${engineClass(d.engine)}">${short}</span>
      <span class="page-log-time">${(d.elapsed_ms / 1000).toFixed(1)}s</span>
    `;
    const log = $("page-log");
    log.appendChild(li);
    log.scrollTop = log.scrollHeight;
  });

  src.addEventListener("completed", (ev) => {
    src.close();
    state.source = null;
    showDone(JSON.parse(ev.data));
  });

  src.addEventListener("error", (ev) => {
    // SSE 'error' event from server, OR a connection error.
    if (ev.data) {
      try {
        const d = JSON.parse(ev.data);
        showError(d.message || "unknown error");
        return;
      } catch (_) { /* fall through */ }
    }
    // Connection-level error — only treat as a hard error if the job
    // hasn't already completed (in which case the close is expected).
    if (state.source) {
      showError("lost connection to server");
    }
  });
}

// ============================================================
// Done / Error views
// ============================================================
function showDone(payload) {
  $("done-filename").textContent = state.file.name;
  $("done-pages").textContent = payload.total_pages;
  $("done-words").textContent = payload.word_count.toLocaleString();
  $("done-chars").textContent = payload.char_count.toLocaleString();

  // Engine breakdown
  const byEngine = {};
  for (const [page, eng] of Object.entries(payload.engine_by_page || {})) {
    byEngine[eng] = (byEngine[eng] || 0) + 1;
  }
  const wrap = $("engine-breakdown");
  wrap.innerHTML = "";
  for (const [eng, count] of Object.entries(byEngine)) {
    const badge = document.createElement("div");
    badge.className = "engine-badge " + engineClass(eng);
    badge.innerHTML = `<b>${count}</b> page${count !== 1 ? "s" : ""} · ${engineShort(eng)}`;
    wrap.appendChild(badge);
  }

  $("preview").textContent = payload.preview || "(no preview)";

  const download = $("download-btn");
  download.href = `/api/jobs/${state.jobId}/result`;
  // The server sets Content-Disposition filename; browser uses that.

  showView("done");
}

function showError(message) {
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  $("error-message").textContent = message;
  showView("error");
}

function resetToIdle() {
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  state.jobId = null;
  setFile(null);
  showView("idle");
}

// ============================================================
// Wire up form + buttons
// ============================================================
$("upload-form").addEventListener("submit", (e) => {
  e.preventDefault();
  startConversion();
});
$("reset-btn").addEventListener("click", resetToIdle);
$("error-retry").addEventListener("click", resetToIdle);

// ============================================================
// Bootstrap
// ============================================================
checkHealth();
updateSubmitEnabled();
showView("idle");

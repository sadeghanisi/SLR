/**
 * SLR Web Application — Frontend Logic
 * Manages stage navigation, API calls, file uploads, progress streaming,
 * and result rendering.
 */

(function () {
  "use strict";

  // ═══════════════════════════════════════════════════════════════════════
  // State
  // ═══════════════════════════════════════════════════════════════════════
  const S = {
    providers: {},
    defaults: {},
    info: {},
    models: {},
    config: {
      provider: "",
      api_key: "",
      model: "",
      base_url: "",
    },
    refFilePath: "",
    refCount: 0,
    pdfFolder: "",
    pdfCount: 0,
    pollingInterval: null,
    eventSource: null,
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Helpers
  // ═══════════════════════════════════════════════════════════════════════
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  function showToast(message, type = "info") {
    const container = $("#toastContainer");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    
    // Icons based on type
    let icon = "";
    if (type === "success") icon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>`;
    else if (type === "error") icon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
    else icon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;

    toast.innerHTML = `${icon} <span>${escHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add("fade-out");
      toast.addEventListener("animationend", () => toast.remove());
    }, 4000);
  }

  function setButtonLoading(btn, isLoading, originalText = "") {
    if (!btn) return;
    if (isLoading) {
      btn.dataset.originalText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span> ${originalText || "Loading..."}`;
    } else {
      btn.disabled = false;
      if (btn.dataset.originalText) {
        btn.innerHTML = btn.dataset.originalText;
      }
    }
  }

  async function api(path, opts = {}) {
    const defaults = { headers: { "Content-Type": "application/json" } };
    if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
      opts.body = JSON.stringify(opts.body);
    }
    if (opts.body instanceof FormData) {
      delete defaults.headers["Content-Type"];
    }
    const resp = await fetch(path, { ...defaults, ...opts });
    if (!resp.ok && resp.headers.get("content-type")?.includes("json")) {
      const err = await resp.json();
      throw new Error(err.error || `HTTP ${resp.status}`);
    }
    return resp;
  }

  function formatNumber(n) {
    if (n === undefined || n === null) return "—";
    return Number(n).toLocaleString();
  }

  function decisionClass(decision) {
    const d = (decision || "").toLowerCase();
    if (d.includes("include")) return "include";
    if (d.includes("exclude")) return "exclude";
    if (d.includes("flag") || d.includes("human")) return "flag";
    if (d.includes("error")) return "error";
    return "";
  }

  function decisionBadge(decision) {
    const cls = decisionClass(decision);
    return `<span class="decision-badge ${cls}">${decision || "—"}</span>`;
  }

  function escHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function logLine(msg) {
    const log = $("#processLog");
    if (!log) return;
    const t = new Date().toLocaleTimeString();
    log.innerHTML += `<div class="log-line"><span class="log-time">${t}</span>${escHtml(msg)}</div>`;
    log.scrollTop = log.scrollHeight;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Stage navigation
  // ═══════════════════════════════════════════════════════════════════════
  function initStages() {
    $$(".stage-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        const stage = tab.dataset.stage;
        $$(".stage-tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        $$(".stage").forEach((s) => s.classList.remove("active"));
        $(`#stage-${stage}`).classList.add("active");
      });
    });
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Provider configuration (Stage 1)
  // ═══════════════════════════════════════════════════════════════════════
  async function loadProviders() {
    try {
      const resp = await api("/api/providers");
      const data = await resp.json();
      S.providers = data.providers || [];
      S.defaults = data.defaults || {};
      S.info = data.info || {};
      S.models = data.models || {};

      const sel = $("#providerSelect");
      sel.innerHTML = S.providers.map((p) => `<option value="${p}">${p}</option>`).join("");

      sel.addEventListener("change", onProviderChange);
      onProviderChange();
      renderProviderList();
    } catch (e) {
      console.error("Failed to load providers:", e);
    }
  }

  // Returns the effective model: custom input wins over dropdown
  function getActiveModel() {
    const custom = ($("#customModelInput").value || "").trim();
    return custom || $("#modelSelect").value;
  }

  // Sync visual state when custom model input changes
  function updateCustomModelUI() {
    const custom = ($("#customModelInput").value || "").trim();
    const modelSel = $("#modelSelect");
    const clearBtn = $("#customModelClear");
    const hint = $("#customModelHint");

    if (custom) {
      modelSel.classList.add("model-overridden");
      clearBtn.style.display = "block";
      // Show active badge if not already there
      let badge = $("#customModelBadge");
      if (!badge) {
        badge = document.createElement("div");
        badge.id = "customModelBadge";
        badge.className = "custom-model-active-badge";
        hint.insertAdjacentElement("afterend", badge);
      }
      badge.textContent = `↳ Using: ${custom}`;
    } else {
      modelSel.classList.remove("model-overridden");
      clearBtn.style.display = "none";
      const badge = $("#customModelBadge");
      if (badge) badge.remove();
    }
    S.config.model = getActiveModel();
  }

  function onProviderChange() {
    const p = $("#providerSelect").value;
    S.config.provider = p;

    const modelSel = $("#modelSelect");
    const models = S.models[p] || [];
    const defaultModel = S.defaults[p] || models[0] || "";
    modelSel.innerHTML = models.map((m) =>
      `<option value="${m}" ${m === defaultModel ? "selected" : ""}>${m}</option>`
    ).join("");

    // Clear custom model when switching providers so old custom doesn't carry over
    $("#customModelInput").value = "";
    updateCustomModelUI();
    S.config.model = getActiveModel();

    const needsUrl = p === "Ollama (Local)" || p === "Custom OpenAI-Compatible";
    $("#baseUrlGroup").style.display = needsUrl ? "block" : "none";
    if (needsUrl && !$("#baseUrlInput").value) {
      $("#baseUrlInput").value = p === "Ollama (Local)" ? "http://localhost:11434" : "";
    }

    const info = S.info[p] || {};
    const infoHtml = [];
    if (info.website && info.website !== "Custom") {
      infoHtml.push(`<p>Website: <a href="${info.website}" target="_blank" rel="noopener">${info.website}</a></p>`);
    }
    if (info.requires_api_key === false) {
      infoHtml.push(`<p style="color:var(--accept)">No API key required.</p>`);
    }
    if (info.free_tier === true) {
      infoHtml.push(`<p style="color:var(--accept)">Free tier available.</p>`);
    }
    $("#providerInfo").innerHTML = infoHtml.join("") || '<p class="info-muted">Select a provider to see details.</p>';
  }

  function renderProviderList() {
    const el = $("#providerQuickList");
    el.innerHTML = S.providers.map((p) => {
      const info = S.info[p] || {};
      let badge = "paid";
      let label = "Paid";
      if (info.free_tier === true) { badge = "free"; label = "Free"; }
      else if (info.free_tier === "Varies") { badge = "trial"; label = "Varies"; }
      return `<div class="provider-quick-item">
        <span class="pqi-name">${p}</span>
        <span class="pqi-badge ${badge}">${label}</span>
      </div>`;
    }).join("");
  }

  function initConfigHandlers() {
    // Toggle password visibility
    $("#toggleKeyBtn").addEventListener("click", () => {
      const inp = $("#apiKeyInput");
      inp.type = inp.type === "password" ? "text" : "password";
    });

    // Model dropdown change
    $("#modelSelect").addEventListener("change", () => {
      S.config.model = getActiveModel();
    });

    // Custom model input
    $("#customModelInput").addEventListener("input", updateCustomModelUI);
    $("#customModelInput").addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        $("#customModelInput").value = "";
        updateCustomModelUI();
      }
    });

    // Clear button
    $("#customModelClear").addEventListener("click", () => {
      $("#customModelInput").value = "";
      updateCustomModelUI();
      $("#customModelInput").focus();
    });

    // Test connection
    $("#testConnBtn").addEventListener("click", async () => {
      const btn = $("#testConnBtn");
      const res = $("#testResult");
      const dot = $("#statusDot");
      const txt = $("#statusText");

      S.config.api_key = $("#apiKeyInput").value;
      S.config.base_url = $("#baseUrlInput").value;
      S.config.model = getActiveModel();
      S.config.provider = $("#providerSelect").value;

      setButtonLoading(btn, true, "Testing...");
      res.textContent = "";
      res.className = "test-result";
      dot.className = "status-dot testing";
      txt.textContent = "Testing...";

      try {
        const resp = await api("/api/provider/test", {
          method: "POST",
          body: {
            provider: S.config.provider,
            api_key: S.config.api_key,
            model: S.config.model,
            base_url: S.config.base_url || undefined,
          },
        });
        const data = await resp.json();
        if (data.success) {
          res.textContent = "Connected — " + data.message;
          res.className = "test-result success";
          dot.className = "status-dot connected";
          txt.textContent = `${S.config.provider} / ${S.config.model}`;
          showToast("Connection successful", "success");
        } else {
          res.textContent = "Failed — " + data.message;
          res.className = "test-result error";
          dot.className = "status-dot error";
          txt.textContent = "Connection failed";
          showToast("Connection failed", "error");
        }
      } catch (e) {
        res.textContent = "Error: " + e.message;
        res.className = "test-result error";
        dot.className = "status-dot error";
        txt.textContent = "Error";
        showToast("Error testing connection: " + e.message, "error");
      }
      setButtonLoading(btn, false);
    });
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Reference upload (Stage 2)
  // ═══════════════════════════════════════════════════════════════════════
  function initRefUpload() {
    const zone = $("#refUploadZone");
    const input = $("#refFileInput");

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("dragover"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("dragover");
      if (e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        uploadRefFile(e.dataTransfer.files[0]);
      }
    });
    input.addEventListener("change", () => {
      if (input.files.length) uploadRefFile(input.files[0]);
    });
  }

  async function uploadRefFile(file) {
    const status = $("#refUploadStatus");
    status.textContent = `Uploading ${file.name}...`;

    const fd = new FormData();
    fd.append("file", file);
    try {
      const resp = await api("/api/references/upload", { method: "POST", body: fd });
      const data = await resp.json();
      if (data.error) {
        status.textContent = "Error: " + data.error;
        showToast(data.error, "error");
        return;
      }
      S.refFilePath = data.path;
      status.textContent = `Uploaded: ${data.filename} (${(data.size / 1024).toFixed(1)} KB)`;
      showToast("Reference file uploaded", "success");
      $("#parseBtn").disabled = false;
    } catch (e) {
      status.textContent = "Upload failed: " + e.message;
      showToast("Upload failed", "error");
    }
  }

  function initRefActions() {
    // Parse
    $("#parseBtn").addEventListener("click", async () => {
      const btn = $("#parseBtn");
      const stats = $("#parseStats");
      setButtonLoading(btn, true, "Parsing...");
      stats.innerHTML = "";
      try {
        const resp = await api("/api/references/parse", {
          method: "POST",
          body: { path: S.refFilePath },
        });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        S.refCount = data.count;
        stats.innerHTML = `<span class="stat-chip">${data.count} records found</span>`;
        $("#dedupBtn").disabled = false;
        $("#startScreenBtn").disabled = false;
        renderRefTable(data.sample, true);
        showToast(`Successfully parsed ${data.count} references`, "success");
      } catch (e) {
        stats.innerHTML = `<span style="color:var(--reject)">${e.message}</span>`;
        showToast("Parse failed: " + e.message, "error");
      }
      setButtonLoading(btn, false);
    });

    // Deduplicate
    $("#dedupBtn").addEventListener("click", async () => {
      const btn = $("#dedupBtn");
      const stats = $("#parseStats");
      setButtonLoading(btn, true, "Deduplicating...");
      try {
        const resp = await api("/api/references/deduplicate", {
          method: "POST",
          body: { threshold: 90 },
        });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        const s = data.stats;
        S.refCount = data.remaining;
        stats.innerHTML = `
          <span class="stat-chip">${s.total_before} imported</span>
          <span class="stat-chip exclude">${s.removed_doi + s.removed_fuzzy} duplicates</span>
          <span class="stat-chip include">${s.total_after} unique</span>
        `;
        showToast(`Removed ${s.removed_doi + s.removed_fuzzy} duplicates`, "success");
        await refreshRefTable();
      } catch (e) {
        stats.innerHTML += ` <span style="color:var(--reject)">${e.message}</span>`;
        showToast("Deduplication failed: " + e.message, "error");
      }
      setButtonLoading(btn, false);
    });
  }

  async function refreshRefTable() {
    try {
      const resp = await api("/api/references/list?per_page=200");
      const data = await resp.json();
      renderRefTable(data.records, false);
    } catch (e) {
      console.error(e);
    }
  }

  function renderRefTable(records, isSample) {
    const card = $("#refTableCard");
    const body = $("#refTableBody");
    if (!records || !records.length) {
      card.style.display = "none";
      return;
    }
    card.style.display = "block";
    body.innerHTML = records.map((r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td class="cell-truncate">${escHtml(r.title)}</td>
        <td class="cell-truncate">${escHtml(r.authors)}</td>
        <td>${escHtml(r.year)}</td>
        <td>${r.decision ? decisionBadge(r.decision) : "—"}</td>
        <td class="cell-truncate">${escHtml(r.rationale || "")}</td>
      </tr>
    `).join("");
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Abstract screening (Stage 2)
  // ═══════════════════════════════════════════════════════════════════════
  function initScreening() {
    let pollId = null;

    $("#startScreenBtn").addEventListener("click", async () => {
      S.config.api_key = $("#apiKeyInput").value;
      S.config.provider = $("#providerSelect").value;
      S.config.model = getActiveModel();
      S.config.base_url = $("#baseUrlInput").value;

      const criteria = $("#screenCriteria").value;
      if (!criteria.trim()) {
        showToast("Please enter screening criteria before starting.", "error");
        return;
      }

      setButtonLoading($("#startScreenBtn"), true, "Screening...");
      $("#stopScreenBtn").disabled = false;
      $("#screenProgressSection").style.display = "block";
      updateScreenProgress(0, S.refCount);

      try {
        await api("/api/screening/start", {
          method: "POST",
          body: {
            provider: S.config.provider,
            api_key: S.config.api_key,
            model: S.config.model,
            base_url: S.config.base_url || undefined,
            criteria: criteria,
            rate_delay: 0.5,
          },
        });

        pollId = setInterval(async () => {
          try {
            const resp = await api("/api/screening/results");
            const data = await resp.json();
            const done = data.total;
            updateScreenProgress(done, S.refCount);
            renderScreeningInRefTable(data.results);

            if (done >= S.refCount) {
              clearInterval(pollId);
              setButtonLoading($("#startScreenBtn"), false);
              $("#stopScreenBtn").disabled = true;
            }
          } catch (e) { /* ignore polling errors */ }
        }, 2000);
      } catch (e) {
        showToast("Screening failed: " + e.message, "error");
        setButtonLoading($("#startScreenBtn"), false);
      }
    });

    $("#stopScreenBtn").addEventListener("click", async () => {
      await api("/api/screening/stop", { method: "POST" });
      if (pollId) clearInterval(pollId);
      $("#stopScreenBtn").disabled = true;
      setButtonLoading($("#startScreenBtn"), false);
      showToast("Screening stopped", "info");
    });

    $("#exportScreeningBtn").addEventListener("click", async () => {
      try {
        const resp = await api("/api/screening/export", {
          method: "POST",
          body: { format: "xlsx" },
        });
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "abstract_screening.xlsx";
        a.click();
        URL.revokeObjectURL(url);
        showToast("Export successful!", "success");
      } catch (e) {
        showToast("Export failed: " + e.message, "error");
      }
    });
  }

  function updateScreenProgress(done, total) {
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    const bar = $("#screenProgressBar");
    const txt = $("#screenProgressText");
    bar.style.width = pct + "%";
    txt.textContent = `${done}/${total} (${pct}%)`;

    const stats = $("#screenStats");
    stats.innerHTML = `<span class="stat-chip">${done} screened of ${total}</span>`;
  }

  function renderScreeningInRefTable(results) {
    if (!results || !results.length) return;
    const rows = $$("#refTableBody tr");
    results.forEach((r, i) => {
      if (rows[i]) {
        const cells = rows[i].querySelectorAll("td");
        if (cells[4]) cells[4].innerHTML = decisionBadge(r.decision);
        if (cells[5]) cells[5].innerHTML = escHtml(r.rationale || "");
      }
    });
  }

  // ═══════════════════════════════════════════════════════════════════════
  // PDF upload & processing (Stage 3)
  // ═══════════════════════════════════════════════════════════════════════
  function initPdfUpload() {
    const zone  = $("#pdfUploadZone");
    const input = $("#pdfFileInput");

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("dragover",  (e) => { e.preventDefault(); zone.classList.add("dragover"); });
    zone.addEventListener("dragleave", ()  => zone.classList.remove("dragover"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("dragover");
      if (e.dataTransfer.files.length) uploadPdfs(e.dataTransfer.files);
    });
    input.addEventListener("change", () => {
      if (input.files.length) uploadPdfs(input.files);
    });

    // "Add More" button re-triggers the hidden file input
    $("#addMorePdfsBtn").addEventListener("click", () => input.click());

    // Clear All
    $("#clearAllPdfsBtn").addEventListener("click", async () => {
      if (!confirm("Remove all uploaded PDFs?")) return;
      try {
        await api("/api/pdfs/clear", { method: "POST" });
        S.pdfFolder = "";
        S.pdfCount  = 0;
        $("#pdfListCard").style.display = "none";
        $("#pdfUploadStatus").textContent = "";
        $("#startProcessBtn").disabled = true;
        showToast("All PDFs cleared", "info");
      } catch (e) {
        showToast("Could not clear PDFs: " + e.message, "error");
      }
    });
  }

  async function uploadPdfs(files) {
    const status = $("#pdfUploadStatus");
    const pdfs = Array.from(files).filter(f => f.name.toLowerCase().endsWith(".pdf"));
    if (!pdfs.length) { showToast("No PDF files selected", "error"); return; }

    status.innerHTML = `<span class="spinner"></span> Uploading ${pdfs.length} file(s)…`;

    const fd = new FormData();
    pdfs.forEach(f => fd.append("files", f));

    try {
      const resp = await api("/api/pdfs/upload", { method: "POST", body: fd });
      const data = await resp.json();
      if (data.error) {
        status.textContent = "Error: " + data.error;
        showToast(data.error, "error");
        return;
      }
      S.pdfFolder = data.folder;
      status.textContent = "";
      showToast(`${data.count} PDF(s) uploaded`, "success");
      await refreshPdfList();
      $("#startProcessBtn").disabled = false;
    } catch (e) {
      status.textContent = "Upload failed: " + e.message;
      showToast("Upload failed: " + e.message, "error");
    }
  }

  async function refreshPdfList() {
    try {
      const resp = await api("/api/pdfs/list");
      const data = await resp.json();
      renderPdfList(data.files || []);
    } catch (e) {
      console.error("Could not refresh PDF list:", e);
    }
  }

  function renderPdfList(files) {
    const card  = $("#pdfListCard");
    const body  = $("#pdfTableBody");
    const badge = $("#pdfCountBadge");

    S.pdfCount = files.length;
    badge.textContent = files.length;

    if (!files.length) {
      card.style.display = "none";
      $("#startProcessBtn").disabled = true;
      return;
    }

    card.style.display = "block";
    body.innerHTML = files.map((f, i) => `
      <tr>
        <td style="color:var(--ink-muted);font-family:var(--font-mono);font-size:0.8rem">${i + 1}</td>
        <td class="pdf-filename">${escHtml(f.name)}</td>
        <td class="pdf-size">${formatBytes(f.size)}</td>
        <td>
          <div style="display:flex;gap:var(--sp-2)">
            <button class="pdf-action-btn" data-action="view"   data-name="${escHtml(f.name)}" title="Open PDF in new tab">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              View
            </button>
            <button class="pdf-action-btn del" data-action="delete" data-name="${escHtml(f.name)}" title="Delete this PDF">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
              Delete
            </button>
          </div>
        </td>
      </tr>
    `).join("");

    // Wire up per-row actions via event delegation
    body.querySelectorAll(".pdf-action-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const action = btn.dataset.action;
        const name   = btn.dataset.name;
        if (action === "view") {
          window.open(`/api/pdfs/file/${encodeURIComponent(name)}`, "_blank");
        } else if (action === "delete") {
          if (!confirm(`Delete "${name}"?`)) return;
          try {
            const resp = await api("/api/pdfs/delete", { method: "POST", body: { filename: name } });
            const data = await resp.json();
            if (data.error) { showToast(data.error, "error"); return; }
            showToast(`Deleted ${name}`, "info");
            await refreshPdfList();
            if (data.remaining === 0) $("#startProcessBtn").disabled = true;
          } catch (e) {
            showToast("Delete failed: " + e.message, "error");
          }
        }
      });
    });
  }

  function formatBytes(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  }

  function initProcessing() {
    let pollId = null;

    $("#startProcessBtn").addEventListener("click", async () => {
      S.config.api_key = $("#apiKeyInput").value;
      S.config.provider = $("#providerSelect").value;
      S.config.model = getActiveModel();
      S.config.base_url = $("#baseUrlInput").value;

      const fieldsText = $("#extractionFields").value.trim();
      const fields = fieldsText ? fieldsText.split("\n").map((l) => l.trim()).filter(Boolean) : undefined;

      const body = {
        provider: S.config.provider,
        api_key: S.config.api_key,
        model: S.config.model,
        base_url: S.config.base_url || undefined,
        pdf_folder: S.pdfFolder,
        parallel: $("#parallelCheck").checked,
        max_workers: parseInt($("#workersInput").value) || 3,
        rate_delay: parseFloat($("#rateDelayInput").value) || 1.0,
        two_stage: $("#twoStageCheck").checked,
        cache_enabled: $("#cacheCheck").checked,
        screening_prompt: $("#pdfScreenPrompt").value || undefined,
        extraction_fields: fields,
      };

      setButtonLoading($("#startProcessBtn"), true, "Processing...");
      $("#stopProcessBtn").disabled = false;
      $("#monitorCard").style.display = "block";
      $("#processLog").innerHTML = "";
      logLine("Processing started...");

      try {
        const resp = await api("/api/processing/start", { method: "POST", body });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);

        logLine(`${data.total} PDFs queued`);

        pollId = setInterval(async () => {
          try {
            const r = await api("/api/processing/status");
            const d = await r.json();
            updateProcessMonitor(d);
            if (!d.active) {
              clearInterval(pollId);
              logLine("Processing complete.");
              setButtonLoading($("#startProcessBtn"), false);
              $("#stopProcessBtn").disabled = true;
              loadResults();
              showToast("Processing complete", "success");
            }
          } catch (e) { /* ignore */ }
        }, 2000);
      } catch (e) {
        logLine("Error: " + e.message);
        showToast("Processing failed: " + e.message, "error");
        setButtonLoading($("#startProcessBtn"), false);
        $("#stopProcessBtn").disabled = true;
      }
    });

    $("#stopProcessBtn").addEventListener("click", async () => {
      await api("/api/processing/stop", { method: "POST" });
      if (pollId) clearInterval(pollId);
      logLine("Stop requested...");
      $("#stopProcessBtn").disabled = true;
      showToast("Processing stopped", "info");
      setTimeout(() => { setButtonLoading($("#startProcessBtn"), false); }, 2000);
    });
  }

  function updateProcessMonitor(d) {
    const stats = d.stats || {};
    const total = stats.total_files || 1;
    const processed = stats.processed_files || 0;
    const pct = Math.round((processed / total) * 100);

    const bar = $("#processProgressBar");
    bar.style.width = pct + "%";
    $("#processProgressText").textContent = `${processed}/${total} (${pct}%)`;

    $("#kpiProcessed").textContent = processed;
    $("#kpiInclude").textContent = stats.likely_include || 0;
    $("#kpiExclude").textContent = stats.likely_exclude || 0;
    $("#kpiFlag").textContent = (stats.flag_for_review || 0) + (stats.flag_for_human_review || 0);
    $("#kpiTokens").textContent = formatNumber(stats.total_api_tokens);

    if (stats.total_processing_time > 0 && processed > 0) {
      const fpm = (processed / (stats.total_processing_time / 60)).toFixed(1);
      $("#kpiRate").textContent = fpm;
    }

    if (stats.current_file) {
      logLine(`Processing: ${stats.current_file}`);
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Results (Stage 4)
  // ═══════════════════════════════════════════════════════════════════════
  function initResults() {
    // Result tab switching
    $$(".res-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        $$(".res-tab").forEach((t) => t.classList.remove("active"));
        $$(".res-panel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        $(`#panel-${tab.dataset.restab}`).classList.add("active");
      });
    });

    // Filter
    $("#decisionFilter").addEventListener("change", filterResults);
    $("#searchResults").addEventListener("input", filterResults);

    // Export buttons
    $("#exportScreeningXlsx").addEventListener("click", () => exportProcessing("screening"));
    $("#exportExtractionXlsx").addEventListener("click", () => exportProcessing("extraction"));
  }

  async function loadResults() {
    try {
      const resp = await api("/api/processing/results");
      const data = await resp.json();
      renderScreeningResults(data.screening || []);
      renderExtractionResults(data.extraction || []);
      updatePrismaSummary(data.screening || []);
    } catch (e) {
      console.error("Failed to load results:", e);
    }
  }

  function renderScreeningResults(results) {
    const body = $("#screeningTableBody");
    if (!results || !results.length) {
      body.innerHTML = `<tr><td colspan="6">
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          <h3>No Screening Results</h3>
          <p>Process some PDFs or references first to see results here.</p>
        </div>
      </td></tr>`;
      return;
    }
    body.innerHTML = results.map((r) => `
      <tr data-decision="${r.decision || ""}" data-search="${(r.filename + ' ' + r.reasoning).toLowerCase()}">
        <td class="cell-truncate">${escHtml(r.filename)}</td>
        <td>${decisionBadge(r.decision)}</td>
        <td>${escHtml(r.stage || "")}</td>
        <td class="cell-truncate">${escHtml(r.reasoning)}</td>
        <td style="font-family:var(--font-mono);font-size:0.8rem">${r.processing_time ? r.processing_time.toFixed(1) + "s" : "—"}</td>
        <td style="font-family:var(--font-mono);font-size:0.8rem">${formatNumber(r.api_tokens_used)}</td>
      </tr>
    `).join("");

    // Row click for detail modal
    body.querySelectorAll("tr").forEach((row, i) => {
      row.addEventListener("click", () => showDetailModal(results[i]));
    });
  }

  function renderExtractionResults(results) {
    const head = $("#extractionHead");
    const body = $("#extractionTableBody");

    if (!results || !results.length) {
      head.innerHTML = "";
      body.innerHTML = `<tr><td>
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
          <h3>No Extraction Data</h3>
          <p>Run full-text processing on PDFs to extract data.</p>
        </div>
      </td></tr>`;
      return;
    }

    const allKeys = new Set();
    results.forEach((r) => {
      Object.keys(r.fields || {}).forEach((k) => allKeys.add(k));
    });
    const keys = ["filename", ...allKeys];

    head.innerHTML = keys.map((k) => `<th>${escHtml(k.replace(/_/g, " "))}</th>`).join("");

    body.innerHTML = results.map((r) => {
      const cells = keys.map((k) => {
        const val = k === "filename" ? r.filename : (r.fields || {})[k] || "";
        return `<td class="cell-truncate">${escHtml(String(val))}</td>`;
      });
      return `<tr>${cells.join("")}</tr>`;
    }).join("");
  }

  function updatePrismaSummary(screening) {
    if (!screening.length) return;
    const total = screening.length;
    let inc = 0, exc = 0;
    screening.forEach((r) => {
      const d = (r.decision || "").toLowerCase();
      if (d.includes("include")) inc++;
      if (d.includes("exclude")) exc++;
    });

    $("#prismaIdentified").textContent = total;
    $("#prismaScreened").textContent = total;
    $("#prismaIncluded").textContent = inc;
    $("#prismaExcluded").textContent = exc;
  }

  function filterResults() {
    const decision = $("#decisionFilter").value;
    const search = ($("#searchResults").value || "").toLowerCase();
    $$("#screeningTableBody tr").forEach((row) => {
      const matchDecision = !decision || row.dataset.decision === decision;
      const matchSearch = !search || (row.dataset.search || "").includes(search);
      row.style.display = matchDecision && matchSearch ? "" : "none";
    });
  }

  function showDetailModal(result) {
    const modal = $("#detailModal");
    const title = $("#modalTitle");
    const body = $("#modalBody");

    title.textContent = result.filename || "Paper Details";
    let html = "";

    const fields = [
      ["Decision", result.decision],
      ["Stage", result.stage],
      ["Reasoning", result.reasoning],
      ["Notes", result.notes],
      ["Processing Time", result.processing_time ? result.processing_time.toFixed(2) + "s" : "—"],
      ["Tokens Used", formatNumber(result.api_tokens_used)],
      ["Text Length", formatNumber(result.text_length)],
    ];

    fields.forEach(([label, value]) => {
      if (value) {
        html += `<div class="detail-row">
          <div class="detail-label">${label}</div>
          <div class="detail-value">${label === "Decision" ? decisionBadge(value) : escHtml(String(value))}</div>
        </div>`;
      }
    });

    body.innerHTML = html;
    modal.classList.add("open");
  }

  async function exportProcessing(which) {
    try {
      const resp = await api("/api/processing/export", {
        method: "POST",
        body: { which },
      });
      if (!resp.ok) {
        const err = await resp.json();
        showToast("Export failed: " + (err.error || "Unknown error"), "error");
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${which}_results.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      showToast("Export successful!", "success");
    } catch (e) {
      showToast("Export failed: " + e.message, "error");
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Modal
  // ═══════════════════════════════════════════════════════════════════════
  function initModal() {
    const modal = $("#detailModal");
    $("#modalClose").addEventListener("click", () => modal.classList.remove("open"));
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.classList.remove("open");
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") modal.classList.remove("open");
    });
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Settings persistence
  // ═══════════════════════════════════════════════════════════════════════
  async function loadSettings() {
    try {
      const resp = await api("/api/settings");
      const data = await resp.json();
      if (data.provider) {
        $("#providerSelect").value = data.provider;
        onProviderChange();
      }
      if (data.model) {
        setTimeout(() => { $("#modelSelect").value = data.model; }, 100);
      }
      if (data.base_url) {
        $("#baseUrlInput").value = data.base_url;
      }
      if (data.custom_model) {
        $("#customModelInput").value = data.custom_model;
        updateCustomModelUI();
      }
      if (data.screening_criteria) {
        $("#screenCriteria").value = data.screening_criteria;
      }
    } catch (e) { /* no saved settings */ }
  }

  // Save settings on provider/model change
  function autoSaveSettings() {
    const save = () => {
      const body = {
        provider: $("#providerSelect").value,
        model: $("#modelSelect").value,
        custom_model: ($("#customModelInput").value || "").trim(),
        base_url: $("#baseUrlInput").value,
        screening_criteria: $("#screenCriteria").value,
      };
      api("/api/settings", { method: "POST", body }).catch(() => {});
    };
    $("#providerSelect").addEventListener("change", save);
    $("#modelSelect").addEventListener("change", save);
    $("#customModelInput").addEventListener("blur", save);
    $("#screenCriteria").addEventListener("blur", save);
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Enhance buttons — use the user's LLM to improve criteria/prompts/fields
  // ═══════════════════════════════════════════════════════════════════════
  function initEnhanceButtons() {
    // Each .btn-enhance carries data-target (textarea id) and data-type (api field type)
    $$(".btn-enhance").forEach((btn) => {
      // Store per-button original text so we can restore it
      btn.dataset.origLabel = btn.innerHTML;

      // Revert buttons
      const barId = btn.dataset.target + "RevertBar";
      const bar   = $(`#${barId}`);
      if (bar) {
        const revertBtn = bar.querySelector(".btn-revert");
        if (revertBtn) {
          revertBtn.addEventListener("click", () => {
            const ta = $(`#${revertBtn.dataset.target}`);
            const savedKey = `__enhance_orig_${revertBtn.dataset.target}`;
            if (ta && ta.dataset[savedKey.replace("__enhance_orig_", "enhanceOrig")]) {
              ta.value = ta.dataset[savedKey.replace("__enhance_orig_", "enhanceOrig")];
              delete ta.dataset[savedKey.replace("__enhance_orig_", "enhanceOrig")];
            }
            bar.style.display = "none";
          });
        }
      }

      btn.addEventListener("click", async () => {
        const targetId = btn.dataset.target;
        const ftype    = btn.dataset.type;
        const ta       = $(`#${targetId}`);
        const revertBar = $(`#${targetId}RevertBar`);
        if (!ta) return;

        const content = ta.value.trim();
        if (!content) {
          showToast("Write something first — the field is empty.", "error");
          return;
        }

        // Collect current AI config
        const provider = $("#providerSelect").value;
        const apiKey   = $("#apiKeyInput").value.trim();
        const model    = getActiveModel();
        const baseUrl  = $("#baseUrlInput").value.trim();

        if (!provider || !apiKey) {
          showToast("Set up your AI provider in Stage 1 first.", "error");
          return;
        }

        // Save original for revert
        ta.dataset.enhanceOrig = ta.value;
        if (revertBar) revertBar.style.display = "none";

        // Loading state
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner"></span> Enhancing…`;
        ta.classList.add("enhancing");

        try {
          const resp = await api("/api/enhance", {
            method: "POST",
            body: {
              content,
              type:     ftype,
              provider,
              api_key:  apiKey,
              model,
              base_url: baseUrl || undefined,
            },
          });
          const data = await resp.json();
          if (data.error) throw new Error(data.error);

          ta.value = data.enhanced;
          // Trigger change so auto-save picks it up
          ta.dispatchEvent(new Event("input", { bubbles: true }));

          if (revertBar) revertBar.style.display = "flex";
          showToast("Content enhanced successfully!", "success");
        } catch (e) {
          // Restore original on failure
          ta.value = ta.dataset.enhanceOrig || ta.value;
          showToast("Enhance failed: " + e.message, "error");
        } finally {
          ta.classList.remove("enhancing");
          btn.disabled = false;
          btn.innerHTML = btn.dataset.origLabel;
        }
      });
    });
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Help drawer
  // ═══════════════════════════════════════════════════════════════════════
  function initHelp() {
    const drawer   = $("#helpDrawer");
    const backdrop = $("#helpBackdrop");
    const trigger  = $("#helpTrigger");
    const closeBtn = $("#helpClose");

    if (!drawer) return;

    function openHelp() {
      drawer.classList.add("open");
      backdrop.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
      closeBtn.focus();
    }
    function closeHelp() {
      drawer.classList.remove("open");
      backdrop.classList.remove("open");
      drawer.setAttribute("aria-hidden", "true");
      trigger && trigger.focus();
    }

    trigger  && trigger.addEventListener("click", openHelp);
    closeBtn && closeBtn.addEventListener("click", closeHelp);
    backdrop && backdrop.addEventListener("click", closeHelp);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && drawer.classList.contains("open")) closeHelp();
    });

    // Topic switching
    $$(".help-nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const topic = btn.dataset.topic;
        $$(".help-nav-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        $$(".help-topic").forEach((s) => s.classList.remove("active"));
        const panel = $(`#htopic-${topic}`);
        if (panel) {
          panel.classList.add("active");
          // scroll content area to top
          const content = $("#helpContent");
          if (content) content.scrollTop = 0;
        }
      });
    });
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Init
  // ═══════════════════════════════════════════════════════════════════════
  document.addEventListener("DOMContentLoaded", async () => {
    initStages();
    initConfigHandlers();
    initRefUpload();
    initRefActions();
    initScreening();
    initPdfUpload();
    initProcessing();
    initResults();
    initModal();
    initHelp();
    initEnhanceButtons();

    await loadProviders();
    await loadSettings();
    autoSaveSettings();
  });
})();

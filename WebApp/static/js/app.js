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
    refFileName: "",
    refCount: 0,
    pdfFolder: "",
    pdfCount: 0,
    workspace: null,
    workspaceExports: [],
reviewSummary: null,
    lastQueueMeta: null,
    lastImportSummary: null,
    exclusionReasons: [],
    pollingInterval: null,
    eventSource: null,
    refState: { page: 1, perPage: 50, q: "" },
    refTotal: 0,
    refFilteredTotal: 0,
    recentWorkspaces: [],
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

  function statusLabel(value) {
    const labels = {
      pending: "Pending",
      suggested: "Suggested",
      included: "Included",
      excluded: "Excluded",
      maybe: "Maybe",
      failed: "Failed",
    };
    return labels[value] || value || "All statuses";
  }

  function stageLabel(stage) {
    return stage === "full_text" ? "Full text" : "Title/abstract";
  }

  function originLabel(origin) {
    const labels = {
      imported_reference: "Imported references",
      pdf_only: "PDF-only records",
      manual: "Manual records",
    };
    return labels[origin] || origin || "All origins";
  }

  function decisionClass(decision) {
    const d = (decision || "").toLowerCase();
    if (d.includes("include")) return "include";
    if (d.includes("exclude")) return "exclude";
    if (d.includes("maybe")) return "maybe";
    if (d.includes("flag") || d.includes("human")) return "flag";
    if (d.includes("error") || d.includes("fail")) return "error";
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
  // Workspace shell
  // ═══════════════════════════════════════════════════════════════════════
function updateWorkspaceUI(payload) {
    const isOpen = !!(payload && payload.is_open && payload.workspace);
    S.workspace = isOpen ? payload.workspace : null;

    const nameEl = $("#workspaceName");
    const metaEl = $("#workspaceMeta");
    const modeEl = $("#workspaceModePill");
    const titleEl = $("#workspaceReviewTitle");
    const closeBtn = $("#closeWorkspaceBtn");
    if (!nameEl || !metaEl || !closeBtn) return;

    if (!isOpen) {
      if (modeEl) modeEl.textContent = "Legacy Mode - one-off run";
      nameEl.textContent = "No workspace open";
      metaEl.textContent = "Not saved as a persistent review project";
      if (titleEl) titleEl.textContent = "Review title: not saved";
      closeBtn.disabled = true;
      const reviewCard = $("#workspaceReviewCard");
      if (reviewCard) reviewCard.style.display = "none";
      const exportCard = $("#workspaceExportCard");
      if (exportCard) exportCard.style.display = "none";
      const onboarding = $("#workspaceOnboarding");
      if (onboarding) onboarding.style.display = "";
      const progress = $("#workspaceProgressPanel");
      if (progress) progress.style.display = "none";
      hideStartForms();
      return;
    }

    const counts = payload.workspace.counts || {};
    if (modeEl) modeEl.textContent = "Workspace Mode - saved locally";
    nameEl.textContent = payload.workspace.name || "Workspace";
    metaEl.textContent = `Saved locally on this computer | ${formatNumber(counts.active_unique_records || counts.records || 0)} active records | ${formatNumber(counts.pdfs || 0)} PDFs`;
    if (titleEl) titleEl.textContent = `Review title: ${payload.workspace.review_title || payload.workspace.name || "Workspace"}`;
    closeBtn.disabled = false;
    S.pdfFolder = payload.workspace.pdf_folder || "workspace:pdfs";
    const onboarding = $("#workspaceOnboarding");
    if (onboarding) onboarding.style.display = "none";
    const exportCard = $("#workspaceExportCard");
    if (exportCard) exportCard.style.display = "block";
    renderWorkspaceProgress();
  }

  function hideStartForms() {
    const form = $("#newWorkspaceForm");
    if (form) form.style.display = "none";
  }

  function renderWorkspaceProgress() {
    const panel = $("#workspaceProgressPanel");
    const grid = $("#workspaceProgressGrid");
    const empty = $("#workspaceProgressEmptyStates");
    if (!panel || !grid) return;
    if (!S.workspace) {
      panel.style.display = "none";
      return;
    }

    const counts = S.workspace.counts || {};
    const origins = counts.records_by_origin || {};
    const activeOrigins = counts.active_records_by_origin || origins;
    const statusCounts = (S.reviewSummary && S.reviewSummary.by_status) || counts.review_items_by_status || {};
    const aiCount = (S.reviewSummary && S.reviewSummary.ai_suggestion_count) ?? counts.ai_suggestions ?? 0;
    const humanCount = (S.reviewSummary && S.reviewSummary.human_decision_count) ?? counts.human_decisions ?? 0;
    const rawImported = counts.raw_imported_records ?? origins.imported_reference ?? 0;
    const activeUnique = counts.active_unique_records ?? counts.records ?? 0;
    const activeImported = activeOrigins.imported_reference ?? origins.imported_reference ?? 0;
    const duplicateRecords = counts.duplicate_records ?? counts.duplicate_source_records ?? 0;
    const items = [
      ["Workspace", "Created/opened"],
      ["Sources imported", counts.sources || 0],
      ["Parsed reference rows", rawImported],
      ["Active unique imported refs", activeImported],
      ["Duplicate records hidden", duplicateRecords],
      ["PDF-only records", activeOrigins.pdf_only || 0],
      ["Manual records", activeOrigins.manual || 0],
      ["Total workspace records", counts.records || 0],
      ["PDFs uploaded", counts.pdfs || 0],
      ["Review items", counts.review_items || 0],
      ["AI suggestions", aiCount],
      ["Human decisions", humanCount],
      ["Pending review items", statusCounts.pending || 0],
      ["Included / Excluded / Maybe", `${formatNumber(statusCounts.included || 0)} / ${formatNumber(statusCounts.excluded || 0)} / ${formatNumber(statusCounts.maybe || 0)}`],
    ];

    grid.innerHTML = items.map(([label, value]) => `
      <div class="workspace-progress-stat">
        <span class="workspace-progress-label">${escHtml(label)}</span>
        <span class="workspace-progress-value">${escHtml(String(typeof value === "number" ? formatNumber(value) : value))}</span>
      </div>
    `).join("");
    if (empty) {
      const messages = [];
      if (!rawImported) messages.push("No references imported yet.");
      if (!(counts.pdfs || 0)) messages.push("No PDFs uploaded yet.");
      if (!aiCount) messages.push("No AI suggestions yet. Run screening to generate suggestions.");
      if (!humanCount) messages.push("No human decisions yet. Review suggested items to finalize decisions.");
      empty.innerHTML = messages.map((message) => `<span>${escHtml(message)}</span>`).join("");
    }
    panel.style.display = "block";
  }

async function refreshRecentWorkspaces() {
    const select = $("#workspaceRecentSelect");
    if (select) select.innerHTML = `<option value="">Recent</option>`;
    let recent = [];
    try {
      const resp = await api("/api/workspaces/recent");
      const data = await resp.json();
      recent = data.recent || [];
      S.recentWorkspaces = recent;
      if (select) {
        select.innerHTML = `<option value="">Recent</option>` + recent.map((item) =>
          `<option value="${escHtml(item.workspace_id)}">${escHtml(item.name)}</option>`
        ).join("");
      }
    } catch (e) {
      S.recentWorkspaces = [];
    }
    renderRecentWorkspaceCards(recent);
  }

  function renderRecentWorkspaceCards(recent) {
    const wrap = $("#recentWorkspaceCards");
    if (!wrap) return;
    if (!recent || !recent.length) {
      wrap.innerHTML = `<div class="recent-workspace-empty">No recent workspaces on this computer yet. Create a new one above.</div>`;
      return;
    }
    wrap.innerHTML = recent.map((item) => {
      const title = item.review_title || item.name || "Untitled review";
      const reviewType = item.review_type ? escHtml(reviewTypeLabel(item.review_type)) : "";
      const opened = item.last_opened_at ? formatDateShort(item.last_opened_at) : "";
      return `
        <button class="recent-workspace-card" type="button" data-workspace-id="${escHtml(item.workspace_id)}" title="Open this workspace">
          <span class="recent-workspace-title">${escHtml(title)}</span>
          ${item.review_title && item.name ? `<span class="recent-workspace-name">${escHtml(item.name)}</span>` : ""}
          <span class="recent-workspace-tags">
            ${reviewType ? `<span class="origin-badge">${reviewType}</span>` : ""}
            <span class="origin-badge">Local only</span>
          </span>
          ${opened ? `<span class="recent-workspace-opened">Last opened: ${opened}</span>` : ""}
        </button>
      `;
    }).join("");
  }

  function reviewTypeLabel(value) {
    const labels = {
      systematic_review: "Systematic review",
      scoping_review: "Scoping review",
      other: "Other",
    };
    return labels[value] || value || "";
  }

  function formatDateShort(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    } catch (e) {
      return iso;
    }
  }

  async function refreshWorkspaceState() {
    try {
      const resp = await api("/api/workspaces/current");
      const data = await resp.json();
      updateWorkspaceUI(data);
      await refreshRecentWorkspaces();
      if (data.is_open) {
        await refreshRefTable();
        await refreshPdfList();
        await loadReviewQueue();
        await loadWorkspaceExportsSummary();
      }
    } catch (e) {
      updateWorkspaceUI({ is_open: false, workspace: null });
    }
  }

function initWorkspace() {
    const createBtn = $("#createWorkspaceBtn");
    const openBtn = $("#openWorkspaceBtn");
    const closeBtn = $("#closeWorkspaceBtn");
    const startNew = $("#startNewWorkspaceBtn");
    const startOpen = $("#startOpenWorkspaceBtn");
    const continueLegacy = $("#continueLegacyBtn");
    const onboardingFocus = $("#workspaceOnboardingFocusBtn");

    if (onboardingFocus) {
      onboardingFocus.addEventListener("click", () => {
        showNewWorkspaceForm();
      });
    }

    if (startNew) {
      startNew.addEventListener("click", () => {
        showNewWorkspaceForm();
      });
    }

    if (startOpen) {
      startOpen.addEventListener("click", async () => {
        const open = $("#openWorkspaceArea");
        if (!open) return;
        open.style.display = "block";
        await refreshRecentWorkspaces();
        open.scrollIntoView({ behavior: "smooth", block: "start" });
        const form = $("#newWorkspaceForm");
        if (form) form.style.display = "none";
      });
    }

    if (continueLegacy) {
      continueLegacy.addEventListener("click", () => {
        const configureTab = document.querySelector('.stage-tab[data-stage="configure"]');
        if (configureTab) configureTab.click();
        $("#stage-configure")?.scrollIntoView({ behavior: "smooth", block: "start" });
        showToast("Continuing in Legacy Mode. This is a one-off run, not a persistent review project.", "info");
      });
    }

    function showNewWorkspaceForm() {
      const form = $("#newWorkspaceForm");
      if (!form) return;
      form.style.display = "block";
      form.scrollIntoView({ behavior: "smooth", block: "start" });
      const titleInput = $("#reviewTitleInput");
      if (titleInput) titleInput.focus();
    }

    const cardsWrap = $("#recentWorkspaceCards");
    if (cardsWrap) {
      cardsWrap.addEventListener("click", (e) => {
        const card = e.target.closest("[data-workspace-id]");
        if (!card) return;
        openWorkspaceById(card.dataset.workspaceId, card);
      });
    }

    if (createBtn) {
      createBtn.addEventListener("click", async () => {
        const reviewTitle = ($("#reviewTitleInput")?.value || "").trim();
        const reviewType = ($("#reviewTypeSelect")?.value || "").trim() || undefined;
        const reviewQuestion = ($("#reviewQuestionInput")?.value || "").trim() || undefined;
        const reviewerName = ($("#reviewerNameInput")?.value || "").trim() || undefined;
        const path = ($("#workspacePathInput")?.value || "").trim() || undefined;
        const name = ($("#workspaceNameInput")?.value || "").trim() || undefined;
        if (!path && !reviewTitle && !name) {
          showToast("Enter a review title to create a workspace.", "error");
          $("#reviewTitleInput")?.focus();
          return;
        }
        setButtonLoading(createBtn, true, "Creating...");
        try {
          const resp = await api("/api/workspaces/create", {
            method: "POST",
            body: {
              path,
              name,
              review_title: reviewTitle || undefined,
              review_type: reviewType,
              review_question: reviewQuestion,
              reviewer_name: reviewerName,
            },
          });
          const data = await resp.json();
          if (data.error) throw new Error(data.error);
          updateWorkspaceUI(data);
          await refreshRecentWorkspaces();
          const configureTab = document.querySelector('.stage-tab[data-stage="configure"]');
          if (configureTab) configureTab.click();
          showToast("Workspace created.", "success");
        } catch (e) {
          showToast("Workspace create failed: " + e.message, "error");
        }
        setButtonLoading(createBtn, false);
      });
    }

    if (openBtn) {
      openBtn.addEventListener("click", async () => {
        const manualPath = ($("#openWorkspacePathInput")?.value || "").trim();
        if (!manualPath) {
          showToast("Pick a recent workspace above, or enter a folder path in the advanced section.", "error");
          return;
        }
        setButtonLoading(openBtn, true, "Opening...");
        try {
          const resp = await api("/api/workspaces/open", {
            method: "POST",
            body: { path: manualPath },
          });
          const data = await resp.json();
          if (data.error) throw new Error(data.error);
          await afterWorkspaceOpened(data);
        } catch (e) {
          showToast("Workspace open failed: " + e.message, "error");
        }
        setButtonLoading(openBtn, false);
      });
    }

    openWorkspaceById = async (workspaceId, card) => {
      if (!workspaceId) return;
      if (card) setButtonLoading(card, true, "Opening...");
      let data = null;
      try {
        const resp = await api("/api/workspaces/open", {
          method: "POST",
          body: { workspace_id: workspaceId },
        });
        data = await resp.json();
        if (data.error) throw new Error(data.error);
        await afterWorkspaceOpened(data);
      } catch (e) {
        showToast("Workspace open failed: " + e.message, "error");
        if (data && data.error && /not found|does not exist/i.test(data.error || "")) {
          // Offer to drop from recent list if it no longer exists
          readonlyDropRecent(workspaceId, "This workspace no longer exists on this computer.");
        }
      }
      if (card) setButtonLoading(card, false);
    };

    if (closeBtn) {
      closeBtn.addEventListener("click", async () => {
        try {
          const resp = await api("/api/workspaces/close", { method: "POST" });
          const data = await resp.json();
          updateWorkspaceUI(data);
          S.refFilePath = "";
          S.refFileName = "";
          S.refCount = 0;
          S.pdfFolder = "";
          S.pdfCount = 0;
          S.reviewSummary = null;
          S.workspaceExports = [];
          S.lastQueueMeta = null;
          S.lastImportSummary = null;
          S.refState = { page: 1, perPage: 50, q: "" };
          S.refTotal = 0;
          S.refFilteredTotal = 0;
          $("#refTableCard").style.display = "none";
          $("#pdfListCard").style.display = "none";
          const reviewCard = $("#workspaceReviewCard");
          if (reviewCard) reviewCard.style.display = "none";
          const exportCard = $("#workspaceExportCard");
          if (exportCard) exportCard.style.display = "none";
          renderImportSummary(null);
          $("#parseStats").innerHTML = "";
          $("#pdfUploadStatus").textContent = "";
          $("#parseBtn").disabled = true;
          $("#dedupBtn").disabled = true;
          const startScreenBtn = $("#startScreenBtn");
          if (startScreenBtn) startScreenBtn.disabled = true;
          $("#startProcessBtn").disabled = true;
          showToast("Workspace closed", "info");
        } catch (e) {
          showToast("Workspace close failed: " + e.message, "error");
        }
      });
    }
  }

  let openWorkspaceById = null;

  async function afterWorkspaceOpened(data) {
    updateWorkspaceUI(data);
    await refreshRecentWorkspaces();
    await refreshRefTable();
    await refreshPdfList();
    await loadReviewQueue();
    await loadWorkspaceExportsSummary();
    showToast("Workspace opened.", "success");
  }

  async function readonlyDropRecent(workspaceId, message) {
    // Best-effort: reload recent list so the card disappears if the backend
    // already pruned it. The backend keeps recent paths local-only and never
    // exposes absolute paths, so we do not delete files here.
    await refreshRecentWorkspaces();
    showToast(message, "info");
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

    const info = S.info[p] || {};
    const needsUrl = !!info.show_base_url;
    $("#baseUrlGroup").style.display = needsUrl ? "block" : "none";
    if (needsUrl && !$("#baseUrlInput").value) {
      $("#baseUrlInput").value = info.base_url || "";
    } else if (!needsUrl) {
      $("#baseUrlInput").value = "";
    }

    const infoHtml = [];
    if (info.privacy_label) {
      infoHtml.push(`<p class="privacy-label privacy-${info.privacy_level}">${info.privacy_label}</p>`);
    }
    if (info.privacy_note) {
      infoHtml.push(`<p class="privacy-note">${escHtml(info.privacy_note)}</p>`);
    }
    if (info.website && info.website !== "Custom") {
      infoHtml.push(`<p>Website: <a href="${info.website}" target="_blank" rel="noopener">${info.website}</a></p>`);
    }
    if (info.requires_api_key === false) {
      infoHtml.push(`<p style="color:var(--accept)">No API key required.</p>`);
    }
    if (info.free_tier === true) {
      infoHtml.push(`<p style="color:var(--accept)">Free tier available.</p>`);
    }
    if (info.model_id_guidance && info.model_id_guidance.latest_alias_warning) {
      infoHtml.push(`<p class="privacy-note">${escHtml(info.model_id_guidance.latest_alias_warning)}</p>`);
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
      S.refFileName = data.original_filename || data.filename || file.name;
      status.textContent = `Uploaded: ${data.original_filename || data.filename} (${(data.size / 1024).toFixed(1)} KB)`;
      showToast("Reference file uploaded", "success");
      $("#parseBtn").disabled = false;
    } catch (e) {
      status.textContent = "Upload failed: " + e.message;
      showToast("Upload failed", "error");
    }
  }

  function renderImportSummary(summary) {
    const panel = $("#importSummaryPanel");
    if (!panel) return;
    if (!summary) {
      panel.style.display = "none";
      panel.innerHTML = "";
      return;
    }

    const workspaceCounts = (S.workspace && S.workspace.counts) || {};
    const origins = workspaceCounts.records_by_origin || {};
    const activeOrigins = workspaceCounts.active_records_by_origin || origins;
    const parsedRows = summary.parsedRows ?? summary.recordsImported ?? workspaceCounts.raw_imported_records ?? 0;
    const savedRecords = summary.savedWorkspaceRecords ?? workspaceCounts.records ?? summary.recordsImported ?? 0;
    const activeUnique = summary.activeUniqueRecords ?? workspaceCounts.active_unique_records ?? activeOrigins.imported_reference ?? summary.kept ?? parsedRows;
    const duplicates = summary.duplicateRecords ?? summary.duplicates ?? workspaceCounts.duplicate_records ?? 0;
    const doiDuplicates = summary.doiDuplicates ?? 0;
    const fuzzyDuplicates = summary.fuzzyDuplicates ?? 0;
    const sourceCountText = S.workspace
      ? formatNumber(workspaceCounts.sources || summary.sourceCount || 0)
      : "Not persisted in legacy mode";
    const nextAction = summary.dedupRun
      ? "Next suggested action: start screening the deduplicated records."
      : "Next suggested action: run deduplication, then start screening.";
    const mainCopy = summary.dedupRun
      ? `Parsed ${formatNumber(parsedRows)} reference rows. Saved ${formatNumber(activeUnique)} active unique records after deduplication. ${formatNumber(duplicates)} duplicate records remain stored for audit/provenance but are hidden from active screening.`
      : `Parsed ${formatNumber(parsedRows)} reference rows. Saved ${formatNumber(savedRecords)} workspace records. Run deduplication before screening if this file came from multiple databases.`;

    panel.innerHTML = `
      <div class="import-summary-main">
        <div>
          <h4>Import summary</h4>
          <p>${escHtml(summary.filename || "Reference file")} parsed successfully. ${escHtml(mainCopy)}</p>
        </div>
        <div class="import-summary-actions">
          <button class="btn btn-sm btn-secondary" type="button" data-import-action="records">View imported records</button>
          <button class="btn btn-sm btn-secondary" type="button" data-import-action="duplicates" ${summary.dedupRun && duplicates ? "" : "disabled"}>View duplicates</button>
          <button class="btn btn-sm btn-primary" type="button" data-import-action="screen">Start screening</button>
        </div>
      </div>
      <div class="import-summary-grid">
        <span><strong>${escHtml(summary.filename || "Reference file")}</strong> imported file</span>
        <span><strong>${formatNumber(parsedRows)}</strong> parsed rows</span>
        <span><strong>${formatNumber(savedRecords)}</strong> saved workspace records</span>
        <span><strong>${formatNumber(activeUnique)}</strong> active unique records</span>
        <span><strong>${formatNumber(duplicates)}</strong> duplicate records hidden</span>
        <span><strong>${formatNumber(doiDuplicates)}</strong> DOI duplicates</span>
        <span><strong>${formatNumber(fuzzyDuplicates)}</strong> fuzzy-title duplicates</span>
        <span><strong>${escHtml(sourceCountText)}</strong> sources imported</span>
      </div>
      <p class="import-summary-next">${escHtml(nextAction)}</p>
    `;
    panel.style.display = "block";
  }

  function initImportSummaryActions() {
    const panel = $("#importSummaryPanel");
    if (!panel) return;
    panel.addEventListener("click", (e) => {
      const button = e.target.closest("[data-import-action]");
      if (!button) return;
      const action = button.dataset.importAction;
      if (action === "records") {
        $("#refTableCard")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (action === "duplicates") {
        showToast("Duplicate details are summarized in the deduplication counts for now.", "info");
      } else if (action === "screen") {
        $("#screenCriteria")?.focus();
        $("#startScreenBtn")?.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
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
        const workspaceCounts = data.workspace && data.workspace.summary ? data.workspace.summary.counts || {} : {};
        S.lastImportSummary = {
          filename: S.refFileName || "Reference file",
          recordsImported: data.count,
          parsedRows: data.count,
          savedWorkspaceRecords: data.workspace ? data.workspace.record_count : data.count,
          activeUniqueRecords: workspaceCounts.active_unique_records ?? data.count,
          duplicateRecords: workspaceCounts.duplicate_records ?? 0,
          sourceCount: workspaceCounts.sources || 0,
          dedupRun: false,
        };
stats.innerHTML = `<span class="stat-chip">${data.count} records found</span>`;
        $("#dedupBtn").disabled = false;
        $("#startScreenBtn").disabled = false;
        S.refState = { page: 1, perPage: S.refState.perPage || 50, q: "" };
        const search = $("#refSearchInput");
        if (search) search.value = "";
        await refreshRefTable();
        if (data.workspace && data.workspace.summary) {
          updateWorkspaceUI({ is_open: true, workspace: data.workspace.summary });
          await loadReviewQueue();
        }
        renderImportSummary(S.lastImportSummary);
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
        const workspaceCounts = data.workspace && data.workspace.summary ? data.workspace.summary.counts || {} : {};
        S.refCount = data.remaining;
        if (data.workspace && data.workspace.summary) {
          updateWorkspaceUI({ is_open: true, workspace: data.workspace.summary });
        }
        S.lastImportSummary = {
          ...(S.lastImportSummary || { filename: S.refFileName || "Reference file", recordsImported: s.total_before }),
          recordsImported: s.total_before,
          parsedRows: workspaceCounts.raw_imported_records ?? s.total_before,
          savedWorkspaceRecords: workspaceCounts.records ?? s.total_before,
          activeUniqueRecords: workspaceCounts.active_unique_records ?? s.total_after,
          duplicateRecords: workspaceCounts.duplicate_records ?? (s.removed_doi + s.removed_fuzzy),
          duplicates: s.removed_doi + s.removed_fuzzy,
          doiDuplicates: s.removed_doi,
          fuzzyDuplicates: s.removed_fuzzy,
          kept: s.total_after,
          sourceCount: workspaceCounts.sources || 0,
          dedupRun: true,
        };
        stats.innerHTML = `
          <span class="stat-chip">${s.total_before} imported</span>
          <span class="stat-chip exclude">${s.removed_doi + s.removed_fuzzy} duplicates</span>
          <span class="stat-chip include">${s.total_after} unique</span>
        `;
renderImportSummary(S.lastImportSummary);
        showToast(`Removed ${s.removed_doi + s.removed_fuzzy} duplicates`, "success");
        S.refState.page = 1;
        await refreshRefTable();
        if (S.workspace) await loadReviewQueue();
      } catch (e) {
        stats.innerHTML += ` <span style="color:var(--reject)">${e.message}</span>`;
        showToast("Deduplication failed: " + e.message, "error");
      }
      setButtonLoading(btn, false);
    });
  }

  async function refreshRefTable() {
    const st = S.refState;
    const params = new URLSearchParams();
    params.set("page", String(st.page));
    params.set("per_page", String(st.perPage));
    if (st.q) params.set("q", st.q);
    try {
      const resp = await api(`/api/references/list?${params.toString()}`);
      const data = await resp.json();
      S.refTotal = data.total || 0;
      S.refFilteredTotal = data.filtered_total != null ? data.filtered_total : data.total || 0;
      renderRefTable(data.records || [], data);
    } catch (e) {
      console.error(e);
    }
  }

  function renderRefTable(records, meta) {
    const card = $("#refTableCard");
    const body = $("#refTableBody");
    const showingEl = $("#refShowing");
    const emptyState = $("#refEmptyState");
    const card2 = $("#refTableCard");
    const totalForShowing = (meta && meta.filtered_total != null) ? meta.filtered_total : (meta && meta.total) || S.refFilteredTotal || S.refTotal || 0;
    const visible = records.length;
    if (showingEl) showingEl.textContent = `Showing ${formatNumber(visible)} of ${formatNumber(totalForShowing)} records${(meta && meta.query) ? " matching filter" : ""}`;

    if (!records || !records.length) {
      if (body) {
        body.innerHTML = `<tr><td colspan="6">
          <div class="empty-state">
            <h3>${(meta && meta.query) ? "No Records Match This Filter" : "No References Imported"}</h3>
            <p>${(meta && meta.query) ? "No records match this search. Clear the filter to see all imported references." : "No references imported yet. Upload and parse a reference file to populate the list."}</p>
            ${(meta && meta.query) ? `<button class="btn btn-sm btn-secondary" type="button" id="refEmptyClearBtn">Clear filter</button>` : ""}
          </div>
        </td></tr>`;
        const clr = $("#refEmptyClearBtn");
        if (clr) clr.addEventListener("click", clearRefFilter);
      }
      if (card) card.style.display = "block";
      if (emptyState) emptyState.style.display = "none";
      updateRefPager(meta);
      return;
    }
    if (card) card.style.display = "block";
    if (emptyState) emptyState.style.display = "none";
    const startIdx = ((S.refState.page - 1) * S.refState.perPage);
    body.innerHTML = records.map((r, i) => `
      <tr>
        <td>${startIdx + i + 1}</td>
        <td class="cell-truncate">${escHtml(r.title)}</td>
        <td class="cell-truncate">${escHtml(r.authors)}</td>
        <td>${escHtml(r.year)}</td>
        <td>${r.decision ? decisionBadge(r.decision) : "—"}</td>
        <td class="cell-truncate">${escHtml(r.rationale || "")}</td>
      </tr>
    `).join("");
    updateRefPager(meta);
  }

  function updateRefPager(meta) {
    const prev = $("#refPrevPageBtn");
    const next = $("#refNextPageBtn");
    const info = $("#refPageInfo");
    const page = S.refState.page;
    const filtered = (meta && meta.filtered_total != null) ? meta.filtered_total : S.refFilteredTotal || 0;
    const perPage = S.refState.perPage;
    const totalPages = Math.max(1, Math.ceil((filtered || 0) / perPage));
    if (info) info.textContent = `Page ${formatNumber(page)} of ${formatNumber(totalPages)}`;
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= totalPages;
  }

  function clearRefFilter() {
    S.refState.q = "";
    S.refState.page = 1;
    const search = $("#refSearchInput");
    if (search) search.value = "";
    refreshRefTable();
  }

  function initRefListControls() {
    const search = $("#refSearchInput");
    const pageSize = $("#refPageSize");
    const clear = $("#refClearFilterBtn");
    const prev = $("#refPrevPageBtn");
    const next = $("#refNextPageBtn");
    if (search) {
      let debounceId = null;
      search.addEventListener("input", () => {
        if (debounceId) clearTimeout(debounceId);
        debounceId = setTimeout(() => {
          S.refState.q = (search.value || "").trim();
          S.refState.page = 1;
          refreshRefTable();
        }, 300);
      });
    }
    if (pageSize) {
      pageSize.addEventListener("change", () => {
        S.refState.perPage = parseInt(pageSize.value, 10) || 50;
        S.refState.page = 1;
        refreshRefTable();
      });
    }
    if (clear) clear.addEventListener("click", clearRefFilter);
    if (prev) prev.addEventListener("click", () => {
      if (S.refState.page > 1) { S.refState.page--; refreshRefTable(); }
    });
    if (next) next.addEventListener("click", () => {
      S.refState.page++; refreshRefTable();
    });
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
              if (S.workspace) await loadReviewQueue();
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

    $("#includeSubfoldersCheck").addEventListener("change", refreshPdfList);

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
      if (data.workspace) await refreshWorkspaceState();
      $("#startProcessBtn").disabled = false;
    } catch (e) {
      status.textContent = "Upload failed: " + e.message;
      showToast("Upload failed: " + e.message, "error");
    }
  }

  async function refreshPdfList() {
    try {
      const includeSubfolders = $("#includeSubfoldersCheck").checked;
      const resp = await api(`/api/pdfs/list?include_subfolders=${includeSubfolders ? "1" : "0"}`);
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
    const emptyState = $("#pdfEmptyState");

    S.pdfCount = files.length;
    badge.textContent = files.length;

    if (!files.length) {
      card.style.display = "none";
      $("#startProcessBtn").disabled = true;
      if (emptyState) emptyState.style.display = "block";
      return;
    }
    if (emptyState) emptyState.style.display = "none";

    card.style.display = "block";
    body.innerHTML = files.map((f, i) => `
      <tr>
        <td style="color:var(--ink-muted);font-family:var(--font-mono);font-size:0.8rem">${i + 1}</td>
        <td class="pdf-filename">${escHtml(f.display_name || f.name)}</td>
        <td class="pdf-size">${formatBytes(f.size)}</td>
        <td>
          <div style="display:flex;gap:var(--sp-2)">
            <button class="pdf-action-btn" data-action="view" data-name="${escHtml(f.name)}" data-display="${escHtml(f.display_name || f.name)}" title="Open PDF in new tab">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              View
            </button>
            <button class="pdf-action-btn del" data-action="delete" data-name="${escHtml(f.name)}" data-display="${escHtml(f.display_name || f.name)}" title="Delete this PDF">
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
        const displayName = btn.dataset.display || name;
        if (action === "view") {
          window.open(`/api/pdfs/file/${encodeURIComponent(name)}`, "_blank");
        } else if (action === "delete") {
          if (!confirm(`Delete "${displayName}"?`)) return;
          try {
            const resp = await api("/api/pdfs/delete", {
              method: "POST",
              body: {
                filename: name,
                include_subfolders: $("#includeSubfoldersCheck").checked,
              },
            });
            const data = await resp.json();
            if (data.error) { showToast(data.error, "error"); return; }
            showToast(`Deleted ${displayName}`, "info");
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
        include_subfolders: $("#includeSubfoldersCheck").checked,
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
            if (d.error) {
              clearInterval(pollId);
              logLine("Processing failed: " + d.error);
              setButtonLoading($("#startProcessBtn"), false);
              $("#stopProcessBtn").disabled = true;
              loadResults();
              showToast("Processing failed: " + d.error, "error");
              return;
            }
            if (!d.active) {
              clearInterval(pollId);
              if (d.report_errors && d.report_errors.length) {
                logLine("Processing completed, but report generation needs attention: " + d.report_errors.join("; "));
              } else {
                logLine("Processing complete.");
              }
              setButtonLoading($("#startProcessBtn"), false);
              $("#stopProcessBtn").disabled = true;
              loadResults();
              showToast(d.report_errors && d.report_errors.length ? "Processing complete with report warnings" : "Processing complete", d.report_errors && d.report_errors.length ? "error" : "success");
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
    const counters = d.counters || {};
    const total = counters.total_files || stats.total_files || 1;
    const processed = counters.processed_files ?? stats.processed_files ?? 0;
    const pct = Math.round((processed / total) * 100);

    const bar = $("#processProgressBar");
    bar.style.width = pct + "%";
    $("#processProgressText").textContent = `${processed}/${total} (${pct}%)`;

    $("#kpiProcessed").textContent = processed;
    $("#kpiInclude").textContent = counters.included ?? stats.likely_include ?? 0;
    $("#kpiExclude").textContent = counters.excluded ?? stats.likely_exclude ?? 0;
    $("#kpiFlag").textContent = counters.flagged ?? ((stats.flag_for_review || 0) + (stats.flag_for_human_review || 0));
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
  // Workspace review queue
  // ═══════════════════════════════════════════════════════════════════════
  function statusBadge(status) {
    const clean = (status || "pending").toLowerCase();
    return `<span class="status-badge ${escHtml(clean)}">${escHtml(clean)}</span>`;
  }

  function renderReviewSummary(summary) {
    const el = $("#reviewSummaryChips");
    if (!el) return;
    const counts = (summary && summary.by_status) || {};
    const order = ["pending", "suggested", "included", "excluded", "maybe", "failed"];
    el.innerHTML = order.map((key) => `
      <span class="review-summary-chip">${escHtml(key)} ${formatNumber(counts[key] || 0)}</span>
    `).join("");
  }

  function reviewFilterQuery() {
    const params = new URLSearchParams();
    const stage = $("#reviewStageFilter") ? $("#reviewStageFilter").value : "";
    const status = $("#reviewStatusFilter") ? $("#reviewStatusFilter").value : "";
    const origin = $("#reviewOriginFilter") ? $("#reviewOriginFilter").value : "";
    if (stage) params.set("stage", stage);
    if (status) params.set("status", status);
    if (origin) params.set("origin", origin);
    const text = params.toString();
    return text ? `?${text}` : "";
  }

  async function loadReviewQueue() {
    const card = $("#workspaceReviewCard");
    if (!card) return;
    if (!S.workspace) {
      card.style.display = "none";
      return;
    }

    try {
      const resp = await api(`/api/workspace/review/queue${reviewFilterQuery()}`);
      const data = await resp.json();
      if (data.error) throw new Error(data.error);
      S.reviewSummary = data.summary || null;
      S.lastQueueMeta = data;
      if (S.workspace && data.workspace_counts) {
        S.workspace.counts = { ...(S.workspace.counts || {}), ...data.workspace_counts };
      }
      S.exclusionReasons = (data.summary && data.summary.exclusion_reasons) || [];
      renderReviewSummary(S.reviewSummary);
      renderReviewQueueContext(data);
      renderWorkspaceProgress();
      renderReviewQueue(data.items || [], data);
      card.style.display = "block";
    } catch (e) {
      card.style.display = "none";
    }
  }

  function renderReviewQueueContext(data) {
    const meta = $("#reviewQueueMeta");
    const explanation = $("#reviewQueueExplanation");
    if (!meta || !explanation) return;

    const filter = data.current_filter || {};
    const counts = data.workspace_counts || (S.workspace && S.workspace.counts) || {};
    const origins = data.records_by_origin || data.active_records_by_origin || counts.active_records_by_origin || counts.records_by_origin || {};
    const visible = data.visible_count ?? (data.items || []).length;
    const total = data.total_count ?? visible;
    const activeReviewItems = data.active_review_item_count ?? (S.reviewSummary && S.reviewSummary.total_count) ?? counts.review_items ?? total;
    const activeUniqueRecords = data.active_unique_records ?? counts.active_unique_records ?? 0;
    const duplicateRecords = data.duplicate_records ?? counts.duplicate_records ?? 0;
    const activeImported = data.imported_reference_records ?? origins.imported_reference ?? 0;
    const pdfOnly = data.pdf_only_records ?? origins.pdf_only ?? 0;
    const manualRecords = data.manual_records ?? origins.manual ?? 0;
    const stage = filter.stage || "";
    const status = filter.status || "";
    const origin = filter.record_origin || "";
    const activeFilters = [
      stage ? `Stage = ${stageLabel(stage)}` : "",
      status ? `Status = ${statusLabel(status)}` : "",
      origin ? `Origin = ${originLabel(origin)}` : "",
    ].filter(Boolean);

meta.innerHTML = [
      `Stage: ${stage ? stageLabel(stage) : "All stages"}`,
      `Status: ${status ? statusLabel(status) : "All statuses"}`,
      `Origin: ${origin ? originLabel(origin) : "All origins"}`,
      `Visible review items: ${formatNumber(visible)}`,
      `Active review items: ${formatNumber(activeReviewItems)}`,
      `Active unique records: ${formatNumber(activeUniqueRecords)}`,
      `Active unique imported refs: ${formatNumber(activeImported)}`,
      `PDF-only records: ${formatNumber(pdfOnly)}`,
      `Manual records: ${formatNumber(manualRecords)}`,
      `Duplicates hidden: ${formatNumber(duplicateRecords)}`,
    ].map((text) => `<span>${escHtml(text)}</span>`).join("");

    const showingEl = $("#reviewQueueShowing");
    if (showingEl) {
      showingEl.textContent = `Showing ${formatNumber(visible)} of ${formatNumber(activeReviewItems)} review items`;
    }

    const duplicateCopy = duplicateRecords
      ? ` ${formatNumber(duplicateRecords)} duplicate records are stored for audit but hidden from active screening.`
      : "";
    if (origin === "pdf_only") {
      explanation.textContent = `Showing ${formatNumber(visible)} PDF-only records. These were created from PDFs without imported reference metadata, are usable in the review queue, and are counted separately from imported database/reference records.${duplicateCopy}`;
    } else if (!activeReviewItems) {
      explanation.textContent = "No review items yet. Import references and run screening to create review items.";
    } else if (!visible && activeFilters.length) {
      explanation.textContent = `No records match this filter. Clear filters to see all items.${duplicateCopy}`;
    } else if (activeFilters.length) {
      explanation.textContent = `Showing ${formatNumber(visible)} of ${formatNumber(activeReviewItems)} active review items because ${activeFilters.join(" and ")}.${duplicateCopy}`;
    } else {
      explanation.textContent = `Showing ${formatNumber(visible)} of ${formatNumber(activeReviewItems)} active review items. AI suggestions must be checked before use.${duplicateCopy}`;
    }
  }

  function renderDecisionBlock(decision, kind) {
    const label = kind === "ai" ? "AI suggestion — not final" : "Human decision — final";
    if (!decision) {
      const text = kind === "ai" ? "No AI suggestion yet" : "Needs human review";
      return `<div class="review-decision-block empty">
        <div class="review-decision-label">${escHtml(label)}</div>
        <span class="info-muted">${escHtml(text)}</span>
      </div>`;
    }
    const meta = [decision.provider, decision.model].filter(Boolean).join(" / ");
    return `
      <div class="review-decision-block ${kind === "human" ? "human" : "ai"}">
        <div class="review-decision-label">${escHtml(label)}</div>
        ${decisionBadge(decision.decision)}
        ${decision.rationale ? `<div class="review-rationale-text">${escHtml(decision.rationale)}</div>` : ""}
        ${meta ? `<div class="review-item-meta">${escHtml(meta)}</div>` : ""}
      </div>
    `;
  }

  function reviewReasonOptions(selected = "") {
    const options = S.exclusionReasons.map((reason) => `
      <option value="${escHtml(reason.reason_id)}" ${reason.reason_id === selected ? "selected" : ""}>
        ${escHtml(reason.label)}
      </option>
    `).join("");
    return `<option value="">Exclusion reason</option>${options}`;
  }

  function renderReviewQueue(items, data = {}) {
    const body = $("#reviewQueueBody");
    if (!body) return;
    if (!items.length) {
      const total = data.active_review_item_count ?? data.total_count ?? 0;
      const currentFilter = data.current_filter || {};
      const hasFilter = !!(currentFilter.stage || currentFilter.status || currentFilter.record_origin);
      const message = total
        ? "No records match this filter. Clear filters to see all items."
        : "No review items yet. Import references and run screening to create review items.";
      body.innerHTML = `<tr><td colspan="6">
        <div class="empty-state">
          <h3>${hasFilter ? "No Records Match This Filter" : "No Review Items Yet"}</h3>
          <p>${escHtml(message)}</p>
          ${hasFilter ? `<button class="btn btn-sm btn-secondary" type="button" id="emptyClearReviewFiltersBtn">Clear filters</button>` : ""}
        </div>
      </td></tr>`;
      const clear = $("#emptyClearReviewFiltersBtn");
      if (clear) clear.addEventListener("click", clearReviewFilters);
      return;
    }

    body.innerHTML = items.map((item) => {
      const ai = item.latest_ai_suggestion;
      const human = item.latest_human_decision;
      const title = item.display_title || item.title || item.pdf_display_name || item.record_id;
      const meta = [item.authors, item.year, item.pdf_display_name].filter(Boolean).join(" · ");
      const origin = item.record_origin || "";
      const reasonSelected = human && human.exclusion_reason_id ? human.exclusion_reason_id : "";
      const isFullText = item.stage === "full_text";
      const hasHuman = human ? "1" : "0";
      const acceptDisabled = !ai || ai.decision === "failed" ? "disabled" : "";
      return `
        <tr data-item="${escHtml(item.item_id)}" data-stage="${escHtml(item.stage)}" data-has-human="${hasHuman}">
          <td>
            <div class="review-item-title">${escHtml(title)}</div>
            ${meta ? `<div class="review-item-meta">${escHtml(meta)}</div>` : ""}
            ${origin ? `<div class="review-item-meta"><span class="origin-badge ${escHtml(origin)}">${originLabel(origin)}</span></div>` : ""}
            ${origin === "pdf_only" ? `<div class="review-origin-note">This record was created from a PDF without imported reference metadata. It is usable in the review queue and counted separately from imported database/reference records.</div>` : ""}
          </td>
          <td><span class="review-stage">${stageLabel(item.stage)}</span></td>
          <td>${statusBadge(item.status)}</td>
          <td>${renderDecisionBlock(ai, "ai")}</td>
          <td>${renderDecisionBlock(human, "human")}</td>
          <td>
            <textarea class="input-textarea review-rationale" rows="1" placeholder="Rationale or note"></textarea>
            <select class="input-select input-sm review-reason-select" ${isFullText ? "" : "disabled"}>
              ${reviewReasonOptions(reasonSelected)}
            </select>
            ${isFullText ? `<div class="review-action-hint">Full-text exclusions should include a reason.</div>` : ""}
            <div class="review-action-row">
              <button class="btn btn-secondary" type="button" data-review-action="accept" ${acceptDisabled}>Finalize from suggestion</button>
              <button class="btn btn-secondary" type="button" data-review-action="include">Include</button>
              <button class="btn btn-danger" type="button" data-review-action="exclude">Exclude</button>
              <button class="btn btn-secondary" type="button" data-review-action="maybe">Maybe</button>
            </div>
          </td>
        </tr>
      `;
    }).join("");
  }

  function clearReviewFilters() {
    if ($("#reviewStageFilter")) $("#reviewStageFilter").value = "";
    if ($("#reviewStatusFilter")) $("#reviewStatusFilter").value = "";
    if ($("#reviewOriginFilter")) $("#reviewOriginFilter").value = "";
    loadReviewQueue();
  }

  async function submitReviewAction(button) {
    const row = button.closest("tr");
    if (!row) return;
    const action = button.dataset.reviewAction;
    const itemId = row.dataset.item;
    const stage = row.dataset.stage;
    const hasHuman = row.dataset.hasHuman === "1";
    const rationale = row.querySelector(".review-rationale")?.value || "";
    const reason = row.querySelector(".review-reason-select")?.value || "";

    if (stage === "full_text" && action === "exclude" && !reason) {
      showToast("Choose an exclusion reason for full-text excludes.", "error");
      return;
    }

    const endpoint = action === "accept"
      ? "/api/workspace/review/accept-ai"
      : (hasHuman ? "/api/workspace/review/override" : "/api/workspace/review/decision");
    const body = {
      review_item_id: itemId,
      rationale,
    };
    if (action !== "accept") body.decision = action;
    if (reason) body.exclusion_reason_id = reason;

    setButtonLoading(button, true, "Saving...");
    try {
      const resp = await api(endpoint, { method: "POST", body });
      const data = await resp.json();
      if (data.error) throw new Error(data.error);
      showToast("Review decision saved", "success");
      await loadReviewQueue();
    } catch (e) {
      showToast("Decision failed: " + e.message, "error");
    }
    setButtonLoading(button, false);
  }

  function initReviewQueue() {
    const stage = $("#reviewStageFilter");
    const filter = $("#reviewStatusFilter");
    const origin = $("#reviewOriginFilter");
    const refresh = $("#refreshReviewQueueBtn");
    const clear = $("#clearReviewFiltersBtn");
    const showAll = $("#showAllReviewItemsBtn");
    const body = $("#reviewQueueBody");
    if (stage) stage.addEventListener("change", loadReviewQueue);
    if (filter) filter.addEventListener("change", loadReviewQueue);
    if (origin) origin.addEventListener("change", loadReviewQueue);
    if (refresh) refresh.addEventListener("click", loadReviewQueue);
    if (clear) clear.addEventListener("click", clearReviewFilters);
    if (showAll) showAll.addEventListener("click", clearReviewFilters);
    if (body) {
      body.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-review-action]");
        if (btn) submitReviewAction(btn);
      });
    }
  }

  // Workspace exports
  async function loadWorkspaceExportsSummary() {
    const card = $("#workspaceExportCard");
    if (!card) return;
    if (!S.workspace) {
      card.style.display = "none";
      return;
    }
    card.style.display = "block";
    try {
      const resp = await api("/api/workspace/exports/summary");
      const data = await resp.json();
      const latest = data.latest_export || null;
      S.workspaceExports = latest ? [latest] : [];
      renderWorkspaceExports(latest, data.counts || null);
    } catch (e) {
      $("#workspaceExportMeta").textContent = "Workspace export status unavailable.";
      $("#workspaceExportFiles").innerHTML = "";
    }
  }

  async function loadWorkspaceExportsList() {
    if (!S.workspace) return;
    try {
      const resp = await api("/api/workspace/exports/list");
      const data = await resp.json();
      S.workspaceExports = data.exports || [];
      renderWorkspaceExports(S.workspaceExports[0] || null, null);
    } catch (e) {
      showToast("Could not load workspace exports: " + e.message, "error");
    }
  }

  function renderWorkspaceExports(latest, counts) {
    const meta = $("#workspaceExportMeta");
    const files = $("#workspaceExportFiles");
    if (!meta || !files) return;

    const countData = counts && counts.counts ? counts.counts : {};
    const aiOnly = countData.ai_only_unfinalized_suggestions ? countData.ai_only_unfinalized_suggestions.value : null;
    const activeImported = countData.active_unique_imported_references ? countData.active_unique_imported_references.value : null;
    const countText = counts
      ? `Current PRISMA-ready count snapshot: ${formatNumber(activeImported)} active unique imported references; ${formatNumber(aiOnly)} AI-only unfinalized suggestions.`
      : "";

    if (!latest) {
      meta.textContent = countText || "No workspace export generated yet.";
      files.innerHTML = "";
      return;
    }

    meta.textContent = `Latest export: ${latest.created_at || latest.export_id}. ${countText}`;
    const exportId = latest.export_id || "";
    files.innerHTML = (latest.files || []).map((file) => `
      <button class="workspace-export-file" type="button"
              data-export-id="${escHtml(exportId)}"
              data-export-filename="${escHtml(file.filename)}">
        <span>${escHtml(file.filename)}</span>
        <small>${formatNumber(file.bytes || 0)} bytes</small>
      </button>
    `).join("");
  }

  async function generateWorkspaceExports() {
    const btn = $("#generateWorkspaceExportsBtn");
    if (!S.workspace) {
      showToast("Open a workspace before generating workspace exports.", "error");
      return;
    }
    setButtonLoading(btn, true, "Generating...");
    try {
      const resp = await api("/api/workspace/exports/generate", { method: "POST", body: {} });
      const data = await resp.json();
      const latest = data.export || null;
      S.workspaceExports = latest ? [latest] : [];
      renderWorkspaceExports(latest, null);
      showToast("Workspace exports generated.", "success");
    } catch (e) {
      showToast("Workspace export failed: " + e.message, "error");
    }
    setButtonLoading(btn, false);
  }

  async function downloadWorkspaceExport(exportId, filename) {
    try {
      const resp = await fetch(`/api/workspace/exports/download/${encodeURIComponent(exportId)}/${encodeURIComponent(filename)}`);
      if (!resp.ok) {
        let message = `HTTP ${resp.status}`;
        if (resp.headers.get("content-type")?.includes("json")) {
          const err = await resp.json();
          message = err.error || message;
        }
        throw new Error(message);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      showToast("Download failed: " + e.message, "error");
    }
  }

  function initWorkspaceExports() {
    const generateBtn = $("#generateWorkspaceExportsBtn");
    const refreshBtn = $("#refreshWorkspaceExportsBtn");
    const files = $("#workspaceExportFiles");
    if (generateBtn) generateBtn.addEventListener("click", generateWorkspaceExports);
    if (refreshBtn) refreshBtn.addEventListener("click", loadWorkspaceExportsList);
    if (files) {
      files.addEventListener("click", (e) => {
        const button = e.target.closest(".workspace-export-file");
        if (!button) return;
        downloadWorkspaceExport(button.dataset.exportId || "", button.dataset.exportFilename || "");
      });
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
    initReviewQueue();
    initWorkspaceExports();
  }

  async function loadResults() {
    try {
      const resp = await api("/api/processing/results");
      const data = await resp.json();
      renderScreeningResults(data.screening || []);
      renderExtractionResults(data.extraction || []);
      updateProcessingSummary(data.screening || []);
      if (S.workspace) await loadReviewQueue();
      if (S.workspace) await loadWorkspaceExportsSummary();
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
    body.innerHTML = results.map((r) => {
      const filename = r.display_filename || r.filename || "";
      const reason = r.reasoning || r.rationale || r.error || "";
      const searchText = `${filename} ${r.title || ""} ${reason}`.toLowerCase();
      return `
      <tr data-decision="${r.decision || ""}" data-search="${escHtml(searchText)}">
        <td class="cell-truncate">${escHtml(filename)}</td>
        <td>${decisionBadge(r.decision)}</td>
        <td>${escHtml(r.stage || "")}</td>
        <td class="cell-truncate">${escHtml(reason)}</td>
        <td style="font-family:var(--font-mono);font-size:0.8rem">${r.processing_time ? r.processing_time.toFixed(1) + "s" : "—"}</td>
        <td style="font-family:var(--font-mono);font-size:0.8rem">${formatNumber(r.api_tokens_used)}</td>
      </tr>
    `;
    }).join("");

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
        const val = k === "filename" ? (r.display_filename || r.filename) : (r.fields || {})[k] || "";
        return `<td class="cell-truncate">${escHtml(String(val))}</td>`;
      });
      return `<tr>${cells.join("")}</tr>`;
    }).join("");
  }

  function updateProcessingSummary(screening) {
    if (!screening.length) return;
    const total = screening.length;
    let inc = 0, exc = 0;
    screening.forEach((r) => {
      const d = (r.decision || "").toLowerCase();
      if (d.includes("include")) inc++;
      if (d.includes("exclude")) exc++;
    });

    $("#processingIdentified").textContent = total;
    $("#processingScreened").textContent = total;
    $("#processingIncluded").textContent = inc;
    $("#processingExcluded").textContent = exc;
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

    title.textContent = result.display_filename || result.filename || "Paper Details";
    let html = "";

    const fields = [
      ["Decision", result.decision],
      ["Stage", result.stage],
      ["Reasoning", result.reasoning],
      ["Notes", result.notes],
      ["Error", result.error],
      ["Extraction Status", result.extraction_status],
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
    initWorkspace();
    initConfigHandlers();
initRefUpload();
    initImportSummaryActions();
    initRefActions();
    initRefListControls();
    initScreening();
    initPdfUpload();
    initProcessing();
    initResults();
    initModal();
    initHelp();
    initEnhanceButtons();

    await loadProviders();
    await loadSettings();
    await refreshWorkspaceState();
    autoSaveSettings();
  });
})();

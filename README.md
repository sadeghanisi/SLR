# Universal SLR Assistant

<div align="center">

[![Version](https://img.shields.io/badge/version-3.5.2-blue?style=for-the-badge)](https://github.com/sadeghanisi/SLR/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=for-the-badge&logo=python)](https://python.org)
[![Providers](https://img.shields.io/badge/AI%20Providers-13-purple?style=for-the-badge)](#ai-provider-quick-reference)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge)](#quick-start)
[![WebApp](https://img.shields.io/badge/WebApp-local--only-orange?style=for-the-badge)](#web-application)

**AI-assisted systematic/scoping review workflow for screening, extraction, and reproducible outputs.**

[Quick Start](#quick-start) | [Web App](#web-application) | [Full Guide](COMPLETE_USER_GUIDE.md) | [Issues](https://github.com/sadeghanisi/SLR/issues) | [Features](#features)

</div>

---

Universal SLR Assistant is a local-first, privacy-conscious tool for individual researchers running systematic or scoping review workflows on their own computer. It supports reference ingestion, deduplication, title/abstract screening, full-text PDF screening, structured extraction, JSON caching, audit ledgers, and a local Workspace mode for persistent project state. It is available as both a desktop GUI and a browser-based local Web App.

The AI assists the review process; it does not replace human reviewers. In Workspace mode, LLM screening output is stored as a suggestion only. Researchers remain responsible for final inclusion/exclusion/maybe decisions, extracted data verification, PRISMA reporting, and methodological integrity.

> New to this tool? Read [COMPLETE_USER_GUIDE.md](COMPLETE_USER_GUIDE.md) for a beginner-friendly walkthrough.

---

## Author

**Farahnaz Yazdanpanah Faragheh**
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Profile-blue?style=flat&logo=linkedin)](https://www.linkedin.com/in/farahnaz-yazdanpanah-faragheh-sleep-researcher/)

---

## Features

### Multi-LLM Support

The provider catalog uses a small set of native adapters plus OpenAI-compatible profiles. Built-in model names are recommendations only; users can manually type any valid model ID supported by their provider.

- **Native providers:** OpenAI, Anthropic Claude, Google Gemini, Ollama / Local
- **OpenAI-compatible profiles:** OpenRouter, DeepSeek, Mistral, Kimi / Moonshot, Grok / xAI, LM Studio, vLLM, LocalAI, and Custom OpenAI-Compatible endpoints
- **Privacy labels:** `local_only`, `direct_cloud`, `router_third_party`, `custom_endpoint`
- **Manual model IDs:** Newly released or custom model IDs can be typed directly without code changes

Router profiles such as OpenRouter send paper text through an additional third party before it reaches the selected model provider. Ollama and other local endpoints are the most privacy-preserving option because paper text can stay on your own computer.

### Reference Ingestion and Deduplication

- Import RIS, BibTeX, CSV, and plain text reference files
- Deduplicate with DOI matching and fuzzy title matching
- Optionally screen titles/abstracts before collecting full PDFs

### Workspace Mode and Human Review

- Create, open, close, and reopen local review workspaces in the Web App
- Store references, source provenance, PDF metadata, review items, decisions, and audit events in `workspace.sqlite3`
- Keep imported reference files under workspace `imports/` and uploaded PDFs under workspace `pdfs/`
- Track record origin as imported reference, PDF-only, or manual so workspace counts can distinguish database/reference imports from PDFs added without reference metadata
- Show a workspace progress panel with persistent counts for sources, records, PDFs, review items, AI suggestions, human decisions, and pending/final statuses
- Show AI suggestions separately from human final decisions
- Persist human Include / Exclude / Maybe decisions with rationale and reviewer metadata
- Require an exclusion reason for full-text excludes
- Generate workspace reporting data under workspace `exports/`, including decision CSV/XLSX files, AI and human decision exports, full-text exclusion exports, PRISMA-ready counts, a methods disclosure draft, and an export manifest

Workspace mode is currently WebApp-first. The Desktop GUI remains available with the existing run-based workflow.

When no workspace is open, the Web App remains in Legacy Mode for one-off runs. Legacy Mode is useful for quick processing, but it is not a persistent review project and does not populate the workspace review queue.

### Full-Text Processing and Extraction

- PDF text extraction cascade: PyMuPDF4LLM, pdfplumber, then PyPDF2 fallback
- Two-stage screening option: title/abstract-like pass, then full-text pass
- Structured data extraction using configurable extraction fields
- JSON cache to avoid repeat LLM calls when the same inputs/configuration are reused
- Excel, CSV, summary report, and audit ledger outputs

### Local-First Privacy and Safety

- Desktop GUI and Web App are designed for local use on the researcher's own computer
- The Web App binds to `127.0.0.1` and is not intended for public deployment or multi-user hosting
- Desktop GUI does not write API keys to `settings.json`
- Web App does not write API keys to `webapp_settings.json`
- Legacy `.pkl` cache files are not loaded automatically at runtime

---

## Web Application

The browser-based interface is located in `WebApp/`. It is a local-only UI for a researcher running the tool on their own computer at `127.0.0.1`. It is not a production web service and should not be hosted publicly without a separate security review and substantial redesign.

### Web App Features

| Feature | Description |
|---|---|
| 4-stage pipeline UI | Configure, Ingest, Process, Results |
| AI Enhance buttons | Optional AI improvement for criteria, prompts, and extraction fields using the current session key |
| PDF file manager | Upload PDFs, view the list, open in browser, delete individually, or clear all |
| Custom model input | Type any valid model ID supported by the selected provider |
| Privacy metadata | Shows where paper text is sent: local only, direct cloud, router / third party, or custom endpoint |
| Workspace shell | Create/open/close local workspaces and reopen recent workspaces |
| Workspace progress | Shows DB-backed counts for imported references, PDF-only records, manual records, PDFs, sources, review items, AI suggestions, and human decisions |
| Review queue | Persist AI suggestions and human decisions in workspace mode, with status/stage/origin filters and visible-vs-total count explanations |
| Workspace exports | Generates workspace reporting data, PRISMA-ready counts, methods disclosure text, and auditable CSV/XLSX/JSON/MD files from the workspace database |
| Real-time monitor | Live progress, decision counters, processing log, and export status |
| Local settings | Provider, model, Base URL, and criteria can persist; API keys are not saved |
| AI processing run summary | Displays run-level identified, screened, included, excluded, flagged, and failed counts. These are not human-final PRISMA-ready counts |

Version `3.5.2` adds a redesigned Workspace start screen and navigation, a persistent human review queue foundation, AI suggestions treated as non-final, human Include / Exclude / Maybe decisions as final, reference-list search/pagination with `Showing X of Y` copy, recent workspace cards, and workspace export generation for PRISMA-ready reporting data and a methods disclosure draft. AI suggestions are not final decisions in workspace mode; a human Include / Exclude / Maybe decision is required.

If the review queue shows fewer records than you imported, check the queue filters. For example, importing 900 references may still show only 5 queue rows when Status is set to Suggested, or when the origin filter is set to PDF-only records.

### Launch the Web App

**Windows:**

```bat
REM From the WebApp directory:
run.bat
```

**Manual:**

```bash
# Activate your virtual environment first:
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows

cd WebApp
python app.py
```

Then open `http://127.0.0.1:5000` in your browser. Keep it bound to localhost.

---

## Quick Start

### 1. Install

**Windows:**

```bat
setup.bat
```

**Manual:**

```bash
git clone https://github.com/sadeghanisi/SLR.git
cd SLR

python -m venv .venv

# Windows:
.venv\Scripts\activate

# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Launch

**Desktop GUI:**

```bash
python slr_gui.py
```

**Web App:**

```bash
cd WebApp
python app.py
```

Then open `http://127.0.0.1:5000`.

### 3. Configure an AI Provider

- Select a provider.
- Enter an API key if the provider requires one.
- Choose a recommended model or manually type any valid model ID.
- Click **Test Connection**.

For maximum privacy, use **Ollama (Local)** or another local endpoint. For cloud providers, extracted paper text may be sent to the provider API. Router profiles add an additional third party.

### 4. Ingest References

Use the desktop **Ingestion** tab or Web App **Ingest** stage to load RIS, BibTeX, CSV, or text reference exports. Deduplicate records and optionally screen titles/abstracts.

### 5. Process PDFs

Use the desktop **Setup** tab or Web App **Process** stage to select or upload PDFs, set criteria, and start processing. Review decisions and exported files before using results in research outputs.

---

## AI Provider Quick Reference

| Provider | Privacy level | Adapter type | Model behavior |
|---|---|---|---|
| OpenAI | `direct_cloud` | Native | Recommended defaults plus manual model IDs |
| Anthropic Claude | `direct_cloud` | Native | Recommended models are configurable guidance |
| Google Gemini | `direct_cloud` | Native | Prefer stable model IDs for reproducibility |
| OpenRouter | `router_third_party` | OpenAI-compatible profile | Router slugs and aliases accepted; adds third party |
| DeepSeek | `direct_cloud` | OpenAI-compatible profile | Manual model IDs accepted |
| Mistral | `direct_cloud` | OpenAI-compatible profile | Manual model IDs accepted |
| Kimi / Moonshot | `direct_cloud` | OpenAI-compatible profile | Manual model IDs accepted |
| Grok / xAI | `direct_cloud` | OpenAI-compatible profile | Manual model IDs accepted |
| Ollama | `local_only` | Native local | Local model names discovered or typed manually |
| LM Studio | `local_only` | OpenAI-compatible profile | Local/custom model IDs |
| vLLM | `custom_endpoint` | OpenAI-compatible profile | Local or custom hosted model IDs |
| LocalAI | `custom_endpoint` | OpenAI-compatible profile | Local or custom model IDs |
| Custom OpenAI-Compatible | `custom_endpoint` | OpenAI-compatible adapter | User supplies Base URL and model ID |

Provider pricing changes frequently; always check the provider pricing page before large runs. Token usage depends on paper length, selected model, prompt size, extraction fields, cache hits, and retry behavior.

---

## Cache and Auditability

Runtime cache loading is JSON-only. Old `.pkl` cache files are not loaded automatically because pickle files can execute unsafe data if tampered with.

Cache keys are configuration-aware. Changing any of the following creates a different cache entry:

- Normalized paper text hash
- Screening or extraction stage
- Provider/profile
- Model ID
- Prompt hash
- Extraction fields hash
- Advanced configuration hash
- Cache schema and app/pipeline version

Each run writes an audit ledger such as `audit_YYYYMMDD_HHMMSS.jsonl` in the output folder. Audit records include non-secret metadata such as provider, model, prompt hash, text hash, cache key, cache hit/miss, parse status, retry count, token count when available, and error category if a call fails.

The audit ledger does not store API keys, raw secrets, full prompts, or full paper text.

---

## Project Structure

```text
SLR/
├── slr_gui.py                # Desktop GUI
├── housing_enhanced.py       # Core review workflow engine
├── llm_interface.py          # Provider catalog, adapters, model discovery, retry/limiter helpers
├── ingestion.py              # Reference import, deduplication, abstract screening
├── workspace_store.py        # Local workspace folder, SQLite schema, review queue, decisions
├── prompt_editor.py          # Criteria editor
├── advanced_config.py        # Advanced settings dialog
├── custom_models.json        # User-added model IDs, auto-created when needed
├── requirements.txt          # Python dependencies
├── tests/                    # Pytest regression tests
├── setup.bat                 # Windows setup helper
├── launch_gui.bat            # Windows GUI launcher
├── COMPLETE_USER_GUIDE.md    # Beginner-friendly guide
├── README.md                 # Project overview
├── docs/                     # GitHub Pages website
└── WebApp/                   # Local-only browser UI
    ├── app.py                # Flask backend
    ├── run.bat               # Windows Web App launcher
    ├── requirements.txt      # Web App dependencies
    ├── services/             # WebApp service helpers, including workspace exports
    ├── templates/
    ├── static/
    └── uploads/              # Uploaded files, gitignored
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| LLM manager or connection test fails | Check provider, model ID, API key, Base URL, and internet connection |
| Rate limit or timeout errors | Reduce Max Workers and increase Rate Delay; try smaller batches |
| Ollama connection failed | Run `ollama serve`, verify `http://localhost:11434`, and check `ollama list` |
| Missing module error | Activate your virtual environment and run `pip install -r requirements.txt` |
| Web App does not start | Install Flask or run from the `WebApp/` folder with the project environment active |
| Workspace will not open | Confirm the folder contains `workspace.json` and `workspace.sqlite3`, and is not a filesystem root, drive root, or unrelated non-workspace folder |
| Workspace review queue is empty | Import references or upload/process PDFs while a workspace is open. Legacy no-workspace runs do not populate the workspace queue |
| Imported many records but only a few queue items are visible | Clear the review queue filters or switch Status, Stage, and Origin to All. Suggested, PDF-only, and other filtered views can show a small subset of the workspace |
| Full-text exclude is rejected | Choose an exclusion reason before saving a full-text Exclude decision |
| Web App counters/results/export look stale | Refresh the browser, check `/api/processing/results`, and review the server terminal/output log. Versions `3.5.2` and newer fix known stale counter/report visibility issues from earlier builds |
| Export file missing | Check the output folder and the Web App report warnings; failed report generation should now be surfaced instead of silently completing |
| Workspace export is missing | Open a workspace, go to Results, use Generate workspace exports, and check the workspace `exports/<export_id>/` folder. Legacy no-workspace exports remain separate |

---

## Testing

Run the primary test suite with:

```bash
python -m pytest -q
```

The legacy `test_tool.py` smoke script is not the primary test suite.

---

## Benchmarks

The repository includes a lightweight benchmark suite in `benchmarks/` for reproducible engineering checks:

```bash
python benchmarks/run_benchmarks.py --quick
```

Latest quick benchmark summary:

- `python -m pytest -q` -> 136 tests passed.
- `python benchmarks/run_benchmarks.py --quick` -> completed in 13.405 seconds.
- No external API calls were made; mocked/fake providers only.
- Fuzzy title deduplication was measured when `thefuzz` was installed.
- Provider-level rate limiter maximum concurrency was verified.
- Recursive PDF discovery and same-basename subfolder handling were verified.

These are synthetic mocked engineering benchmarks. They do not measure real-world LLM screening quality, provider latency, token usage, cost, or availability.

---

## Contributing

Pull requests are welcome. Key extension points:

- New LLM provider: update `llm_interface.py`; prefer an OpenAI-compatible profile unless the API shape requires a native adapter
- Domain template: update `prompt_editor.py`
- GUI enhancement: update `slr_gui.py`
- Web App: update `WebApp/app.py`, `WebApp/templates/`, or `WebApp/static/`
- Tests: add or update pytest tests under `tests/`

Please open an [issue](https://github.com/sadeghanisi/SLR/issues) before major changes.

---

## License

[MIT](LICENSE) - free to use, modify, and distribute with attribution.

---

## Support

1. Read the [Complete User Guide](COMPLETE_USER_GUIDE.md).
2. Check the in-app Help panel or Help tab.
3. Review logs in the output folder.
4. Run `python -m pytest -q`.
5. Open an [issue on GitHub](https://github.com/sadeghanisi/SLR/issues).

---

## Disclaimer

**As Is Provision.** This software is provided "as is," without warranty of any kind, express or implied. The authors and distributors accept no responsibility for decisions made based on AI-generated screening or extraction results.

**AI Limitations.** This tool assists with, but does not replace, human judgment. AI models can make errors, including incorrect inclusion/exclusion decisions and inaccurate data extraction. All AI outputs must be independently verified by qualified researchers before use in any publication, thesis, clinical decision, or policy document.

**PRISMA and Academic Responsibility.** This tool supports PRISMA-aligned workflows. Researchers remain responsible for final PRISMA reporting, methodological integrity, transparency, and accuracy.

**Local-First Scope.** The desktop GUI and Web App are designed for individual researchers running the tool locally on their own computers. The Web App is not a production multi-user service.

**Data Privacy.** When using cloud-based AI providers, paper content may be transmitted to third-party servers. Router providers such as OpenRouter add another third party between this tool and the final model provider. Consult each provider's privacy policy before processing sensitive or unpublished material. For confidential data, use a local provider such as Ollama when feasible.

**API Keys.** The desktop GUI does not write API keys to `settings.json`; when the optional OS keyring backend is available it stores keys in the operating system credential manager, otherwise keys remain in memory for the current session or can be supplied through environment variables such as `SLR_API_KEY`. The Web App does not save API keys to `webapp_settings.json`.

**Cost and Billing.** API usage fees are charged directly by third-party AI providers. Provider pricing changes frequently; always check the provider pricing page and set billing limits before large runs.

**Institutional Compliance.** Verify that AI-assisted research methods comply with your institution's policies, funding requirements, and field-specific ethical standards. Disclose AI tool usage in relevant research outputs.

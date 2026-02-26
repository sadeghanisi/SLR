# 📚 Universal SLR Automation Tool

<div align="center">

[![Version](https://img.shields.io/badge/version-3.2.0-blue?style=for-the-badge)](https://github.com/sadeghanisi/SLR/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=for-the-badge&logo=python)](https://python.org)
[![Providers](https://img.shields.io/badge/AI%20Providers-9-purple?style=for-the-badge)](#-ai-provider-quick-reference)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge)](#-installation)

**Automate your systematic literature reviews with AI — from import to extraction table.**

[🚀 Quick Start](#-quick-start) · [📖 Full Guide](COMPLETE_USER_GUIDE.md) · [🐛 Issues](https://github.com/sadeghanisi/SLR/issues) · [💡 Features](#-features)

</div>

---

A powerful, open-source tool for automating systematic literature reviews (SLRs) with support for **9 AI providers**, reference ingestion, deduplication, two-stage screening, and structured data extraction.

> **New to this tool?** Read [COMPLETE_USER_GUIDE.md](COMPLETE_USER_GUIDE.md) for a beginner-friendly walkthrough (assumes no prior AI/LLM knowledge).

---

## 👤 Author

**Mo Anisi**  
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue?style=flat&logo=linkedin)](https://www.linkedin.com/in/manisi/)

---

## ✨ Features

### 🤖 Multi-LLM Support (9 Providers)
- **OpenAI** — GPT-4o, GPT-4.1, o3, o4-mini, o1, and more
- **Anthropic Claude** — Claude Sonnet 4, Opus 4, Claude 3.7/3.5
- **Google Gemini** — Gemini 2.5 Pro/Flash, 2.0, 1.5
- **DeepSeek** — deepseek-chat, deepseek-reasoner, deepseek-coder
- **Mistral** — Large, Medium, Small, Codestral, Pixtral, Ministral
- **Kimi (Moonshot AI)** — moonshot-v1-auto, 8k/32k/128k, kimi-latest
- **Grok (xAI)** — Grok 3, Grok 3 Mini, Grok 2
- **Ollama** — Any local model, completely free, no API key
- **Custom** — Any OpenAI-compatible API (LM Studio, vLLM, LocalAI, etc.)
- **User-defined models** — Add any model ID not yet in the built-in list via the “+” button

### 📥 Reference Ingestion & Deduplication
- Import RIS (PubMed/Scopus/WoS), BibTeX, and CSV reference files
- Automatic deduplication via exact DOI match + fuzzy title matching (≥90 % Levenshtein)
- Abstract-level screening before downloading PDFs (saves time & API cost)

### 📄 Full-Text Processing & Extraction
- PDF text extraction cascade: pymupdf4llm → pdfplumber → PyPDF2
- Anti-hallucination: Pydantic schemas + instructor library + Quote-Then-Answer prompts
- Parallel processing with configurable workers
- Intelligent JSON caching to avoid reprocessing
- Multiple output formats: Excel (colour-coded), CSV, summary reports

### ⚙️ Fully Customisable
- Define your own inclusion/exclusion screening criteria
- Specify exactly what data fields to extract
- 5 built-in domain templates (Generic, Medical, Education, Environmental, Tech)
- Advanced settings: temperature, max tokens, rate limits, chunk sizes

---

## 🚀 Quick Start

### 1. Install

**Windows (one-click):**
```bat
REM Double-click setup.bat — creates a virtual environment and installs everything
setup.bat
```

**Manual (any OS):**
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
```bash
python slr_gui.py
# Windows shortcut: double-click launch_gui.bat
```

### 3. Configure AI Provider
- Select a provider → enter API key → choose a model → **Test Connection**
- **Ollama (free):** install from [ollama.ai](https://ollama.ai), run `ollama serve`, pull a model (`ollama pull llama3`), select "Ollama (Local)" — no API key needed.

### 4. Ingest References *(optional)*
- **Ingestion** tab → load your RIS/BIB/CSV export → Deduplicate → run abstract screening → export included records

### 5. Process PDFs
- **Setup** tab → select PDF folder + output folder → customise criteria (or use a template) → **Start Processing**
- Monitor progress in the **Monitor** tab, view results in the **Results** tab

---

## 💰 AI Provider Quick Reference

| Provider | Free Tier? | Recommended Model | Sign-up |
|---|---|---|---|
| OpenAI | Trial credit | gpt-4o-mini | [platform.openai.com](https://platform.openai.com) |
| Anthropic | — | claude-sonnet-4-20250514 | [console.anthropic.com](https://console.anthropic.com) |
| Google Gemini | ✅ Yes | gemini-2.5-flash | [aistudio.google.com](https://aistudio.google.com) |
| DeepSeek | ✅ Generous | deepseek-chat | [platform.deepseek.com](https://platform.deepseek.com) |
| Mistral | ✅ Free tier | mistral-large-latest | [console.mistral.ai](https://console.mistral.ai) |
| Kimi (Moonshot) | ✅ Free tier | moonshot-v1-auto | [platform.moonshot.cn](https://platform.moonshot.cn) |
| Grok (xAI) | — | grok-3-mini-fast | [console.x.ai](https://console.x.ai) |
| Ollama | ✅ Fully free | llama3 / mistral | [ollama.ai](https://ollama.ai) |
| Custom | Varies | — | — |


**Cost estimates:**
| Approach | Est. Cost | Best For |
|---|---|---|
| Ollama (local) | $0 | Large projects, privacy-sensitive data |
| DeepSeek / Gemini | Free tier | Budget-friendly cloud option |
| GPT-4o-mini | ~$0.05–0.20 / 1,000 papers | Good balance of cost & quality |
| GPT-4o / Claude Sonnet 4 | ~$0.50–5.00 / 1,000 papers | Highest quality |

> **Tip:** Always test with 5–10 PDFs before processing your full corpus.

---

## 🗂️ Project Structure

```
SLR/
├── slr_gui.py                # Main GUI (Tkinter, 5 tabs)
├── housing_enhanced.py       # Core automation engine
├── llm_interface.py          # Universal LLM provider interface (9 providers)
├── ingestion.py              # Reference import, dedup & abstract screening
├── prompt_editor.py          # Screening/extraction criteria editor
├── advanced_config.py        # Advanced settings dialog
├── custom_models.json        # User-added model IDs (auto-created on first use)
├── test_tool.py              # Basic test suite
├── requirements.txt          # All Python dependencies (pinned)
├── setup.bat                 # Windows one-click setup
├── install_dependencies.bat  # Alternative dependency installer
├── launch_gui.bat            # Windows launcher
├── COMPLETE_USER_GUIDE.md    # Detailed beginner-friendly guide
├── README.md                 # This file
├── LICENSE                   # MIT License
└── docs/                     # GitHub Pages website
```

---

## 🔧 Troubleshooting

| Problem | Solution |
|---|---|
| "Failed to initialise LLM manager" | Check API key & internet; click **Test Connection** |
| "Rate limit exceeded" | Increase rate-limit delay in Advanced Config; reduce workers |
| Ollama connection failed | Run `ollama serve`, verify `http://localhost:11434`, check `ollama list` |
| Missing module error | Run `pip install -r requirements.txt` inside your venv |
| Model not in dropdown | Type the model name directly, or use the **+** button to add it |

---

## 🤝 Contributing

Pull requests are welcome! Key extension points:

- **New LLM provider** → [`llm_interface.py`](llm_interface.py) — subclass `LLMProvider`
- **Domain template** → [`prompt_editor.py`](prompt_editor.py) — add to `TemplateSelector`
- **GUI enhancement** → [`slr_gui.py`](slr_gui.py)
- **Extraction logic** → [`housing_enhanced.py`](housing_enhanced.py)

Please open an [issue](https://github.com/sadeghanisi/SLR/issues) before major changes.

---

## 📜 License

[MIT](LICENSE) — free to use, modify, and distribute.

---

## 🆘 Support

1. Read the [Complete User Guide](COMPLETE_USER_GUIDE.md)
2. Check the in-app **Help** tab (14+ topics)
3. Review logs in the output folder
4. Run the test suite: `python test_tool.py`
5. Open an [issue on GitHub](https://github.com/sadeghanisi/SLR/issues)

---

## ⚠️ Disclaimer

> **IMPORTANT — Please read before use.**

**“As Is” Provision.** This software is provided "as is," without warranty of any kind, express or implied. The authors and distributors accept no responsibility for decisions made based on AI-generated screening or extraction results.

**AI Limitations.** This tool assists with — but does not replace — human judgment. AI models can and do make errors, including incorrect inclusion/exclusion decisions and inaccurate data extraction. All AI outputs must be independently verified by qualified researchers before use in any publication, thesis, clinical decision, or policy document.

**No Academic Guarantee.** Use of this tool does not ensure compliance with PRISMA, CONSORT, or any other reporting standard. Researchers remain solely responsible for the methodological integrity, transparency, and accuracy of their systematic reviews.

**Data Privacy.** When using cloud-based AI providers (OpenAI, Anthropic, Google, DeepSeek, or others), your paper content is transmitted to third-party servers. The authors of this tool make no representations regarding how those providers store, process, or use your data. Consult each provider’s privacy policy before processing sensitive or unpublished material. **For confidential data, use the local Ollama option.**

**Cost and Billing.** API usage fees are charged directly by third-party AI providers. The authors of this tool have no visibility into, or responsibility for, charges incurred through your API account. Monitor your usage and set billing limits with your provider before running large processing jobs.

**Institutional Compliance.** It is your responsibility to verify that AI-assisted research methods comply with your institution’s policies, your funding body’s requirements, and the ethical standards of your field. Disclose AI tool usage in all relevant sections of your research output.

**No Liability.** To the fullest extent permitted by law, the authors, contributors, and distributors of this tool shall not be liable for any direct, indirect, incidental, or consequential damages arising from its use, including but not limited to data loss, incorrect research conclusions, academic penalties, or financial charges.

*By using this tool, you acknowledge that you have read, understood, and accepted these terms.*

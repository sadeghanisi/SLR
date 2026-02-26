# Complete User Guide
# Universal Systematic Literature Review (SLR) Automation Tool

**For Students, Researchers, and Professors — No Technical Background Required**

---

## Table of Contents

1. [What Is This Tool and Why Should I Use It?](#1-what-is-this-tool-and-why-should-i-use-it)
2. [Understanding the Key Concepts (Plain Language)](#2-understanding-the-key-concepts-plain-language)
3. [What You Will Need Before Starting](#3-what-you-will-need-before-starting)
4. [Installing Python (Step-by-Step for Beginners)](#4-installing-python-step-by-step-for-beginners)
5. [Installing the Tool](#5-installing-the-tool)
6. [Choosing and Setting Up an AI Provider](#6-choosing-and-setting-up-an-ai-provider)
7. [Launching the Application](#7-launching-the-application)
8. [Understanding the Application Window](#8-understanding-the-application-window)
9. [Workflow A — Screening from a Reference List (Recommended First Step)](#9-workflow-a--screening-from-a-reference-list-recommended-first-step)
10. [Workflow B — Processing Full-Text PDF Papers](#10-workflow-b--processing-full-text-pdf-papers)
11. [Customizing Your Research Criteria](#11-customizing-your-research-criteria)
12. [Advanced Settings Explained](#12-advanced-settings-explained)
13. [Understanding Your Results](#13-understanding-your-results)
14. [Cost Guide — Free and Paid Options](#14-cost-guide--free-and-paid-options)
15. [Troubleshooting Common Problems](#15-troubleshooting-common-problems)
16. [Frequently Asked Questions](#16-frequently-asked-questions)
17. [Best Practices for Researchers](#17-best-practices-for-researchers)
18. [Keyboard Shortcuts](#18-keyboard-shortcuts)
19. [Glossary of Terms](#19-glossary-of-terms)

---

## 1. What Is This Tool and Why Should I Use It?

### What Is a Systematic Literature Review?

A **Systematic Literature Review (SLR)** is a rigorous, structured method of reviewing all published research on a specific topic. Unlike a regular literature review where you pick papers you already know, a systematic review follows a strict protocol:

1. You define exact **inclusion** and **exclusion criteria** (rules for which papers count).
2. You search multiple academic databases (PubMed, Scopus, Web of Science, etc.).
3. You screen **every** result — sometimes thousands of papers — against your criteria.
4. You extract specific information from the papers that qualify.
5. You report your findings transparently so other researchers can replicate your process.

This process is considered the **gold standard** in research because it is unbiased and reproducible. However, it is also extremely time-consuming. Screening 5,000 papers manually can take months.

### What Does This Tool Do?

This tool uses **Artificial Intelligence** to automate the most time-consuming steps:

- **Screening**: It reads each paper and decides whether it meets your inclusion criteria — in seconds.
- **Data Extraction**: It automatically pulls out the specific information you need (study design, sample size, outcomes, etc.).
- **Deduplication**: It removes duplicate papers that came from different databases.
- **Export**: It generates clean Excel and CSV files ready for your PRISMA flow diagram and final report.

**You remain in control.** The AI assists you; it does not replace your academic judgment. You can review, override, and adjust every decision the AI makes.

### Who Is This Tool For?

- **Students** conducting a systematic review as part of a thesis or dissertation.
- **Researchers** managing large literature screening projects.
- **Professors** supervising students or leading multi-paper research projects.
- **Anyone** who needs to process many research papers systematically.

**You do NOT need any programming or computer science knowledge to use this tool.**

---

## 2. Understanding the Key Concepts (Plain Language)

Before diving in, here are simple explanations of technical terms you will encounter.

### What Is Artificial Intelligence (AI)?

Artificial Intelligence refers to computer programs that can perform tasks that normally require human intelligence — reading text, understanding language, making decisions, and summarizing information. In this tool, AI reads your papers and decides whether they match your research topic.

### What Is a Large Language Model (LLM)?

A **Large Language Model** (LLM) is a specific type of AI that has been trained on billions of pages of text (books, scientific articles, websites) and learned to understand and generate human language at an expert level.

Think of it like this: you have a very knowledgeable research assistant who has read essentially everything ever published, can read a new paper in seconds, and can answer questions like "Does this paper study the effect of air pollution on children's asthma in a randomized controlled trial?"

Examples of LLMs:
- **GPT-4o** (made by OpenAI, the company behind ChatGPT)
- **Claude** (made by Anthropic)
- **Gemini** (made by Google)
- **DeepSeek** (a Chinese company offering very affordable options)
- **Llama** (a model you can run on your own computer for free)

### What Is an API?

An **API** (Application Programming Interface) is a way for one software program to talk to another. When this tool sends a paper to an AI for screening, it does so through an API — it's like a postal system that sends your paper to the AI company's servers and receives the screening decision back.

Most AI companies charge a small fee for each piece of text you send them. This fee is measured in "tokens" (roughly, every 4 characters of text equals 1 token).

### What Is an API Key?

An **API Key** is like a password or ID card that tells the AI company "this request is coming from my account." When you sign up with an AI provider (OpenAI, Anthropic, etc.), they give you a unique key. You paste this key into the tool so it can access the AI on your behalf.

**Keep your API key private** — treat it like a password. Anyone with your key can use your account and spend your credits.

### What Is a Model?

Different AI providers offer several versions of their AI, called **models**. Larger, more powerful models are more expensive but make better decisions. Smaller models are cheaper and faster.

For example, OpenAI offers:
- **gpt-4o** — most capable, more expensive
- **gpt-4o-mini** — nearly as good, much cheaper (recommended for large reviews)

You choose the model inside the tool. If you are unsure, the tool defaults to a good balance of quality and cost.

### What Is PRISMA?

**PRISMA** (Preferred Reporting Items for Systematic Reviews and Meta-Analyses) is an international standard for reporting systematic reviews. It defines a flow diagram showing how many papers you found, removed as duplicates, screened, and included. This tool follows the PRISMA workflow and generates the data you need to complete your PRISMA diagram.

---

## 3. What You Will Need Before Starting

### Hardware Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Operating System | Windows 10, macOS 10.14, Linux | Windows 11, macOS 14+ |
| RAM (computer memory) | 4 GB | 8 GB or more |
| Disk Space | 2 GB free | 5 GB free |
| Internet Connection | Required (for cloud AI) | Stable broadband |

> **Note:** If you choose the free local AI option (Ollama), you need at least 8 GB of RAM and 10 GB of free disk space. More details in Section 6.

### Software Requirements

- **Python 3.8 or newer** — a free programming language. You will install it in Section 4.
- **This tool's files** — which you already have.

### Research Materials

You will need either or both of the following:
- **Reference files** exported from academic databases (PubMed, Scopus, Web of Science) in `.ris`, `.bib`, or `.csv` format.
- **PDF files** of full-text papers you want to process.

### Account with an AI Provider (Optional — Free Options Available)

You need access to an AI service. If you want a completely **free** option, you can use Ollama (runs on your own computer). Details in Section 6.

---

## 4. Installing Python (Step-by-Step for Beginners)

Python is the programming language this tool is written in. You need to install it once, and then it runs in the background — you will never need to write any code yourself.

### Step 1: Check if Python is Already Installed

1. Press the **Windows key + R** on your keyboard.
2. Type `cmd` and press Enter. A black window (called the Command Prompt) will open.
3. Type the following and press Enter:
   ```
   python --version
   ```
4. If you see something like `Python 3.11.5`, Python is already installed. Skip to Section 5.
5. If you see an error or a version starting with `2.`, continue below.

### Step 2: Download Python

1. Open your web browser and go to: **https://www.python.org/downloads/**
2. Click the large yellow button that says **"Download Python 3.xx.x"** (the exact version number does not matter as long as it starts with 3).
3. The download will start automatically. Wait for it to finish.

### Step 3: Install Python

1. Open the downloaded file (it will be named something like `python-3.12.0-amd64.exe`).
2. **IMPORTANT**: Before clicking Install, check the box at the bottom that says **"Add Python to PATH"**. This step is critical.
3. Click **"Install Now"**.
4. Wait for the installation to complete (about 2 minutes).
5. Click **"Close"**.

### Step 4: Verify the Installation

1. Close and reopen the Command Prompt (press Windows + R, type `cmd`, press Enter).
2. Type:
   ```
   python --version
   ```
3. You should now see `Python 3.x.x`. Installation is complete.

---

## 5. Installing the Tool

### Method A: Automatic Installation (Recommended for Windows)

This is the easiest method. You only need to click a file.

1. Find the file called **`install_dependencies.bat`** in the tool's folder.
2. **Double-click** it.
3. A black window will open and you will see text scrolling as packages are downloaded and installed.
4. Wait until you see "All dependencies installed successfully" or the window closes on its own.
5. Done! You can now launch the tool.

### Method B: Manual Installation

If Method A does not work on your computer:

1. Open the Command Prompt (Windows + R, type `cmd`, Enter).
2. Navigate to the tool's folder. For example, if the tool is on your Desktop in a folder called "systematic", type:
   ```
   cd Desktop\systematic
   ```
   (Replace the path with wherever you saved the tool.)
3. Type the following command and press Enter:
   ```
   pip install -r requirements.txt
   ```
4. Wait for all packages to download and install. This may take 3–5 minutes.
5. When you see the cursor return to a normal prompt, installation is complete.

### What Was Just Installed?

The tool requires several supporting software packages:
- **PDF readers** — to extract text from PDF files
- **Data handlers** — to create Excel and CSV output files
- **AI connectors** — to communicate with AI providers
- **Interface components** — to display the graphical window

---

## 6. Choosing and Setting Up an AI Provider

This is the most important decision before using the tool. You need AI to screen your papers. Here are all your options, from completely free to paid.

---

### Option 1: Ollama — Completely FREE, Runs on Your Computer

**Best for:** Researchers with large projects who want to avoid any costs, or those with privacy concerns about sending paper content to external servers.

**Requirement:** A computer with at least 8 GB of RAM.

**How it works:** Ollama downloads an AI model (a large file, typically 4–8 GB) and runs it entirely on your own computer. No data ever leaves your machine. No internet needed after setup.

#### Setting Up Ollama

**Step 1: Download Ollama**
1. Go to: **https://ollama.com/download**
2. Click "Download for Windows" (or macOS/Linux as appropriate).
3. Run the installer and follow the prompts.

**Step 2: Download an AI Model**
1. Open the Command Prompt.
2. Type the following and press Enter:
   ```
   ollama pull llama3.2
   ```
   This downloads a capable, free AI model (~2.0 GB). Wait for it to complete.
3. Alternatively, for a stronger model (requires more RAM):
   ```
   ollama pull mistral
   ```

**Step 3: Start the Ollama Service**
1. In the Command Prompt, type:
   ```
   ollama serve
   ```
2. Leave this window open while you use the tool. Ollama must be running in the background.

**Step 4: In the Tool**
- Set **Provider** to: `Ollama (Local)`
- **API Key**: Leave blank (not required)
- **Model**: Type `llama3.2` (or whichever model you downloaded)
- **Base URL**: `http://localhost:11434`

---

### Option 2: DeepSeek — Very Affordable, with Free Credits

**Best for:** Researchers who want cloud AI quality at minimal cost.

**Cost:** Starts with free credits; then approximately $0.01 per 1 million tokens (~2,000 papers at no charge).

#### Setting Up DeepSeek

1. Go to: **https://platform.deepseek.com**
2. Click **"Sign Up"** and create a free account using your email.
3. After signing in, click your profile picture (top right) → **"API Keys"**.
4. Click **"Create new API key"**, give it a name (e.g., "SLR Project"), and click **Create**.
5. **Copy the key** (it starts with `sk-`). Store it somewhere safe — you can only view it once.

**In the Tool:**
- Set **Provider** to: `DeepSeek`
- **API Key**: Paste your key
- **Model**: `deepseek-chat`

---

### Option 3: OpenAI (GPT-4o / ChatGPT) — Industry Standard

**Best for:** Researchers who want the most widely validated AI for research tasks.

**Cost:** New accounts receive a small free credit. After that, approximately $0.15–$2.00 per 1,000 papers depending on the model chosen.

#### Setting Up OpenAI

1. Go to: **https://platform.openai.com**
2. Click **"Sign Up"** if you are new, or **"Log In"** if you already have a ChatGPT account (they share the same login).
3. After logging in, click your profile (top right) → **"API keys"** in the left sidebar.
4. Click **"+ Create new secret key"**.
5. Give it a name, click **"Create secret key"**.
6. **Copy the key immediately.** It starts with `sk-` and you cannot view it again.
7. You may need to add a payment method: go to **"Billing"** → **"Add payment method"**. A $5 credit is a good starting point for testing.

**In the Tool:**
- Set **Provider** to: `OpenAI`
- **API Key**: Paste your key
- **Model**: `gpt-4o-mini` (recommended — very capable and inexpensive)

---

### Option 4: Anthropic Claude — Excellent for Scientific Text

**Best for:** Researchers who find Claude's reasoning particularly well-suited for academic papers.

**Cost:** Similar to OpenAI pricing. Free trial credits available for new accounts.

#### Setting Up Anthropic Claude

1. Go to: **https://console.anthropic.com**
2. Click **"Sign Up"** and create an account.
3. After logging in, go to **"API Keys"** in the left sidebar.
4. Click **"Create Key"**, name it, and copy it (starts with `sk-ant-`).
5. Add a payment method if needed under **"Billing"**.

**In the Tool:**
- Set **Provider** to: `Anthropic (Claude)`
- **API Key**: Paste your key
- **Model**: `claude-3-5-haiku-20241022` (fast and affordable) or `claude-3-5-sonnet-20241022` (higher quality)

---

### Option 5: Google Gemini — Strong Alternative

**Best for:** Researchers already using Google services, or those wanting a strong free-tier option.

**Cost:** Generous free tier available.

#### Setting Up Google Gemini

1. Go to: **https://aistudio.google.com**
2. Sign in with your Google account.
3. Click **"Get API Key"** → **"Create API key"**.
4. Copy the key.

**In the Tool:**
- Set **Provider** to: `Google Gemini`
- **API Key**: Paste your key
- **Model**: `gemini-2.0-flash` (fast and free-tier eligible)

---

### Option 6: Mistral AI — European Provider

**Best for:** Researchers requiring EU data compliance (GDPR).

#### Setting Up Mistral

1. Go to: **https://console.mistral.ai**
2. Sign up and create an account.
3. Navigate to **"API Keys"** and create one.

**In the Tool:**
- Set **Provider** to: `Mistral`
- **API Key**: Paste your key
- **Model**: `mistral-small-latest` (affordable) or `mistral-large-latest` (highest quality)

---

### Which Provider Should I Choose?

| Your Situation | Recommended Option |
|---|---|
| I have no budget at all | Ollama (free, local) |
| I want cheap cloud AI | DeepSeek |
| I want the most trusted option | OpenAI (gpt-4o-mini) |
| I care about EU data privacy | Mistral |
| I already have a Google account | Google Gemini |
| I want the best scientific reasoning | Anthropic Claude |

---

## 7. Launching the Application

### On Windows (Easiest Method)

1. Find the file called **`launch_gui.bat`** in the tool's folder.
2. **Double-click** it.
3. The application window will open within a few seconds.

### Alternative Method (All Operating Systems)

1. Open the Command Prompt (Windows) or Terminal (macOS/Linux).
2. Navigate to the tool's folder:
   ```
   cd path\to\systematic
   ```
   (Replace `path\to\systematic` with the actual location, e.g., `cd Desktop\systematic`)
3. Type and press Enter:
   ```
   python slr_gui.py
   ```
4. The application window will open.

### If the Application Does Not Open

If you see an error about a missing module, go back to Section 5 and run the installation again. The most common cause is that the dependencies were not installed correctly.

---

## 8. Understanding the Application Window

When the application opens, you will see a window with a **blue header bar** at the top and **five tabs** below it.

### The Header Bar

At the very top of the window:
- **Left side**: The tool's name and version number.
- **Right side**: A connection indicator (⬤) that shows whether the AI is ready:
  - **Gray "Not tested"**: You have not tested the connection yet.
  - **Green**: Connected successfully.
  - **Red**: Connection failed — check your API key and internet.

At the very bottom of the window:
- A **status bar** that shows what the tool is currently doing and the current time.

### The Five Tabs

| Tab | Icon | Purpose |
|---|---|---|
| Ingestion | 📥 | Import reference lists from databases, remove duplicates, screen titles and abstracts |
| Setup | ⚙ | Configure AI settings, select PDF folders, set screening criteria |
| Monitor | 📊 | Watch processing in real-time with progress bars and statistics |
| Results | 📋 | Review and export your final results |
| Help | ❓ | Built-in help and quick reference |

---

## 9. Workflow A — Screening from a Reference List (Recommended First Step)

This workflow is for **PRISMA Phase 2 and 3**: importing your search results from academic databases and screening titles and abstracts before downloading full PDFs.

**When to use this:** When you have just done your database searches and have hundreds or thousands of references to screen.

### Step 1: Export Your Search Results from Databases

In PubMed, Scopus, Web of Science, or any other database, save your search results as:
- `.ris` format (most universal — works with all databases)
- `.bib` format (common in computer science databases)
- `.csv` format (spreadsheet format)

**How to export from PubMed:**
1. Run your search in PubMed.
2. Click **"Save"** above the results list.
3. Under "Format", select **"PubMed"** or **"Citation"**.
4. Click **"Create file"**.

**How to export from Scopus:**
1. Run your search and select all results (checkbox at top).
2. Click **"Export"**.
3. Choose **"RIS format"**.
4. Make sure all metadata fields are checked.
5. Click **"Export"**.

**How to export from Web of Science:**
1. Select all results on the page.
2. Click **"Export"** → **"RIS Format"**.
3. Select "Record Content: Full Record".
4. Click **"Export"**.

### Step 2: Open the Ingestion Tab

Click the **📥 Ingestion** tab at the top of the application window.

You will see a workflow banner explaining the steps, and below it several sections.

### Step 3: Load Your Reference File

In the **① Reference File** section:

1. Click the **"Browse…"** button.
2. Navigate to where you saved your exported reference file.
3. Select the file and click **"Open"**.
4. The tool will display basic information about the file (number of records found, file size).

### Step 4: Parse the References

Click the **"Parse"** button (or similar — the exact label may read "Parse File").

The tool will read through your file and display how many references were found. Each reference includes the title, abstract, authors, year, and journal where available.

### Step 5: Deduplicate

If you searched multiple databases, the same paper may appear multiple times. Click **"Deduplicate"**.

The tool uses **fuzzy matching** (a technique that finds papers with very similar titles even if they are not letter-for-letter identical) to identify and remove duplicates. After deduplication, you will see a summary:
- Total records found
- Duplicates removed
- Unique records remaining

### Step 6: Set Up Your Screening Criteria

Before the AI can screen your abstracts, you need to tell it what to look for. Go to the **② Screening Criteria** section within the Ingestion tab, or click **"Customize Screening & Extraction Criteria"** in the Setup tab.

See Section 11 of this guide for detailed instructions on writing screening criteria.

### Step 7: Configure Your AI (Before Screening)

The Ingestion tab uses the same AI settings you configure in the Setup tab. Before running screening, go to the **⚙ Setup** tab and:
1. Select your **Provider** from the dropdown menu.
2. Enter your **API Key**.
3. Select your **Model**.
4. Click **"Test Connection"** to confirm everything works.

### Step 8: Run Abstract Screening

Return to the **📥 Ingestion** tab and click **"Screen Abstracts"** (the exact button label may vary).

The AI will:
1. Read each paper's title and abstract.
2. Compare it against your inclusion/exclusion criteria.
3. Assign one of four decisions to each paper:
   - **Include** — meets your criteria
   - **Exclude** — does not meet your criteria
   - **Flag for Review** — borderline case (you must decide)
   - **Error** — the abstract could not be read

You will see a progress bar as papers are processed. A table will fill in with decisions and the AI's reasoning.

### Step 9: Review and Override Decisions

After screening, go through the results table. For any paper where you disagree with the AI's decision:
1. Click on the paper in the table.
2. Look for an **"Override"** button or a dropdown to change the decision.
3. Select your preferred decision.

**This is an essential quality control step.** Always review flagged papers and a random sample of excluded papers to ensure the AI is working correctly.

### Step 10: Export Your Results

Click **"Export Included"** to save only the papers marked as "Include" to a CSV or Excel file. Use this list to then download the full-text PDFs for the next stage of your review.

---

## 10. Workflow B — Processing Full-Text PDF Papers

This workflow is for **PRISMA Phase 4**: detailed screening and data extraction from full-text PDF papers.

**When to use this:** After you have downloaded the PDFs for all papers that passed title/abstract screening.

### Step 1: Organize Your PDF Files

Create a folder on your computer and place all PDF files in it. Tips:
- Name each PDF clearly (e.g., `Smith_2022_RCT_diabetes.pdf`).
- Keep all PDFs in one folder (subfolders are also supported).
- Make sure files are actual PDFs, not just renamed image files.

### Step 2: Open the Setup Tab

Click the **⚙ Setup** tab.

### Step 3: Configure Your AI Provider

In the **AI Provider Configuration** section:

1. **Provider**: Click the dropdown and select your AI service (e.g., "OpenAI", "Ollama (Local)", "DeepSeek").
2. **API Key**: Paste your API key into the field. Click the **"Show"** checkbox if you want to check it.
3. **Model**: Select a model from the dropdown. If you are unsure:
   - **OpenAI**: Choose `gpt-4o-mini`
   - **Anthropic**: Choose `claude-3-5-haiku-20241022`
   - **DeepSeek**: Choose `deepseek-chat`
   - **Ollama**: Type the name of the model you downloaded (e.g., `llama3.2`)
4. **Base URL (Ollama only)**: Enter `http://localhost:11434`
5. Click **"Test Connection"**. The indicator in the header should turn green.

### Step 4: Select Your PDF Folder

In the **File Paths** section:

1. **PDF Folder**: Click **"Browse"** and navigate to the folder containing your PDFs. Click **"Select Folder"**. The path will appear in the field and the number of PDFs found will be shown.
2. **Output Folder**: This is where your results will be saved. The default `output` folder inside the tool's directory is fine. You can change it by clicking **"Browse"** if you prefer a different location (e.g., your desktop or a project folder).

### Step 5: Configure Processing Settings

In the **Processing Settings** section:

**Parallel Processing:**
- **Enable Parallel Processing** (checkbox): When checked, the tool processes multiple PDF files at the same time, like having several assistants working simultaneously. This is faster but uses more computer resources. Recommended: **checked**.
- **Max Workers** (number): How many files to process at once. Start with **3** and increase to 5 if your computer handles it well. If you get errors, reduce to 1 or 2.

**Rate Limit Delay (seconds):**
- This is a pause the tool takes between sending papers to the AI. It prevents you from overwhelming the AI service and getting blocked.
- **1.0 second** is a safe default. Increase to 2.0 if you encounter "rate limit" errors.

**Cache Settings:**
- **Enable Caching** (checkbox): When checked, the tool remembers which PDFs it has already processed. If you need to re-run processing (e.g., after a crash), it skips files already done. **Always keep this checked.** It saves time and money.

**Two-Stage Processing** (optional):
- When enabled, the tool first does a quick screen to decide if a paper qualifies, and only extracts detailed data from papers that pass the screening. This saves cost when many papers are likely to be excluded.

### Step 6: Set Your Research Criteria

Click **"Customize Screening & Extraction Criteria"**.

This is where you tell the AI exactly what criteria to apply to each paper. See Section 11 for a complete guide to writing effective criteria.

### Step 7: Start Processing

Click the large **"Start Processing"** button.

- The tool will begin reading each PDF, extracting the text, sending it to the AI, and recording decisions.
- Switch to the **📊 Monitor** tab to watch progress in real time.
- You can click **"Stop Processing"** at any time to pause. Cached results will not be lost.

### Understanding the Monitor Tab

The **📊 Monitor** tab shows:

- **Progress Bar**: A visual indicator of how many files have been processed out of the total.
- **Files Processed**: The count of completed files.
- **Time Elapsed**: How long processing has been running.
- **Processing Rate**: Files per minute (useful for estimating how long the full run will take).
- **API Tokens Used**: A running count of AI usage (helps you track cost).
- **Status Messages**: What the tool is currently doing.
- **Processing Log**: A detailed, timestamped record of every action — very useful for troubleshooting.

**Estimating time:** If the rate is 2 files/minute and you have 200 PDFs, expect about 100 minutes. Using parallel processing (3 workers) roughly triples the speed to ~6 files/minute.

### Step 8: Review Results

When processing completes (or at any point during), go to the **📋 Results** tab to review what the AI found.

---

## 11. Customizing Your Research Criteria

This is one of the most important steps. The quality of your systematic review depends on how well you define your criteria.

### Accessing the Criteria Editor

In the **⚙ Setup** tab, click **"Customize Screening & Extraction Criteria"**.

A new window will open with two sections: **Screening Criteria** and **Data Extraction Fields**.

### Writing Screening Criteria

The AI uses your criteria exactly as you write them. Write them clearly and specifically.

#### Inclusion Criteria (papers you WANT to keep)

Examples for a medical research review:
```
INCLUSION CRITERIA:
• Study Type: Randomized controlled trials (RCTs) or quasi-experimental studies
• Population: Adult human participants (age 18+)
• Intervention: Any pharmacological or behavioral intervention for type 2 diabetes
• Outcome: At least one primary outcome measuring glycemic control (HbA1c, fasting glucose)
• Publication Year: 2015 to 2025
• Language: English only
• Publication Type: Peer-reviewed journal articles (no conference proceedings, editorials, or letters)
```

Examples for an education research review:
```
INCLUSION CRITERIA:
• Study Type: Any empirical study (quantitative or qualitative)
• Population: Primary or secondary school students (ages 5-18)
• Intervention: Technology-based learning interventions (apps, games, online platforms)
• Outcome: Measurable academic achievement or engagement outcomes
• Setting: Formal school environment
• Language: English or Spanish
• Publication Year: 2018 to present
```

#### Exclusion Criteria (papers you WANT to remove)

```
EXCLUSION CRITERIA:
• Animal studies or in vitro studies
• Review articles, systematic reviews, or meta-analyses
• Conference abstracts without full text
• Studies with fewer than 30 participants
• Studies without a control group
• Grey literature (theses, reports not peer-reviewed)
```

#### Tips for Writing Good Criteria

1. **Be specific**: "RCTs only" is better than "good studies."
2. **Use common terminology**: The AI knows standard research terminology (RCT, cohort study, cross-sectional, etc.).
3. **Separate inclusion from exclusion clearly**: Do not mix them.
4. **Test with known papers**: Find 5 papers you know should be included and 5 that should be excluded. Run them through and check whether the AI decides correctly.
5. **Iterate**: Refine your criteria if the AI is making systematic errors.

### Configuring Data Extraction Fields

After screening, the AI can extract specific information from included papers. Define what you want:

```json
{
    "title": "Full title of the paper",
    "authors": "Author names and institutions",
    "publication_year": "Year published",
    "journal": "Journal name",
    "study_design": "Research design (RCT, cohort, cross-sectional, etc.)",
    "sample_size": "Total number of participants",
    "age_range": "Age range of participants",
    "country": "Country or countries where the study was conducted",
    "intervention": "Description of the intervention or exposure",
    "comparison": "Control or comparison condition",
    "primary_outcome": "Main outcome measure and how it was assessed",
    "key_findings": "Main results and conclusions",
    "limitations": "Reported study limitations",
    "funding": "Funding sources"
}
```

You can add or remove any field depending on your review's needs.

### Saving Your Criteria

After writing your criteria, click **"Save"** or **"Apply"** in the criteria editor. The criteria are saved automatically and will persist the next time you open the tool.

---

## 12. Advanced Settings Explained

In the **⚙ Setup** tab, click **"Advanced Config"** to access fine-tuning options. You do not need to change these for basic use.

### Text Processing Settings

**Max Text Characters (default: 100,000):**
- PDFs are converted to text. Very long papers (books, theses) produce very long texts. This setting limits how much text is sent to the AI at once.
- 100,000 characters is about 15,000 words — enough for any typical research paper.
- Reduce if you encounter "too long" errors.

**Enable Smart Truncation (default: on):**
- When a paper is too long, the tool intelligently cuts sections in the least important parts (middle of the methods section) and always preserves the abstract, introduction, and conclusions.
- Keep this enabled for best results.

**Preserve Sections:**
- Sections the tool will always keep even when truncating: abstract, introduction, methods, results, discussion, conclusion.

### AI Behavior Settings

**Temperature (default: 0.05):**
- Controls how "creative" the AI is. At 0.05 (nearly zero), the AI is very consistent and deterministic — it will give the same answer every time for the same paper. This is what you want for systematic reviews, which require reproducibility.
- Do not increase this above 0.2 for systematic review work.

**Max Tokens per Response (default: 4,000):**
- The maximum length of the AI's response for each paper. 4,000 tokens (~3,000 words) is enough for detailed extraction.
- Increase to 8,000 if you need very detailed extractions.

**Max Retries (default: 3):**
- If the AI fails to respond (network error, server busy), the tool tries again this many times before marking a file as an error.

**Retry Delay (seconds, default: 0.5):**
- How long to wait between retries.

### Saving and Loading Configurations

To save your current configuration (including AI provider, model, criteria, and settings):
1. In the **⚙ Setup** tab, click **"Save Settings"**.
2. Choose a location and filename (e.g., `diabetes_review_settings.json`).

To load a saved configuration:
1. Click **"Load Settings"**.
2. Select the saved `.json` file.

This is very useful when managing multiple review projects.

---

## 13. Understanding Your Results

After processing, results are saved in your chosen output folder. The tool generates several files.

### Output Files Overview

| File Name | Format | Contents |
|---|---|---|
| `screening_results_TIMESTAMP.xlsx` | Excel | All papers with screening decisions |
| `screening_results_TIMESTAMP.csv` | Spreadsheet | Same as above, compatible with any spreadsheet app |
| `extraction_results_TIMESTAMP.xlsx` | Excel | Detailed extracted data from included papers |
| `extraction_results_TIMESTAMP.csv` | Spreadsheet | Same as above |
| `processing_summary_TIMESTAMP.txt` | Text | Statistics and summary of the processing run |
| `slr_automation.log` | Text | Detailed log of every action (for troubleshooting) |

`TIMESTAMP` is replaced with the date and time of the run (e.g., `screening_results_2026-02-26_14-30.xlsx`).

### Reading the Screening Results File

Open the Excel file. You will see columns including:

**Filename / Reference ID**
- The name of the PDF file or the reference identifier from your database export.

**Decision**
- What the AI decided:
  - **Likely Include**: The paper appears to meet your inclusion criteria.
  - **Likely Exclude**: The paper does not meet your criteria.
  - **Flag for Review / Flag for Human Review**: The AI was uncertain. You must review this paper yourself.
  - **Error**: The file could not be processed (e.g., a scanned image PDF without text layer, or corrupted file).

**Reasoning**
- The AI's explanation for its decision. Read this carefully. If the reasoning seems wrong, the paper deserves a closer look.

**Processing Time**
- How many seconds it took to process this paper.

**API Tokens**
- How many AI "words" were used for this paper. This directly corresponds to cost.

**Text Length**
- How many characters of text were extracted from the PDF.

### Reading the Extraction Results File

For papers marked "Include", the extraction file shows all the fields you defined in your criteria, filled in by the AI (title, authors, sample size, methodology, findings, etc.).

**Important**: Always verify a random sample of extractions against the actual papers. AI extraction is highly accurate but not perfect. Treat it as a first draft that requires your review.

### Viewing Results in the Application

Go to the **📋 Results** tab to see a summary table of decisions inside the application. You can:
- Filter by decision type.
- Click a row to see the full reasoning.
- Override decisions directly in the application.
- Export filtered results.

### Understanding the Processing Summary

The text file `processing_summary_TIMESTAMP.txt` contains a report including:
- Total files processed
- Number of successes and failures
- Decision breakdown (how many included, excluded, flagged, errors)
- Processing speed (files per minute)
- Total processing time
- Total API tokens used and estimated cost

---

## 14. Cost Guide — Free and Paid Options

Understanding your costs prevents surprises on your billing statement.

### How AI Pricing Works

AI providers charge per **token**. A token is roughly 4 characters of text, or about ¾ of a word.
- A typical research abstract is about 250 words ≈ 330 tokens of input.
- A full research paper is 5,000–10,000 words ≈ 6,600–13,000 tokens of input.

You are charged for both input tokens (what you send to the AI) and output tokens (what the AI sends back to you).

### Cost Examples

**Screening 1,000 abstracts with GPT-4o-mini:**
- Each abstract ≈ 400 tokens input + 200 tokens output = 600 tokens
- 1,000 abstracts × 600 tokens = 600,000 tokens
- Cost: approximately **$0.09** (nine cents)

**Extracting data from 200 full PDFs with GPT-4o-mini:**
- Each paper ≈ 10,000 tokens input + 1,000 tokens output = 11,000 tokens
- 200 papers × 11,000 tokens = 2,200,000 tokens
- Cost: approximately **$0.33** (thirty-three cents)

**Full review: 3,000 abstracts screened + 150 PDFs extracted with GPT-4o-mini:**
- Total cost: approximately **$0.50–$1.00** (fifty cents to one dollar)

### Cost Comparison by Provider

| Provider | Model | Approximate Cost per 1,000 Abstracts | Notes |
|---|---|---|---|
| Ollama | llama3.2 | $0.00 | Free — runs locally |
| DeepSeek | deepseek-chat | ~$0.01 | Very affordable |
| Google Gemini | gemini-2.0-flash | ~$0.02 | Free tier generous |
| OpenAI | gpt-4o-mini | ~$0.09 | Great balance |
| Anthropic | claude-3-5-haiku | ~$0.10 | Fast and accurate |
| OpenAI | gpt-4o | ~$1.50 | Most capable |
| Anthropic | claude-3-5-sonnet | ~$1.80 | Excellent quality |

### Tips to Minimize Costs

1. **Always enable caching** — If you restart a run or re-process files, the cache prevents re-charging for completed files.
2. **Test with 5–10 papers first** — Check that your criteria and settings are correct before running all 3,000.
3. **Use smaller models for abstract screening** — gpt-4o-mini or claude-3-5-haiku are more than sufficient for title/abstract screening.
4. **Use larger models only for extraction** — If you need high-quality extraction, upgrade only for the full-text stage.
5. **Set rate limits** — Avoid accidental bulk processing by keeping rate limits at 1 second initially.
6. **Monitor tokens in real time** — The Monitor tab shows running token usage so you can stop if costs climb unexpectedly.

---

## 15. Troubleshooting Common Problems

### "The application does not open at all"

**Cause**: Python or required packages are not installed.

**Solution**:
1. Double-click `install_dependencies.bat` again.
2. If it shows errors, open Command Prompt and type `pip install -r requirements.txt` and read the error message carefully.
3. Make sure you are running Python 3.8 or newer: open Command Prompt and type `python --version`.

---

### "No PDF files found"

**Cause**: The tool cannot find any PDF files in the selected folder.

**Solution**:
1. Check that your folder actually contains files ending in `.pdf` (lowercase).
2. If files are `.PDF` (uppercase), rename them.
3. Make sure you selected the correct folder using the "Browse" button.
4. Check that the PDF files are not corrupted or password-protected.

---

### "API Key Error" or "Authentication failed"

**Cause**: The API key is incorrect, expired, or has no credit.

**Solution**:
1. Log into your AI provider's website and verify the key is still active.
2. Copy the key again carefully — there are sometimes hidden spaces at the beginning or end when pasting.
3. Check your account has credit/payment set up.
4. Use the **"Test Connection"** button in the Setup tab to see the exact error message.

---

### "Rate Limit Error" or "Too many requests"

**Cause**: You are sending papers to the AI faster than your account tier allows.

**Solution**:
1. Increase the **Rate Limit Delay** setting to 2.0 or 3.0 seconds.
2. Reduce **Max Workers** to 1 or 2.
3. Wait 5–10 minutes and try again. Rate limits often reset automatically.
4. If this happens frequently, upgrade your API plan.

---

### "Ollama connection failed"

**Cause**: Ollama is not running on your computer.

**Solution**:
1. Open Command Prompt and type `ollama serve`. Leave this window open.
2. Make sure the **Base URL** in the tool is set to `http://localhost:11434`.
3. Verify a model is downloaded: in Command Prompt, type `ollama list`.
4. If no models appear, type `ollama pull llama3.2` to download one.

---

### "Text too long" or papers are being truncated

**Cause**: The PDF contains more text than the set limit (default: 100,000 characters).

**Solution**:
- This is normal and handled automatically. The tool preserves the most important sections (abstract, introduction, results, conclusion) and truncates the least important.
- You can increase the **Max Text Characters** limit in Advanced Config if you believe important content is being cut.
- If papers are books or very long theses, this limit may need to be increased to 200,000.

---

### "Processing stopped unexpectedly"

**Cause**: Various — network dropout, AI server error, or memory issue.

**Solution**:
1. Check the **Processing Log** in the Monitor tab for the last error message.
2. Verify your internet connection.
3. Re-run processing. Because caching is enabled, completed files will not be re-processed.
4. If RAM is an issue (common with large PDFs), reduce Max Workers to 1 and try again.

---

### "Some papers show 'Error' in the decision column"

**Cause**: Individual PDFs failed to process. Common reasons include:
- Scanned image PDFs (no text layer — text cannot be extracted)
- Password-protected PDFs
- Corrupted files
- Very unusual PDF formatting

**Solution**:
- Open the log file (`slr_automation.log`) for the specific error.
- For scanned PDFs, you need to use OCR (Optical Character Recognition) software first to add a text layer (e.g., Adobe Acrobat, ABBYY FineReader, or free tools like OCRmyPDF).
- Move problematic files out of the folder and process them separately after fixing them.

---

### The AI is making wrong decisions on papers that clearly match my criteria

**Solution**:
1. Review and rewrite your inclusion/exclusion criteria to be clearer and more specific.
2. Test with 10 known papers (5 that should be included, 5 that should not). Analyze where the AI goes wrong.
3. Try a more capable model (e.g., switch from gpt-4o-mini to gpt-4o).
4. Add example decisions to your criteria prompt: "For example, a paper titled 'Effect of metformin on HbA1c in type 2 diabetics' SHOULD be included; a paper titled 'Review of diabetes treatments' SHOULD be excluded."

---

## 16. Frequently Asked Questions

**Q: Is my data safe? Does the AI company read my papers?**

A: When using cloud providers (OpenAI, Anthropic, etc.), your paper text is sent to their servers for processing. Most academic and business plans explicitly state that your data is not used to train new models. Check each provider's privacy policy. For maximum privacy, use Ollama — everything runs on your computer and nothing leaves it.

---

**Q: Will the AI make mistakes? Is it reliable enough for a real systematic review?**

A: Yes, AI can make mistakes. You must review its decisions, particularly:
- All papers marked "Flag for Review" (you must decide these yourself).
- A random 5–10% sample of papers marked "Exclude" to verify accuracy.
- All included papers before using them in your review.

Research has shown that modern LLMs achieve accuracy comparable to trained human reviewers for abstract screening (80–95% agreement). Use the AI as a first pass, then apply your expert judgment.

---

**Q: Do I still need to follow PRISMA reporting guidelines?**

A: Yes. This tool helps you execute PRISMA phases efficiently, but you still need to:
- Document your search strategy.
- Report the numbers at each PRISMA stage (identified, duplicates removed, screened, excluded, included).
- Justify your inclusion/exclusion criteria.
- Report that AI-assisted screening was used and describe how (this is increasingly accepted and often required to disclose).

---

**Q: Can I use this tool for a scoping review, not just a systematic review?**

A: Yes. The tool works for scoping reviews, rapid reviews, umbrella reviews, and any structured literature search where you need to screen many papers against defined criteria.

---

**Q: The AI extracted incorrect information from a paper (e.g., wrong sample size). What do I do?**

A: Manual verification of extracted data is always required. Use the tool's extraction as a first draft and check all critical data points against the original papers. This is standard practice in systematic reviews even with human extractors.

---

**Q: Can I use this tool for papers in languages other than English?**

A: Yes. The AI can process papers in multiple languages. However, your performance may vary by language. Write your criteria in the same language as your papers, or write criteria in English and note that papers may be in other languages.

---

**Q: My university has restrictions on using AI tools. Can I still use this?**

A: Check your institution's policies. Most universities now have guidance on acceptable AI use in research. Key considerations:
- **Transparency**: Disclose AI use in your methods section.
- **Verification**: All AI decisions must be human-verified.
- **Data privacy**: Use local models (Ollama) if your papers are confidential or unpublished.

---

**Q: Can multiple people use the same project simultaneously?**

A: Not directly — this is a single-user desktop application. However, you can share the output folder on a network drive and have multiple team members review results simultaneously. For multi-user screening (the gold standard is dual independent screening), each reviewer can run the tool separately and compare results.

---

## 17. Best Practices for Researchers

### Before You Start

1. **Write your protocol first** — Decide your research question (PICO/PICOS framework is common), inclusion/exclusion criteria, and data extraction fields before touching the tool. A well-written protocol leads to better AI screening.
2. **Do a pilot test** — Before processing all 3,000 papers, process 20–30 known papers (including both ones you know should be included and excluded) to calibrate the AI.
3. **Start small** — Run 10 PDFs first to confirm your settings, criteria, and output format are correct.

### During Processing

4. **Keep caching enabled** — Always. This is your safety net if processing is interrupted.
5. **Monitor the token counter** — Stop early if costs are much higher than expected.
6. **Save your settings** — Use "Save Settings" to preserve your configuration for each project.

### After Processing

7. **Review all "Flag for Review" papers** — These must be human-decided.
8. **Audit a random sample of "Exclude" decisions** — Check 5–10% of excluded papers to verify the AI is not incorrectly excluding relevant papers.
9. **Cross-validate extraction data** — Spot-check 10–20% of extracted data against the original papers.
10. **Document your AI use** — For your methods section, record: which AI provider and model you used, how you configured the criteria, and what human verification steps you took.

### For Collaborative Projects

11. **Share criteria files** — Export your criteria and give them to collaborators so everyone uses the same settings.
12. **Use dated output folders** — Name your output folders with dates (e.g., `output_2026-02-26`) to keep different processing runs organized.
13. **Back up results regularly** — Copy output files to a cloud drive or external storage after each processing run.

---

## 18. Keyboard Shortcuts

These shortcuts work when the application window is in focus:

| Shortcut | Action |
|---|---|
| `F5` | Start Processing |
| `F6` | Stop Processing |
| `F1` | Go to Help tab |
| `Ctrl + S` | Save Settings |

---

## 19. Glossary of Terms

**Abstract**: A short summary (usually 150–300 words) at the beginning of a research paper. In PRISMA, you first screen abstracts before reading full papers.

**API (Application Programming Interface)**: A communication channel that allows this tool to send your papers to an AI service over the internet and receive results.

**API Key**: A unique password/identifier that connects your account to an AI provider. Keep it confidential.

**Caching**: Saving the results of completed work so they do not need to be repeated if the process is interrupted.

**CONSORT**: A reporting standard similar to PRISMA, specifically for randomized controlled trials.

**CSV (Comma-Separated Values)**: A basic spreadsheet file format that can be opened with Excel, Google Sheets, or any data analysis software.

**Deduplication**: The process of removing duplicate records that appear multiple times (often because the same paper was found in multiple databases).

**Excel (.xlsx)**: A Microsoft Office spreadsheet format. The tool generates Excel files with color-coded results.

**Extraction**: Pulling specific information from papers (e.g., sample size, methods, findings) and recording it in a structured format.

**PICO / PICOS**: A framework for defining systematic review research questions: Population, Intervention, Comparison, Outcome, (Study design). Commonly used to derive inclusion/exclusion criteria.

**PRISMA**: Preferred Reporting Items for Systematic Reviews and Meta-Analyses. An international standard workflow and reporting checklist for systematic reviews.

**Provider**: An AI company whose AI models this tool connects to (OpenAI, Anthropic, DeepSeek, Mistral, Google, Ollama).

**RIS Format**: A standard file format for sharing reference lists between academic database software and reference managers (e.g., Zotero, Mendeley, EndNote). Files end in `.ris`.

**Screening**: The process of reading paper titles and/or abstracts to decide whether they meet inclusion criteria.

**SLR (Systematic Literature Review)**: A rigorous, reproducible method for identifying, evaluating, and synthesizing all available evidence on a research question.

**Token**: A unit of text processed by AI. Roughly 4 characters or ¾ of an English word. AI providers charge per token.

**Two-Stage Processing**: An option where the AI first screens papers and then, for those that pass, performs detailed data extraction. Saves time and cost when many papers are expected to be excluded.

**Model**: A specific version of an AI (e.g., gpt-4o-mini is one model made by OpenAI). Different models have different capabilities and prices.

**LLM (Large Language Model)**: A type of AI trained on vast amounts of text, capable of reading, understanding, and generating human language. The AI powering the screening and extraction in this tool is an LLM.

**Ollama**: A free, open-source program that lets you run AI models on your own computer without internet access or any fees.

**Parallel Processing**: Running multiple tasks at the same time. When enabled, the tool processes several PDF files simultaneously instead of one at a time.

**Rate Limit**: A restriction set by AI providers on how many requests you can make per minute. If exceeded, you receive an error and must slow down.

**Temperature**: A setting that controls how predictable vs. creative an AI's responses are. For systematic reviews, use a very low temperature (close to 0) so results are consistent and reproducible.

---

*This guide covers the tool's full functionality as of version 3.0. If you encounter a situation not covered here, check the built-in Help tab (❓) in the application, or review the Processing Log for detailed error messages.*

*For systematic reviews, always consult your institution's research methods guidance and report AI-assisted screening transparently in your methods section.*

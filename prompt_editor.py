"""
Prompt Editor — Universal SLR / Scoping Review Automation
Allows customization of screening criteria, extraction prompts,
and the list of extraction fields (fully domain-agnostic).
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import json


class PromptEditorDialog:

    def __init__(self, parent, screening_prompt=None, extraction_prompt=None,
                 extraction_fields=None):
        self.parent = parent
        self.result = None

        # ── Defaults ──────────────────────────────────────────────────────
        self.default_screening_prompt = (
            "You are an expert AI assistant supporting a systematic or scoping review.\n"
            "Read the paper below and decide whether it meets the review criteria.\n\n"
            "INCLUSION CRITERIA:\n"
            "  [Define here — e.g. study design, population, intervention, outcome, date range]\n\n"
            "EXCLUSION CRITERIA:\n"
            "  [Define here — e.g. animal-only, non-English, editorials, grey literature]\n\n"
            "Paper text:\n{text}\n\n"
            "Return ONLY a valid JSON object (no prose, no markdown fences):\n"
            '{{\n'
            '    "decision": "Likely Include | Likely Exclude | Flag for Review | Flag for Human Review",\n'
            '    "reasoning": "Detailed reasoning referencing each criterion",\n'
            '    "notes": "Quality concerns, missing information, or caveats"\n'
            '}}'
        )

        self.default_extraction_prompt = (
            "You are an expert data extractor for academic systematic/scoping reviews.\n"
            "Extract the information below from the research paper.\n"
            "Use 'Not reported' if a field cannot be found in the text.\n\n"
            "Paper text:\n{text}\n\n"
            "Return ONLY a valid JSON object (no prose, no markdown fences):\n"
            "{{\n"
            '    "field_name": "extracted value",\n'
            '    "add_your_fields_here": "value"\n'
            "}}"
        )

        self.default_extraction_fields = [
            "title", "authors", "publication_year", "study_design",
            "study_objectives", "methodology", "population", "sample_size",
            "main_findings", "conclusions", "limitations", "keywords"
        ]

        self.screening_prompt  = screening_prompt  or self.default_screening_prompt
        self.extraction_prompt = extraction_prompt or self.default_extraction_prompt
        self.extraction_fields = list(extraction_fields or self.default_extraction_fields)

        self._create_dialog()

    def _create_dialog(self):
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Customize Research Criteria, Prompts & Extraction Fields")
        self.dialog.geometry("860x700")
        self.dialog.transient(self.parent)
        self.dialog.grab_set()
        self.dialog.resizable(True, True)

        # Center
        self.dialog.update_idletasks()
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        self.dialog.geometry(f"860x700+{(sw-860)//2}+{(sh-700)//2}")

        main = ttk.Frame(self.dialog, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        self.dialog.columnconfigure(0, weight=1)
        self.dialog.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text="Customize Research Criteria, Extraction Fields & Prompts",
                  font=("Segoe UI", 12, "bold")).grid(row=0, column=0, pady=(0, 10))

        self.nb = ttk.Notebook(main)
        self.nb.grid(row=1, column=0, sticky="nsew", pady=(0, 10))

        self._tab_screening()
        self._tab_extraction()
        self._tab_fields()
        self._tab_help()

        # Buttons
        btn_row = ttk.Frame(main)
        btn_row.grid(row=2, column=0, sticky="ew")
        ttk.Button(btn_row, text="Save & Apply",  command=self._save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Load Template", command=self._load_template).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Reset Defaults", command=self._reset).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Cancel",         command=self._cancel).pack(side=tk.RIGHT)

        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)

    # ── Tab: Screening ───────────────────────────────────────────────────────

    def _tab_screening(self):
        frm = ttk.Frame(self.nb, padding=10)
        self.nb.add(frm, text="Screening Criteria")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)

        info = ("Define your inclusion and exclusion criteria.\n"
                "The AI will apply these to decide Include / Exclude / Flag.\n"
                "Keep the {text} placeholder exactly as-is — it is replaced with the paper text.")
        ttk.Label(frm, text=info, foreground="#555", wraplength=800,
                  justify=tk.LEFT).grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.screening_text = scrolledtext.ScrolledText(frm, wrap=tk.WORD, font=("Consolas", 10))
        self.screening_text.grid(row=1, column=0, sticky="nsew")
        self.screening_text.insert(tk.END, self.screening_prompt)

    # ── Tab: Extraction Prompt ───────────────────────────────────────────────

    def _tab_extraction(self):
        frm = ttk.Frame(self.nb, padding=10)
        self.nb.add(frm, text="Extraction Prompt")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)

        info = ("Write your data extraction prompt.\n"
                "The AI will return a JSON object with keys matching your field names.\n"
                "Tip: Define fields in the 'Extraction Fields' tab first, then use\n"
                "'Reset Defaults' to auto-generate a prompt that references those fields.")
        ttk.Label(frm, text=info, foreground="#555", wraplength=800,
                  justify=tk.LEFT).grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.extraction_text = scrolledtext.ScrolledText(frm, wrap=tk.WORD, font=("Consolas", 10))
        self.extraction_text.grid(row=1, column=0, sticky="nsew")
        self.extraction_text.insert(tk.END, self.extraction_prompt)

    # ── Tab: Extraction Fields ───────────────────────────────────────────────

    def _tab_fields(self):
        frm = ttk.Frame(self.nb, padding=10)
        self.nb.add(frm, text="Extraction Fields")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(2, weight=1)

        info = ("These field names become the columns in your CSV and Excel output.\n"
                "Add, remove, or rename fields to match your research domain.\n"
                "One field name per line. Spaces are replaced with underscores automatically.")
        ttk.Label(frm, text=info, foreground="#555", wraplength=800,
                  justify=tk.LEFT).grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(frm, text="Field names (one per line):",
                  font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky=tk.W, pady=(0, 4))

        self.fields_text = scrolledtext.ScrolledText(frm, wrap=tk.WORD, font=("Consolas", 10),
                                                      height=20)
        self.fields_text.grid(row=2, column=0, sticky="nsew")
        self.fields_text.insert(tk.END, "\n".join(self.extraction_fields))

        # Quick domain presets
        preset_row = ttk.Frame(frm)
        preset_row.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(preset_row, text="Presets:").pack(side=tk.LEFT, padx=(0, 8))
        presets = {
            "Generic SLR":        ["title","authors","publication_year","study_design","study_objectives",
                                   "methodology","population","sample_size","main_findings",
                                   "conclusions","limitations","keywords"],
            "Medical / Clinical": ["title","authors","year","study_design","condition_disease",
                                   "population","intervention","comparator","outcomes_measured",
                                   "sample_size","follow_up_duration","main_results",
                                   "adverse_events","funding_source","risk_of_bias"],
            "Education":          ["title","authors","year","education_level","subject_area",
                                   "study_design","participants","intervention_description",
                                   "control_condition","outcome_measures","key_findings",
                                   "effect_size","context_country"],
            "Environmental":      ["title","authors","year","environmental_domain",
                                   "geographic_location","study_duration","exposure_factors",
                                   "outcome_measured","data_collection_method",
                                   "main_findings","policy_implications"],
            "Psychology / Social":["title","authors","year","theoretical_framework",
                                   "population","sample_size","study_design","measurement_tools",
                                   "independent_variables","dependent_variables",
                                   "main_findings","effect_size","limitations"],
            "Engineering / Tech": ["title","authors","year","technology_domain",
                                   "research_objective","methodology","datasets_used",
                                   "performance_metrics","results","comparison_baselines",
                                   "limitations","future_work"],
        }
        for name, fields in presets.items():
            ttk.Button(preset_row, text=name,
                       command=lambda f=fields: self._apply_field_preset(f)).pack(
                side=tk.LEFT, padx=(0, 4))

    def _apply_field_preset(self, fields):
        self.fields_text.delete(1.0, tk.END)
        self.fields_text.insert(tk.END, "\n".join(fields))

    # ── Tab: Help ────────────────────────────────────────────────────────────

    def _tab_help(self):
        frm = ttk.Frame(self.nb, padding=10)
        self.nb.add(frm, text="Help & Tips")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        help_text = """
QUICK START
  1. Go to 'Extraction Fields' → choose a domain preset or define your own fields.
  2. Go to 'Screening Criteria' → replace the placeholder criteria with your actual
     PICO/SPIDER/PEO or custom inclusion/exclusion criteria.
  3. Optionally edit the 'Extraction Prompt' to match your fields.
  4. Click 'Save & Apply'.

SCREENING PROMPT TIPS
  • Be specific — vague criteria produce inconsistent AI decisions.
  • Mention study types you want (RCT, qualitative, mixed-methods, scoping, etc.).
  • Specify publication year range if relevant.
  • Include language requirements.
  • Mention any domain-specific must-have or must-exclude elements.
  • The {text} placeholder is where the paper content is inserted — keep it intact.

EXTRACTION PROMPT TIPS
  • Name your fields exactly as you list them in 'Extraction Fields'.
  • Instruct the model to use "Not reported" for missing data (avoids hallucination).
  • For specific formats (e.g. "year as YYYY" or "sample size as integer"), say so.
  • Tell the model what to do with multiple values, e.g. "list all authors separated by semicolons".

SCREENING DECISIONS
  • "Likely Include"       → meets inclusion criteria
  • "Likely Exclude"       → fails inclusion or meets exclusion
  • "Flag for Review"      → uncertain; human should check abstract/methodology
  • "Flag for Human Review"→ needs full human reading (conflicting criteria, key paper, etc.)

COST-SAVING TIPS
  • Enable Two-Stage Screening in Setup — reads only title/abstract first, saves ~40-70% tokens.
  • Use a smaller model (gpt-4o-mini, gemini-flash, claude-haiku) for screening,
    and switch to a larger model for extraction if precision matters.
  • Enable caching — already-processed files are never re-sent to the API.

JSON FORMAT NOTE
  The tool automatically strips markdown fences (```json```) from AI responses
  and extracts the first valid {…} block, so minor LLM formatting issues
  never crash processing.
"""
        st = scrolledtext.ScrolledText(frm, wrap=tk.WORD, font=("Segoe UI", 10))
        st.grid(row=0, column=0, sticky="nsew")
        st.insert(tk.END, help_text)
        st.config(state=tk.DISABLED)

    # ── Load template ────────────────────────────────────────────────────────

    def _load_template(self):
        TemplateSelector(self.dialog, self._apply_template)

    def _apply_template(self, name, screening, extraction, fields):
        self.screening_text.delete(1.0, tk.END)
        self.screening_text.insert(tk.END, screening)
        self.extraction_text.delete(1.0, tk.END)
        self.extraction_text.insert(tk.END, extraction)
        self._apply_field_preset(fields)
        messagebox.showinfo("Template Applied", f"Applied template: {name}")

    # ── Reset ────────────────────────────────────────────────────────────────

    def _reset(self):
        if messagebox.askyesno("Reset", "Reset all prompts and fields to defaults?"):
            self.screening_text.delete(1.0, tk.END)
            self.screening_text.insert(tk.END, self.default_screening_prompt)
            self.extraction_text.delete(1.0, tk.END)
            self.extraction_text.insert(tk.END, self.default_extraction_prompt)
            self.fields_text.delete(1.0, tk.END)
            self.fields_text.insert(tk.END, "\n".join(self.default_extraction_fields))

    # ── Validate & Save ──────────────────────────────────────────────────────

    def _validate(self) -> bool:
        sp = self.screening_text.get(1.0, tk.END).strip()
        ep = self.extraction_text.get(1.0, tk.END).strip()

        if "{text}" not in sp:
            messagebox.showerror("Validation", "Screening prompt must contain {text} placeholder.")
            self.nb.select(0)
            return False
        if "{text}" not in ep:
            messagebox.showerror("Validation", "Extraction prompt must contain {text} placeholder.")
            self.nb.select(1)
            return False

        raw_fields = [ln.strip().replace(' ', '_')
                      for ln in self.fields_text.get(1.0, tk.END).splitlines()
                      if ln.strip()]
        if not raw_fields:
            messagebox.showerror("Validation", "At least one extraction field is required.")
            self.nb.select(2)
            return False

        self._parsed_fields = raw_fields
        return True

    def _save(self):
        if self._validate():
            self.result = {
                'screening_prompt':  self.screening_text.get(1.0, tk.END).strip(),
                'extraction_prompt': self.extraction_text.get(1.0, tk.END).strip(),
                'extraction_fields': self._parsed_fields,
            }
            self.dialog.destroy()

    def _cancel(self):
        self.result = None
        self.dialog.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Template selector
# ─────────────────────────────────────────────────────────────────────────────

class TemplateSelector:

    TEMPLATES = [
        (
            "Generic SLR / Scoping Review",
            # Screening
            (
                "You are screening papers for a systematic/scoping review.\n\n"
                "INCLUSION CRITERIA:\n"
                "  • Primary research (any design)\n"
                "  • Published 2010–2024\n"
                "  • English language\n"
                "  • Addresses [your topic here]\n\n"
                "EXCLUSION CRITERIA:\n"
                "  • Editorials, opinions, commentaries\n"
                "  • Conference abstracts only (no full text)\n"
                "  • Duplicate studies\n\n"
                "Paper text:\n{text}\n\n"
                "Return ONLY JSON:\n"
                '{{\n'
                '    "decision": "Likely Include | Likely Exclude | Flag for Review | Flag for Human Review",\n'
                '    "reasoning": "Reasoning referencing each criterion",\n'
                '    "notes": "Caveats or missing info"\n'
                '}}'
            ),
            # Extraction
            (
                "Extract data from this research paper for a systematic review.\n\n"
                "Text:\n{text}\n\n"
                "Return ONLY JSON:\n"
                '{{\n'
                '    "title": "Full title",\n'
                '    "authors": "Surname, Initials; ...",\n'
                '    "publication_year": "YYYY",\n'
                '    "study_design": "RCT / cohort / qualitative / etc.",\n'
                '    "study_objectives": "What the study aimed to do",\n'
                '    "methodology": "Methods used",\n'
                '    "population": "Sample description",\n'
                '    "sample_size": "N = ?",\n'
                '    "main_findings": "Key results",\n'
                '    "conclusions": "Authors conclusions",\n'
                '    "limitations": "Study limitations",\n'
                '    "keywords": "Keyword1; Keyword2"\n'
                '}}'
            ),
            ["title","authors","publication_year","study_design","study_objectives",
             "methodology","population","sample_size","main_findings",
             "conclusions","limitations","keywords"],
        ),
        (
            "Medical / Clinical Research",
            (
                "Screen this clinical/medical study for inclusion in a systematic review.\n\n"
                "INCLUSION CRITERIA:\n"
                "  • Human participants\n"
                "  • Clinical intervention or observational study\n"
                "  • Published in peer-reviewed journal\n"
                "  • Reports quantitative or mixed-methods results\n"
                "  • [Add your condition / population / intervention here]\n\n"
                "EXCLUSION CRITERIA:\n"
                "  • Animal/lab studies only\n"
                "  • Case reports (n<5)\n"
                "  • Non-English\n"
                "  • No measurable outcomes\n\n"
                "Text:\n{text}\n\n"
                "Return ONLY JSON:\n"
                '{{\n'
                '    "decision": "Likely Include | Likely Exclude | Flag for Review | Flag for Human Review",\n'
                '    "reasoning": "Criterion-by-criterion reasoning",\n'
                '    "notes": "Bias risks or data quality notes"\n'
                '}}'
            ),
            (
                "Extract clinical data from this study.\n\nText:\n{text}\n\nReturn ONLY JSON:\n"
                '{{\n'
                '    "title": "", "authors": "", "year": "",\n'
                '    "study_design": "", "condition_disease": "",\n'
                '    "population": "", "intervention": "", "comparator": "",\n'
                '    "outcomes_measured": "", "sample_size": "",\n'
                '    "follow_up_duration": "", "main_results": "",\n'
                '    "adverse_events": "", "funding_source": "", "risk_of_bias": ""\n'
                '}}'
            ),
            ["title","authors","year","study_design","condition_disease",
             "population","intervention","comparator","outcomes_measured",
             "sample_size","follow_up_duration","main_results",
             "adverse_events","funding_source","risk_of_bias"],
        ),
        (
            "Education Research",
            (
                "Screen this education study for inclusion.\n\n"
                "INCLUSION CRITERIA:\n"
                "  • Educational setting (K-12, higher education, or vocational training)\n"
                "  • Reports measurable learning/teaching outcomes\n"
                "  • Empirical study (qualitative or quantitative)\n\n"
                "EXCLUSION CRITERIA:\n"
                "  • Purely theoretical/conceptual papers\n"
                "  • Unpublished theses only\n\n"
                "Text:\n{text}\n\n"
                "Return ONLY JSON:\n"
                '{{"decision":"...","reasoning":"...","notes":"..."}}'
            ),
            (
                "Extract education research data.\n\nText:\n{text}\n\nReturn ONLY JSON:\n"
                '{{\n'
                '    "title":"","authors":"","year":"","education_level":"","subject_area":"",\n'
                '    "study_design":"","participants":"","intervention_description":"",\n'
                '    "control_condition":"","outcome_measures":"","key_findings":"",\n'
                '    "effect_size":"","context_country":""\n'
                '}}'
            ),
            ["title","authors","year","education_level","subject_area",
             "study_design","participants","intervention_description",
             "control_condition","outcome_measures","key_findings",
             "effect_size","context_country"],
        ),
        (
            "Environmental / Sustainability",
            (
                "Screen this environmental study.\n\n"
                "INCLUSION CRITERIA:\n"
                "  • Empirical environmental data collection\n"
                "  • Climate, ecology, pollution, or sustainability focus\n"
                "  • Published 2015–2024\n\n"
                "EXCLUSION CRITERIA:\n"
                "  • Policy/opinion pieces without primary data\n"
                "  • Non-peer reviewed\n\n"
                "Text:\n{text}\n\n"
                "Return ONLY JSON:\n"
                '{{"decision":"...","reasoning":"...","notes":"..."}}'
            ),
            (
                "Extract environmental study data.\n\nText:\n{text}\n\nReturn ONLY JSON:\n"
                '{{\n'
                '    "title":"","authors":"","year":"","environmental_domain":"",\n'
                '    "geographic_location":"","study_duration":"","exposure_factors":"",\n'
                '    "outcome_measured":"","data_collection_method":"",\n'
                '    "main_findings":"","policy_implications":""\n'
                '}}'
            ),
            ["title","authors","year","environmental_domain","geographic_location",
             "study_duration","exposure_factors","outcome_measured",
             "data_collection_method","main_findings","policy_implications"],
        ),
        (
            "Technology / Engineering",
            (
                "Screen this technology or engineering research paper.\n\n"
                "INCLUSION CRITERIA:\n"
                "  • Proposes or evaluates a technical system, algorithm, or method\n"
                "  • Reports quantitative performance metrics\n"
                "  • Peer-reviewed\n\n"
                "EXCLUSION CRITERIA:\n"
                "  • Position papers without experiments\n"
                "  • Purely mathematical proofs without system evaluation\n\n"
                "Text:\n{text}\n\n"
                "Return ONLY JSON:\n"
                '{{"decision":"...","reasoning":"...","notes":"..."}}'
            ),
            (
                "Extract technology research data.\n\nText:\n{text}\n\nReturn ONLY JSON:\n"
                '{{\n'
                '    "title":"","authors":"","year":"","technology_domain":"",\n'
                '    "research_objective":"","methodology":"","datasets_used":"",\n'
                '    "performance_metrics":"","results":"","comparison_baselines":"",\n'
                '    "limitations":"","future_work":""\n'
                '}}'
            ),
            ["title","authors","year","technology_domain","research_objective",
             "methodology","datasets_used","performance_metrics","results",
             "comparison_baselines","limitations","future_work"],
        ),
    ]

    def __init__(self, parent, callback):
        self.callback = callback
        dlg = tk.Toplevel(parent)
        dlg.title("Select Template")
        dlg.geometry("640x400")
        dlg.transient(parent)
        dlg.grab_set()
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"640x400+{(sw-640)//2}+{(sh-400)//2}")

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=1)

        ttk.Label(main, text="Select a Template",
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, pady=(0, 8))

        self.lb = tk.Listbox(main, font=("Segoe UI", 10), activestyle="dotbox",
                             selectbackground="#2D6A9F", selectforeground="white")
        self.lb.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(main, command=self.lb.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.lb.configure(yscrollcommand=sb.set)

        for name, *_ in self.TEMPLATES:
            self.lb.insert(tk.END, f"  {name}")

        bf = ttk.Frame(main)
        bf.grid(row=2, column=0, pady=(8, 0))
        ttk.Button(bf, text="Apply", command=lambda: self._apply(dlg)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bf, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT)
        self.lb.bind("<Double-1>", lambda _: self._apply(dlg))

    def _apply(self, dlg):
        sel = self.lb.curselection()
        if not sel:
            messagebox.showwarning("Select", "Please select a template first.")
            return
        name, screening, extraction, fields = self.TEMPLATES[sel[0]]
        self.callback(name, screening, extraction, fields)
        dlg.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Public helper called by slr_gui.py
# ─────────────────────────────────────────────────────────────────────────────

def show_prompt_editor(parent, screening_prompt=None, extraction_prompt=None,
                       extraction_fields=None):
    dlg = PromptEditorDialog(parent, screening_prompt, extraction_prompt, extraction_fields)
    parent.wait_window(dlg.dialog)
    return dlg.result


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    r = show_prompt_editor(root)
    if r:
        print("Screening prompt set:", bool(r.get('screening_prompt')))
        print("Extraction fields:", r.get('extraction_fields'))
    root.destroy()

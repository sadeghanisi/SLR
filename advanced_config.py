"""
Advanced Configuration Dialog — SLR Automation Tool
Covers: LLM generation parameters, text handling, output options, processing behavior.
"""

import tkinter as tk
from tkinter import ttk, messagebox


def show_advanced_config(parent, current_config: dict) -> dict | None:
    dlg = AdvancedConfigDialog(parent, current_config)
    parent.wait_window(dlg.dialog)
    return dlg.result


class AdvancedConfigDialog:

    DEFAULTS = {
        # LLM generation
        "temperature": 0.1,
        "max_tokens": 4000,
        "request_timeout": 90,
        "max_retries": 3,
        "retry_delay": 5,
        # Text handling
        "max_chars": 12000,
        "two_stage_chars": 3000,
        "skip_pages": 0,
        "strip_references": True,
        # Processing
        "max_workers": 1,
        "use_cache": True,
        "dry_run": False,
        # Output
        "include_excluded": True,
        "output_format": "both",    # csv | excel | both
    }

    def __init__(self, parent, current_config: dict):
        self.parent = parent
        self.result = None
        cfg = {**self.DEFAULTS, **current_config}

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Advanced Configuration")
        self.dialog.geometry("560x560")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.resizable(True, True)
        self.dialog.update_idletasks()
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        self.dialog.geometry(f"560x560+{(sw-560)//2}+{(sh-560)//2}")

        main = ttk.Frame(self.dialog, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text="Advanced Configuration",
                  font=("Segoe UI", 12, "bold")).pack(pady=(0, 8))

        nb = ttk.Notebook(main)
        nb.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # ── Build widgets ─────────────────────────────────────────────────
        t1 = ttk.Frame(nb, padding=14)
        t2 = ttk.Frame(nb, padding=14)
        t3 = ttk.Frame(nb, padding=14)
        t4 = ttk.Frame(nb, padding=14)
        nb.add(t1, text="LLM Parameters")
        nb.add(t2, text="Text Handling")
        nb.add(t3, text="Processing")
        nb.add(t4, text="Output")

        self._build_llm_tab(t1, cfg)
        self._build_text_tab(t2, cfg)
        self._build_proc_tab(t3, cfg)
        self._build_out_tab(t4, cfg)

        # Buttons
        bf = ttk.Frame(main)
        bf.pack(fill=tk.X)
        ttk.Button(bf, text="Save",          command=self._save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bf, text="Reset Defaults", command=lambda: self._reset(cfg)).pack(side=tk.LEFT)
        ttk.Button(bf, text="Cancel",         command=self._cancel).pack(side=tk.RIGHT)

        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)

    # ── LLM Parameters tab ───────────────────────────────────────────────────

    def _build_llm_tab(self, frm, cfg):
        frm.columnconfigure(1, weight=1)
        rows = [
            ("Temperature (0–1):",      "temperature",    "float",
             "Controls randomness. Lower = more deterministic (recommended: 0.0–0.2 for extraction)."),
            ("Max tokens per response:", "max_tokens",     "int",
             "Maximum tokens the model may return per call. 2000–8000 recommended."),
            ("Request timeout (s):",    "request_timeout","int",
             "Seconds before aborting an unresponsive API call."),
            ("Max retries on error:",   "max_retries",    "int",
             "How many times to retry a failed API call automatically."),
            ("Retry delay (s):",        "retry_delay",    "int",
             "Seconds to wait between retries (exponential back-off applied)."),
        ]
        self._llm_vars = {}
        for r, (label, key, typ, tip) in enumerate(rows):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky=tk.W, pady=4)
            var = tk.DoubleVar(value=cfg[key]) if typ == "float" else tk.IntVar(value=int(cfg[key]))
            self._llm_vars[key] = (var, typ)
            ent = ttk.Entry(frm, textvariable=var, width=12)
            ent.grid(row=r, column=1, sticky=tk.W, padx=(8, 0))
            ttk.Label(frm, text=tip, foreground="#777", font=("Segoe UI", 8),
                      wraplength=340).grid(row=r, column=2, sticky=tk.W, padx=(10, 0))

    # ── Text Handling tab ────────────────────────────────────────────────────

    def _build_text_tab(self, frm, cfg):
        frm.columnconfigure(1, weight=1)
        rows = [
            ("Max characters per paper:", "max_chars", "int",
             "Maximum characters extracted from each PDF. Larger = more context, higher cost."),
            ("Stage-1 chars (two-stage):", "two_stage_chars", "int",
             "Characters used for first-pass title/abstract screening when two-stage is enabled."),
            ("Skip first N pages:", "skip_pages", "int",
             "Skip cover/copyright pages. Useful for journals that put metadata on page 1."),
        ]
        self._text_vars = {}
        for r, (label, key, typ, tip) in enumerate(rows):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky=tk.W, pady=4)
            var = tk.IntVar(value=int(cfg[key]))
            self._text_vars[key] = var
            ent = ttk.Entry(frm, textvariable=var, width=12)
            ent.grid(row=r, column=1, sticky=tk.W, padx=(8, 0))
            ttk.Label(frm, text=tip, foreground="#777", font=("Segoe UI", 8),
                      wraplength=340).grid(row=r, column=2, sticky=tk.W, padx=(10, 0))

        r += 1
        self._strip_refs = tk.BooleanVar(value=bool(cfg.get("strip_references", True)))
        ttk.Checkbutton(frm, text="Strip reference list before sending to LLM",
                        variable=self._strip_refs).grid(row=r, column=0, columnspan=3,
                                                         sticky=tk.W, pady=(10, 0))
        ttk.Label(frm,
                  text="Heuristically removes the bibliography section to reduce token usage.",
                  foreground="#777", font=("Segoe UI", 8),
                  wraplength=500).grid(row=r+1, column=0, columnspan=3, sticky=tk.W)

    # ── Processing tab ───────────────────────────────────────────────────────

    def _build_proc_tab(self, frm, cfg):
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Parallel workers:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self._workers = tk.IntVar(value=int(cfg.get("max_workers", 1)))
        ttk.Spinbox(frm, from_=1, to=16, textvariable=self._workers, width=5).grid(
            row=0, column=1, sticky=tk.W, padx=(8, 0))
        ttk.Label(frm, text="Number of PDFs processed simultaneously. "
                              "Increase carefully — too high risks rate-limit errors.",
                  foreground="#777", font=("Segoe UI", 8),
                  wraplength=360).grid(row=0, column=2, sticky=tk.W, padx=(10, 0))

        self._use_cache = tk.BooleanVar(value=bool(cfg.get("use_cache", True)))
        self._dry_run   = tk.BooleanVar(value=bool(cfg.get("dry_run", False)))

        cf = ttk.Checkbutton(frm, text="Enable result caching (skip already-processed files)",
                             variable=self._use_cache)
        cf.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(12, 2))
        ttk.Label(frm, text="Saves progress between runs. Re-running on same folder resumes where it left off.",
                  foreground="#777", font=("Segoe UI", 8),
                  wraplength=500).grid(row=2, column=0, columnspan=3, sticky=tk.W)

        dr = ttk.Checkbutton(frm, text="Dry run (extract text, skip LLM calls — for testing)",
                             variable=self._dry_run)
        dr.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(12, 2))
        ttk.Label(frm, text="Processes PDFs but sends no API calls. "
                              "Use to verify PDF extraction quality before spending credits.",
                  foreground="#777", font=("Segoe UI", 8),
                  wraplength=500).grid(row=4, column=0, columnspan=3, sticky=tk.W)

    # ── Output tab ───────────────────────────────────────────────────────────

    def _build_out_tab(self, frm, cfg):
        frm.columnconfigure(0, weight=1)

        self._include_excluded = tk.BooleanVar(value=bool(cfg.get("include_excluded", True)))
        ttk.Checkbutton(frm,
                        text="Include excluded papers in output (with reason)",
                        variable=self._include_excluded).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(frm, text="Recommended: keeps full audit trail for PRISMA reporting.",
                  foreground="#777", font=("Segoe UI", 8)).grid(row=1, column=0, sticky=tk.W)

        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(row=2, column=0, sticky="ew", pady=12)
        ttk.Label(frm, text="Output format:", font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, sticky=tk.W)

        self._out_format = tk.StringVar(value=cfg.get("output_format", "both"))
        fmts = [("CSV only", "csv"), ("Excel only", "excel"),
                ("Both CSV and Excel", "both")]
        for i, (lbl, val) in enumerate(fmts):
            ttk.Radiobutton(frm, text=lbl, value=val,
                            variable=self._out_format).grid(
                row=4+i, column=0, sticky=tk.W, padx=(16, 0))

    # ── Collect & save ───────────────────────────────────────────────────────

    def _collect(self) -> dict:
        cfg = {}

        # LLM vars
        for key, (var, typ) in self._llm_vars.items():
            cfg[key] = float(var.get()) if typ == "float" else int(var.get())

        # Text vars
        for key, var in self._text_vars.items():
            cfg[key] = int(var.get())
        cfg["strip_references"] = self._strip_refs.get()

        # Processing
        cfg["max_workers"]     = int(self._workers.get())
        cfg["use_cache"]       = self._use_cache.get()
        cfg["dry_run"]         = self._dry_run.get()

        # Output
        cfg["include_excluded"] = self._include_excluded.get()
        cfg["output_format"]    = self._out_format.get()

        return cfg

    def _validate(self, cfg: dict) -> bool:
        if not (0.0 <= cfg["temperature"] <= 1.0):
            messagebox.showerror("Validation", "Temperature must be between 0.0 and 1.0.")
            return False
        if cfg["max_tokens"] < 256:
            messagebox.showerror("Validation", "Max tokens should be at least 256.")
            return False
        if cfg["max_workers"] < 1:
            messagebox.showerror("Validation", "Workers must be ≥ 1.")
            return False
        return True

    def _save(self):
        try:
            cfg = self._collect()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid value", str(exc))
            return
        if self._validate(cfg):
            self.result = cfg
            self.dialog.destroy()

    def _reset(self, _prev_cfg):
        if messagebox.askyesno("Reset", "Reset all advanced settings to defaults?"):
            self.dialog.destroy()
            new_dlg = AdvancedConfigDialog(self.parent, self.DEFAULTS)
            self.parent.wait_window(new_dlg.dialog)
            self.result = new_dlg.result

    def _cancel(self):
        self.result = None
        self.dialog.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    r = show_advanced_config(root, {})
    if r:
        print("Config saved:", r)
    root.destroy()

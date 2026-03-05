"""
Universal Systematic / Scoping Review Automation — GUI
Works for any academic research domain.
"""

__version__ = "3.3.0"

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import queue
import os
import re
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
import webbrowser
import time
import traceback

try:
    from housing_enhanced import SystematicReviewAutomation, setup_logging
    from advanced_config  import show_advanced_config
    from prompt_editor    import show_prompt_editor
    from ingestion import (
        parse_references, deduplicate, AbstractScreener,
        export_records_to_csv, export_records_to_excel,
        DECISION_INCLUDE, DECISION_EXCLUDE, DECISION_FLAG, DECISION_ERROR,
    )
except ImportError as e:
    import tkinter.messagebox as _mb
    _mb.showerror("Import Error", f"Missing module:\n{e}\nEnsure all files are in the same directory.")
    sys.exit(1)

# ── Auto-save settings path ───────────────────────────────────────────────────
APP_DIR      = Path(__file__).parent
SETTINGS_FILE = APP_DIR / "settings.json"

# ── Tooltip helper ────────────────────────────────────────────────────────────

class Tooltip:
    def __init__(self, widget, text: str, delay: int = 600):
        self.widget = widget
        self.text   = text
        self.delay  = delay
        self._job   = None
        self._tip   = None
        widget.bind("<Enter>",  self._schedule)
        widget.bind("<Leave>",  self._cancel)
        widget.bind("<Button>", self._cancel)

    def _schedule(self, _=None):
        self._cancel()
        self._job = self.widget.after(self.delay, self._show)

    def _cancel(self, _=None):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def _show(self):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, background="#FFFFE0", relief="solid", borderwidth=1,
                 font=("Segoe UI", 9), wraplength=300, justify=tk.LEFT,
                 padx=6, pady=4).pack()


# ─────────────────────────────────────────────────────────────────────────────
# Main application
# ─────────────────────────────────────────────────────────────────────────────

class SLRAutomationGUI:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("SLR Automation Tool v3.3.0  —  by Mo Anisi")
        self.root.geometry("1150x800")
        self.root.minsize(950, 680)

        self._apply_theme()
        self._init_vars()
        self._build_ui()
        self._load_settings()
        self._check_queue()

    # ── Theme ────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        style = ttk.Style(self.root)
        try:
            from ttkthemes import ThemedStyle
            style = ThemedStyle(self.root)
            style.set_theme("arc")
        except ImportError:
            style.theme_use("clam")

        bg  = "#F7F9FC"
        acc = "#2D6A9F"
        self.root.configure(bg=bg)

        style.configure(".",             background=bg, font=("Segoe UI", 9))
        style.configure("TFrame",        background=bg)
        style.configure("TLabelframe",   background=bg)
        style.configure("TLabelframe.Label", foreground=acc, font=("Segoe UI", 9, "bold"))
        style.configure("TNotebook",     background=bg)
        style.configure("TNotebook.Tab", font=("Segoe UI", 9, "bold"), padding=[12, 5])

        style.configure("Title.TLabel",  font=("Segoe UI", 15, "bold"), foreground=acc, background=bg)
        style.configure("Sub.TLabel",    font=("Segoe UI", 9),          foreground="#555555", background=bg)
        style.configure("H.TLabel",      font=("Segoe UI", 9, "bold"),  background=bg)
        style.configure("OK.TLabel",     font=("Segoe UI", 9, "bold"),  foreground="#27ae60", background=bg)
        style.configure("ERR.TLabel",    font=("Segoe UI", 9, "bold"),  foreground="#c0392b", background=bg)
        style.configure("WARN.TLabel",   font=("Segoe UI", 9, "bold"),  foreground="#e67e22", background=bg)
        style.configure("PROC.TLabel",   font=("Segoe UI", 9, "bold"),  foreground=acc,       background=bg)

        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))
        style.configure("Stop.TButton",   font=("Segoe UI", 9, "bold"), foreground="#c0392b")
        style.configure("Big.TButton",    font=("Segoe UI", 10, "bold"), padding=[10, 6])
        style.configure("BigStop.TButton",font=("Segoe UI", 10, "bold"), foreground="#c0392b", padding=[10, 6])
        style.configure("Step.TButton",   font=("Segoe UI", 9, "bold"), padding=[6, 4])
        style.configure("Stat.TLabel",    font=("Segoe UI", 11, "bold"), background=bg)
        style.configure("StatSmall.TLabel",font=("Segoe UI", 8),        foreground="#777", background=bg)

        self._bg  = bg
        self._acc = acc

    # ── Variable initialisation ──────────────────────────────────────────────

    def _init_vars(self):
        self.pdf_folder      = tk.StringVar()
        self.output_folder   = tk.StringVar(value="output")
        self.api_key         = tk.StringVar()
        self.max_workers     = tk.IntVar(value=3)
        self.rate_limit_delay= tk.DoubleVar(value=1.0)
        self.parallel_proc   = tk.BooleanVar(value=True)
        self.cache_enabled   = tk.BooleanVar(value=True)
        self.two_stage       = tk.BooleanVar(value=False)
        self.llm_provider    = tk.StringVar(value="OpenAI")
        self.llm_model       = tk.StringVar(value="gpt-4o-mini")
        self.llm_base_url    = tk.StringVar()
        self.show_key        = tk.BooleanVar(value=False)

        self.advanced_config = {
            'max_text_chars': 100000,
            'max_retries': 3,
            'retry_delay': 0.5,
            'intermediate_save_interval': 5,
            'enable_smart_truncation': True,
            'preserve_sections': ['abstract', 'introduction', 'method', 'result', 'discussion', 'conclusion'],
        }

        self.screening_prompt  = None
        self.extraction_prompt = None
        self.extraction_fields = None   # None → backend uses defaults

        # ── Ingestion tab state ──────────────────────────────────────────────
        self._ingest_file_path   = tk.StringVar()
        self._ingest_file_info   = tk.StringVar(value="No file loaded")
        self._ingest_stats_var   = tk.StringVar(value="")
        self._ingest_records: list      = []   # raw parsed records
        self._ingest_dedup:   list      = []   # after deduplication
        self._ingest_results: list      = []   # AbstractScreeningResult list
        self._ingest_dedup_stats        = None
        self._screener: AbstractScreener | None = None
        self._ingest_running     = False

        self.is_processing      = False
        self.stop_event         = threading.Event()
        self.automation_instance = None
        self.message_queue      = queue.Queue()
        self._start_time        = None
        self._pdf_count_total   = 0
        self._conn_status       = "unchecked"   # "ok" | "fail" | "unchecked"

    # ── Master layout ─────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header bar
        hdr = tk.Frame(self.root, bg=self._acc, height=60)
        hdr.pack(fill=tk.X, side=tk.TOP)
        hdr.pack_propagate(False)
        title_blk = tk.Frame(hdr, bg=self._acc)
        title_blk.pack(side=tk.LEFT, padx=16, pady=8)
        tk.Label(title_blk, text="Universal SLR / Scoping Review Automation",
                 bg=self._acc, fg="white",
                 font=("Segoe UI", 13, "bold")).pack(anchor=tk.W)
        tk.Label(title_blk,
                 text="Systematic · Scoping · Any Research Domain",
                 bg=self._acc, fg="#BDD7EE",
                 font=("Segoe UI", 8)).pack(anchor=tk.W)
        # Version chip
        chip = tk.Frame(hdr, bg="#1A4971", padx=6, pady=2)
        chip.pack(side=tk.LEFT, padx=(0, 12), pady=18)
        tk.Label(chip, text="v3.0", bg="#1A4971", fg="#BDD7EE",
                 font=("Segoe UI", 8, "bold")).pack()
        # Connection indicator (right side)
        right_hdr = tk.Frame(hdr, bg=self._acc)
        right_hdr.pack(side=tk.RIGHT, padx=16)
        self._conn_dot = tk.Label(right_hdr, text="⬤ Not tested", bg=self._acc, fg="#AAAAAA",
                                  font=("Segoe UI", 9))
        self._conn_dot.pack()
        tk.Label(right_hdr, text="LLM connection", bg=self._acc, fg="#8EB4D8",
                 font=("Segoe UI", 7)).pack()

        # Notebook tabs
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 10))

        self.tab_ingest   = ttk.Frame(self.nb)
        self.tab_setup    = ttk.Frame(self.nb)
        self.tab_monitor  = ttk.Frame(self.nb)
        self.tab_results  = ttk.Frame(self.nb)
        self.tab_help     = ttk.Frame(self.nb)

        self.nb.add(self.tab_ingest,  text="📥  Ingestion")
        self.nb.add(self.tab_setup,   text="⚙  Setup")
        self.nb.add(self.tab_monitor, text="📊  Monitor")
        self.nb.add(self.tab_results, text="📋  Results")
        self.nb.add(self.tab_help,    text="❓  Help")

        self._build_ingestion_tab()
        self._build_setup_tab()
        self._build_monitor_tab()
        self._build_results_tab()
        self._build_help_tab()

        # Bottom status bar
        sbar = tk.Frame(self.root, bg="#DDE5EE", height=30)
        sbar.pack(fill=tk.X, side=tk.BOTTOM)
        sbar.pack_propagate(False)
        self.status_var = tk.StringVar(value="Ready — load a reference file or PDF folder to begin")
        tk.Label(sbar, textvariable=self.status_var, bg="#DDE5EE",
                 font=("Segoe UI", 9), anchor=tk.W, padx=12).pack(side=tk.LEFT, fill=tk.Y)
        self._status_time_var = tk.StringVar(value="")
        tk.Label(sbar, textvariable=self._status_time_var, bg="#DDE5EE",
                 font=("Segoe UI", 8), anchor=tk.E, padx=10,
                 foreground="#666").pack(side=tk.RIGHT, fill=tk.Y)
        # Keyboard shortcuts
        self.root.bind("<F5>",   lambda _: self._start())
        self.root.bind("<F6>",   lambda _: self._stop())
        self.root.bind("<F1>",   lambda _: self.nb.select(self.tab_help))
        self.root.bind("<Control-s>", lambda _: self._save_settings())
        self._tick_clock()

    def _tick_clock(self):
        self._status_time_var.set(datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    # ── INGESTION TAB ─────────────────────────────────────────────────────────

    def _build_ingestion_tab(self):
        """
        PRISMA Phase 2 & 3: import reference files (RIS/BIB/CSV),
        deduplicate, and run LLM title-abstract screening.
        No PDFs required at this stage.
        """
        outer = ttk.Frame(self.tab_ingest, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(6, weight=1)   # treeview row expands

        # ── Workflow banner ────────────────────────────────────────────────
        wf_frm = tk.Frame(outer, bg="#EAF2FB", bd=1, relief=tk.SOLID)
        wf_frm.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        wf_inner = tk.Frame(wf_frm, bg="#EAF2FB", padx=12, pady=8)
        wf_inner.pack(fill=tk.X)
        tk.Label(wf_inner, text="PRISMA Workflow  —  Phase 2 & 3: Reference Ingestion → Deduplication → Abstract Screening",
                 bg="#EAF2FB", fg=self._acc,
                 font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        steps = [
            "① Export search results from PubMed / Scopus / Web of Science as .ris, .bib, or .csv",
            "② Browse & Parse the file  →  ③ Deduplicate  →  ④ Screen abstracts with AI",
            "⑤ Review decisions, override if needed, export Included records  →  upload PDFs in Setup tab",
        ]
        for stp in steps:
            tk.Label(wf_inner, text=stp, bg="#EAF2FB", fg="#555",
                     font=("Segoe UI", 8)).pack(anchor=tk.W, padx=(12, 0))

        # ── Top section: file + criteria side by side ──────────────────────
        top_row = ttk.Frame(outer)
        top_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        top_row.columnconfigure(0, weight=2)
        top_row.columnconfigure(1, weight=3)

        # File picker card
        file_frm = ttk.LabelFrame(top_row, text="① Reference File", padding=8)
        file_frm.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        file_frm.columnconfigure(1, weight=1)

        ttk.Label(file_frm, text="File:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(file_frm, textvariable=self._ingest_file_path, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(file_frm, text="Browse…",
                   command=self._ingest_browse, style="Step.TButton").grid(row=0, column=2)
        ttk.Label(file_frm, textvariable=self._ingest_file_info,
                  foreground=self._acc, font=("Segoe UI", 8)).grid(
            row=1, column=0, columnspan=3, sticky=tk.W, pady=(4, 4))
        # Supported formats hint
        ttk.Label(file_frm,
                  text="Supported: .ris  .bib  .csv  .txt",
                  foreground="#888", font=("Segoe UI", 7, "italic")).grid(
            row=2, column=0, columnspan=3, sticky=tk.W)

        # Criteria card
        crit_frm = ttk.LabelFrame(top_row, text="Screening Criteria (for AI abstract screening)", padding=8)
        crit_frm.grid(row=0, column=1, sticky="nsew")
        crit_frm.columnconfigure(0, weight=1)
        ttk.Label(
            crit_frm,
            text="Paste your inclusion / exclusion criteria (PICO, SPIDER, or free text):",
            foreground="#555", font=("Segoe UI", 8),
        ).grid(sticky=tk.W)
        self._ingest_criteria = scrolledtext.ScrolledText(
            crit_frm, wrap=tk.WORD, height=5, font=("Segoe UI", 9))
        self._ingest_criteria.grid(sticky="ew", pady=(4, 0))
        self._ingest_criteria.insert(
            tk.END,
            "INCLUDE:\n"
            "  • Study types: RCTs, cohort studies, systematic reviews\n"
            "  • Population: [define target population]\n"
            "  • Intervention / Exposure: [define]\n"
            "  • Outcome: [define primary outcome]\n\n"
            "EXCLUDE:\n"
            "  • Editorials, letters, animal studies, conference abstracts\n"
            "  • Non-English papers, studies published before [year]"
        )

        # ── Step buttons row ───────────────────────────────────────────────
        btn_frm = tk.Frame(outer, bg=self._bg)
        btn_frm.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        # Step 1
        self._ingest_parse_btn = ttk.Button(
            btn_frm, text="② Parse File", style="Step.TButton",
            command=self._ingest_parse)
        self._ingest_parse_btn.pack(side=tk.LEFT, padx=(0, 4))
        Tooltip(self._ingest_parse_btn, "Read the reference file and extract records.")

        # Separator arrow
        tk.Label(btn_frm, text="→", bg=self._bg, fg="#AAA",
                 font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=(0, 4))

        # Step 2
        self._ingest_dedup_btn = ttk.Button(
            btn_frm, text="③ Deduplicate", style="Step.TButton",
            command=self._ingest_dedup_run, state=tk.DISABLED)
        self._ingest_dedup_btn.pack(side=tk.LEFT, padx=(0, 4))
        Tooltip(self._ingest_dedup_btn, "Remove duplicate records by DOI and fuzzy title matching.")

        # Separator arrow
        tk.Label(btn_frm, text="→", bg=self._bg, fg="#AAA",
                 font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=(0, 4))

        # Step 3
        self._ingest_screen_btn = ttk.Button(
            btn_frm, text="④ Screen Abstracts with AI", style="Accent.TButton",
            command=self._ingest_screen_start, state=tk.DISABLED)
        self._ingest_screen_btn.pack(side=tk.LEFT, padx=(0, 4))
        Tooltip(self._ingest_screen_btn,
                "Send each title + abstract to the AI for Include / Exclude / Flag decisions.\n"
                "Configure your provider in the Setup tab first.")

        self._ingest_stop_btn = ttk.Button(
            btn_frm, text="⏹ Stop", command=self._ingest_stop, style="Stop.TButton",
            state=tk.DISABLED)
        self._ingest_stop_btn.pack(side=tk.LEFT, padx=(0, 20))

        # Separator
        ttk.Separator(btn_frm, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(btn_frm, text="Export CSV",
                   command=lambda: self._ingest_export("csv")).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_frm, text="Export Excel",
                   command=lambda: self._ingest_export("xlsx")).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Button(btn_frm, text="🗑 Clear All",
                   command=self._ingest_clear).pack(side=tk.RIGHT)

        # ── Screening progress bar ─────────────────────────────────────────
        self._ingest_prog_var = tk.DoubleVar(value=0)
        self._ingest_pb = ttk.Progressbar(
            outer, variable=self._ingest_prog_var, maximum=100, mode="determinate")
        self._ingest_pb.grid(row=3, column=0, sticky="ew", pady=(0, 3))

        # ── Stats / counts row ─────────────────────────────────────────────
        stats_bar = tk.Frame(outer, bg=self._bg)
        stats_bar.grid(row=4, column=0, sticky="ew", pady=(0, 4))
        self._ingest_stats_var.set("")
        self._ingest_stats_lbl = ttk.Label(
            stats_bar, textvariable=self._ingest_stats_var,
            foreground=self._acc, font=("Segoe UI", 9, "bold"))
        self._ingest_stats_lbl.pack(side=tk.LEFT)

        # Live count chips
        chip_frm = tk.Frame(stats_bar, bg=self._bg)
        chip_frm.pack(side=tk.RIGHT)
        self._cnt_inc  = tk.StringVar(value="Include: —")
        self._cnt_exc  = tk.StringVar(value="Exclude: —")
        self._cnt_flag = tk.StringVar(value="Flag: —")
        for txt_var, fg in [(self._cnt_inc, "#27ae60"), (self._cnt_exc, "#c0392b"),
                             (self._cnt_flag, "#e67e22")]:
            tk.Label(chip_frm, textvariable=txt_var, bg=self._bg, fg=fg,
                     font=("Segoe UI", 9, "bold"), padx=10).pack(side=tk.LEFT)

        # ── Column header with record count ───────────────────────────────
        self._tree_hdr_var = tk.StringVar(value="Records (0)")
        hdr_row = ttk.Frame(outer)
        hdr_row.grid(row=5, column=0, sticky="ew")
        ttk.Label(hdr_row, textvariable=self._tree_hdr_var,
                  font=("Segoe UI", 9, "bold"), foreground="#444").pack(side=tk.LEFT)
        ttk.Label(hdr_row, text="  Double-click to view detail  ·  Right-click to override decision",
                  foreground="#888", font=("Segoe UI", 8)).pack(side=tk.LEFT)

        # ── Results treeview ───────────────────────────────────────────────
        tree_frm = ttk.Frame(outer)
        tree_frm.grid(row=6, column=0, sticky="nsew")
        tree_frm.columnconfigure(0, weight=1)
        tree_frm.rowconfigure(0, weight=1)

        cols = ("title", "year", "journal", "decision", "confidence", "rationale")
        self._ingest_tree = ttk.Treeview(
            tree_frm, columns=cols, show="headings", selectmode="browse")

        col_cfg = {
            "title":      ("Title",       300, True),
            "year":       ("Year",         50, False),
            "journal":    ("Journal",     150, True),
            "decision":   ("Decision",    105, False),
            "confidence": ("Confidence",   80, False),
            "rationale":  ("AI Rationale",300, True),
        }
        for col, (heading, width, stretch) in col_cfg.items():
            self._ingest_tree.heading(col, text=heading,
                                      command=lambda c=col: self._ingest_sort(c))
            self._ingest_tree.column(col, width=width, stretch=stretch)

        # Color tags
        self._ingest_tree.tag_configure("include", background="#C6EFCE", foreground="#1D6B2E")
        self._ingest_tree.tag_configure("exclude", background="#FFC7CE", foreground="#9B1B2A")
        self._ingest_tree.tag_configure("flag",    background="#FFEB9C", foreground="#7A5C00")
        self._ingest_tree.tag_configure("error",   background="#DDEBF7", foreground="#1F497D")
        self._ingest_tree.tag_configure("pending", background="#F5F5F5", foreground="#555")
        self._ingest_tree.tag_configure("alt",     background="#FAFAFA")

        vsb = ttk.Scrollbar(tree_frm, orient=tk.VERTICAL,   command=self._ingest_tree.yview)
        hsb = ttk.Scrollbar(tree_frm, orient=tk.HORIZONTAL, command=self._ingest_tree.xview)
        self._ingest_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._ingest_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._ingest_tree.bind("<Double-1>", self._ingest_show_detail)
        self._ingest_tree.bind("<Button-3>", self._ingest_context_menu)
        self._ingest_tree.bind("<Return>",   self._ingest_show_detail)

        # Right-click context menu
        self._ingest_ctx = tk.Menu(self.root, tearoff=0)
        self._ingest_ctx.add_command(label="✅  Override → Include",
                                     command=lambda: self._ingest_override(DECISION_INCLUDE))
        self._ingest_ctx.add_command(label="❌  Override → Exclude",
                                     command=lambda: self._ingest_override(DECISION_EXCLUDE))
        self._ingest_ctx.add_command(label="⚑  Override → Flag for Review",
                                     command=lambda: self._ingest_override(DECISION_FLAG))
        self._ingest_ctx.add_separator()
        self._ingest_ctx.add_command(label="📋  View Detail",
                                     command=self._ingest_show_detail)

        # Sort state
        self._ingest_sort_col = None
        self._ingest_sort_rev = False

        # Bottom tip
        ttk.Label(
            outer,
            text="💡 Tip: After screening, export the 'Include' list, locate matching PDFs, then run full-text screening in the Setup tab.",
            foreground="#888", font=("Segoe UI", 8), wraplength=1000,
        ).grid(row=7, column=0, sticky=tk.W, pady=(4, 0))

    # ── Ingestion helpers ────────────────────────────────────────────────────

    def _ingest_browse(self):
        path = filedialog.askopenfilename(
            title="Select Reference File",
            filetypes=[
                ("Reference files", "*.ris *.bib *.csv *.txt"),
                ("RIS", "*.ris"), ("BibTeX", "*.bib"),
                ("CSV", "*.csv"), ("All files", "*.*"),
            ]
        )
        if path:
            self._ingest_file_path.set(path)
            size_kb = Path(path).stat().st_size // 1024
            self._ingest_file_info.set(
                f"{Path(path).name}  ·  {size_kb:,} KB  ·  "
                f"{Path(path).suffix.upper().lstrip('.')} format — click ② Parse File"
            )
            self._ingest_parse_btn.config(state=tk.NORMAL)

    def _ingest_parse(self):
        path = self._ingest_file_path.get()
        if not path:
            messagebox.showwarning("No File", "Browse to a .ris, .bib, or .csv file first.")
            return
        try:
            self._ingest_parse_btn.config(state=tk.DISABLED)
            self._set_status("Parsing reference file…", "PROC.TLabel")
            self.root.update_idletasks()
            records = parse_references(path)
            self._ingest_records = records
            self._ingest_dedup   = list(records)
            self._ingest_results = []
            self._ingest_tree.delete(*self._ingest_tree.get_children())
            for i, r in enumerate(records):
                self._ingest_tree.insert("", tk.END, iid=r["record_id"], values=(
                    r.get("title", "")[:120],
                    r.get("year", ""),
                    r.get("journal", "")[:60],
                    "Pending", "", "",
                ), tags=("pending",))
            n = len(records)
            self._ingest_stats_var.set(
                f"✔ Parsed {n:,} records from {Path(path).name}  —  click ③ Deduplicate next."
            )
            self._tree_hdr_var.set(f"Records ({n:,})")
            self._ingest_parse_btn.config(state=tk.NORMAL)
            self._ingest_dedup_btn.config(state=tk.NORMAL)
            self._ingest_screen_btn.config(state=tk.DISABLED)
            self._ingest_prog_var.set(0)
            self._reset_count_chips()
            self._set_status(f"Parsed {n:,} records — ready to deduplicate.")
        except Exception as exc:
            self._ingest_parse_btn.config(state=tk.NORMAL)
            messagebox.showerror("Parse Error", str(exc))

    def _ingest_dedup_run(self):
        if not self._ingest_records:
            messagebox.showwarning("No Records", "Parse a file first.")
            return
        self._ingest_dedup_btn.config(state=tk.DISABLED)
        self._set_status("Deduplicating…", "PROC.TLabel")
        self.root.update_idletasks()
        deduped, stats = deduplicate(self._ingest_records)
        self._ingest_dedup        = deduped
        self._ingest_dedup_stats  = stats
        self._ingest_results      = []

        # Refresh tree
        self._ingest_tree.delete(*self._ingest_tree.get_children())
        for i, r in enumerate(deduped):
            self._ingest_tree.insert("", tk.END, iid=r["record_id"], values=(
                r.get("title", "")[:120],
                r.get("year", ""),
                r.get("journal", "")[:60],
                "Pending", "", "",
            ), tags=("pending",))

        removed = stats.removed_doi + stats.removed_fuzzy
        self._ingest_stats_var.set(
            f"✔ Deduplicated — Before: {stats.total_before:,}  ·  "
            f"Removed: {removed} ({stats.removed_doi} by DOI, {stats.removed_fuzzy} fuzzy)  ·  "
            f"Remaining: {stats.total_after:,}  —  click ④ Screen Abstracts to continue."
        )
        self._tree_hdr_var.set(f"Records ({stats.total_after:,})")
        self._ingest_dedup_btn.config(state=tk.NORMAL)
        self._ingest_screen_btn.config(state=tk.NORMAL)
        self._ingest_prog_var.set(0)
        self._reset_count_chips()
        self._set_status(
            f"Deduplication complete — {stats.total_after:,} unique records ready."
        )

    def _ingest_screen_start(self):
        if not self._ingest_dedup:
            messagebox.showwarning("No Records", "Parse and deduplicate first.")
            return
        provider = self.llm_provider.get()
        api_key  = self.api_key.get().strip()
        if not api_key and provider != "Ollama (Local)":
            messagebox.showwarning("API Key",
                                   "Enter your API key in the Setup tab before screening.")
            return

        criteria = self._ingest_criteria.get(1.0, tk.END).strip()
        total    = len(self._ingest_dedup)

        if not messagebox.askyesno(
            "Confirm",
            f"Screen {total} records with {provider}?\n"
            "This will make API calls and may incur costs."
        ):
            return

        # Build LLM manager
        try:
            from llm_interface import LLMManager
            kwargs = {}
            if self.llm_base_url.get():
                kwargs["base_url"] = self.llm_base_url.get()
            mgr = LLMManager(
                provider_name=provider,
                api_key=api_key,
                model=self.llm_model.get(),
                **kwargs,
            )
        except Exception as exc:
            messagebox.showerror("LLM Error", str(exc))
            return

        self._ingest_running = True
        self._ingest_results = []
        self._ingest_screen_btn.config(state=tk.DISABLED)
        self._ingest_dedup_btn.config(state=tk.DISABLED)
        self._ingest_parse_btn.config(state=tk.DISABLED)
        self._ingest_stop_btn.config(state=tk.NORMAL)
        self._ingest_prog_var.set(0)
        self._reset_count_chips()
        self._ingest_stats_var.set(f"Screening 0 / {total:,} …")

        screener = AbstractScreener(
            llm_manager=mgr,
            max_retries=self.advanced_config.get("max_retries", 3),
            retry_delay=self.advanced_config.get("retry_delay", 1.0),
        )
        self._screener = screener

        records_snapshot = list(self._ingest_dedup)

        def _run():
            results = screener.screen_all(
                records_snapshot, criteria,
                callback=lambda res, cur, tot: self.message_queue.put(
                    ("ingest_progress", res, cur, tot)
                )
            )
            self.message_queue.put(("ingest_done", results))

        threading.Thread(target=_run, daemon=True).start()

    def _ingest_stop(self):
        if self._screener:
            self._screener.stop()
        self._ingest_stop_btn.config(state=tk.DISABLED)
        self._ingest_stats_var.set("Stopping after current record…")

    def _reset_count_chips(self):
        self._cnt_inc.set("Include: —")
        self._cnt_exc.set("Exclude: —")
        self._cnt_flag.set("Flag: —")

    def _update_count_chips(self):
        from collections import Counter
        counts = Counter(r.decision for r in self._ingest_results)
        self._cnt_inc .set(f"Include: {counts.get('Include', 0):,}")
        self._cnt_exc .set(f"Exclude: {counts.get('Exclude', 0):,}")
        self._cnt_flag.set(f"Flag: {counts.get('Flag for Human Review', 0):,}")

    def _ingest_sort(self, col: str):
        """Sort ingest treeview by column; toggle direction on repeated click."""
        if self._ingest_sort_col == col:
            self._ingest_sort_rev = not self._ingest_sort_rev
        else:
            self._ingest_sort_col = col
            self._ingest_sort_rev = False

        col_idx = ("title", "year", "journal", "decision", "confidence", "rationale").index(col)
        items = [(self._ingest_tree.set(k, col), k)
                 for k in self._ingest_tree.get_children("")]
        items.sort(reverse=self._ingest_sort_rev,
                   key=lambda t: t[0].lower() if t[0] else "")
        for idx, (_, k) in enumerate(items):
            self._ingest_tree.move(k, "", idx)

    def _ingest_override(self, new_decision: str):
        sel = self._ingest_tree.selection()
        if not sel:
            return
        iid = sel[0]
        vals = list(self._ingest_tree.item(iid, "values"))
        vals[3] = new_decision
        tag = {DECISION_INCLUDE: "include", DECISION_EXCLUDE: "exclude",
               DECISION_FLAG: "flag"}.get(new_decision, "")
        self._ingest_tree.item(iid, values=vals, tags=(tag,))
        # Update result list
        for r in self._ingest_results:
            if r.record_id == iid:
                r.decision = new_decision
                r.rationale = f"[Human override] {r.rationale}"
                break

    def _ingest_context_menu(self, event):
        row = self._ingest_tree.identify_row(event.y)
        if row:
            self._ingest_tree.selection_set(row)
            self._ingest_ctx.tk_popup(event.x_root, event.y_root)

    def _ingest_show_detail(self, event=None):
        sel = self._ingest_tree.selection()
        if not sel:
            return
        iid = sel[0]
        vals = self._ingest_tree.item(iid, "values")
        rec  = next((r for r in self._ingest_dedup if r["record_id"] == iid), None)
        res  = next((r for r in self._ingest_results if r.record_id == iid), None)

        win = tk.Toplevel(self.root)
        win.title(vals[0][:80] if vals else "Detail")
        win.geometry("700x500")
        win.transient(self.root)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(3, weight=1)

        if res:
            dec_color = {DECISION_INCLUDE: "#27ae60", DECISION_EXCLUDE: "#c0392b",
                         DECISION_FLAG: "#e67e22"}.get(res.decision, "#555")
            ttk.Label(frm, text=res.decision, foreground=dec_color,
                      font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky=tk.W)
            ttk.Label(frm, text=f"Confidence: {res.confidence}  |  Rationale: {res.rationale}",
                      wraplength=670, foreground="#555"
                      ).grid(row=1, column=0, sticky=tk.W, pady=(2, 10))
        if rec:
            for r_idx, (lbl, key) in enumerate(
                [("Title", "title"), ("Authors", "authors"), ("Year / Journal", "year"),
                 ("DOI", "doi"), ("Keywords", "keywords")], start=2
            ):
                val = rec.get(key, "")
                if key == "year":
                    val = f"{rec.get('year','')}  |  {rec.get('journal','')}"
                ttk.Label(frm, text=f"{lbl}: ", font=("Segoe UI", 9, "bold")).grid(
                    row=r_idx, column=0, sticky=tk.W)
                ttk.Label(frm, text=val, wraplength=670, foreground="#333"
                          ).grid(row=r_idx, column=0, sticky=tk.W, padx=(80, 0))
            # Abstract
            ttk.Label(frm, text="Abstract:",
                      font=("Segoe UI", 9, "bold")).grid(row=8, column=0, sticky=tk.W)
            ab_st = scrolledtext.ScrolledText(frm, wrap=tk.WORD, font=("Segoe UI", 9),
                                              height=10)
            ab_st.grid(row=9, column=0, sticky="nsew", pady=(2, 0))
            ab_st.insert(tk.END, rec.get("abstract", "Not available"))
            ab_st.config(state=tk.DISABLED)

    def _ingest_export(self, fmt: str):
        if not self._ingest_dedup:
            messagebox.showwarning("Nothing to export", "No records loaded.")
            return
        ext = "csv" if fmt == "csv" else "xlsx"
        path = filedialog.asksaveasfilename(
            defaultextension=f".{ext}",
            filetypes=[(ext.upper(), f"*.{ext}"), ("All", "*.*")],
            title="Export Screening Results"
        )
        if not path:
            return
        try:
            if fmt == "csv":
                export_records_to_csv(self._ingest_dedup, self._ingest_results, path)
            else:
                export_records_to_excel(
                    self._ingest_dedup, self._ingest_results, path,
                    stats=self._ingest_dedup_stats
                )
            messagebox.showinfo("Exported",
                                f"Saved {len(self._ingest_dedup)} records to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _ingest_clear(self):
        if messagebox.askyesno("Clear", "Clear all ingested records and screening results?"):
            self._ingest_records  = []
            self._ingest_dedup    = []
            self._ingest_results  = []
            self._ingest_dedup_stats = None
            self._ingest_tree.delete(*self._ingest_tree.get_children())
            self._ingest_file_path.set("")
            self._ingest_file_info.set("No file loaded")
            self._ingest_stats_var.set("")
            self._ingest_prog_var.set(0)
            self._tree_hdr_var.set("Records (0)")
            self._reset_count_chips()
            self._ingest_dedup_btn.config(state=tk.DISABLED)
            self._ingest_screen_btn.config(state=tk.DISABLED)
            self._set_status("Ready")

    # ── SETUP TAB ────────────────────────────────────────────────────────────

    def _build_setup_tab(self):
        outer = ttk.Frame(self.tab_setup, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)

        # ─ Column 1 ──────────────────────────────────────────────────────
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(0, weight=1)

        # Provider card
        pf = ttk.LabelFrame(left, text="AI Provider", padding=10)
        pf.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        pf.columnconfigure(1, weight=1)

        ttk.Label(pf, text="Provider:", style="H.TLabel").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        from llm_interface import LLMManager
        self.provider_cb = ttk.Combobox(pf, textvariable=self.llm_provider,
                                         values=LLMManager.get_supported_providers(),
                                         state="readonly", width=26)
        self.provider_cb.grid(row=0, column=1, columnspan=2, sticky="ew")
        self.provider_cb.bind("<<ComboboxSelected>>", self._on_provider_changed)
        Tooltip(self.provider_cb, "Choose your AI provider. Ollama runs locally for free.")

        ttk.Label(pf, text="Model:", style="H.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        model_frame = ttk.Frame(pf)
        model_frame.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        model_frame.columnconfigure(0, weight=1)
        self.model_cb = ttk.Combobox(model_frame, textvariable=self.llm_model, width=22)
        self.model_cb.grid(row=0, column=0, sticky="ew")
        Tooltip(self.model_cb, "Select a model or type any model name manually.")
        ttk.Button(model_frame, text="+", width=3,
                   command=self._manage_custom_models).grid(row=0, column=1, padx=(4, 0))

        ttk.Label(pf, text="API Key:", style="H.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
        key_frame = ttk.Frame(pf)
        key_frame.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        key_frame.columnconfigure(0, weight=1)
        self.key_entry = ttk.Entry(key_frame, textvariable=self.api_key, show="*")
        self.key_entry.grid(row=0, column=0, sticky="ew")
        ttk.Checkbutton(key_frame, text="Show", variable=self.show_key,
                        command=self._toggle_key).grid(row=0, column=1, padx=(4, 0))
        Tooltip(self.key_entry, "Your API key. Not needed for Ollama.")

        ttk.Label(pf, text="Base URL:", style="H.TLabel").grid(row=3, column=0, sticky=tk.W, pady=(6, 0))
        self.url_entry = ttk.Entry(pf, textvariable=self.llm_base_url)
        self.url_entry.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        Tooltip(self.url_entry, "Required for Ollama (http://localhost:11434) and custom endpoints.")

        self.test_btn = ttk.Button(pf, text="Test Connection", command=self._test_connection)
        self.test_btn.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))

        # Paths card
        pth = ttk.LabelFrame(left, text="File Paths", padding=10)
        pth.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        pth.columnconfigure(1, weight=1)

        ttk.Label(pth, text="PDF Folder:", style="H.TLabel").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        ttk.Entry(pth, textvariable=self.pdf_folder).grid(row=0, column=1, sticky="ew")
        ttk.Button(pth, text="Browse", command=self._browse_pdf).grid(row=0, column=2, padx=(4, 0))
        self.pdf_count_lbl = ttk.Label(pth, text="", style="Sub.TLabel")
        self.pdf_count_lbl.grid(row=1, column=1, sticky=tk.W, pady=(2, 0))
        self.pdf_folder.trace_add("write", self._on_pdf_folder_changed)

        ttk.Label(pth, text="Output Folder:", style="H.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(pth, textvariable=self.output_folder).grid(row=2, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(pth, text="Browse", command=self._browse_output).grid(row=2, column=2, padx=(4, 0), pady=(8, 0))

        # ─ Column 2 ──────────────────────────────────────────────────────
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.columnconfigure(0, weight=1)

        # Processing settings
        proc = ttk.LabelFrame(right, text="Processing Settings", padding=10)
        proc.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        proc.columnconfigure(1, weight=1)

        ttk.Checkbutton(proc, text="Parallel processing (faster, uses more API quota)",
                        variable=self.parallel_proc).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        Tooltip(proc.winfo_children()[-1], "Process multiple PDFs simultaneously.")

        ttk.Checkbutton(proc, text="Enable result caching (skip already-processed files)",
                        variable=self.cache_enabled).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        ttk.Checkbutton(proc, text="Two-stage screening  (title/abstract → full-text — saves tokens)",
                        variable=self.two_stage).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(4, 8))
        Tooltip(proc.winfo_children()[-1],
                "Stage 1 reads only the title/abstract (first 3,000 chars) and skips clearly\n"
                "irrelevant papers before doing a full read. Recommended for large corpora.")

        ttk.Label(proc, text="Max Workers:", style="H.TLabel").grid(row=3, column=0, sticky=tk.W)
        wf = ttk.Frame(proc)
        wf.grid(row=3, column=1, sticky="ew")
        wf.columnconfigure(0, weight=1)
        ttk.Scale(wf, from_=1, to=10, variable=self.max_workers, orient=tk.HORIZONTAL).grid(row=0, column=0, sticky="ew")
        ttk.Label(wf, textvariable=self.max_workers, width=3).grid(row=0, column=1)

        ttk.Label(proc, text="Rate Delay (s):", style="H.TLabel").grid(row=4, column=0, sticky=tk.W, pady=(6, 0))
        df = ttk.Frame(proc)
        df.grid(row=4, column=1, sticky="ew", pady=(6, 0))
        df.columnconfigure(0, weight=1)
        ttk.Scale(df, from_=0.0, to=5.0, variable=self.rate_limit_delay, orient=tk.HORIZONTAL).grid(row=0, column=0, sticky="ew")
        self.delay_lbl = ttk.Label(df, text="1.0s", width=5)
        self.delay_lbl.grid(row=0, column=1)
        self.rate_limit_delay.trace_add("write", lambda *_: self.delay_lbl.config(
            text=f"{self.rate_limit_delay.get():.1f}s"))
        Tooltip(df, "Delay between API calls. Increase if you hit rate-limit errors.")

        # Research Criteria
        crit = ttk.LabelFrame(right, text="Research Criteria & Extraction Fields", padding=10)
        crit.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        crit.columnconfigure(0, weight=1)

        self.criteria_status = tk.StringVar(value="Using default generic criteria")
        ttk.Label(crit, textvariable=self.criteria_status, style="Sub.TLabel").grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 6))

        btn_row = ttk.Frame(crit)
        btn_row.grid(row=1, column=0, sticky=tk.W)
        ttk.Button(btn_row, text="Customize Criteria & Fields",
                   command=self._customize_prompts).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Reset to Default",
                   command=self._reset_prompts).pack(side=tk.LEFT)

        # Actions
        act = ttk.LabelFrame(right, text="Actions", padding=10)
        act.grid(row=2, column=0, sticky="ew")
        act.columnconfigure(0, weight=1)
        act.columnconfigure(1, weight=1)

        self.start_btn = ttk.Button(act, text="▶  Start Processing  (F5)",
                                    command=self._start, style="Big.TButton")
        self.start_btn.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self.stop_btn = ttk.Button(act, text="⏹  Stop  (F6)",
                                   command=self._stop, state=tk.DISABLED,
                                   style="BigStop.TButton")
        self.stop_btn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Separator(act, orient=tk.HORIZONTAL).grid(row=2, column=0, columnspan=2,
                                                       sticky="ew", pady=(0, 8))

        ttk.Button(act, text="Advanced Config", command=self._show_adv).grid(
            row=3, column=0, sticky="ew")
        ttk.Button(act, text="Open Output Folder", command=self._open_output).grid(
            row=3, column=1, sticky="ew", padx=(8, 0))
        ttk.Button(act, text="Save Settings  (Ctrl+S)",
                   command=self._save_settings).grid(
            row=4, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(act, text="Load Settings", command=self._load_settings_dialog).grid(
            row=4, column=1, sticky="ew", padx=(8, 0), pady=(4, 0))

        # Init provider UI
        self._on_provider_changed()

    # ── MONITOR TAB ──────────────────────────────────────────────────────────

    def _build_monitor_tab(self):
        f = ttk.Frame(self.tab_monitor, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(2, weight=1)

        # Progress bar + stat chips ------------------------------------------
        pb_frame = ttk.LabelFrame(f, text="Progress", padding=10)
        pb_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        pb_frame.columnconfigure(0, weight=1)

        # Progress bar + percentage label
        pb_top = ttk.Frame(pb_frame)
        pb_top.grid(row=0, column=0, sticky="ew")
        pb_top.columnconfigure(0, weight=1)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(pb_top, variable=self.progress_var,
                                             maximum=100, mode="determinate")
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        self._pct_lbl = ttk.Label(pb_top, text="0%", width=5, anchor=tk.E,
                                   font=("Segoe UI", 9, "bold"))
        self._pct_lbl.grid(row=0, column=1, padx=(6, 0))
        self.progress_var.trace_add("write",
            lambda *_: self._pct_lbl.config(text=f"{self.progress_var.get():.0f}%"))

        # KPI chip row (5 boxes)
        chip_f = tk.Frame(pb_frame, bg=self._bg)
        chip_f.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for i in range(5):
            chip_f.columnconfigure(i, weight=1)

        def _kpi(parent, col, title, varname, fg, bg_chip):
            box = tk.Frame(parent, bg=bg_chip, padx=10, pady=6, bd=1, relief=tk.SOLID)
            box.grid(row=0, column=col, sticky="ew", padx=4)
            var = tk.StringVar(value="0")
            setattr(self, varname, var)
            tk.Label(box, text=title, bg=bg_chip, fg="#555",
                     font=("Segoe UI", 7, "bold")).pack()
            tk.Label(box, textvariable=var, bg=bg_chip, fg=fg,
                     font=("Segoe UI", 14, "bold")).pack()

        _kpi(chip_f, 0, "FILES",   "lbl_files_var",   "#2D6A9F", "#EAF2FB")
        _kpi(chip_f, 1, "INCLUDE", "lbl_include_var",  "#1D6B2E", "#C6EFCE")
        _kpi(chip_f, 2, "EXCLUDE", "lbl_exclude_var",  "#9B1B2A", "#FFC7CE")
        _kpi(chip_f, 3, "FLAGGED", "lbl_flag_var",     "#7A5C00", "#FFEB9C")
        _kpi(chip_f, 4, "TOKENS",  "lbl_tokens_var",   "#444",    "#F5F5F5")

        # Time / ETA / Current row
        time_row = ttk.Frame(pb_frame)
        time_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.lbl_time    = ttk.Label(time_row, text="Elapsed: --:--:--",
                                     font=("Segoe UI", 9))
        self.lbl_eta     = ttk.Label(time_row, text="ETA: --",
                                     font=("Segoe UI", 9))
        self.lbl_current = ttk.Label(time_row, text="Current: —",
                                     style="Sub.TLabel")
        self.lbl_time   .pack(side=tk.LEFT, padx=(0, 20))
        self.lbl_eta    .pack(side=tk.LEFT, padx=(0, 20))
        self.lbl_current.pack(side=tk.LEFT)

        # Placeholder labels kept for compatibility with _update_stats
        self.lbl_files   = ttk.Label(f)
        self.lbl_include = ttk.Label(f)
        self.lbl_exclude = ttk.Label(f)
        self.lbl_flag    = ttk.Label(f)
        self.lbl_tokens  = ttk.Label(f)

        # Log ---------------------------------------------------------------
        log_frame = ttk.LabelFrame(f, text="Processing Log", padding=8)
        log_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=18, wrap=tk.WORD,
                                                   font=("Consolas", 9),
                                                   bg="#1E1E1E", fg="#D4D4D4",
                                                   insertbackground="white")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        # Tag colours for log
        self.log_text.tag_config("INFO",    foreground="#9CDCFE")
        self.log_text.tag_config("OK",      foreground="#4EC9B0")
        self.log_text.tag_config("WARN",    foreground="#CE9178")
        self.log_text.tag_config("ERROR",   foreground="#F44747")
        self.log_text.tag_config("INCLUDE", foreground="#4EC9B0", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("EXCLUDE", foreground="#F44747")
        self.log_text.tag_config("FLAG",    foreground="#DCDCAA")

        log_ctrl = ttk.Frame(log_frame)
        log_ctrl.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(log_ctrl, text="Clear Log", command=self._clear_log).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(log_ctrl, text="Save Log",  command=self._save_log).pack(side=tk.LEFT)
        ttk.Button(log_ctrl, text="Help / Manual  (F1)",
                   command=lambda: self.nb.select(self.tab_help)).pack(side=tk.RIGHT)

    # ── RESULTS TAB ─────────────────────────────────────────────────────────

    def _build_results_tab(self):
        f = ttk.Frame(self.tab_results, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        f.rowconfigure(2, weight=1)
        f.columnconfigure(0, weight=1)

        # ── Filter + search bar ───────────────────────────────────────────
        filt = tk.Frame(f, bg=self._bg)
        filt.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(filt, text="Filter:", style="H.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        self._filter_var = tk.StringVar(value="All")

        # Styled segmented-control buttons
        FILTER_OPTS = [
            ("All",                  "#2D6A9F", "#EAF2FB"),
            ("Likely Include",       "#1D6B2E", "#C6EFCE"),
            ("Likely Exclude",       "#9B1B2A", "#FFC7CE"),
            ("Flag for Review",      "#7A5C00", "#FFEB9C"),
            ("Flag for Human Review","#1F497D", "#DDEBF7"),
            ("Error",                "#555",    "#F5F5F5"),
        ]
        self._filter_btns: dict = {}
        btn_bar = tk.Frame(filt, bg=self._bg)
        btn_bar.pack(side=tk.LEFT)
        for label, fg, bg_chip in FILTER_OPTS:
            def _make_cmd(lbl=label):
                return lambda: self._set_filter(lbl)
            b = tk.Button(btn_bar, text=label, command=_make_cmd(),
                          font=("Segoe UI", 8, "bold"),
                          fg=fg, bg=bg_chip, activebackground=bg_chip,
                          relief=tk.FLAT, bd=1, padx=8, pady=3,
                          cursor="hand2")
            b.pack(side=tk.LEFT, padx=2)
            self._filter_btns[label] = b

        # Search box (right side)
        search_frm = tk.Frame(filt, bg=self._bg)
        search_frm.pack(side=tk.RIGHT)
        ttk.Label(search_frm, text="Search:").pack(side=tk.LEFT, padx=(0, 4))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(search_frm, textvariable=self._search_var, width=20).pack(side=tk.LEFT)
        ttk.Button(search_frm, text="✕",
                   command=lambda: self._search_var.set("")).pack(side=tk.LEFT, padx=(2, 0))

        # Export button (below filter bar)
        export_frm = tk.Frame(f, bg=self._bg)
        export_frm.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(export_frm, text="Export Visible Rows to CSV…",
                   command=self._export_visible).pack(side=tk.RIGHT)
        self.prisma_lbl = ttk.Label(export_frm, text="", style="Sub.TLabel")
        self.prisma_lbl.pack(side=tk.LEFT)

        # Treeview
        tree_frame = ttk.Frame(f)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("filename", "decision", "stage", "reasoning", "tokens", "time")
        self.result_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=18)
        self.result_tree.heading("filename",  text="File",      anchor=tk.W)
        self.result_tree.heading("decision",  text="Decision",  anchor=tk.W)
        self.result_tree.heading("stage",     text="Stage",     anchor=tk.W)
        self.result_tree.heading("reasoning", text="Reasoning (excerpt)", anchor=tk.W)
        self.result_tree.heading("tokens",    text="Tokens",    anchor=tk.CENTER)
        self.result_tree.heading("time",      text="Time (s)",  anchor=tk.CENTER)
        self.result_tree.column("filename",  width=200, minwidth=120)
        self.result_tree.column("decision",  width=160, minwidth=120)
        self.result_tree.column("stage",     width=110, minwidth=80)
        self.result_tree.column("reasoning", width=380, minwidth=200)
        self.result_tree.column("tokens",    width=70,  minwidth=60)
        self.result_tree.column("time",      width=70,  minwidth=60)

        # Row tag colours
        self.result_tree.tag_configure("include", background="#EBF9EE")
        self.result_tree.tag_configure("exclude",  background="#FDECEA")
        self.result_tree.tag_configure("flag",     background="#FEF9E7")
        self.result_tree.tag_configure("human",    background="#EAF2FB")
        self.result_tree.tag_configure("error",    background="#F2F2F2")
        self.result_tree.tag_configure("alt",      background="#FAFAFA")

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,   command=self.result_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.result_tree.xview)
        self.result_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.result_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.result_tree.bind("<Double-1>", self._show_detail)
        self.result_tree.bind("<Return>",   self._show_detail)

        self._all_results = []   # [(filename, decision, stage, reasoning, tokens, time_s)]
        self._set_filter("All")   # highlight initial active filter button

    # ── Setup tab helpers ────────────────────────────────────────────────────

    def _on_provider_changed(self, event=None):
        from llm_interface import LLMManager
        p = self.llm_provider.get()
        info = LLMManager.get_provider_info().get(p, {})
        models = LLMManager.get_models_for_provider(p)

        self.model_cb['values'] = models
        default = LLMManager.get_default_models().get(p, models[0] if models else "")
        self.llm_model.set(default)

        # Key/URL field states
        if p == "Ollama (Local)":
            self.key_entry.config(state="disabled")
            self.api_key.set("")
            self.url_entry.config(state="normal")
            if not self.llm_base_url.get():
                self.llm_base_url.set("http://localhost:11434")
        elif LLMManager.needs_base_url(p):
            self.key_entry.config(state="normal")
            self.url_entry.config(state="normal")
        else:
            self.key_entry.config(state="normal")
            self.url_entry.config(state="disabled")
            self.llm_base_url.set("")

        self._conn_status = "unchecked"
        self._update_conn_dot()

    def _on_pdf_folder_changed(self, *_):
        folder = self.pdf_folder.get()
        try:
            pdfs = list(Path(folder).glob("*.pdf")) if folder and Path(folder).is_dir() else []
            n = len(pdfs)
            self._pdf_count_total = n
            if n:
                self.pdf_count_lbl.config(text=f"📄  {n} PDF{'s' if n!=1 else ''} found", foreground="#27ae60")
            else:
                self.pdf_count_lbl.config(text="No PDFs found in this folder", foreground="#c0392b")
        except Exception:
            self.pdf_count_lbl.config(text="")

    def _browse_pdf(self):
        d = filedialog.askdirectory(title="Select PDF Folder")
        if d:
            self.pdf_folder.set(d)

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self.output_folder.set(d)

    def _toggle_key(self):
        self.key_entry.config(show="" if self.show_key.get() else "*")

    def _update_conn_dot(self):
        colour = {"ok": "#2ecc71", "fail": "#e74c3c", "unchecked": "#95a5a6"}[self._conn_status]
        txt    = {"ok": "⬤ Connected", "fail": "⬤ Failed", "unchecked": "⬤ Not tested"}[self._conn_status]
        self._conn_dot.config(text=txt, fg=colour)

    def _test_connection(self):
        from llm_interface import test_provider_connection
        p     = self.llm_provider.get()
        key   = self.api_key.get().strip()
        model = self.llm_model.get()
        kwargs = {}
        if self.llm_base_url.get():
            kwargs['base_url'] = self.llm_base_url.get()

        self._conn_dot.config(text="⬤ Testing…", fg="#f39c12")
        self.test_btn.config(state=tk.DISABLED)
        self.root.update()

        def run():
            ok, msg = test_provider_connection(p, key, model, **kwargs)
            self._conn_status = "ok" if ok else "fail"
            self.message_queue.put(("conn_test", ok, msg))

        threading.Thread(target=run, daemon=True).start()

    def _manage_custom_models(self):
        """Open a dialog to add/remove custom model names for the current provider."""
        from llm_interface import LLMManager, load_custom_models, save_custom_models

        provider = self.llm_provider.get()

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Manage Models — {provider}")
        dlg.geometry("520x480")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(True, True)
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"520x480+{(sw-520)//2}+{(sh-480)//2}")

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        ttk.Label(main, text=f"Models for {provider}",
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky=tk.W, pady=(0, 4))
        ttk.Label(main, text="Built-in models are shown in the list below.\n"
                  "Add your own model IDs (e.g. fine-tunes or newly released models).",
                  foreground="#666", font=("Segoe UI", 8), wraplength=480).grid(
                      row=1, column=0, sticky=tk.W, pady=(0, 8))

        # Model list
        list_frame = ttk.Frame(main)
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        listbox = tk.Listbox(list_frame, selectmode=tk.SINGLE, font=("Consolas", 10))
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.config(yscrollcommand=sb.set)
        listbox.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        # Populate: built-in models (non-removable) + custom models (removable)
        builtin_models = []
        if provider in LLMManager.PROVIDERS:
            try:
                default_model = LLMManager.get_default_models().get(provider, "")
                builtin_models = LLMManager.PROVIDERS[provider](
                    "", default_model
                ).get_available_models()
            except Exception:
                builtin_models = []
        custom = load_custom_models().get(provider, [])

        all_models_data = []  # list of (name, is_custom)
        for m in builtin_models:
            all_models_data.append((m, False))
        for m in custom:
            if m not in builtin_models:
                all_models_data.append((m, True))

        def refresh_list():
            listbox.delete(0, tk.END)
            for name, is_custom in all_models_data:
                label = f"  {name}  [custom]" if is_custom else f"  {name}"
                listbox.insert(tk.END, label)

        refresh_list()

        # Add model row
        add_frame = ttk.Frame(main)
        add_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        add_frame.columnconfigure(0, weight=1)

        new_model_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=new_model_var, font=("Consolas", 10)).grid(
            row=0, column=0, sticky="ew")

        def add_model():
            name = new_model_var.get().strip()
            if not name:
                return
            # Check for duplicates
            existing = [m for m, _ in all_models_data]
            if name in existing:
                messagebox.showwarning("Duplicate", f"'{name}' already exists.", parent=dlg)
                return
            all_models_data.append((name, True))
            refresh_list()
            new_model_var.set("")

        ttk.Button(add_frame, text="Add Model", command=add_model).grid(
            row=0, column=1, padx=(6, 0))

        def remove_selected():
            sel = listbox.curselection()
            if not sel:
                messagebox.showinfo("Select", "Select a custom model to remove.", parent=dlg)
                return
            idx = sel[0]
            name, is_custom = all_models_data[idx]
            if not is_custom:
                messagebox.showinfo("Built-in",
                    f"'{name}' is a built-in model and cannot be removed.\n"
                    "You can add any model name — just type it in the Model dropdown directly.",
                    parent=dlg)
                return
            all_models_data.pop(idx)
            refresh_list()

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(btn_frame, text="Remove Selected", command=remove_selected).pack(side=tk.LEFT)

        ttk.Label(btn_frame, text="Tip: You can also type any model name\n"
                  "directly in the Model dropdown.",
                  foreground="#888", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(12, 0))

        def save_and_close():
            # Save custom models
            custom_data = load_custom_models()
            custom_data[provider] = [m for m, is_c in all_models_data if is_c]
            if not custom_data[provider]:
                custom_data.pop(provider, None)
            save_custom_models(custom_data)
            # Refresh model dropdown
            models = LLMManager.get_models_for_provider(provider)
            self.model_cb['values'] = models
            dlg.destroy()

        def cancel():
            dlg.destroy()

        close_frame = ttk.Frame(main)
        close_frame.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(close_frame, text="Save & Close", command=save_and_close).pack(side=tk.LEFT)
        ttk.Button(close_frame, text="Cancel", command=cancel).pack(side=tk.RIGHT)

        dlg.protocol("WM_DELETE_WINDOW", cancel)

    def _customize_prompts(self):
        try:
            result = show_prompt_editor(self.root, self.screening_prompt,
                                        self.extraction_prompt, self.extraction_fields)
            if result:
                self.screening_prompt  = result.get('screening_prompt')
                self.extraction_prompt = result.get('extraction_prompt')
                self.extraction_fields = result.get('extraction_fields')
                n = len(self.extraction_fields) if self.extraction_fields else 0
                self.criteria_status.set(f"Custom criteria · {n} extraction field(s) defined")
                self._log("Custom research criteria applied", "OK")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open criteria editor:\n{e}")

    def _reset_prompts(self):
        if messagebox.askyesno("Reset", "Reset to default generic criteria?"):
            self.screening_prompt  = None
            self.extraction_prompt = None
            self.extraction_fields = None
            self.criteria_status.set("Using default generic criteria")
            self._log("Criteria reset to default", "INFO")

    def _show_adv(self):
        try:
            result = show_advanced_config(self.root, self.advanced_config)
            if result:
                self.advanced_config.update(result)
                self._log("Advanced configuration updated", "OK")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _open_output(self):
        p = self.output_folder.get()
        if p and Path(p).exists():
            if sys.platform == 'win32':
                os.startfile(p)
            elif sys.platform == 'darwin':
                os.system(f'open "{p}"')
            else:
                os.system(f'xdg-open "{p}"')
        else:
            messagebox.showwarning("Warning", "Output folder does not exist yet.")

    # ── Processing ───────────────────────────────────────────────────────────

    def _validate(self) -> bool:
        if not self.api_key.get().strip() and self.llm_provider.get() != "Ollama (Local)":
            messagebox.showerror("Missing API Key", "Please enter your API key.")
            return False
        if not self.pdf_folder.get().strip():
            messagebox.showerror("Missing Folder", "Please select a PDF folder.")
            return False
        if not Path(self.pdf_folder.get()).is_dir():
            messagebox.showerror("Invalid Folder", "PDF folder does not exist.")
            return False
        pdfs = list(Path(self.pdf_folder.get()).glob("*.pdf"))
        if not pdfs:
            messagebox.showwarning("No PDFs", f"No PDF files found in:\n{self.pdf_folder.get()}")
            return False
        return True

    def _start(self):
        if not self._validate():
            return
        if self.is_processing:
            messagebox.showwarning("Running", "Processing is already running.")
            return

        self.is_processing = True
        self.stop_event    = threading.Event()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.progress_var.set(0)
        self._start_time = time.time()
        self.log_text.delete(1.0, tk.END)
        self.nb.select(self.tab_monitor)
        self._set_status("Processing…", "PROC.TLabel")
        self._log(f"Started at {datetime.now():%H:%M:%S} | Provider: {self.llm_provider.get()} / {self.llm_model.get()}", "INFO")

        t = threading.Thread(target=self._run_processing, daemon=True)
        t.start()

    def _stop(self):
        if self.is_processing:
            self.stop_event.set()
            self._set_status("Stopping — saving partial results…", "WARN.TLabel")
            self.stop_btn.config(state=tk.DISABLED)
            self._log("Stop requested — finishing current file…", "WARN")

    def _run_processing(self):
        try:
            kwargs = {}
            if self.llm_base_url.get():
                kwargs['base_url'] = self.llm_base_url.get()

            self.automation_instance = SystematicReviewAutomation(
                api_key=self.api_key.get().strip(),
                pdf_folder=self.pdf_folder.get(),
                output_folder=self.output_folder.get(),
                cache_enabled=self.cache_enabled.get(),
                parallel_processing=self.parallel_proc.get(),
                max_workers=self.max_workers.get(),
                rate_limit_delay=self.rate_limit_delay.get(),
                screening_prompt=self.screening_prompt,
                extraction_prompt=self.extraction_prompt,
                extraction_fields=self.extraction_fields,
                llm_provider=self.llm_provider.get(),
                llm_model=self.llm_model.get(),
                two_stage_screening=self.two_stage.get(),
                stop_event=self.stop_event,
                advanced_config=self.advanced_config,
                **kwargs,
            )

            # Start progress monitor thread
            monitor = threading.Thread(target=self._monitor_progress, daemon=True)
            monitor.start()

            results = self.automation_instance.process_pdfs()

            self.message_queue.put(("results", results))
        except Exception as e:
            self.message_queue.put(("error", str(e), traceback.format_exc()))
        finally:
            self.message_queue.put(("finished", None))

    def _monitor_progress(self):
        while self.is_processing:
            if self.automation_instance:
                stats = self.automation_instance.stats.copy()
                self.message_queue.put(("stats", stats))
            time.sleep(1.5)

    # ── Queue handler ────────────────────────────────────────────────────────

    def _check_queue(self):
        try:
            while True:
                msg = self.message_queue.get_nowait()
                kind = msg[0]

                if kind == "stats":
                    self._update_stats(msg[1])

                elif kind == "results":
                    self._show_results(msg[1])

                elif kind == "error":
                    self._log(f"ERROR: {msg[1]}", "ERROR")
                    self._set_status("Processing failed!", "ERR.TLabel")
                    messagebox.showerror("Processing Error", f"{msg[1]}\n\nSee log for details.")

                elif kind == "finished":
                    self._processing_done()

                elif kind == "ingest_progress":
                    # msg = ("ingest_progress", result, current, total)
                    res, cur, total = msg[1], msg[2], msg[3]
                    dec_tag = {"Include": "include", "Exclude": "exclude",
                               "Flag for Human Review": "flag", "Error": "error"}.get(res.decision, "alt")
                    if hasattr(self, "_ingest_tree") and self._ingest_tree.exists(res.record_id):
                        vals = list(self._ingest_tree.item(res.record_id, "values"))
                        vals[3] = res.decision
                        vals[4] = f"{res.confidence:.0%}" if isinstance(res.confidence, float) else str(res.confidence)
                        vals[5] = (res.rationale or "")[:120]
                        self._ingest_tree.item(res.record_id, values=vals, tags=(dec_tag,))
                        self._ingest_tree.see(res.record_id)
                    if res not in self._ingest_results:
                        self._ingest_results.append(res)
                    if hasattr(self, "_ingest_stats_var"):
                        self._ingest_stats_var.set(f"Screening {cur:,} / {total:,} \u2026")
                    if hasattr(self, "_ingest_prog_var") and total:
                        self._ingest_prog_var.set(cur / total * 100)
                    if hasattr(self, "_cnt_inc"):
                        self._update_count_chips()

                elif kind == "ingest_done":
                    # msg = ("ingest_done", results)
                    self._ingest_results = list(msg[1])
                    self._ingest_running = False
                    if hasattr(self, "_ingest_screen_btn"):
                        self._ingest_screen_btn.config(state=tk.NORMAL)
                    if hasattr(self, "_ingest_dedup_btn"):
                        self._ingest_dedup_btn.config(state=tk.NORMAL)
                    if hasattr(self, "_ingest_parse_btn"):
                        self._ingest_parse_btn.config(state=tk.NORMAL)
                    if hasattr(self, "_ingest_stop_btn"):
                        self._ingest_stop_btn.config(state=tk.DISABLED)
                    if hasattr(self, "_ingest_prog_var"):
                        self._ingest_prog_var.set(100)
                    from collections import Counter
                    counts = Counter(r.decision for r in self._ingest_results)
                    if hasattr(self, "_ingest_stats_var"):
                        self._ingest_stats_var.set(
                            f"\u2714 Done \u2014 {len(self._ingest_results):,} screened | "
                            f"Include: {counts.get('Include', 0)} | "
                            f"Exclude: {counts.get('Exclude', 0)} | "
                            f"Flag: {counts.get('Flag for Human Review', 0)} | "
                            f"Error: {counts.get('Error', 0)}"
                        )
                    if hasattr(self, "_cnt_inc"):
                        self._update_count_chips()
                    self._log(
                        f"Abstract screening complete: {len(self._ingest_results):,} records | "
                        f"Include {counts.get('Include', 0)} / Exclude {counts.get('Exclude', 0)} / "
                        f"Flag {counts.get('Flag for Human Review', 0)}",
                        "OK"
                    )
                    self._set_status(
                        f"Abstract screening done \u2014 {counts.get('Include', 0)} included, "
                        f"{counts.get('Exclude', 0)} excluded, "
                        f"{counts.get('Flag for Human Review', 0)} flagged."
                    )

                elif kind == "conn_test":
                    _, ok, detail = msg
                    self._update_conn_dot()
                    self.test_btn.config(state=tk.NORMAL)
                    if ok:
                        messagebox.showinfo("Connection OK", f"Connection successful!\n{detail}")
                        self._log(f"Connection test passed ({self.llm_provider.get()})", "OK")
                    else:
                        messagebox.showerror("Connection Failed", f"Could not connect:\n{detail}")
                        self._log(f"Connection test FAILED: {detail}", "ERROR")

        except queue.Empty:
            pass
        self.root.after(150, self._check_queue)

    def _update_stats(self, stats: dict):
        total     = stats.get('total_files', 0)
        processed = stats.get('processed_files', 0)
        include   = stats.get('likely_include', 0)
        exclude   = stats.get('likely_exclude', 0)
        flag      = stats.get('flag_for_review', 0) + stats.get('flag_for_human_review', 0)
        tokens    = stats.get('total_api_tokens', 0)
        current   = stats.get('current_file', '')

        pct = (processed / total * 100) if total else 0
        self.progress_var.set(pct)

        # KPI chips
        self.lbl_files_var  .set(f"{processed} / {total}")
        self.lbl_include_var.set(str(include))
        self.lbl_exclude_var.set(str(exclude))
        self.lbl_flag_var   .set(str(flag))
        self.lbl_tokens_var .set(f"{tokens:,}")
        # Legacy labels (hidden but kept for compat)
        self.lbl_files  .config(text=f"Files: {processed}/{total}")
        self.lbl_include.config(text=f"Include: {include}")
        self.lbl_exclude.config(text=f"Exclude: {exclude}")
        self.lbl_flag   .config(text=f"Flagged: {flag}")
        self.lbl_tokens .config(text=f"Tokens: {tokens:,}")
        self.lbl_current.config(text=f"Current: {current or '—'}")

        elapsed = time.time() - self._start_time if self._start_time else 0
        h, r = divmod(int(elapsed), 3600)
        m, s = divmod(r, 60)
        self.lbl_time.config(text=f"Elapsed: {h:02d}:{m:02d}:{s:02d}")

        if processed > 0 and total > 0:
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = (total - processed) / rate if rate > 0 else 0
            eta = str(timedelta(seconds=int(remaining)))
            self.lbl_eta.config(text=f"ETA: {eta}")

        self._set_status(f"Processing: {current}", "PROC.TLabel")

        # Mirror live screening results into results tab
        if self.automation_instance:
            self._populate_results_tree()

    def _processing_done(self):
        self.is_processing = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.progress_var.set(100)
        self.lbl_eta.config(text="ETA: Done")
        self._populate_results_tree()
        self._save_settings()   # auto-save after run

    def _show_results(self, results: dict):
        self._set_status("Processing complete!", "OK.TLabel")
        self._log(f"Completed at {datetime.now():%H:%M:%S}", "OK")

        p = results.get('prisma', {})
        s = results.get('statistics', {})

        msg = (
            f"PRISMA FLOW\n"
            f"  Identified:       {p.get('identified', 0)}\n"
            f"  Screened:         {p.get('screened', 0)}\n"
            f"  Likely Include:   {p.get('included', 0)}\n"
            f"  Likely Exclude:   {p.get('excluded', 0)}\n"
            f"  Flagged:          {p.get('flagged', 0)}\n"
            f"  Errors:           {p.get('errors', 0)}\n"
            f"  Data Extracted:   {p.get('extracted', 0)}\n\n"
            f"Tokens used: {s.get('total_api_tokens', 0):,}\n"
            f"Time:        {s.get('total_processing_time', 0):.1f}s\n\n"
            f"Results saved to:\n  {results.get('screening_excel', '')}"
        )
        messagebox.showinfo("Processing Complete", msg)
        self.nb.select(self.tab_results)

    # ── Results tab ──────────────────────────────────────────────────────────

    def _populate_results_tree(self):
        if not self.automation_instance:
            return
        results = self.automation_instance.screening_results

        # Rebuild _all_results list
        self._all_results = []
        for r in results:
            self._all_results.append((
                r.filename,
                r.decision,
                r.stage,
                r.reasoning[:120].replace('\n', ' ') + ("…" if len(r.reasoning) > 120 else ""),
                r.api_tokens_used,
                round(r.processing_time, 1),
            ))

        self._apply_filter()

        # Update PRISMA line
        inc = sum(1 for _, d, *_ in self._all_results if d == "Likely Include")
        exc = sum(1 for _, d, *_ in self._all_results if d == "Likely Exclude")
        flg = sum(1 for _, d, *_ in self._all_results if "Flag" in d)
        self.prisma_lbl.config(
            text=f"Total: {len(self._all_results)}  |  "
                 f"Include: {inc}  |  Exclude: {exc}  |  Flagged: {flg}"
        )

    def _set_filter(self, value: str):
        self._filter_var.set(value)
        for lbl, btn in self._filter_btns.items():
            if lbl == value:
                btn.config(relief=tk.SUNKEN, bd=2)
            else:
                btn.config(relief=tk.FLAT, bd=1)
        self._apply_filter()

    def _apply_filter(self):
        fval   = self._filter_var.get()
        search = getattr(self, "_search_var", None)
        sterm  = search.get().strip().lower() if search else ""
        self.result_tree.delete(*self.result_tree.get_children())

        for i, (fn, dec, stage, reason, toks, t) in enumerate(self._all_results):
            if fval != "All" and dec != fval:
                continue
            if sterm and sterm not in fn.lower() and sterm not in dec.lower() and sterm not in reason.lower():
                continue
            tag = {
                "Likely Include":       "include",
                "Likely Exclude":       "exclude",
                "Flag for Review":      "flag",
                "Flag for Human Review":"human",
                "Error":                "error",
            }.get(dec, "alt" if i % 2 == 0 else "")
            self.result_tree.insert("", tk.END,
                                    values=(fn, dec, stage, reason, toks, t),
                                    tags=(tag,))

    def _show_detail(self, event=None):
        item = self.result_tree.focus()
        if not item:
            return
        vals = self.result_tree.item(item, "values")
        if not vals or not self.automation_instance:
            return
        fn = vals[0]

        screen_rec = next(
            (r for r in self.automation_instance.screening_results if r.filename == fn), None
        )
        if not screen_rec:
            return

        extract_rec = next(
            (r for r in self.automation_instance.extraction_results if r.filename == fn), None
        )
        paper_text = self.automation_instance._paper_texts.get(fn, "")

        win = tk.Toplevel(self.root)
        win.title(f"Detail — {fn}")
        win.geometry("1100x680")
        win.transient(self.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        nb2 = ttk.Notebook(win)
        nb2.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        # ── Tab 1: Screening decision ────────────────────────────────────────────
        sc_frm = ttk.Frame(nb2, padding=10)
        nb2.add(sc_frm, text="Screening")
        sc_frm.columnconfigure(0, weight=1)

        ttk.Label(sc_frm, text=f"Decision: {screen_rec.decision}",
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(sc_frm,
                  text=f"Stage: {screen_rec.stage}  │  Tokens: {screen_rec.api_tokens_used}  "
                       f" │  Time: {screen_rec.processing_time:.1f}s",
                  foreground="#666").grid(row=1, column=0, sticky=tk.W, pady=(2, 10))

        for r_idx, (lbl, content) in enumerate((
            ("Reasoning", screen_rec.reasoning),
            ("Notes",     screen_rec.notes),
        ), start=2):
            ttk.Label(sc_frm, text=lbl + ":",
                      font=("Segoe UI", 9, "bold")).grid(row=r_idx * 2,     column=0, sticky=tk.W)
            st = scrolledtext.ScrolledText(sc_frm, wrap=tk.WORD, font=("Segoe UI", 10), height=6)
            st.grid(row=r_idx * 2 + 1, column=0, sticky="ew", pady=(2, 10))
            st.insert(tk.END, content)
            st.config(state=tk.DISABLED)

        # ── Tab 2: Extraction + human-in-the-loop verifier ──────────────────────
        if extract_rec and extract_rec.fields:
            fields = extract_rec.fields
            ex_frm = ttk.Frame(nb2)
            nb2.add(ex_frm, text="Extraction & Verification")
            ex_frm.columnconfigure(0, weight=2)
            ex_frm.columnconfigure(1, weight=3)
            ex_frm.rowconfigure(1, weight=1)

            # Left: paper text viewer
            ttk.Label(
                ex_frm,
                text="Paper Text (Ctrl+F in your text editor for quotes)",
                font=("Segoe UI", 9, "bold"), foreground="#444",
            ).grid(row=0, column=0, sticky=tk.W, padx=(8, 4), pady=(8, 2))
            paper_st = scrolledtext.ScrolledText(
                ex_frm, wrap=tk.WORD, font=("Consolas", 9),
                background="#1E1E1E", foreground="#D4D4D4",
                insertbackground="white", width=48,
            )
            paper_st.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
            paper_st.insert(tk.END, paper_text or "(Paper text not available)")
            paper_st.config(state=tk.DISABLED)

            # Right: scrollable quote + value editor
            ttk.Label(
                ex_frm,
                text="Extracted Fields  —  edit values then click Save Changes",
                font=("Segoe UI", 9, "bold"), foreground="#444",
            ).grid(row=0, column=1, sticky=tk.W, padx=(4, 8), pady=(8, 2))

            right_canvas = tk.Canvas(ex_frm, highlightthickness=0)
            right_canvas.grid(row=1, column=1, sticky="nsew", padx=(4, 4), pady=(0, 0))
            r_sb = ttk.Scrollbar(ex_frm, orient=tk.VERTICAL, command=right_canvas.yview)
            r_sb.grid(row=1, column=2, sticky="ns")
            right_canvas.configure(yscrollcommand=r_sb.set)

            inner = ttk.Frame(right_canvas, padding=(4, 4))
            cwin  = right_canvas.create_window((0, 0), window=inner, anchor="nw")
            inner.columnconfigure(0, weight=1)

            right_canvas.bind("<Configure>",
                              lambda e: right_canvas.itemconfig(cwin, width=e.width))
            inner.bind("<Configure>",
                       lambda e: right_canvas.configure(scrollregion=right_canvas.bbox("all")))

            def _on_mousewheel(e):
                right_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            right_canvas.bind("<MouseWheel>", _on_mousewheel)
            right_canvas.bind("<Enter>",
                              lambda e: right_canvas.bind_all("<MouseWheel>", _on_mousewheel))
            right_canvas.bind("<Leave>",
                              lambda e: right_canvas.unbind_all("<MouseWheel>"))

            # Build field rows: detect Quote-Then-Answer pairs (_quote sibling)
            base_fields  = [k for k in fields if not k.endswith("_quote")]
            entry_vars: dict = {}
            r_idx = 0

            for base in base_fields:
                quote_val = fields.get(f"{base}_quote", "")
                value_val = str(fields.get(base, ""))

                # Field name header
                ttk.Label(
                    inner,
                    text=base.replace("_", " ").title() + ":",
                    font=("Segoe UI", 9, "bold"),
                ).grid(row=r_idx, column=0, sticky=tk.W, pady=(10, 0))
                r_idx += 1

                # Verbatim quote (grey, italic) — only shown when present
                if quote_val and quote_val not in ("Not found", "Not reported", ""):
                    ttk.Label(
                        inner,
                        text=f'Quote: “{quote_val}”',
                        foreground="#888",
                        font=("Segoe UI", 8, "italic"),
                        wraplength=400,
                        justify=tk.LEFT,
                    ).grid(row=r_idx, column=0, sticky=tk.W, padx=(12, 0))
                    r_idx += 1

                # Editable value entry
                var = tk.StringVar(value=value_val)
                entry_vars[base] = var
                ent = ttk.Entry(inner, textvariable=var, font=("Segoe UI", 10))
                ent.grid(row=r_idx, column=0, sticky="ew", padx=(12, 4), pady=(2, 0))
                r_idx += 1

            # Save / Copy buttons
            save_row = ttk.Frame(ex_frm)
            save_row.grid(row=2, column=1, columnspan=2, sticky="ew",
                          padx=(4, 8), pady=(6, 8))

            def _save_changes():
                for key, var in entry_vars.items():
                    extract_rec.fields[key] = var.get()
                messagebox.showinfo(
                    "Saved",
                    "Extraction values updated in memory.\n"
                    "Click 'Export Results' on the Results tab to save to file.",
                    parent=win,
                )

            ttk.Button(save_row, text="Save Changes", command=_save_changes).pack(
                side=tk.LEFT, padx=(0, 8))
            ttk.Button(
                save_row, text="Copy Paper Text",
                command=lambda: (win.clipboard_clear(),
                                 win.clipboard_append(paper_text)),
            ).pack(side=tk.LEFT)

        # ── Tab 3: Full paper text (standalone dark viewer) ───────────────────
        pt_frm = ttk.Frame(nb2, padding=4)
        nb2.add(pt_frm, text="Full Paper Text")
        pt_frm.columnconfigure(0, weight=1)
        pt_frm.rowconfigure(0, weight=1)
        pt_st = scrolledtext.ScrolledText(
            pt_frm, wrap=tk.WORD, font=("Consolas", 9),
            background="#1E1E1E", foreground="#D4D4D4",
        )
        pt_st.grid(sticky="nsew")
        pt_st.insert(tk.END, paper_text or "(Paper text not available)")
        pt_st.config(state=tk.DISABLED)

    def _export_visible(self):
        rows = [self.result_tree.item(i, "values")
                for i in self.result_tree.get_children()]
        if not rows:
            messagebox.showinfo("Export", "No rows to export.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
            title="Export visible results"
        )
        if path:
            import csv
            headers = ["filename", "decision", "stage", "reasoning", "tokens", "time_s"]
            with open(path, 'w', newline='', encoding='utf-8') as fh:
                w = csv.writer(fh)
                w.writerow(headers)
                w.writerows(rows)
            messagebox.showinfo("Exported", f"Saved {len(rows)} rows to:\n{path}")

    # ── Log helpers ──────────────────────────────────────────────────────────

    def _log(self, message: str, level: str = "INFO"):
        ts  = datetime.now().strftime("%H:%M:%S")
        tag = level.upper()
        tag_map = {"OK": "OK", "WARN": "WARN", "ERROR": "ERROR", "PROC": "INFO",
                   "INCLUDE": "INCLUDE", "EXCLUDE": "EXCLUDE", "FLAG": "FLAG"}
        t = tag_map.get(tag, "INFO")
        self.log_text.insert(tk.END, f"[{ts}] ", "INFO")
        self.log_text.insert(tk.END, message + "\n", t)
        self.log_text.see(tk.END)

    def _clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def _save_log(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
            title="Save Log"
        )
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.log_text.get(1.0, tk.END))

    def _set_status(self, text: str, style: str = ""):
        self.status_var.set(text)

    # ── Settings persistence ─────────────────────────────────────────────────

    def _settings_dict(self) -> dict:
        return {
            'pdf_folder':        self.pdf_folder.get(),
            'output_folder':     self.output_folder.get(),
            'api_key':           self.api_key.get(),
            'max_workers':       self.max_workers.get(),
            'rate_limit_delay':  self.rate_limit_delay.get(),
            'parallel_proc':     self.parallel_proc.get(),
            'cache_enabled':     self.cache_enabled.get(),
            'two_stage':         self.two_stage.get(),
            'llm_provider':      self.llm_provider.get(),
            'llm_model':         self.llm_model.get(),
            'llm_base_url':      self.llm_base_url.get(),
            'advanced_config':   self.advanced_config,
            'screening_prompt':  self.screening_prompt,
            'extraction_prompt': self.extraction_prompt,
            'extraction_fields': self.extraction_fields,
        }

    def _save_settings(self, path: str = None):
        try:
            dest = Path(path) if path else SETTINGS_FILE
            with open(dest, 'w', encoding='utf-8') as f:
                json.dump(self._settings_dict(), f, indent=2)
            if path:
                messagebox.showinfo("Saved", f"Settings saved to:\n{path}")
        except Exception as e:
            if path:
                messagebox.showerror("Save Error", str(e))

    def _apply_settings(self, s: dict):
        self.pdf_folder      .set(s.get('pdf_folder', ''))
        self.output_folder   .set(s.get('output_folder', 'output'))
        self.api_key         .set(s.get('api_key', ''))
        self.max_workers     .set(s.get('max_workers', 3))
        self.rate_limit_delay.set(s.get('rate_limit_delay', 1.0))
        self.parallel_proc   .set(s.get('parallel_proc', True))
        self.cache_enabled   .set(s.get('cache_enabled', True))
        self.two_stage       .set(s.get('two_stage', False))
        self.llm_provider    .set(s.get('llm_provider', 'OpenAI'))
        self.llm_base_url    .set(s.get('llm_base_url', ''))
        self.screening_prompt  = s.get('screening_prompt')
        self.extraction_prompt = s.get('extraction_prompt')
        self.extraction_fields = s.get('extraction_fields')
        if 'advanced_config' in s:
            self.advanced_config.update(s['advanced_config'])
        # Update criteria status label
        if self.screening_prompt or self.extraction_prompt:
            n = len(self.extraction_fields) if self.extraction_fields else 0
            self.criteria_status.set(f"Custom criteria · {n} extraction field(s) defined")
        self._on_provider_changed()
        # Restore saved model AFTER provider change (which resets to default)
        saved_model = s.get('llm_model', '')
        if saved_model:
            self.llm_model.set(saved_model)

    def _load_settings(self):
        """Auto-load from fixed settings.json on startup."""
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, encoding='utf-8') as f:
                    self._apply_settings(json.load(f))
            except Exception:
                pass   # Silently ignore corrupted settings

    def _load_settings_dialog(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
            title="Load Settings"
        )
        if path:
            try:
                with open(path, encoding='utf-8') as f:
                    self._apply_settings(json.load(f))
                messagebox.showinfo("Loaded", f"Settings loaded from:\n{path}")
            except Exception as e:
                messagebox.showerror("Load Error", str(e))

    # ── About ────────────────────────────────────────────────────────────────

    def _about(self):
        self.nb.select(self.tab_help)

    # ── HELP TAB ─────────────────────────────────────────────────────────────

    # Full help content keyed by topic label
    _HELP_TOPICS = [
        ("Overview",             "overview"),
        ("Key Concepts",         "concepts"),
        ("PRISMA Workflow",      "prisma"),
        ("── Phase 2 & 3: Ingestion Tab", "ingestion"),
        ("── Phase 4 & 5: Setup Tab",     "setup"),
        ("── Monitor Tab",               "monitor"),
        ("── Results Tab",               "results"),
        ("AI Providers",         "providers"),
        ("Screening Criteria",   "criteria"),
        ("Extraction Fields",    "extraction"),
        ("Anti-Hallucination",   "antihalluc"),
        ("Keyboard Shortcuts",   "shortcuts"),
        ("Troubleshooting",      "trouble"),
        ("FAQ",                  "faq"),
        ("About & Author",       "about"),
        ("\u26a0 Disclaimer",    "disclaimer"),
    ]

    _HELP_CONTENT = {
        "concepts": ("""\
Key Concepts Explained  —  Plain Language for Every Researcher
══════════════════════════════════════════════════════════════

This page explains every technical term you will encounter in this
tool, in plain language. No prior computer science knowledge needed.

WHAT IS ARTIFICIAL INTELLIGENCE (AI)?
───────────────────────────────────────
Artificial Intelligence refers to computer programs that can perform
tasks normally requiring human intelligence: reading text, understanding
language, making decisions, and summarising information.

In this tool, AI reads your papers and decides whether each one meets
your research inclusion criteria — just like a trained research
assistant, but in seconds.

WHAT IS A LARGE LANGUAGE MODEL (LLM)?
───────────────────────────────────────
A Large Language Model is a specific type of AI trained on billions of
pages of text (books, articles, websites). It learned to read and
generate human language at an expert level.

Think of it as a research assistant who has read almost everything
ever published and can answer the question "Does this paper study
the effect of X on Y in an RCT?" in a second.

Examples of LLMs used by this tool:
  GPT-4o       — made by OpenAI (the company behind ChatGPT)
  Claude       — made by Anthropic
  Gemini       — made by Google
  DeepSeek     — very affordable; made by a Chinese AI company
  Llama / Phi  — can run on your own computer for free (via Ollama)

WHAT IS AN API?
────────────────
An API (Application Programming Interface) is a communication channel
that lets one software program talk to another over the internet.

When this tool sends a paper to an AI for screening, it does so
through an API — like a postal system that sends your paper to the
AI company's servers and receives the decision back.

Cloud AI providers (OpenAI, Anthropic, etc.) charge a small fee for
each piece of text you send. This fee is measured in "tokens".

WHAT IS AN API KEY?
─────────────────────
An API Key is like a unique password or ID card. When you sign up with
an AI provider, they give you a key (a long string of letters and
numbers, starting with "sk-"). You paste this into the Setup tab so
the tool can access the AI on your behalf.

KEEP YOUR KEY PRIVATE — treat it exactly like a password.
Anyone with your key can use your account and spend your credits.
Do NOT share screenshots with your key visible.
Do NOT put your key in a shared document or email.

WHAT IS A MODEL?
──────────────────
Each AI provider offers several versions of their AI, called models.
Larger models give better results but cost more and run slower.
Smaller models are cheaper, faster, and still very accurate for
standard systematic review screening.

For example, OpenAI's models range from:
  gpt-4o-mini  — smaller, cheap, still very good  (recommended start)
  gpt-4o       — most capable, higher cost

WHAT IS A TOKEN?
──────────────────
AI providers charge per "token" — roughly 4 characters of text (about
3/4 of an English word). You are charged for both input tokens (the
paper text you send in) and output tokens (the AI's response).

A typical 200-word abstract uses about 400 input tokens.
A typical 8-page full-text paper uses about 6,000–15,000 input tokens.

The Monitor tab shows your running token count so you can track cost.

WHAT DOES CACHING MEAN?
─────────────────────────
Caching means saving the result of completed work so it does not need
to be repeated if processing is interrupted. When caching is enabled:
  • If the tool crashes or you stop it midway, results already
    completed are not lost and will not be re-charged.
  • If you re-run with slightly different settings, already-processed
    papers are loaded from cache instantly.
Always keep caching enabled.

WHAT IS RATE LIMITING?
────────────────────────
AI providers restrict how many requests you can make per minute (your
"rate limit"). If you exceed it, you receive an error and must slow
down. The Rate Delay setting in the Setup tab adds a pause between
requests to keep you within your limit.

Default 1.0 second is safe for most accounts. Increase to 2–3 seconds
if you see "rate limit" errors in the Monitor log.

WHAT IS PARALLEL PROCESSING?
──────────────────────────────
Parallel processing means running multiple tasks at the same time.
When enabled, the tool processes several PDFs simultaneously using
multiple "workers" — like having several assistants each reading a
different paper at the same time. This can triple your processing
speed but uses more API quota per minute.

WHAT IS PRISMA?
─────────────────
PRISMA (Preferred Reporting Items for Systematic Reviews and
Meta-Analyses) is the international standard for reporting systematic
reviews. It defines a flow diagram showing how many papers you:
  ① Identified in database searches
  ② Removed as duplicates
  ③ Screened by title and abstract
  ④ Assessed as full text
  ⑤ Included in your final synthesis

This tool follows the PRISMA workflow and automatically tracks all
the counts you need to complete your PRISMA flow diagram.

HARDWARE AND SYSTEM REQUIREMENTS
───────────────────────────────────
  Windows 10/11, macOS 10.14+, or Linux
  4 GB RAM minimum (8 GB recommended for large corpora)
  2 GB free disk space + space for your PDF collection
  Internet connection (required for cloud AI; not needed for Ollama)

  For Ollama (local free AI): 8 GB RAM minimum
  For models >7B parameters: dedicated GPU with 8–16 GB VRAM
"""),
        "overview": ("""\
Universal SLR / Scoping Review Automation Tool  —  v3.0
════════════════════════════════════════════════════════

WHAT IS THIS TOOL?
──────────────────
This application automates the most time-consuming stages of a
Systematic Literature Review (SLR) or Scoping Review: importing
reference lists from academic databases, deduplicating records,
screening titles and abstracts with AI, processing full-text PDFs,
and extracting structured data — all in a single desktop application
that works with ANY research domain.

A review that typically takes weeks of manual work can be completed
in hours, with full human oversight and PRISMA-compliant reporting.

WHO IS IT FOR?
──────────────
  • Academic researchers conducting systematic or scoping reviews
  • PhD students performing literature synthesis
  • Research teams needing consistent, reproducible screening
  • Evidence synthesis teams working to Cochrane or PRISMA standards
  • Anyone who needs to process large volumes of academic papers

KEY CAPABILITIES
────────────────
  REFERENCE IMPORT
  Import reference lists exported from PubMed, Scopus, Web of Science,
  CINAHL, Embase, and any other database that supports .ris, .bib,
  or .csv export formats.

  AUTOMATIC DEDUPLICATION
  Records are deduplicated automatically using two passes:
    Pass 1 — Exact DOI matching (instant, highly reliable).
    Pass 2 — Fuzzy title matching using Levenshtein distance at ≥90%
              similarity, catching the same paper from two databases
              with slightly different titles or punctuation.

  AI ABSTRACT SCREENING
  Title and abstract screening with Include / Exclude / Flag decisions,
  rationale text, and a 0–100% confidence score — for every record.
  The AI follows your exact PICO / SPIDER / free-text criteria.

  FULL-TEXT PDF SCREENING
  Process PDF files with a cascade of three extraction engines
  (pymupdf4llm → pdfplumber → PyPDF2) to maximise text recovery.
  Two-stage screening reduces cost: irrelevant papers are filtered
  cheaply before the expensive full-text read.

  STRUCTURED DATA EXTRACTION
  Define your own extraction fields per domain. The AI extracts each
  field and provides a verbatim quote from the paper as evidence.
  6 domain presets available (Clinical, Education, Environmental, etc.).

  ANTI-HALLUCINATION SYSTEM
  5 layered safeguards prevent the AI from fabricating data:
  Quote-Then-Answer pairing, instructor structured outputs, dynamic
  Pydantic schemas, fallback JSON parsing, and human verification UI.

  PROVIDER FLEXIBILITY
  Works with 7 AI providers: OpenAI GPT, Anthropic Claude, DeepSeek,
  Mistral, Google Gemini, Ollama (fully local / free), and any custom
  OpenAI-compatible endpoint.

  PRISMA-COMPLIANT EXPORT
  Export colour-coded Excel workbooks with a PRISMA 2020 flow summary
  sheet tracking all stage counts, from identification to inclusion.

  PERSISTENT SETTINGS
  All settings are auto-saved to settings.json and restored between
  sessions. Use Ctrl+S to save manually at any time.

WORKFLOW SUMMARY
────────────────
  The tool covers PRISMA Phases 2–6:

  ①  Import & Deduplicate reference lists       (Ingestion tab)
  ②  AI screen titles and abstracts             (Ingestion tab)
  ③  Export "Include" list for PDF retrieval    (Ingestion tab)
  ④  Configure AI provider + extraction fields  (Setup tab)
  ⑤  Process full-text PDFs                    (Setup → Monitor)
  ⑥  Verify, edit, and export results           (Results tab)

See the PRISMA Workflow topic for the full stage mapping.

SYSTEM REQUIREMENTS
────────────────────
  Python 3.10+   with pip-installed dependencies (see requirements.txt)
  Internet       for cloud AI providers (OpenAI, Anthropic, etc.)
  No internet    required for Ollama local mode
  RAM            4 GB minimum; 8 GB+ recommended for large corpora
  Storage        Space for your PDF collection + output files
"""),
        "prisma": ("""\
PRISMA Workflow Overview
════════════════════════

WHAT IS PRISMA?
───────────────
PRISMA 2020 (Preferred Reporting Items for Systematic reviews and
Meta-Analyses) is the internationally recognised standard for
reporting systematic and scoping reviews. It requires you to document
how many records were found, screened, excluded, and included at
every stage, with reasons for exclusion.

This tool automates Phases 2 through 6 and tracks all required counts
automatically so your Methods section and flow diagram are accurate.

FULL PHASE MAPPING
──────────────────
  PHASE 1 — IDENTIFICATION  (done externally, before you open the tool)
  ─────────────────────────────────────────────────────────────────────
  Search each database using your search string:
    PubMed      → pubmed.ncbi.nlm.nih.gov
    Scopus      → scopus.com
    Web of Sci  → webofscience.com
    CINAHL      → via EBSCOhost
    Embase      → embase.com
    PsycINFO    → via EBSCOhost or ProQuest

  Export results as .ris or .bib files.
  Record the number of results per database for your PRISMA flow.

  PHASE 2 — IMPORT & DEDUPLICATION  ← INGESTION TAB
  ───────────────────────────────────────────────────
  Load each exported file via the Ingestion tab.
  Click Parse File → records appear in the table.
  Repeat for each database export (records accumulate).
  Click Deduplicate → duplicates are identified and marked.
  The tool tracks:
    Records identified  — total parsed (all databases)
    Duplicates removed  — by DOI + by fuzzy title match

  PHASE 3 — TITLE/ABSTRACT SCREENING  ← INGESTION TAB
  ──────────────────────────────────────────────────────
  Click Screen Abstracts with AI.
  The AI reads each record's title + abstract and applies your
  inclusion/exclusion criteria (entered in the Criteria text box).
  Decisions appear in real time:
    Include         — green row
    Exclude         — red row
    Flag for Review — amber row (human check required)
  The tool tracks:
    Records screened            — all non-duplicate records
    Records excluded (abstract) — Exclude decisions
    Records included for retrieval — Include decisions

  PHASE 4 — FULL-TEXT RETRIEVAL  (done externally)
  ──────────────────────────────────────────────────
  Use the Ingestion tab Export buttons to download the Include list
  as CSV or Excel. Obtain the PDFs from:
    • Publisher websites (DOI links)
    • Institutional library access
    • PubMed Central (free PDFs)
    • Unpaywall / Open Access Button
    • Interlibrary loan for paywalled papers
  Place all PDFs in a single folder on your computer.

  PHASE 5 — FULL-TEXT SCREENING  ← SETUP + MONITOR TABS
  ───────────────────────────────────────────────────────
  Setup tab: select the PDF folder, configure AI provider + criteria.
  Click ▶ Start Processing (or press F5).
  The Monitor tab shows live progress: KPI cards, progress bar, log.
  The tool tracks:
    Full-texts assessed         — total PDFs found and processed
    Full-texts excluded         — Exclude decisions with reasons
    Full-texts included         — Include decisions (for extraction)

  PHASE 6 — DATA EXTRACTION  ← RESULTS TAB
  ───────────────────────────────────────────
  Included papers are processed for structured data extraction.
  The AI fills each field you defined in the Extraction Fields editor.
  Every value comes with a verbatim quote for human verification.
  You can edit any value in the Results → Detail → Extraction tab.
  Export to Excel produces a fully populated data extraction sheet.

PRISMA COUNTS — AUTOMATIC TRACKING
────────────────────────────────────
  The following counts are maintained automatically:

  Records identified                  (sum of all parsed records)
  Records after deduplication         (identified − duplicates)
  Records screened (title/abstract)   (all non-duplicates)
  Records excluded (title/abstract)   (Exclude decisions in Ingestion)
  Full-texts assessed                 (PDFs in the selected folder)
  Full-texts excluded                 (Exclude decisions in Results)
  Studies included in synthesis       (Include decisions in Results)
  Duplicates removed                  (DOI + fuzzy deduplicated count)

  These counts appear in:
    • The status chips in the Ingestion tab
    • The KPI cards in the Monitor tab
    • The PRISMA Summary sheet in the Excel export
    • The PRISMA summary line above the Export button in Results tab

REPORTING YOUR REVIEW
──────────────────────
  When writing up your Methods section:
  1. State the databases searched and the date of the search.
  2. Report the search string used for each database.
  3. Use the PRISMA counts from the export for your flow diagram.
     (Use the free PRISMA flow diagram tool at prisma-statement.org)
  4. State that AI-assisted screening was used, which model, and that
     all Include and Flag decisions were human-verified.
  5. Report inter-rater reliability if a second screener was used.

IMPORTANT NOTE ON VERIFICATION
────────────────────────────────
  AI screening is a decision-support tool, not a replacement for human
  judgment. PRISMA and Cochrane standards require that:
    • All Include and Flagged decisions are human-verified.
    • Exclude decisions at abstract stage are spot-checked.
    • At least one human reviewer verifies all extracted data.
"""),
        "ingestion": ("""\
Ingestion Tab  —  Phase 2 & 3: Import, Deduplicate & Screen Abstracts
══════════════════════════════════════════════════════════════════════

OVERVIEW
────────
The Ingestion tab handles the first two active phases of your review:
importing reference lists from academic databases, removing duplicates,
and using AI to screen titles and abstracts against your criteria.
This is where you decide which records proceed to full-text retrieval.

STEP 1 — EXPORT FROM YOUR DATABASES
─────────────────────────────────────
Before you open the Ingestion tab, export your search results. Each
database has its own export procedure:

  PubMed
    Search → Send to → Citation Manager → Create file (.ris)
    Do NOT use "MEDLINE" format; use "Citation Manager".
    Tip: PubMed limits exports to 10,000 records per batch.

  Scopus
    Search → Export → RIS format → check all desired fields
    Include: Title, Author, Year, Source, Abstract, DOI, Keywords.
    Tip: Scopus allows full export regardless of result count.

  Web of Science (Clarivate)
    Search → Export → Other File Formats
    Select: Plain Text (RIS) or BibTeX
    Content: Full Record and Cited References (for completeness)
    Records per file: max 500 — repeat for large sets.

  CINAHL / PsycINFO (EBSCOhost)
    Search → Share → E-mail/Export → Direct Export in RIS format
    Tip: Export in batches of 200 if over that limit.

  Embase
    Search → Export → RIS (tagged) — ensure Abstract is included.

  Other databases
    Any database that exports .ris, .bib, or .csv is supported.

STEP 2 — LOAD THE FILE
───────────────────────
  Click "Browse File" or drag a file into the file path box.
  Supported formats:
    .ris  — RIS tagged format (standard for all major databases)
    .bib  — BibTeX format (common for bibliographic managers)
    .csv  — Comma-separated values (from custom exports or Excel)
    .txt  — Plain text RIS format (some databases use .txt extension)

  CSV FORMAT SPECIFICATION
  CSV files must have a 'title' column. These additional columns are
  auto-detected (case-insensitive, any order):
    title       — article title (REQUIRED)
    abstract    — full abstract text
    doi         — Digital Object Identifier
    authors     — author list (any format)
    year        — publication year (4-digit integer)
    journal     — journal or source name
    keywords    — keyword list (semicolon or comma separated)

  The record count badge updates immediately after selecting the file.

STEP 3 — PARSE FILE
────────────────────
  Click the "② Parse File" button.
  The tool parses the file and populates the records table.
  Each record initially shows:
    Status: Pending
    Title, Authors, Year, Source — populated from the file
    Abstract — shown in the detail popup (double-click the row)
  Parse errors are shown in a red banner above the table.
  Repeat for each database export file — records accumulate.

STEP 4 — DEDUPLICATE
─────────────────────
  Click "③ Deduplicate" after loading all database exports.

  The deduplication algorithm uses TWO passes:

  PASS 1 — EXACT DOI MATCHING
  Compares the DOI field of every record pair. Exact match = duplicate.
  Very fast. Catches ~95% of true duplicates when DOIs are present.
  The earlier-loaded record is kept; the later one is marked Duplicate.

  PASS 2 — FUZZY TITLE MATCHING
  For records without DOIs, or where DOIs differ but papers are
  the same, the tool compares normalised title strings using
  Levenshtein distance (via the 'thefuzz' library).
  Similarity ≥ 90% = duplicate. Catches:
    • Same paper from two databases with different punctuation
    • Pre-print vs published version with slightly different titles
    • Subtly different title formatting between databases

  DEDUPLICATION RESULTS
  A summary chip is shown after deduplication:
    "Removed by DOI: N | Removed by fuzzy: N | Remaining: N"
  Duplicate records are greyed out in the table (status: Duplicate).
  They are excluded from all further processing and counts.

STEP 5 — ENTER SCREENING CRITERIA
───────────────────────────────────
  In the Criteria panel (right side of the Ingestion tab), enter your
  inclusion and exclusion criteria as plain text. Example format:

    INCLUDE:
    - RCTs, cohort studies, or systematic reviews
    - Adults (18+) with Type 2 Diabetes
    - Dietary or physical activity interventions
    - Reports HbA1c, weight, or quality of life outcomes
    - Published 2015–2025, English language

    EXCLUDE:
    - Animal or in-vitro studies
    - Conference abstracts without full text
    - N < 20 participants
    - Duplicate publications

  See the Screening Criteria help topic for full guidance on PICO and
  SPIDER frameworks.

STEP 6 — SCREEN ABSTRACTS WITH AI
───────────────────────────────────
  Click "④ Screen Abstracts with AI".
  The tool sends each non-duplicate record's title and abstract to
  the AI provider configured in the Setup tab (or the default provider
  if setup has not been visited yet).

  What the AI receives for each record:
    • Your inclusion/exclusion criteria (as entered in the Criteria box)
    • The title and abstract text
    • An instruction to return: decision, rationale, confidence (0–100)

  Processing is rate-limit safe: a configurable delay (default 0.5s)
  is inserted between calls. Exponential back-off is applied on 429
  (rate limit) errors: waits 2s, 4s, 8s before giving up.

  Results appear in real time as rows colour in:
    Green  — Include
    Red    — Exclude
    Amber  — Flag for Human Review (AI uncertain — must be human-checked)
    Blue   — Error (API call failed — re-screen individually or in bulk)

  You can click Stop at any time. Results so far are preserved and you
  can resume by clicking Screen Abstracts again (it skips already
  screened records).

UNDERSTANDING DECISIONS
────────────────────────
  Include
    The paper clearly meets ALL inclusion criteria based on title and
    abstract alone. Proceed to full-text retrieval.

  Exclude
    The paper clearly does NOT meet one or more inclusion criteria.
    The rationale column states the specific exclusion reason.
    Spot-check a sample of excluded records for quality assurance.

  Flag for Human Review
    The AI is uncertain — the abstract is ambiguous, too short, or the
    criteria require full-text confirmation. You MUST manually review
    every flagged record before making a final Include/Exclude decision.
    Right-click → Override → Include or Exclude after manual review.

  Error
    The API call failed after retries. The error message is in the
    rationale column. Fix the issue (check API key, rate limits) then
    right-click → Re-screen, or click Screen Abstracts again.

HUMAN OVERRIDE
──────────────
  You can override any AI decision:
    Right-click any row in the table → Override → Include / Exclude / Flag
  The rationale column is updated with "[Human override – original: X]"
  followed by the original rationale. Overrides are preserved in exports.

  To view full details of any record:
    Double-click a row — opens a detail popup showing the full abstract,
    full rationale text, confidence score, and source metadata.

SORTING AND FILTERING THE TABLE
────────────────────────────────
  Click any column header to sort by that column (ascending).
  Click again to reverse (descending).
  Use the filter buttons below the table to show only a subset:
    All / Include / Exclude / Flag / Error / Duplicate

TABLE COLUMNS
─────────────
  #           — record sequence number (for reference)
  Status      — current decision (Pending, Include, Exclude, etc.)
  Title       — article title (truncated; full text in popup)
  Authors     — first author + et al.
  Year        — publication year
  Source      — journal or conference name
  Confidence  — AI confidence score 0–100% (shown after screening)
  Rationale   — first 80 characters of AI reasoning

EXPORT AFTER SCREENING
──────────────────────
  After screening, use the Export buttons at the bottom:

  Export CSV
    Flat CSV file with all records and their screening decisions.
    Columns: all source metadata + Decision, Rationale, Confidence.
    Import into Excel, Zotero, Mendeley, or other reference managers.

  Export Excel
    Multi-sheet workbook:
      Sheet 1 (Screening Results) — colour-coded rows per decision.
        Green rows = Include, Red = Exclude, Amber = Flag.
      Sheet 2 (PRISMA Summary) — automatic stage counts for your
        flow diagram: Identified, Deduplicated, Screened, Included.
      Sheet 3 (Duplicates) — list of records removed as duplicates.

  Include List CSV
    Exports ONLY the Include decisions — use this to retrieve PDFs.
    One row per included paper, with title, authors, year, DOI, source.
    The DOI column can be used with doi.org links to find PDFs quickly.
"""),
        "setup": ("""\
Setup Tab  —  Phase 4 & 5: Full-text Screening Configuration
═════════════════════════════════════════════════════════════

OVERVIEW
────────
The Setup tab is your control centre for full-text PDF processing.
Here you configure the AI provider, point the tool at your PDF folder
and output folder, tune processing performance, and define the
criteria and extraction fields that govern what the AI looks for.
A working configuration must be saved before you start processing.

AI PROVIDER CONFIGURATION
──────────────────────────
  PROVIDER DROPDOWN
  Select your AI service from the list. Available options:
    OpenAI · Anthropic · DeepSeek · Mistral · Google Gemini
    Ollama (local) · Custom Endpoint
  See the AI Providers help topic for setup URLs and model guidance.

  MODEL DROPDOWN
  Automatically populated with available models for the selected
  provider. For OpenAI the list is fetched live from the API.
  For Ollama: only models you have pulled locally appear here.
  Type a model name directly if yours does not appear.

  API KEY
  Paste your API key from the provider's developer console.
  Click the "Show" checkbox to reveal / hide the key text.
  The key is saved to settings.json (encrypted in memory, plain on
  disk — do not share your settings.json with others).

  BASE URL
  Required for: Ollama, Custom Endpoint, LM Studio, vLLM.
  For Ollama the default is: http://localhost:11434
  Leave blank for all cloud providers (OpenAI, Anthropic, etc.).

  TEST CONNECTION
  Sends a minimal "ping" prompt to the provider to verify the key,
  model, and network are all working.
  Result is shown in the indicator top-right of the main header:
    Grey circle  ⬤  — not yet tested this session
    Green circle ⬤  — last test passed; you are good to go
    Red circle   ⬤  — last test failed; check key/model/network

FILE AND FOLDER PATHS
──────────────────────
  PDF FOLDER
  The folder containing your full-text PDFs for processing.
  Click Browse to open a folder picker, or paste a path directly.
  The tool scans for *.pdf files RECURSIVELY in this folder,
  including all sub-folders. A badge shows how many PDFs were found.
  Tip: PDFs should be named recognisably (e.g. surname_year.pdf)
       so Results tab filenames are easy to match back to records.

  OUTPUT FOLDER
  Where result files (Excel, CSV, cache) are saved.
  If the folder does not exist, it is created automatically.
  The cache sub-folder (.slr_cache) is created here to enable
  result caching across sessions.

PROCESSING SETTINGS
────────────────────
  TWO-STAGE SCREENING (recommended for > 30 papers)
  Stage 1: the AI reads only the first ~3,000 characters of each PDF
  (title, abstract, introduction). Papers clearly outside scope are
  excluded at this stage without sending the full text — saving tokens
  and cost significantly.
  Stage 2: papers that passed Stage 1 are processed with the full
  text (up to the configured token limit).
  Papers that are excluded in Stage 1 appear with Stage = "title/abstract"
  in the Results tab; those processed fully show Stage = "full-text".

  RESULT CACHING
  When enabled, each successfully processed PDF's result is saved to
  .slr_cache/. On subsequent runs, cached results are loaded instantly
  without an API call — saving cost and time when resuming an interrupted
  run or changing extraction fields on already-processed papers.
  To force reprocessing: disable caching, or delete the .slr_cache folder.

  PARALLEL PROCESSING
  Allows multiple PDFs to be processed simultaneously using threads.
  Faster, but each worker makes independent API calls, so your API
  quota per minute is shared across all workers.
  Recommended: start at 2–3 workers. Increase to 5–8 only if your
  provider plan has a high rate limit (e.g. OpenAI Tier 3+).
  Disable (set to 1) if you see many 429 rate-limit errors.

  MAX WORKERS
  The number of parallel processing threads (1–10).
  Each worker processes one PDF at a time independently.
  Higher = faster throughput, higher instantaneous token rate.

  RATE DELAY
  Seconds of pause between API calls PER WORKER.
  Default: 0.5 seconds. Increase to 2–5 if you hit rate limits.
  At 3 workers with 1.0s delay: up to 3 calls per second maximum.

RESEARCH CRITERIA AND EXTRACTION FIELDS
─────────────────────────────────────────
  Click "Customize Criteria & Fields" to open the editor.
  This editor has four sub-tabs:

  TAB 1 — SCREENING CRITERIA
  Write the rules the AI uses to decide Include / Exclude / Flag
  when reading a full-text PDF. This is typically the same as (or a
  refined version of) your abstract screening criteria.
  Tip: at the full-text stage you can be more specific, e.g. requiring
  specific outcome measures that may not appear in abstracts.

  TAB 2 — EXTRACTION PROMPT
  The instruction prefix given to the AI before it fills the fields.
  Default is suitable for most reviews. Customise if your domain uses
  specialised language the AI should be aware of.

  TAB 3 — EXTRACTION FIELDS
  Define what structured data the AI extracts from each included paper.
  See the Extraction Fields help topic for full field guidance.

  TAB 4 — HELP
  In-editor field-level guidance for the Extraction Fields tab.

STARTING AND STOPPING PROCESSING
──────────────────────────────────
  ▶ START PROCESSING (F5)
  Validates configuration, then begins processing all PDFs in the
  selected folder. Switch to the Monitor tab to watch progress and
  to the Results tab to see decisions as they arrive.
  You do not need to stay on the Setup tab once processing starts.

  ⏹ STOP PROCESSING (F6)
  Sends a stop signal. The current PDF finishes processing, then
  the run halts cleanly. Partial results are saved. You can resume
  by clicking Start again — already-processed PDFs are skipped if
  caching is enabled.

ADVANCED CONFIGURATION
───────────────────────
  Click "Advanced Config" to open additional options:

  MAX TOKENS PER REQUEST
  Maximum tokens sent to the AI per paper (input + output combined).
  Larger = more context for the AI, but slower and more expensive.
  Recommended: 8,000–16,000 for most papers.

  PDF EXTRACTION CHUNK SIZE
  Controls how many characters are extracted from a PDF at a time.
  Increase for very long papers; decrease if you hit token limits.

  MAX RETRIES
  Number of times to retry a failed API call before marking the paper
  as Error. Default: 3. The retry delay doubles each attempt.

  RETRY DELAY BASE
  Initial wait in seconds before the first retry. Doubles with each
  subsequent retry (exponential back-off).

  STAGE 1 CHARACTER LIMIT
  How many characters to send in the first stage of two-stage
  screening. Default: 3,000 (roughly one page of a paper).
  Increase if your papers have very long introductions.

SAVING AND LOADING SETTINGS
────────────────────────────
  Ctrl+S   — saves all current settings to settings.json in the
              application folder. Settings are auto-loaded next launch.

  Save Settings button — same as Ctrl+S, shown in the toolbar.

  Load Settings button — opens a file picker to restore settings
  from a previously saved settings.json. Use this to switch between
  different review projects or share settings with a team member.

  Settings saved include: provider, model, API key, folder paths,
  all processing options, criteria text, and extraction fields.
  Settings NOT saved: current results and processing logs.
"""),
        "monitor": ("""\
Monitor Tab  —  Live Processing Dashboard
══════════════════════════════════════════

OVERVIEW
────────
The Monitor tab is your live window into the processing run. Once you
click Start Processing in the Setup tab, switch here to watch PDFs
being processed in real time. You do not need to stay on the Setup tab.
Processing continues in the background whether or not the Monitor tab
is visible.

KPI CHIP CARDS (TOP ROW)
─────────────────────────
Five coloured cards display the current running totals:

  FILES  (blue card)
  "processed / total" — e.g. "7 / 42"
  Total = number of PDFs found in the selected folder.
  Processed = PDFs for which a decision has been returned (any result
  including Error counts as processed).

  INCLUDE  (green card)
  Count of PDFs where the AI decision is "Likely Include".
  These papers proceed to data extraction (if configured).
  This is your growing pool of papers for synthesis.

  EXCLUDE  (red card)
  Count of PDFs where the AI decision is "Likely Exclude".
  Excluded papers are shown in the Results tab but are not extracted.

  FLAGGED  (amber card)
  Count of PDFs flagged for human review — the AI was uncertain.
  Do not count these as included or excluded until you manually
  check them in the Results tab and override.

  TOKENS  (purple card)
  Total API tokens consumed so far in this processing run.
  This is the sum of input + output tokens for all completed calls.
  Use this to estimate cost: multiply by your provider's per-token rate.
  A typical 200-word abstract uses ~400 tokens (input) + ~150 (output).
  A typical 8-page full-text paper uses ~6,000–15,000 tokens (input).

PROGRESS BAR AND TIMING
────────────────────────
  PROGRESS BAR
  Fills from left to right as papers are processed.
  The percentage label in the centre updates with each completion.

  ELAPSED TIME
  Total wall-clock time since clicking Start Processing.
  Useful for estimating cost per paper (tokens ÷ papers processed).

  ETA (ESTIMATED TIME REMAINING)
  Calculated from the average processing time per paper × remaining count.
  Becomes more accurate after the first 5–10 papers are processed.
  ETA does not account for rate-limit retries.

  CURRENT FILE
  Shows the filename currently being processed by any worker.
  In parallel mode (>1 worker) this shows the most recently started
  file; others are processing simultaneously in background threads.

PROCESSING LOG
──────────────
The log panel records every significant event during the run.
Each line is time-stamped (HH:MM:SS).

  COLOUR CODING
  Cyan              — INFO: startup messages, provider name, model
  Teal/Green        — OK: successful API call, result saved to cache
  Orange            — WARN: retry attempt, slow response, rate limit
  Red               — ERROR: API failure, parse error, PDF unreadable
  Bold bright teal  — INCLUDE decision for a specific paper
  Bold bright red   — EXCLUDE decision for a specific paper
  Yellow            — FLAG decision for a specific paper

  HOW TO DIAGNOSE PROBLEMS
  • Many WARN/RETRY lines → increase Rate Delay in Setup.
  • Many consecutive ERROR lines → check your API key.
  • ERROR + "JSONDecodeError" → model produced non-JSON output; try a
    different (larger) model or simplify your extraction fields.
  • ERROR + "context_length_exceeded" → paper is too long for the
    model's context window; reduce Max Tokens in Advanced Config.
  • ERROR + "insufficient_quota" → you have run out of API credits;
    add billing to your provider account.

  SAVE LOG
  Click "Save Log" to write the complete log to a .txt file in the
  output folder. Useful for debugging or reporting issues.

  CLEAR LOG
  Empties the on-screen log display. Does NOT delete results or cache.
  Useful when restarting after fixing an issue mid-run.

WHAT TO DO WHILE PROCESSING
────────────────────────────
  You can (and should) switch to the Results tab at any time during
  processing to review decisions as they arrive.

  You can return to the Setup tab and change settings, but changes to
  provider/model/criteria do NOT affect the current running job —
  they take effect at the next Start.

  You can use other applications normally — the tool runs in its own
  thread and does not block the UI or other programs.

PERFORMANCE TIPS
─────────────────
  • For 10–50 papers: use 2 workers, 0.5s delay.
  • For 50–200 papers: use 3–5 workers, 1.0s delay. Enable caching.
  • For 200+ papers: enable two-stage screening + caching.
    Use gpt-4o-mini or claude-haiku for Stage 1 (cheap, fast).
  • If the ETA seems very long: check Max Workers and Rate Delay.
    Also consider whether you need all extraction fields, or whether
    a targeted subset would be faster.
  • Cost control: the TOKENS card × your per-token rate gives a live
    running cost estimate. Stop processing if cost exceeds budget.
"""),
        "results": ("""\
Results Tab  —  Review, Verify and Export Results
══════════════════════════════════════════════════

OVERVIEW
────────
The Results tab is your human verification and export centre.
All screening decisions from full-text PDF processing appear here,
with colour-coded rows and full access to the AI's reasoning and
all extracted data. You can review, edit, and export from this tab
at any time — before, during, or after the processing run completes.

FILTER BUTTONS
──────────────
Six styled filter buttons above the results table:

  All                    — show every record (default view)
  Likely Include         — green rows — AI decided this paper is in scope
  Likely Exclude         — red rows — AI decided this paper is out of scope
  Flag for Review        — amber rows — AI uncertain, human check needed
  Flag for Human Review  — blue rows — two-stage: passed Stage 1 but
                           Stage 2 decision requires human review
  Error                  — grey rows — processing failed for this paper

  The active filter button appears with a sunken / highlighted border.
  Filters are remembered while you are on the tab.
  Click "All" to reset.

LIVE SEARCH BOX
────────────────
  Type any text in the Search box above the table to filter rows
  in real time. The search is case-insensitive and checks across:
    • Filename (the PDF file name)
    • Decision text
    • Reasoning excerpt (first 120 characters)

  Filters and search COMBINE — e.g. filter to "Likely Include" then
  search "diabetes" to find only included papers mentioning diabetes.

  Click the ✕ button (or clear the text) to reset the search.

RESULTS TABLE COLUMNS
──────────────────────
  #              Record number in the current filtered/searched view
  File           PDF filename (without directory path)
  Decision       AI screening decision for this paper
  Stage          "title/abstract" (Stage 1 only) or "full-text" (Stage 2)
  Reasoning      First 120 characters of the AI's full rationale
  Tokens         API tokens used for this specific paper
  Time (s)       Wall-clock seconds taken to process this paper

  Click any column header to sort by that column.
  Click again to reverse the sort order.

  Row colours:
    Green          — Likely Include
    Red            — Likely Exclude
    Amber          — Flag for Review
    Blue           — Flag for Human Review
    Light grey     — Error

DETAIL POPUP  (double-click any row, or press Enter)
────────────────────────────────────────────────────
The detail popup opens a resizable window with up to 3 tabs:

  TAB 1 — SCREENING
  ──────────────────
  Shows the full AI reasoning for the screening decision:
    • Paper filename
    • Decision (Include / Exclude / Flag)
    • Stage at which the decision was made
    • Confidence score (0–100%)
    • Full rationale text (the complete AI explanation)
    • Processing time and token count

  HUMAN NOTES AREA
  A free-text box where you can type your own reviewer notes for
  this paper. Notes are saved to the results and included in exports.
  Use this to record why you agreed or disagreed with the AI decision,
  or to note a manual override reason.

  TAB 2 — EXTRACTION & VERIFICATION
  ───────────────────────────────────
  Available only for papers that were successfully extracted (i.e.
  not excluded in Stage 1, and extraction fields were configured).

  LEFT PANEL — FULL PAPER TEXT (dark viewer)
  The full text extracted from the PDF is shown in a scrollable dark-
  background viewer. Use this to manually look up any value or quote.
  The "Copy Paper Text" button copies the entire text to clipboard.
  Tip: open the paper in your PDF reader side-by-side with the popup
  for the fastest verification workflow.

  RIGHT PANEL — EXTRACTED FIELDS
  For each extraction field you defined, you will see:
    Field label         — the field name (e.g. "Sample Size")
    Quote (grey italic) — the verbatim sentence the AI found as evidence
    Value box           — the extracted value (editable)

  EDITING EXTRACTED VALUES
  Click any value box and type to correct or supplement the AI value.
  Press Tab to move to the next field.
  VALUES ARE NOT AUTO-SAVED — click "Save Changes" to commit.
  Pressing Save Changes updates the in-memory result; it is included
  in all subsequent exports.

  If the quote is blank or clearly wrong, use the left panel to find
  the correct sentence in the paper text, then correct the value.
  If a field says "Not reported" — the AI could not find supporting
  text. Always verify this against the actual paper before accepting.

  TAB 3 — FULL PAPER TEXT
  ─────────────────────────
  A standalone scrollable dark-mode viewer of the full extracted PDF
  text. Use this when you want to read the paper without the
  Extraction panel taking up space.
  The "Copy Paper Text" button is also available here.

PRISMA SUMMARY LINE
────────────────────
Located above the Export button, this line shows the current totals
across ALL records in the Results tab (ignoring any active filter):
  "Total: N  |  Include: N  |  Exclude: N  |  Flagged: N"
This updates live as processing adds results. Use these numbers to
fill in your PRISMA flow diagram.

HUMAN OVERRIDE IN RESULTS TAB
───────────────────────────────
  Right-click any row → Override → [decision option]
  This changes the decision for that paper and updates the row colour.
  The original AI decision is preserved in the Screening tab popup.

EXPORT
──────
  Export Visible Rows to CSV
  Exports exactly the rows currently shown (respects active filter
  AND search box). Useful for exporting only your Include list, or
  only Flagged records for a second reviewer.

  Columns exported:
    File, Decision, Stage, Confidence, Reasoning (full),
    Tokens, Processing Time, Reviewer Notes,
    + one column per extraction field (if extraction was configured)
    + one _quote column per extraction field (verbatim evidence)

  FULL EXCEL EXPORT (with PRISMA summary)
  Available from the Ingestion tab Export → Excel button.
  Produces a multi-sheet workbook with colour-coded rows and the
  PRISMA stage count summary sheet.
"""),
        "providers": ("""\
AI Providers  —  Setup and Step-by-Step Registration Guide
═══════════════════════════════════════════════════════════

OVERVIEW
────────
This tool supports 7 AI providers. You select one in the Setup tab,
enter your API key, choose a model, and test the connection.

Cloud providers require internet. Ollama runs fully locally — free,
no internet needed after the model download, and nothing leaves your PC.

QUICK CHOICE GUIDE
────────────────────
  No budget at all          → Ollama (local, completely free)
  Cheapest cloud option     → DeepSeek or Google Gemini
  Most trusted / verified   → OpenAI (gpt-4o-mini)
  Best scientific reasoning → Anthropic Claude
  EU data compliance        → Mistral AI
  Already use Google        → Google Gemini

OLLAMA  (LOCAL — COMPLETELY FREE — RECOMMENDED FOR PRIVACY)
────────────────────────────────────────────────────────────
  Nothing is sent to any external server. All processing runs on
  your computer. No API key, no account, no charges ever.
  Base URL to enter in Setup tab: http://localhost:11434

  HOW TO SET UP (step by step)
  Step 1: Download from https://ollama.com/download
          Click "Download for Windows" (or macOS / Linux).
  Step 2: Run the installer and follow the prompts.
          Ollama installs as a background service.
  Step 3: Open Command Prompt (Windows + R → type cmd → Enter).
          Type: ollama pull llama3.2
          Press Enter and wait (downloads ~2 GB).
  Step 4: Leave Command Prompt open and return to this tool.
          In Setup tab: Provider = Ollama (Local),
          Base URL = http://localhost:11434, Model = llama3.2
  Step 5: Click Test Connection. Should show a green dot.

  RECOMMENDED MODELS  (run in Command Prompt)
    ollama pull llama3.2           # ~2GB  — fast, good general purpose
    ollama pull qwen2.5:14b        # ~9GB  — excellent instruction-following
    ollama pull phi4               # ~9GB  — very strong for reasoning
    ollama pull mistral            # ~4GB  — good balance

  HARDWARE REQUIREMENTS
  8 GB RAM   : runs 7B parameter models (llama3.2, mistral)
  16 GB RAM  : runs 13B models (qwen2.5:14b, phi4)
  24+ GB RAM : runs 34B+ models for highest accuracy
  CPU only   : works but slow (minutes per paper instead of seconds)
  GPU/VRAM   : same sizes as RAM above; GPU is 5–10× faster than CPU

  TIPS
  • Set Max Workers to 1 for Ollama — local models cannot parallelise.
  • Accuracy is somewhat lower than GPT-4o for complex extraction.
  • Best for: sensitive literature, no-budget projects, privacy-first.

OPENAI  (INDUSTRY STANDARD)
────────────────────────────
  Models: gpt-4o-mini (recommended), gpt-4o, gpt-4-turbo,
          o1-mini, o3-mini, gpt-4.1, gpt-4.1-mini
  Base URL: leave blank

  HOW TO GET AN API KEY (step by step)
  Step 1: Go to https://platform.openai.com
          Click Sign Up if new, or Log In (same account as ChatGPT).
  Step 2: After logging in, click your profile icon (top right)
          → API keys in the left sidebar.
  Step 3: Click + Create new secret key.
          Give it a name (e.g. "SLR Project") and click Create.
  Step 4: COPY THE KEY IMMEDIATELY — it starts with sk-
          You cannot view it again after closing the dialog.
          Paste it into the Setup tab API Key field.
  Step 5: Add a payment method if prompted:
          Go to Billing → Add payment method.
          $5–10 credit is enough to screen hundreds of papers.

  RECOMMENDED MODELS
  gpt-4o-mini  — fast, very cheap, accurate; best for large corpora.
  gpt-4o       — most accurate for complex extraction tasks.
  o3-mini      — reasoning model; best for ambiguous criteria.

  TIPS
  • Monitor usage at platform.openai.com/usage to track cost.
  • New accounts get a small free credit to try the service.
  • Rate limits increase automatically as you use the service.

ANTHROPIC CLAUDE  (EXCELLENT FOR SCIENTIFIC TEXT)
──────────────────────────────────────────────────
  Models: claude-3-5-haiku-20241022 (recommended), claude-3-5-sonnet,
          claude-opus-4-5
  Base URL: leave blank

  HOW TO GET AN API KEY
  Step 1: Go to https://console.anthropic.com
          Click Sign Up and create an account.
  Step 2: After logging in, click API Keys in the left sidebar.
  Step 3: Click Create Key, give it a name, click Create.
  Step 4: Copy the key (starts with sk-ant-). Store it safely.
  Step 5: Go to Billing → Add payment method if you need more usage.

  RECOMMENDED MODELS
  claude-3-5-haiku-20241022   — fastest Claude; cheap; very accurate.
  claude-3-5-sonnet-20241022  — best balance of quality and speed.
  claude-opus-4-5             — highest capability for complex papers.

  TIPS
  • Claude follows precise instructions very reliably — ideal for
    complex PICO criteria with many conditions.
  • No free tier for API access; billing must be configured first.

DEEPSEEK  (MOST AFFORDABLE CLOUD OPTION)
─────────────────────────────────────────
  Models: deepseek-chat (recommended), deepseek-reasoner
  Base URL: leave blank (auto-set to https://api.deepseek.com/v1)

  HOW TO GET AN API KEY
  Step 1: Go to https://platform.deepseek.com
          Click Sign Up and create a free account.
  Step 2: After logging in, click your profile → API Keys.
  Step 3: Click Create new API key, name it, click Create.
  Step 4: Copy the key (starts with sk-). Paste into Setup tab.
  Step 5: Add credit at Billing if needed (starts very affordable).

  NOTES
  DeepSeek is ~10–20× cheaper than gpt-4o for comparable quality.
  deepseek-reasoner uses chain-of-thought reasoning for complex cases.
  Data is processed on servers in China — use Ollama if privacy matters.

GOOGLE GEMINI  (GENEROUS FREE TIER)
─────────────────────────────────────
  Models: gemini-2.0-flash (recommended), gemini-1.5-pro (1M context),
          gemini-2.0-flash-lite
  Base URL: leave blank

  HOW TO GET AN API KEY
  Step 1: Go to https://aistudio.google.com
          Sign in with your Google account.
  Step 2: Click Get API Key → Create API key.
  Step 3: Copy the key and paste it into the Setup tab.
  No billing required for free-tier usage.

  NOTES
  Free tier: 15 requests per minute on Gemini Flash. Reduce workers
  to 1 to stay under this limit on a free account.
  gemini-1.5-pro: 1 million token context — ideal for very long docs.

MISTRAL AI  (EU DATA COMPLIANCE)
──────────────────────────────────
  Models: mistral-small-latest (recommended), mistral-large-latest,
          open-mistral-7b, open-mixtral-8x7b
  Base URL: leave blank

  HOW TO GET AN API KEY
  Step 1: Go to https://console.mistral.ai
          Sign up with your email.
  Step 2: Go to API Keys → Create new key.
  Step 3: Copy the key and paste it into the Setup tab.

  NOTES
  Mistral servers are in the EU — good choice for GDPR compliance.
  Strong multilingual capability for non-English literature.

CUSTOM ENDPOINT
───────────────
  For any OpenAI-compatible server: LM Studio, vLLM, Tabby, etc.
  Set Base URL to your server's address:
    LM Studio:  http://localhost:1234/v1
    vLLM:       http://your-server:8000/v1
  Set API Key to whatever your server expects (often "none" or leave blank).
  Set Model to the model name as your server labels it.

COST COMPARISON  (approximate, subject to change)
────────────────────────────────────────────────────
  Provider       Model                  Input / 1K tokens
  Ollama         any local model        $0.00  (free)
  Google Gemini  gemini-2.0-flash       $0.000075
  DeepSeek       deepseek-chat          $0.00014
  OpenAI         gpt-4o-mini            $0.00015
  Mistral        mistral-small          $0.0002
  Anthropic      claude-3-5-haiku       $0.00025
  OpenAI         gpt-4o                 $0.0025
  Anthropic      claude-3-5-sonnet      $0.003

  TYPICAL COST ESTIMATES
  1,000 abstracts screened (gpt-4o-mini)   ≈ $0.09  (nine cents)
  200 full-text PDFs extracted (gpt-4o-mini) ≈ $0.33 (thirty-three cents)
  Full review: 3,000 abstracts + 150 PDFs   ≈ $0.50–$1.00
  (Varies with paper length, model, field count.)

  COST-SAVING TIPS
  1. Always enable caching — avoids re-charging for completed files.
  2. Test with 5–10 papers first to confirm settings are correct.
  3. Use gpt-4o-mini or claude-haiku for abstract screening.
  4. Use a stronger model only for final full-text extraction.
  5. Start with a small budget top-up ($5–10) until you know costs.
"""),
        "criteria": ("""\
Screening Criteria  —  Writing Effective Inclusion / Exclusion Rules
════════════════════════════════════════════════════════════════════

OVERVIEW
────────
Screening criteria are the rules the AI uses to decide whether each
paper should be Included, Excluded, or Flagged for Human Review.
The quality of your criteria directly determines the quality of the
AI's screening decisions. Specific, clear criteria produce consistent,
accurate results. Vague criteria produce more Flag decisions and
require more human review.

SUPPORTED FRAMEWORKS
─────────────────────
  PICO  — Population · Intervention · Comparison · Outcome
          (Standard for clinical and health sciences reviews)

  SPIDER — Sample · Phenomenon of Interest · Design · Evaluation · Research type
           (Better suited for qualitative and mixed-methods research)

  Free text — Plain English inclusion/exclusion rules (any domain)

Where to enter criteria:
  Abstract screening  → Ingestion tab → Criteria text box (right panel)
  Full-text screening → Setup tab → Customize Criteria & Fields
                        → Screening Criteria tab

EXAMPLE: PICO FORMAT (Clinical)
─────────────────────────────────
  INCLUSION CRITERIA:
  Population:
    - Adults aged 18 years or older
    - Diagnosed with Type 2 Diabetes Mellitus (T2DM)
    - Community-dwelling (not institutionalised)

  Intervention:
    - Dietary interventions (low-carbohydrate, Mediterranean diet,
      caloric restriction, or other named dietary patterns)
    - Physical activity programs (structured exercise, lifestyle activity)
    - Combined diet + exercise interventions

  Comparison:
    - Usual care, standard treatment, or waitlist control
    - Alternative dietary pattern or exercise comparator

  Outcomes (at least one required):
    - HbA1c reduction (primary)
    - Fasting blood glucose
    - Body weight or BMI
    - Quality of life (any validated scale)

  Study Design:
    - Randomised Controlled Trials (RCTs)
    - Quasi-experimental studies
    - Prospective cohort studies
    - Systematic reviews and meta-analyses

  Other:
    - English language
    - Published January 2015 – December 2024
    - Peer-reviewed journals only (not conference abstracts)
    - Minimum follow-up: 12 weeks
    - Minimum N: 30 participants

  EXCLUSION CRITERIA:
    - Animal or in-vitro studies
    - Type 1 diabetes or gestational diabetes only
    - No glycaemic or weight outcome reported
    - Pharmacological interventions only (no dietary/lifestyle component)
    - Conference abstracts without full-text availability
    - Duplicate publications, editorials, commentaries, letters
    - Studies with < 30 participants
    - Follow-up < 12 weeks

EXAMPLE: PICO FORMAT (Non-clinical)
──────────────────────────────────────
  INCLUSION CRITERIA:
  Population:    University students in higher education settings
  Intervention:  Peer-tutoring programs or collaborative learning
  Comparison:    Traditional lecture-based instruction or no tutoring
  Outcome:       Academic achievement, engagement, or retention rates
  Design:        Experimental, quasi-experimental, or mixed methods
  Language:      English
  Date:          2010–2025

  EXCLUSION CRITERIA:
    - K-12 (primary/secondary school) only
    - Online-only interventions without documented outcomes
    - Studies not reporting quantitative or qualitative outcome
    - Dissertations, grey literature, and unpublished studies

EXAMPLE: SPIDER FORMAT (Qualitative)
──────────────────────────────────────
  Sample (S):
    - Nurses, midwives, or allied health professionals
    - Working in acute hospital settings (any country)

  Phenomenon of Interest (PI):
    - Experiences of workplace burnout or moral distress
    - Coping strategies and resilience practices

  Design (D):
    - Qualitative (interviews, focus groups, ethnography)
    - Mixed methods (qualitative component extractable)

  Evaluation (E):
    - Thematic or framework analysis of professional experience
    - Perceived causes and consequences of burnout

  Research type (R):
    - Qualitative and mixed-methods studies
    - Published in peer-reviewed journals, English, 2015–2025

EXAMPLE: FREE-TEXT FORMAT (Technology)
────────────────────────────────────────
  Include papers that:
    1. Describe or evaluate machine learning or deep learning models
       for medical image analysis (radiology, pathology, or ophthalmology).
    2. Report performance metrics (AUC, sensitivity, specificity, accuracy).
    3. Use human-annotated datasets as ground truth.
    4. Include at least 500 images in training or evaluation.

  Exclude papers that:
    1. Focus on natural language processing (NLP) without image analysis.
    2. Are review or survey papers without novel model evaluation.
    3. Report only qualitative or descriptive results.
    4. Use proprietary non-replicable datasets without access details.
    5. Were published before 2018 (pre-deep learning clinical adoption).

TIPS FOR WRITING EFFECTIVE CRITERIA
─────────────────────────────────────
  1. BE SPECIFIC
     Vague: "studies about diabetes"
     Better: "RCTs evaluating dietary interventions in adults with T2DM
              reporting HbA1c or fasting blood glucose outcomes"

  2. INCLUDE BOTH INCLUSIONS AND EXCLUSIONS
     The AI considers both. Listing only inclusions leads to more
     Flag decisions because boundary cases are not handled.

  3. LIST STUDY DESIGNS EXPLICITLY
     Specify which study designs qualify: RCTs, cohort, cross-sectional,
     qualitative, mixed-methods, systematic reviews. This alone accounts
     for many exclusions.

  4. SET DATE AND LANGUAGE LIMITS EXPLICITLY
     "Published 2015–2025, English language only" is a criterion the
     AI can apply reliably at the abstract stage.

  5. DISTINGUISH ABSTRACT VS FULL-TEXT CRITERIA
     Abstract screening: criteria that can be assessed from title +
     abstract alone (study design, population, broad intervention type).
     Full-text criteria: criteria requiring detailed reading (specific
     outcome measures, statistical methods, quality thresholds).
     Enter the appropriate version in the appropriate tab.

  6. USE NUMBERED LISTS
     The AI parses numbered or bulleted lists more reliably than
     long continuous paragraphs.

  7. HANDLE AMBIGUITY EXPLICITLY
     E.g.: "If the abstract does not specify patient age, Flag for Review."
     This reduces incorrect Excludes on ambiguous records.

  8. SPECIFY WHAT TO DO WITH UNCERTAIN RECORDS
     E.g.: "When in doubt, Flag for Human Review rather than Exclude."
     The AI defaults to this but explicit instruction reinforces it.

  9. AVOID DOUBLE NEGATIVES
     Instead of "Do not include studies that do not report outcomes,"
     write "Only include studies that report quantitative outcomes."

  10. UPDATE CRITERIA ITERATIVELY
     After the first 20–30 papers, review the Flag decisions. If the AI
     is consistently wrong in one direction, refine the criteria and
     re-screen the flagged records.
"""),
        "extraction": ("""\
Extraction Fields  —  Defining What Data to Extract from Papers
══════════════════════════════════════════════════════════════════

OVERVIEW
────────
Extraction fields define the structured data the AI collects from
each included paper during full-text processing. Think of these as
the columns in your data extraction table — the same fields you would
fill in manually when doing a traditional systematic review.

The AI extracts each field and provides a verbatim quote from the
paper as evidence. You can edit any value in the Results tab.

ACCESSING THE FIELD EDITOR
──────────────────────────
  Setup tab → Customize Criteria & Fields → Extraction Fields tab

  The editor shows a table of fields with Name and Description columns.
  Add, remove, and reorder fields as needed.
  Click "Save & Close" to apply your changes.

DOMAIN PRESETS
──────────────
Click a preset button to load a domain-specific starting field set.
You can then add, remove, or rename fields from the preset.

  GENERAL (default for any domain)
  Fields: study_title, authors, year, journal, study_design,
          country, sample_size, population_description,
          main_findings, limitations, conclusions, funding_source

  CLINICAL / HEALTH SCIENCES
  Fields: population, inclusion_criteria, exclusion_criteria,
          intervention, comparator, primary_outcome, secondary_outcomes,
          follow_up_duration, sample_size, randomisation_method,
          blinding, allocation_concealment, attrition_rate,
          effect_size, confidence_interval, p_value,
          risk_of_bias, limitations, conclusions

  EDUCATION AND PEDAGOGY
  Fields: educational_level, institution_type, country,
          participant_count, intervention_type, intervention_duration,
          control_condition, outcome_measure, assessment_method,
          data_collection_method, effect_size, limitations, conclusions

  ENVIRONMENTAL SCIENCE
  Fields: study_location, ecosystem_type, geographic_scale,
          species_studied, environmental_variables, methodology,
          data_collection_period, sample_size, statistical_methods,
          key_findings, conservation_implications, limitations

  TECHNOLOGY AND COMPUTING
  Fields: technology_type, application_domain, dataset_name,
          dataset_size, model_architecture, evaluation_metrics,
          reported_performance, baseline_comparison,
          implementation_language, open_source_link,
          limitations, future_work

  SOCIAL SCIENCES AND HUMANITIES
  Fields: theoretical_framework, research_paradigm, methodology,
          data_collection_method, participant_count,
          population_description, country, analysis_approach,
          key_themes, policy_implications, limitations, conclusions

CUSTOM FIELDS
─────────────
  Click "Add Field" to append a new row to the table.
  Enter the field name — use descriptive, short names.
  The field description is shown to the AI as guidance; be specific.
  Click the row's "Remove" button to delete it.

  FIELD NAMING CONVENTIONS
  Use snake_case (lowercase_with_underscores) for field names.
  Avoid spaces or special characters.
  Examples:
    Good:  sample_size, primary_outcome, risk_of_bias, follow_up_weeks
    Avoid: Sample Size, primary-outcome, riskOfBias, Follow Up (Weeks)

  FIELD DESCRIPTION TIPS
  The description is the instruction the AI receives for this field.
  Be specific about format, units, and what to do if not reported.
  Examples:
    Field: sample_size
    Desc:  "Total number of participants enrolled in the study.
            Report the final analysed N, not the recruited N.
            If not reported, write Not reported."

    Field: follow_up_duration
    Desc:  "Duration of follow-up from baseline to final assessment.
            Include units (days/weeks/months/years).
            E.g.: 12 weeks, 6 months, 2 years."

    Field: risk_of_bias
    Desc:  "Overall risk of bias assessment for the study.
            Classify as: Low / Moderate / High / Unclear.
            Base on randomisation, allocation, blinding, attrition."

QUOTE-THEN-ANSWER  —  HOW IT WORKS
────────────────────────────────────
For every extraction field you define, the AI automatically produces
a paired output:

  1. [field_name]_quote — A verbatim sentence copied from the paper
                          that supports the extracted value.
  2. [field_name]        — The actual extracted value derived from
                          that quote.

Example for field "sample_size":
  sample_size_quote:  "A total of 124 participants were randomised,
                       62 to each group."
  sample_size:        "124"

WHY QUOTES MATTER
  • They let you verify every extraction against the source in seconds.
  • They catch hallucination: if the AI cannot find a quote, it must
    write "Not reported" — not invent a value.
  • In the Results → Detail → Extraction tab, you see both the quote
    (in grey italic) and the value (editable) side by side.
  • The quote is included in Excel exports alongside each field value.

WHAT "NOT REPORTED" MEANS
  When a field value is "Not reported", it means the AI could not
  find a verbatim sentence in the paper text that supports a value.
  This may mean:
    (a) The paper genuinely does not report that item — record it
        as "Not reported" in your data table; this is valid data.
    (b) The text was truncated during extraction — check the Full
        Paper Text tab to see if the relevant section was captured.
    (c) The information appears in a table or figure that was not
        extracted as text — check the original PDF directly.

BEST PRACTICES
──────────────
  • Limit to 10–15 fields for best accuracy. More fields = longer
    prompts = higher cost and potential for accuracy drop.
  • The most important fields should come first — the AI gives them
    more attention when context is limited.
  • Add a "limitations" field — researchers consistently find that AI
    captures limitations more thoroughly than manual extraction.
  • After your first few papers, check the Extraction tab in Results
    and adjust descriptions for any field that is being misinterpreted.
  • Use the General preset as a base, then add domain-specific fields
    rather than building from scratch.
"""),
        "antihalluc": ("""\
Anti-Hallucination System  —  How the Tool Prevents AI Fabrication
══════════════════════════════════════════════════════════════════

WHY THIS MATTERS
────────────────
Large language models (LLMs) can produce "hallucinations" — plausible-
sounding but factually incorrect outputs. In systematic reviews, a
fabricated sample size, incorrect effect size, or invented citation
can undermine the entire evidence synthesis and mislead clinical or
policy decisions.

This tool uses FIVE LAYERS of protection to minimise hallucination.
None of them are perfect individually — together they make AI-assisted
extraction reliable enough for academic use when combined with human
verification.

LAYER 1 — QUOTE-THEN-ANSWER PAIRING
─────────────────────────────────────
This is the most important safeguard.

For every extraction field, the AI is required to:
  Step 1: Find a verbatim sentence in the paper that supports the value.
  Step 2: Copy that sentence exactly as the "quote" output.
  Step 3: Derive the value solely from that quote.

If no supporting sentence can be found, the value MUST be "Not reported".
The AI cannot invent a value without a corresponding quote.

EXAMPLE  (field: sample_size)
  Hallucination-prone (without quotes):
    sample_size: "87"  ← AI may confuse values from multiple tables

  With Quote-Then-Answer:
    sample_size_quote: "A total of 87 patients were enrolled between
                        March 2019 and November 2021."
    sample_size: "87"

  Now you can verify it in 3 seconds: search for "87 patients" in the
  Full Paper Text tab or the original PDF.

HOW TO VERIFY
  In the Results tab, double-click a paper → Extraction tab.
  Each field shows its quote in grey italic above the value box.
  Press Ctrl+F in the paper text viewer to find the quote in context.

LAYER 2 — INSTRUCTOR STRUCTURED OUTPUTS
─────────────────────────────────────────
The 'instructor' library wraps every API call with strict JSON schema
enforcement. This means:
  • The AI's response is parsed against a typed schema before accepted.
  • If the response is malformed JSON, instructor retries automatically
    (up to 3 times with a new API call each time).
  • Fields cannot be omitted, renamed, or given wrong data types.

This prevents the AI from:
  • Skipping difficult fields
  • Returning free text instead of a JSON object
  • Adding extra fields you did not ask for

LAYER 3 — DYNAMIC PYDANTIC SCHEMA
───────────────────────────────────
The extraction schema (a Pydantic model) is generated at runtime
based on your exact list of extraction fields. The AI receives a
schema definition that looks like this for each field:

  sample_size: str  (description: "Total participants enrolled.")
  sample_size_quote: str  (description: "Verbatim supporting sentence.")

The AI cannot add columns to the JSON object. It cannot use a field
name you did not request. The schema is re-generated each time you
change your field list — no manual update required.

LAYER 4 — FALLBACK JSON PARSER
────────────────────────────────
If instructor structured output fails entirely after retries (which
can happen with smaller models or Gemini's non-standard output), the
tool falls back to a robust regex-based JSON extractor that handles:

  • Markdown code fences: ```json { ... } ```
  • Trailing commas in objects/arrays (invalid JSON but common)
  • Single-quoted strings instead of double-quoted
  • Truncated JSON (extracts whatever fields were completed)
  • Nested objects with inconsistent whitespace

This fallback means that even imperfect AI outputs produce usable
partial results rather than complete failures.

LAYER 5 — HUMAN VERIFICATION INTERFACE
────────────────────────────────────────
The final layer is you — the researcher.

The Results → Detail → Extraction tab is designed for efficient
human verification:
  • Full paper text shown on the left (dark background for readability)
  • Each extracted field with its quote on the right (editable)
  • Ctrl+F to search the paper text
  • Click any value box to correct it; Tab to move through fields
  • "Save Changes" commits your corrections to the result record

RECOMMENDED VERIFICATION WORKFLOW
───────────────────────────────────
  1. After processing, filter Results to "Likely Include".
  2. For each included paper, double-click → Extraction tab.
  3. Read the quote for each critical field (sample size, outcomes,
     effect sizes) and verify it matches the full paper text.
  4. Correct any discrepancies in the value box.
  5. Click Save Changes.
  6. Export — your corrections are included in the output.

  For high-stakes reviews (Cochrane, clinical guidelines):
    Have a second reviewer independently check the same fields
    and calculate inter-rater reliability (e.g. Cohen's kappa).

INTERPRETING "NOT REPORTED"
────────────────────────────
When you see "Not reported" in an extracted field:

  CASE A: The paper genuinely does not report this item.
  → Record "Not reported" in your data table. This is valid and
     common — lack of reporting is a known methodological limitation.

  CASE B: The text was truncated.
  → Check the Full Paper Text tab. If the paper text appears cut off,
     the PDF may have been too long for the token limit. Try increasing
     Max Tokens in Advanced Config and reprocessing.

  CASE C: The data is in a table or figure.
  → PDF text extraction converts tables inconsistently. Check the
     original PDF. If critical, manually enter the value in the
     editable value box and note it was manually extracted.

  CASE D: The AI misidentified the section.
  → Search the paper text (Ctrl+F) for keywords related to the field.
     If you find the value, correct the extracted value manually.
"""),
        "shortcuts": ("""\
Keyboard Shortcuts  —  Complete Reference
══════════════════════════════════════════

GLOBAL SHORTCUTS  (work from any tab)
───────────────────────────────────────
  F1              Open this Help tab
  F5              Start full-text processing  (same as ▶ Start button)
  F6              Stop full-text processing   (same as ⏹ Stop button)
  Ctrl + S        Save all settings to settings.json

TAB NAVIGATION
──────────────
  Click a tab label to switch tabs at any time.
  Tab switching does NOT interrupt processing — the run continues
  in the background regardless of which tab is active.

IN THE INGESTION TABLE
───────────────────────
  Double-click row      Open detail popup for that record
  Enter                 Open detail popup for selected record
  Right-click row       Open override context menu:
                          Override → Include / Exclude / Flag
  Click column header   Sort ascending by that column
  Click again           Reverse sort (descending)
  Escape                Close detail popup (if open)

IN THE INGESTION CRITERIA BOX
──────────────────────────────
  Ctrl + A         Select all text in the criteria box
  Ctrl + Z         Undo last edit
  Ctrl + Y         Redo last undone edit
  Tab              Indent selected text (4 spaces)

IN THE RESULTS TABLE
─────────────────────
  Double-click row      Open detail popup for that paper
  Enter                 Open detail popup for selected paper
  Right-click row       Open override context menu
  Click column header   Sort ascending / descending by that column
  Up / Down arrows      Move selection through rows

IN THE DETAIL POPUP  (Extraction & Verification tab)
──────────────────────────────────────────────────────
  Tab              Move between editable field value boxes
  Shift + Tab      Move to previous field value box
  Ctrl + A         Select all text in the focused entry
  Enter            (in a field) — accepts current value, moves to next
  Escape           Close the detail popup

IN THE HELP TAB
────────────────
  Enter (in Find box)   Find next match for the search term
  Up / Down arrows      Navigate topics in the left sidebar
  Enter (in sidebar)    Load the selected topic

SETUP TAB BUTTONS
──────────────────
  F5               Same as clicking ▶ Start Processing
  F6               Same as clicking ⏹ Stop
  Ctrl + S         Save Settings

GENERAL WINDOWS SHORTCUTS  (native, always available)
───────────────────────────────────────────────────────
  Ctrl + C         Copy selected text
  Ctrl + V         Paste from clipboard
  Ctrl + X         Cut selected text
  Ctrl + Z         Undo (in text fields)
  Alt + F4         Close the application
  Alt + Tab        Switch between open applications
"""),
        "trouble": ("""\
Troubleshooting  —  Common Problems and Solutions
══════════════════════════════════════════════════

PROBLEM: "API key invalid" / "Authentication error" / "401 Unauthorized"
──────────────────────────────────────────────────────────────────────────
  Cause:  The API key is incorrect, expired, or lacks model access.
  Fix:
    1. Click "Show" in the Setup tab to reveal and verify the key text.
       Check for leading/trailing spaces (common when copy-pasting).
    2. Go to your provider's console and regenerate the key.
    3. Confirm the key has access to the selected model:
       - OpenAI: platform.openai.com/api-keys
       - Anthropic: console.anthropic.com
       - DeepSeek: platform.deepseek.com
    4. Check "Test Connection" reports a green dot after entering the key.
    5. If using a free trial key, check whether it has expired.

PROBLEM: "Rate limit exceeded" / 429 errors / many WARN lines in log
──────────────────────────────────────────────────────────────────────
  Cause:  You are sending more API requests per minute than your plan
          allows. This is especially common with free-tier accounts.
  Fix:
    1. Increase Rate Delay in Setup → Processing Settings to 2–5 seconds.
    2. Reduce Max Workers to 1 or 2.
    3. Enable Two-Stage Screening — reduces total calls per paper.
    4. Wait a few minutes, then restart (the tool backs off automatically
       with 3 retries at 2s, 4s, 8s delays).
    5. Check your provider's dashboard for your current quota level.
    6. Upgrade your API plan if you need higher throughput.

PROBLEM: Processing stops after a few papers / many ERROR lines
───────────────────────────────────────────────────────────────
  Cause:  API errors, quota exhaustion, or network interruptions.
  Fix:
    1. Check the log colour:
       - Red "insufficient_quota" → add billing to your API account.
       - Red "context_length_exceeded" → reduce Max Tokens in Advanced Config.
       - Red "Connection refused" → for Ollama: verify Ollama is running
         (open a terminal and run: ollama list)
       - Red timeout errors → increase Rate Delay; check internet connection.
    2. Click Stop, fix the underlying issue, then click Start again.
       Already-processed papers will be skipped (if caching is enabled).

PROBLEM: "No PDFs found in this folder"
─────────────────────────────────────────
  Cause:  Wrong folder path, or PDFs in an unexpected state.
  Fix:
    1. Click Browse in the Setup tab to manually select the folder.
    2. Verify the folder contains at least one .pdf file (check in
       Windows Explorer — look for the .pdf extension, not .PDF or .PDF.docx).
    3. Note: the tool searches recursively, including all sub-folders.
       If your PDFs are in sub-folders they should still be found.
    4. Verify you have read permission to the folder (try opening a PDF).

PROBLEM: RIS or BIB file fails to parse
─────────────────────────────────────────
  Cause:  Malformed export, wrong encoding, or unsupported variant.
  Fix:
    1. Open the file in Notepad. Check it starts with "TY  - " (RIS)
       or "@article{" (BibTeX). If not, re-export from the database.
    2. For PubMed: use "Citation Manager" export — NOT "MEDLINE Format".
    3. For Web of Science: export as "Plain Text" and rename to .ris,
       or select "BibTeX" format.
    4. For Scopus: select "RIS" in the export dialog.
    5. Try a different character encoding: save the file as UTF-8
       (in Notepad: File → Save As → Encoding: UTF-8).
    6. If the file has mixed line endings, open in a text editor that
       supports Unix/Windows line endings (such as Notepad++) and
       re-save with consistent line endings.

PROBLEM: CSV parse error / records missing from CSV
─────────────────────────────────────────────────────
  Cause:  Missing required column, wrong delimiter, or encoding issue.
  Fix:
    1. Ensure the CSV has a "title" column (case-insensitive).
    2. Open the CSV in Excel and check:
       - The first row is a header row (column names).
       - The file is comma-delimited (not semicolon or tab).
    3. If exported from Excel: File → Save As → CSV UTF-8.
    4. Columns that are auto-detected: title, abstract, doi, authors,
       year, journal, keywords. Rename to match if yours differ.
    5. Abstracts containing commas: these must be quoted in the CSV.
       Excel handles this automatically when saving as CSV.

PROBLEM: Extracted text is blank, garbled, or cut off
──────────────────────────────────────────────────────
  Cause:  Scanned PDFs, copy-protected PDFs, or very large PDFs.
  Fix:
    1. Open the PDF in your PDF reader and try to copy a paragraph.
       If you cannot copy text, the PDF is image-based (scanned).
       Run OCR: Adobe Acrobat (Enhance Scans), ABBYY FineReader,
       Tesseract (free, open-source), or Google Docs (upload PDF).
    2. If the PDF is copy-protected: check File → Properties in
       Acrobat for Content Copying permission. If disabled, you need
       the document owner to remove protection.
    3. If text is garbled (random characters): the PDF uses a custom
       font encoding. Try opening in a browser (drag to Chrome/Edge)
       and printing to PDF to produce a standard version.
    4. If text is truncated at stage 2: increase Max Tokens in
       Advanced Config. Note: the tool uses pymupdf4llm → pdfplumber
       → PyPDF2 in cascade — if all three fail, an Error is recorded.

PROBLEM: "Extraction tab missing" in detail popup
───────────────────────────────────────────────────
  Cause:  Extraction is only available for papers that were:
          (a) processed in full-text mode (not excluded in Stage 1),
          AND (b) had a successful extraction response from the AI.
  Fix:
    1. Check the Decision column — if "Likely Exclude" at Stage 1,
       the paper was not extracted.
    2. Check the Stage column — "title/abstract" means Stage 1 excluded it.
    3. If the paper was included but extraction is missing: check the log
       for JSONDecodeError for that paper. The extraction failed even
       after retries. Try a larger model or simplify extraction fields.

PROBLEM: Settings not saved / settings reset on next launch
─────────────────────────────────────────────────────────────
  Fix:
    1. Press Ctrl+S or click "Save Settings" before closing.
       Settings auto-save when the app closes normally, but not on crash.
    2. Check if settings.json exists in the same folder as slr_gui.py.
    3. Check write permission for that folder (try creating a test file).
    4. If settings.json is corrupted (can happen on crash mid-save):
       delete settings.json and reconfigure — provides a clean start.

PROBLEM: The window is too small / controls are cut off
─────────────────────────────────────────────────────────
  Fix:
    1. Drag the window edges to resize — the layout is fully responsive.
    2. If using a high-DPI (4K) monitor: right-click slr_gui.py in
       Explorer → Properties → Compatibility → Change high DPI settings
       → Override: Application. Then restart the tool.
    3. Alternatively: running the tool with Python's DPI awareness
       setting in Advanced Config resolves most scaling issues.

PROBLEM: Ollama is selected but "Connection refused" error appears
───────────────────────────────────────────────────────────────────
  Fix:
    1. Open a terminal (Command Prompt or PowerShell) and run:
         ollama list
       If Ollama is running, this shows your installed models.
       If it errors, Ollama is not running — start it from the Start menu.
    2. Verify the Base URL in Setup tab is: http://localhost:11434
       (no trailing slash, no extra text)
    3. Verify the model you selected is installed:
         ollama pull llama3.2
    4. If Ollama is running on a different port, update the Base URL.
    5. Windows Firewall may block localhost connections — temporarily
       disable it to test, then add an exception for Ollama.
"""),
        "faq": ("""\
Frequently Asked Questions
══════════════════════════

Q: I am not a computer scientist. Can I still use this tool?
─────────────────────────────────────────────────────────────
  Yes — absolutely. The tool is designed for researchers with no
  programming background. You need to:
  1. Install Python once (see Key Concepts topic for what Python is).
  2. Run install_dependencies.bat (double-click; it downloads everything).
  3. Choose an AI provider and sign up (step-by-step in AI Providers).
  4. Double-click launch_gui.bat to open the tool.
  Everything after that is point-and-click. No code is ever written.

Q: Is my data safe? Does the AI company read my papers?
────────────────────────────────────────────────────────
  For cloud providers (OpenAI, Anthropic, etc.): your paper text is
  sent to their servers for processing. Most academic and business
  plans state that your data is NOT used to retrain their models.
  Check each provider's privacy policy for authoritative details.

  For maximum privacy: use Ollama (local mode).
  Everything runs on your own computer. Nothing leaves your machine.
  No data is transmitted anywhere.

Q: Will the AI make mistakes? Is it reliable enough?
──────────────────────────────────────────────────────
  Yes, the AI can make mistakes — it is a decision-support tool,
  not a perfect replacer of expert judgment. Research shows modern
  LLMs achieve 80–95% agreement with trained human screeners on
  abstract screening. However, you MUST:
    • Review ALL papers marked Flag for Human Review.
    • Spot-check 5–10% of Exclude decisions.
    • Verify all extracted data against the original papers.
  Use the AI as a fast first pass; then apply your expert judgment.

Q: Does my institution allow AI-assisted systematic reviews?
────────────────────────────────────────────────────────────
  Most universities now have guidance on acceptable AI use in
  research. Key requirements typically include:
    1. Transparency — disclose AI use in your methods section.
    2. Verification — all AI decisions must be human-verified.
    3. Data privacy — use local models (Ollama) for confidential
       or unpublished papers.
  Always check your institution's research ethics policy first.

Q: Can I use papers in languages other than English?
──────────────────────────────────────────────────────
  Yes. Most LLMs support multiple languages. Write your criteria
  in the same language as your papers for best results, or write
  English criteria and note that papers may be in other languages.
  Mistral AI has particularly strong multilingual performance.
  Verification quality may vary by language — always spot-check.

Q: Can a team of reviewers use this tool together?
───────────────────────────────────────────────────
  This is a single-user desktop application. For multi-reviewer
  workflows:
  • Share settings.json to ensure all reviewers use identical criteria.
  • Each reviewer can run the tool separately on their own computer.
  • Compare results using the exported CSV/Excel files.
  • Use inter-rater reliability metrics (e.g., Cohen's kappa) on a
    sample of records before committing to full AI-assisted screening.
  Note: share settings.json only with trusted colleagues — it
  contains your API key.

Q: How do I report AI use in my methods section?
──────────────────────────────────────────────────
  Example text you can adapt:
  "Title and abstract screening was conducted using an AI-assisted
  screening tool powered by [Provider] [Model] (v3.0). Criteria were
  defined a priori based on our PICO framework. All Include and Flag
  decisions were independently verified by [reviewer name(s)].
  Data extraction from included full texts applied a Quote-Then-Answer
  approach; all extracted values were verified against source papers
  by [reviewer name(s)]."
  Also cite the specific model version and access date as a footnote.

Q: How many papers can this tool handle?
─────────────────────────────────────────
  Abstract screening (Ingestion tab): tested with 5,000+ records.
  There is no hard limit — performance depends on your PC's RAM.
  8 GB RAM: comfortably handles 10,000 records in the table.

  Full-text PDF processing: limited by your API tier and rate limits,
  not by the tool itself. With caching and multi-worker processing:
  - 50 papers: ~15–60 minutes depending on model and workers
  - 200 papers: ~2–8 hours (use overnight processing)
  - 500+ papers: use two-stage screening + maximum workers + caching

Q: Is my data sent to the AI provider?
────────────────────────────────────────
  Yes — for all cloud providers (OpenAI, Anthropic, DeepSeek, etc.),
  your paper text and criteria are sent to that provider's API.
  Each provider has a data retention policy; check their websites:
  - OpenAI: platform.openai.com/privacy
  - Anthropic: anthropic.com/privacy

  If confidentiality is required (sensitive documents, embargoed data,
  proprietary research), use Ollama (local mode):
  No data leaves your computer. All processing is on-device.
  The trade-off is lower accuracy and slower processing.

Q: Can I use multiple reference files from different databases?
────────────────────────────────────────────────────────────────
  Yes. In the Ingestion tab, parse each file one at a time. Records
  from each parse are added (accumulated) in the table.
  After loading all files, run Deduplicate once to find cross-database
  duplicates. The tool is designed for this multi-database workflow.

  Tip: note how many records each database contributes (shown after
  each Parse) so you can accurately report per-database counts in
  your PRISMA flow diagram.

Q: What happens to "Flag for Human Review" decisions?
───────────────────────────────────────────────────────
  Flagged records must be manually reviewed before making a final
  decision. They are NOT automatically included or excluded.

  HOW TO HANDLE THEM:
  1. Filter the table to show only Flag decisions.
  2. Double-click each flagged record to read the full abstract and
     the AI's rationale for uncertainty.
  3. Apply your own judgment: right-click → Override → Include or Exclude.
  4. Never exclude flagged records without reading them manually.
     Systematic reviews have an obligation to include all eligible papers.

  Flag rate: a well-written criteria set produces 5–15% Flag decisions.
  If you see > 30% Flags, your criteria are likely too vague.

Q: Can I run abstract screening and full-text screening with different criteria?
─────────────────────────────────────────────────────────────────────────────────
  Yes — and this is recommended. The criteria are entered separately:
  - Abstract screening criteria → Ingestion tab Criteria box
    (should be based on what can be judged from title + abstract alone)
  - Full-text criteria → Setup tab → Customize Criteria & Fields
    (can be more specific, including outcome measure requirements)

Q: Can I add my own AI models or use a self-hosted LLM?
─────────────────────────────────────────────────────────
  Yes. Use the "Custom Endpoint" provider option.
  Set Base URL to your server's address (must be OpenAI API-compatible).
  Compatible servers: LM Studio, vLLM, Tabby API, Ollama, llama.cpp HTTP.
  Set Model Name to whatever your server calls the model.
  Set API Key to whatever your server expects (often "none" or blank).

Q: How do I cite this tool in my paper?
─────────────────────────────────────────
  Report AI-assisted screening in the Methods section. Example text:

  "Title and abstract screening was conducted using an AI-assisted
  screening tool powered by [Provider name] [Model name] (version 3.0).
  Screening criteria were defined a priori based on the predefined
  PICO framework. All 'Include' and 'Flag for Human Review' decisions
  were independently verified by [reviewer name(s)]. Data extraction
  from included full texts was performed by the AI tool with
  Quote-Then-Answer evidence pairing; all extracted values were
  verified against source papers by [reviewer name(s)]."

  Also cite:
  - The AI model (add a footnote with model version and access date)
  - Relevant reporting guideline (PRISMA 2020, PRISMA-S for searches)

Q: Does the tool replace human reviewers?
──────────────────────────────────────────
  No. The tool is a decision-support system, not a replacement for
  trained reviewers. Cochrane, Campbell Collaboration, and PRISMA
  all require human verification of screening and extraction.

  WHAT THE TOOL REPLACES:
  - Manual reading of thousands of abstracts for obvious exclusions
  - Tedious copy-paste of data from PDFs into Excel
  - Manual cross-database deduplication

  WHAT STILL REQUIRES HUMAN JUDGMENT:
  - Final decisions on all Flagged records
  - Verification of all Include decisions at both stages
  - Quality assessment / risk of bias (Cochrane RoB 2, GRADE, etc.)
  - Interpretation of extracted data
  - Cross-study synthesis and meta-analysis

Q: Why do some extracted values say "Not reported"?
──────────────────────────────────────────────────────
  "Not reported" means the AI could not find a verbatim supporting
  sentence in the extracted paper text. This is the correct response
  — the AI will not invent a value without evidence.

  There are four reasons this might happen:
  1. The paper genuinely does not report that item.
     (Record it as "Not reported" in your data table.)
  2. The item appears in a table or figure that was not captured as
     readable text by the PDF extractor.
  3. The paper text was truncated at the token limit.
  4. The AI misidentified the relevant section.

  Always verify "Not reported" against the original PDF before
  accepting it in your final data table.

Q: Can I share settings and criteria with a co-reviewer?
─────────────────────────────────────────────────────────
  Yes. Use File → Save Settings (or Ctrl+S) to save settings.json.
  Send this file to your co-reviewer. They load it via Load Settings.
  Settings includes: criteria text, extraction fields, provider choice,
  folder paths, and all processing options.
  API keys ARE included in settings.json — share with trusted colleagues
  only, and never commit settings.json to a public version control repository.

Q: Can I resume a partially completed run?
───────────────────────────────────────────
  Yes, if Result Caching is enabled (on by default):
  1. The run stops (you clicked Stop, or an error interrupted it).
  2. Click Start Processing again.
  3. PDFs already in the .slr_cache folder are skipped.
  4. Only unprocessed PDFs are sent to the API.

  If caching is disabled, the run restarts from the beginning.
  To resume a run from a previous session: ensure the Output Folder
  is the same (so the cache is found); click Start.

Q: How do I handle very large PDFs (book chapters, reports)?
──────────────────────────────────────────────────────────────
  Very long documents can exceed the AI model's context window.
  Options:
  1. Increase Max Tokens in Advanced Config (increases cost).
  2. Use a model with a large context window:
     - gemini-1.5-pro: 1 million token context
     - claude-3-5-sonnet: 200K token context
     - gpt-4o: 128K token context
  3. Use Two-Stage Screening: Stage 1 reads only the first 3,000
     characters (introduction). If Stage 1 includes it, Stage 2 reads
     the full text up to the token limit.
  4. For documents > 200 pages: consider extracting only the relevant
     sections (Introduction, Methods, Results) and saving as a new PDF.
"""),

        "about": ("""\
About This Tool
═══════════════

Universal SLR / Scoping Review Automation Tool
Version 3.2.0

AUTHOR
───────
Mo Anisi
LinkedIn: https://www.linkedin.com/in/manisi/

REPOSITORY
───────────
https://github.com/sadeghanisi/SLR/

LICENSE
────────
MIT License — free to use, modify, and distribute.

CITATION
─────────
If you use this tool in your research, please cite it in your
methods section and acknowledge AI-assisted screening.

SUPPORT
────────
• Read the Complete User Guide (COMPLETE_USER_GUIDE.md)
• Open an issue: https://github.com/sadeghanisi/SLR/issues
• Check the Help tab topics for detailed guidance
"""),

        "disclaimer": ("""\
\u26a0  DISCLAIMER — Please Read Before Use
\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

"AS IS" PROVISION
──────────────────
This software is provided "as is," without warranty of any kind,
express or implied. The authors and distributors accept no
responsibility for decisions made based on AI-generated screening
or extraction results.

AI LIMITATIONS
───────────────
This tool assists with — but does not replace — human judgment.
AI models can and do make errors, including incorrect
inclusion/exclusion decisions and inaccurate data extraction.
All AI outputs must be independently verified by qualified
researchers before use in any publication, thesis, clinical
decision, or policy document.

NO ACADEMIC GUARANTEE
──────────────────────
Use of this tool does not ensure compliance with PRISMA, CONSORT,
or any other reporting standard. Researchers remain solely
responsible for the methodological integrity, transparency, and
accuracy of their systematic reviews.

DATA PRIVACY
─────────────
When using cloud-based AI providers (OpenAI, Anthropic, Google,
DeepSeek, or others), your paper content is transmitted to
third-party servers. The authors of this tool make no
representations regarding how those providers store, process, or
use your data. Consult each provider's privacy policy before
processing sensitive or unpublished material.
For confidential data, use the local Ollama option.

COST AND BILLING
─────────────────
API usage fees are charged directly by third-party AI providers.
The authors of this tool have no visibility into, or
responsibility for, charges incurred through your API account.
Monitor your usage and set billing limits with your provider
before running large processing jobs.

INSTITUTIONAL COMPLIANCE
─────────────────────────
It is your responsibility to verify that AI-assisted research
methods comply with your institution's policies, your funding
body's requirements, and the ethical standards of your field.
Disclose AI tool usage in all relevant sections of your output.

NO LIABILITY
─────────────
To the fullest extent permitted by law, the authors, contributors,
and distributors of this tool shall not be liable for any direct,
indirect, incidental, or consequential damages arising from its
use, including but not limited to data loss, incorrect research
conclusions, academic penalties, or financial charges.

───────────────────────────────────────────────────────────────
By using this tool, you acknowledge that you have read,
understood, and accepted these terms.
───────────────────────────────────────────────────────────────
"""),
    }

    def _build_help_tab(self):
        outer = ttk.Frame(self.tab_help)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # ── Left: topic list ───────────────────────────────────────────────
        left = tk.Frame(outer, bg="#DDE5EE", width=210)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)

        tk.Label(left, text="Contents", bg=self._acc, fg="white",
                 font=("Segoe UI", 10, "bold"),
                 padx=12, pady=8).pack(fill=tk.X)

        self._help_listbox = tk.Listbox(
            left, font=("Segoe UI", 9),
            bg="#DDE5EE", fg="#222",
            selectbackground=self._acc, selectforeground="white",
            relief=tk.FLAT, bd=0,
            activestyle="none",
            highlightthickness=0,
        )
        self._help_listbox.pack(fill=tk.BOTH, expand=True, padx=0)

        self._help_topic_keys: list = []
        for label, key in self._HELP_TOPICS:
            indent = "   " if label.startswith("──") else ""
            display = label.lstrip("─ ") if label.startswith("──") else label
            self._help_listbox.insert(tk.END, f"{indent}{display}")
            self._help_topic_keys.append(key)

        self._help_listbox.bind("<<ListboxSelect>>", self._on_help_topic)

        # ── Right: content viewer ──────────────────────────────────────────
        right = ttk.Frame(outer, padding=(0, 0))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        # Top toolbar
        toolbar = tk.Frame(right, bg="#F0F4F8", pady=4)
        toolbar.grid(row=0, column=0, sticky="ew")
        self._help_title_var = tk.StringVar(value="Select a topic from the left panel")
        tk.Label(toolbar, textvariable=self._help_title_var,
                 bg="#F0F4F8", fg=self._acc,
                 font=("Segoe UI", 11, "bold"), anchor=tk.W,
                 padx=14).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Search within help
        srch_frm = tk.Frame(toolbar, bg="#F0F4F8")
        srch_frm.pack(side=tk.RIGHT, padx=10)
        tk.Label(srch_frm, text="Find:", bg="#F0F4F8",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._help_search_var = tk.StringVar()
        srch_ent = ttk.Entry(srch_frm, textvariable=self._help_search_var, width=18)
        srch_ent.pack(side=tk.LEFT, padx=(4, 2))
        srch_ent.bind("<Return>", self._help_find_next)
        ttk.Button(srch_frm, text="Find",
                   command=self._help_find_next).pack(side=tk.LEFT)
        self._help_search_idx = "1.0"

        # Content text widget
        txt_frm = tk.Frame(right)
        txt_frm.grid(row=1, column=0, sticky="nsew")
        txt_frm.columnconfigure(0, weight=1)
        txt_frm.rowconfigure(0, weight=1)

        self._help_text = scrolledtext.ScrolledText(
            txt_frm,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            bg="#FFFFFF",
            fg="#222222",
            padx=20, pady=14,
            state=tk.DISABLED,
            relief=tk.FLAT,
            borderwidth=0,
        )
        self._help_text.grid(row=0, column=0, sticky="nsew")

        # Text tags for styling
        self._help_text.tag_config("h1",   font=("Segoe UI", 13, "bold"),
                                   foreground=self._acc, spacing3=6)
        self._help_text.tag_config("h2",   font=("Segoe UI", 10, "bold"),
                                   foreground="#333", spacing1=8, spacing3=2)
        self._help_text.tag_config("rule", foreground="#BBBBBB")
        self._help_text.tag_config("code", font=("Consolas", 9),
                                   background="#F5F5F5", foreground="#444")
        self._help_text.tag_config("hl",   background="#FFF3A3")
        self._help_text.tag_config("note", foreground="#888",
                                   font=("Segoe UI", 9, "italic"))

        # Show the first topic by default
        self._help_listbox.select_set(0)
        self._help_listbox.event_generate("<<ListboxSelect>>")

    def _on_help_topic(self, _=None):
        sel = self._help_listbox.curselection()
        if not sel:
            return
        key = self._help_topic_keys[sel[0]]
        content = self._HELP_CONTENT.get(key, "")
        label = self._HELP_TOPICS[sel[0]][0].lstrip("─ ")
        self._help_title_var.set(label)
        self._help_search_idx = "1.0"

        self._help_text.config(state=tk.NORMAL)
        self._help_text.delete(1.0, tk.END)

        # Render content with basic formatting
        for line in content.splitlines():
            stripped = line.rstrip()
            if stripped.startswith("═") or stripped.startswith("─"):
                self._help_text.insert(tk.END, stripped + "\n", "rule")
            elif stripped and all(c in "═─" for c in stripped):
                self._help_text.insert(tk.END, stripped + "\n", "rule")
            elif re.match(r'^[A-Z][A-Z \-/&()]+$', stripped) and len(stripped) > 3:
                # ALL-CAPS heading
                self._help_text.insert(tk.END, stripped + "\n", "h2")
            elif stripped.startswith("Q:"):
                self._help_text.insert(tk.END, stripped + "\n", "h2")
            elif stripped.startswith("  •") or stripped.startswith("  ·"):
                self._help_text.insert(tk.END, stripped + "\n")
            else:
                self._help_text.insert(tk.END, stripped + "\n")

        self._help_text.config(state=tk.DISABLED)
        self._help_text.see("1.0")

    def _help_find_next(self, _=None):
        term = self._help_search_var.get().strip()
        if not term:
            return
        self._help_text.tag_remove("hl", "1.0", tk.END)
        idx = self._help_text.search(term, self._help_search_idx,
                                     nocase=True, stopindex=tk.END)
        if not idx:
            # Wrap around
            idx = self._help_text.search(term, "1.0",
                                          nocase=True, stopindex=tk.END)
            if not idx:
                return
        end = f"{idx}+{len(term)}c"
        self._help_text.tag_add("hl", idx, end)
        self._help_text.see(idx)
        self._help_search_idx = end


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    app  = SLRAutomationGUI(root)
    root.resizable(True, True)
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth()  - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()


if __name__ == "__main__":
    main()

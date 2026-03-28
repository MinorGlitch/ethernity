from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tkinter import END, Menu, StringVar, TclError, Tk, filedialog, font as tkfont, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .analysis import batch_entry_from_result, build_batch_report, inspect_pasted_text
from .bootstrap import DND_FILES, TkinterDnD
from .constants import MODE_AUTO, MODE_FALLBACK, MODE_PAYLOADS
from .formatting import frame_type_name, json_text
from .models import InspectionResult
from .scan_sources import (
    _collect_scan_files,
    _payload_text_from_clipboard_image,
    _payload_text_from_scan_paths,
)
from .styles import ThemeController, configure_styles


@dataclass
class SessionState:
    key: str
    title: str
    source_label: str
    source_paths: tuple[str, ...]
    container: ttk.Frame
    info_var: StringVar
    text_widget: ScrolledText
    result: InspectionResult | None = None


class InspectorApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Ethernity Document Inspector")
        self.root.geometry("1700x900")
        self.root.minsize(1100, 640)
        self.theme: ThemeController = configure_styles(root)

        self.mode_var = StringVar(value=MODE_AUTO)
        self.passphrase_var = StringVar()
        self.status_var = StringVar(value="Ready.")
        self.drop_hint_var = StringVar()
        self.active_session_var = StringVar(value="No session")
        self.active_session_meta_var = StringVar()
        self.batch_report_text = "No batch import has been run.\n"
        self.batch_report_json = json_text({"entries": []})
        self._session_counter = 0
        self._sessions: dict[str, SessionState] = {}

        self._build_ui()
        self._new_session()
        self._sync_theme()
        self.root.bind("<FocusIn>", self._on_focus_in, add=True)
        self._schedule_theme_sync()

    # ── UI construction ───────────────────────────────────────

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.mono_font = tkfont.Font(family=self.theme.mono_font_family, size=11)

        # ── Action bar (row 0) ────────────────────────────────
        bar = ttk.Frame(self.root, style="ActionBar.TFrame", padding=(12, 6, 12, 6))
        bar.grid(row=0, column=0, sticky="ew")

        ttk.Label(bar, text="Document Inspector", style="BarTitle.TLabel").pack(
            side="left", padx=(0, 14)
        )
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=(0, 10), pady=1)

        input_frame = ttk.Frame(bar, style="ActionBar.TFrame")
        input_frame.pack(side="left")
        ttk.Label(input_frame, text="Mode", style="ActionBar.TLabel").pack(side="left", padx=(0, 4))
        ttk.Combobox(
            input_frame,
            state="readonly",
            textvariable=self.mode_var,
            values=(MODE_AUTO, MODE_PAYLOADS, MODE_FALLBACK),
            width=9,
        ).pack(side="left", padx=(0, 10))
        ttk.Label(input_frame, text="Passphrase", style="ActionBar.TLabel").pack(
            side="left", padx=(0, 4)
        )
        ttk.Entry(input_frame, textvariable=self.passphrase_var, show="*", width=16).pack(
            side="left"
        )

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10, pady=1)

        import_frame = ttk.Frame(bar, style="ActionBar.TFrame")
        import_frame.pack(side="left")
        ttk.Button(import_frame, text="New", command=self._new_session).pack(
            side="left", padx=(0, 3)
        )
        ttk.Button(
            import_frame, text="Paste", command=self._paste_screenshot_into_new_session
        ).pack(side="left", padx=(0, 3))
        ttk.Button(import_frame, text="Open", command=self._open_scan_files).pack(
            side="left", padx=(0, 3)
        )
        ttk.Button(import_frame, text="Folder", command=self._open_scan_folder).pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10, pady=1)

        ttk.Button(
            bar,
            text="Parse",
            command=self._parse_current_session,
            style="Primary.TButton",
        ).pack(side="left", padx=(0, 3))
        ttk.Button(bar, text="Close", command=self._clear_current_session).pack(side="left")

        self.export_menu_button = ttk.Menubutton(bar, text="Export", style="Toolbar.TMenubutton")
        self.export_menu_button.pack(side="right")
        self.export_menu = Menu(self.export_menu_button, tearoff=False)
        self.export_menu.add_command(label="Report JSON", command=self._export_current_json)
        self.export_menu.add_command(label="Decrypted Files", command=self._export_current_files)
        self.export_menu.add_command(label="Payloads", command=self._export_current_payloads)
        self.export_menu.add_command(label="Fallback Text", command=self._export_current_fallback)
        self.export_menu.add_command(label="Manifest JSON", command=self._export_current_manifest)
        self.export_menu.add_separator()
        self.export_menu.add_command(label="Batch Report", command=self._export_batch_report)
        self.export_menu_button.configure(menu=self.export_menu)
        self.theme.register_menu(self.export_menu)

        # ── Main content (row 1) ──────────────────────────────
        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.grid(row=1, column=0, sticky="nsew", padx=6, pady=(4, 0))

        # Left panel: session notebook (no chrome)
        left = ttk.Frame(main, style="Surface.TFrame", padding=4)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.session_notebook = ttk.Notebook(left)
        self.session_notebook.grid(row=0, column=0, sticky="nsew")
        self.session_notebook.bind("<<NotebookTabChanged>>", self._on_session_changed)
        main.add(left, weight=2)

        # Right panel: consolidated output tabs
        right_shell = ttk.Frame(main, style="Surface.TFrame", padding=4)
        right_shell.columnconfigure(0, weight=1)
        right_shell.rowconfigure(0, weight=1)
        right = ttk.Notebook(right_shell)
        right.grid(row=0, column=0, sticky="nsew")
        main.add(right_shell, weight=3)

        # Tab 1: Overview (Summary + Diagnostics stacked)
        overview_tab = ttk.Frame(right, padding=6, style="NotebookPage.TFrame")
        overview_tab.columnconfigure(0, weight=1)
        overview_tab.rowconfigure(0, weight=3)
        overview_tab.rowconfigure(1, weight=2)
        self.summary_text = self._build_child_text(overview_tab)
        self.summary_text.grid(row=0, column=0, sticky="nsew")
        self.diagnostics_text = self._build_child_text(overview_tab)
        self.diagnostics_text.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        right.add(overview_tab, text="Overview")

        # Tab 2: Frames (tree + detail sub-tabs)
        frames_tab = ttk.Frame(right, padding=6, style="NotebookPage.TFrame")
        frames_tab.columnconfigure(0, weight=1)
        frames_tab.rowconfigure(0, weight=2)
        frames_tab.rowconfigure(1, weight=3)
        self.frame_tree = ttk.Treeview(
            frames_tab,
            columns=("type", "doc_id", "index", "total", "bytes"),
            show="headings",
            selectmode="browse",
        )
        for col, heading, w in (
            ("type", "Type", 130),
            ("doc_id", "doc_id", 150),
            ("index", "Idx", 60),
            ("total", "Total", 60),
            ("bytes", "Bytes", 90),
        ):
            self.frame_tree.heading(col, text=heading)
            self.frame_tree.column(col, width=w, stretch=col == "doc_id")
        self.frame_tree.grid(row=0, column=0, sticky="nsew")
        self.frame_tree.bind("<<TreeviewSelect>>", self._on_frame_selected)

        frame_details = ttk.Notebook(frames_tab)
        frame_details.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.frame_detail_text = self._build_text_tab(frame_details, "Detail")
        self.frame_raw_text = self._build_text_tab(frame_details, "Raw")
        self.frame_cbor_text = self._build_text_tab(frame_details, "CBOR")
        self.frame_payload_text = self._build_text_tab(frame_details, "Payload")
        self.frame_fallback_text = self._build_text_tab(frame_details, "Fallback")
        right.add(frames_tab, text="Frames")

        # Tab 3: Data (Manifest, Files, Payloads, Fallback as sub-tabs)
        data_tab = ttk.Frame(right, padding=6, style="NotebookPage.TFrame")
        data_tab.columnconfigure(0, weight=1)
        data_tab.rowconfigure(0, weight=1)
        data_nb = ttk.Notebook(data_tab)
        data_nb.grid(row=0, column=0, sticky="nsew")

        self.manifest_text_widget = self._build_text_tab(data_nb, "Manifest")

        files_frame = ttk.Frame(data_nb, padding=6, style="NotebookPage.TFrame")
        files_frame.columnconfigure(0, weight=1)
        files_frame.rowconfigure(0, weight=2)
        files_frame.rowconfigure(1, weight=3)
        self.file_tree = ttk.Treeview(
            files_frame,
            columns=("path", "size", "kind"),
            show="headings",
            selectmode="browse",
        )
        for col, heading, w in (
            ("path", "Path", 300),
            ("size", "Size", 80),
            ("kind", "Preview", 100),
        ):
            self.file_tree.heading(col, text=heading)
            self.file_tree.column(col, width=w, stretch=col == "path")
        self.file_tree.grid(row=0, column=0, sticky="nsew")
        self.file_tree.bind("<<TreeviewSelect>>", self._on_file_selected)
        self.file_preview_text = self._build_child_text(files_frame)
        self.file_preview_text.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        data_nb.add(files_frame, text="Files")

        self.payloads_text = self._build_text_tab(data_nb, "Payloads")
        self.fallback_text_widget = self._build_text_tab(data_nb, "Fallback")
        right.add(data_tab, text="Data")

        # Tab 4: Secrets (tree + detail)
        secrets_tab = ttk.Frame(right, padding=6, style="NotebookPage.TFrame")
        secrets_tab.columnconfigure(0, weight=1)
        secrets_tab.rowconfigure(0, weight=2)
        secrets_tab.rowconfigure(1, weight=3)
        self.secret_tree = ttk.Treeview(
            secrets_tab,
            columns=("label", "status"),
            show="headings",
            selectmode="browse",
        )
        self.secret_tree.heading("label", text="Secret")
        self.secret_tree.heading("status", text="Status")
        self.secret_tree.column("label", width=180, stretch=True)
        self.secret_tree.column("status", width=140, stretch=False)
        self.secret_tree.grid(row=0, column=0, sticky="nsew")
        self.secret_tree.bind("<<TreeviewSelect>>", self._on_secret_selected)
        self.secret_detail_text = self._build_child_text(secrets_tab)
        self.secret_detail_text.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        right.add(secrets_tab, text="Secrets")

        # Tab 5: Report (JSON + Batch as sub-tabs)
        report_tab = ttk.Frame(right, padding=6, style="NotebookPage.TFrame")
        report_tab.columnconfigure(0, weight=1)
        report_tab.rowconfigure(0, weight=1)
        report_nb = ttk.Notebook(report_tab)
        report_nb.grid(row=0, column=0, sticky="nsew")
        self.report_json_text = self._build_text_tab(report_nb, "JSON")
        self.batch_text_widget = self._build_text_tab(report_nb, "Batch")
        self.batch_json_text_widget = self._build_text_tab(report_nb, "Batch JSON")
        right.add(report_tab, text="Report")

        self._set_default_outputs()
        self._configure_import_capabilities(left)

        # ── Status bar (row 2) ────────────────────────────────
        status_frame = ttk.Frame(self.root, style="StatusBar.TFrame", padding=(12, 4, 12, 4))
        status_frame.grid(row=2, column=0, sticky="ew")
        status_left = ttk.Frame(status_frame, style="StatusBar.TFrame")
        status_left.pack(side="left")
        ttk.Label(
            status_left,
            textvariable=self.active_session_var,
            style="StatusSession.TLabel",
        ).pack(side="left", padx=(0, 10))
        ttk.Label(
            status_left,
            textvariable=self.active_session_meta_var,
            style="StatusMeta.TLabel",
        ).pack(side="left")
        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            style="StatusBar.TLabel",
        ).pack(side="right")

    def _build_text_tab(self, notebook: ttk.Notebook, title: str) -> ScrolledText:
        frame = ttk.Frame(notebook, padding=6, style="NotebookPage.TFrame")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        widget = self._build_child_text(frame)
        widget.grid(row=0, column=0, sticky="nsew")
        notebook.add(frame, text=title)
        return widget

    def _build_child_text(self, parent) -> ScrolledText:
        widget = ScrolledText(parent, wrap="word", undo=True, font=self.mono_font)
        self.theme.register_text_widget(widget)
        return widget

    # ── Theme synchronisation ─────────────────────────────────

    def _schedule_theme_sync(self) -> None:
        self.root.after(1600, self._theme_sync_tick)

    def _theme_sync_tick(self) -> None:
        if not self.root.winfo_exists():
            return
        self._sync_theme()
        self._schedule_theme_sync()

    def _on_focus_in(self, _event=None) -> None:
        self._sync_theme()

    def _sync_theme(self) -> None:
        self.theme.refresh()
        self.mono_font.configure(family=self.theme.mono_font_family, size=11)

    # ── Text helpers ──────────────────────────────────────────

    def _set_text(self, widget: ScrolledText, text: str, *, editable: bool = False) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", END)
        widget.insert("1.0", text)
        widget.configure(state="normal" if editable else "disabled")

    def _set_default_outputs(self) -> None:
        self._set_text(self.summary_text, "No parsed data yet.\n")
        self._set_text(self.diagnostics_text, "No diagnostics yet.\n")
        self._set_text(self.frame_detail_text, "Select a frame to inspect it.\n")
        self._set_text(self.frame_raw_text, "Select a frame to inspect raw bytes.\n")
        self._set_text(self.frame_cbor_text, "Select a frame to inspect decoded CBOR.\n")
        self._set_text(
            self.frame_payload_text, "Select a frame to inspect normalized payload text.\n"
        )
        self._set_text(self.frame_fallback_text, "Select a frame to inspect fallback text.\n")
        self._set_text(self.manifest_text_widget, "No manifest available.\n")
        self._set_text(self.file_preview_text, "No file previews available.\n")
        self._set_text(self.payloads_text, "No normalized payloads available.\n")
        self._set_text(self.fallback_text_widget, "No fallback text available.\n")
        self._set_text(self.secret_detail_text, "No reconstructed secrets available.\n")
        self._set_text(self.batch_text_widget, self.batch_report_text)
        self._set_text(self.batch_json_text_widget, self.batch_report_json)
        self._set_text(self.report_json_text, "{}\n")
        for tree in (self.frame_tree, self.file_tree, self.secret_tree):
            for item in tree.get_children():
                tree.delete(item)
        self._set_active_session(None)

    # ── Session management ────────────────────────────────────

    def _session_meta_text(self, session: SessionState) -> str:
        source_count = len(session.source_paths)
        if session.result is None:
            if source_count:
                noun = "source" if source_count == 1 else "sources"
                return f"{source_count} {noun} loaded"
            return "manual session"

        result = session.result
        parts = [f"{result.deduped_frame_count} frame(s)"]
        if result.files:
            parts.append(f"{len(result.files)} file(s)")
        if result.recovered_secrets:
            statuses = ", ".join(
                f"{secret.label}: {secret.status}" for secret in result.recovered_secrets
            )
            parts.append(statuses)
        if source_count:
            parts.append(f"{source_count} source(s)")
        return " | ".join(parts)

    def _set_active_session(self, session: SessionState | None) -> None:
        if session is None:
            self.active_session_var.set("No session")
            self.active_session_meta_var.set("")
            return
        self.active_session_var.set(session.title)
        self.active_session_meta_var.set(self._session_meta_text(session))

    def _configure_import_capabilities(self, left_container: ttk.Frame) -> None:
        self.root.bind_all("<Command-Shift-V>", self._paste_screenshot_shortcut, add=True)
        self.root.bind_all("<Control-Shift-V>", self._paste_screenshot_shortcut, add=True)
        self._drop_enabled = self._enable_drop_target(left_container)

    def _current_session(self) -> SessionState | None:
        return self._sessions.get(self.session_notebook.select())

    def _replace_session_text(self, session: SessionState, text: str) -> None:
        session.text_widget.delete("1.0", END)
        session.text_widget.insert("1.0", text)

    def _append_session_text(self, session: SessionState, text: str) -> None:
        existing = session.text_widget.get("1.0", END).strip()
        incoming = text.strip()
        if existing and incoming:
            merged = f"{existing}\n{incoming}\n"
        elif incoming:
            merged = f"{incoming}\n"
        else:
            merged = existing + ("\n" if existing else "")
        self._replace_session_text(session, merged)

    def _merge_session_sources(self, session: SessionState, *sources: str) -> None:
        merged = list(session.source_paths)
        for source in sources:
            if source and source not in merged:
                merged.append(source)
        session.source_paths = tuple(merged)
        if session.source_paths:
            session.info_var.set("\n".join(session.source_paths))
        else:
            session.info_var.set("Manual session")

    def _target_session_for_import(self) -> SessionState:
        return self._current_session() or self._new_session()

    def _new_session(
        self, *, title: str | None = None, source_label: str | None = None
    ) -> SessionState:
        self._session_counter += 1
        tab = ttk.Frame(self.session_notebook, padding=4, style="NotebookPage.TFrame")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        info_var = StringVar(value=source_label or "Manual session")
        text_widget = ScrolledText(tab, wrap="word", undo=True, font=self.mono_font)
        self.theme.register_text_widget(text_widget)
        text_widget.grid(row=0, column=0, sticky="nsew")
        text_widget.bind("<<Paste>>", self._on_text_paste, add=True)
        self._enable_drop_target(text_widget)
        label = title or f"Session {self._session_counter}"
        self.session_notebook.add(tab, text=label)
        session = SessionState(
            key=f"session-{self._session_counter}",
            title=label,
            source_label=source_label or label,
            source_paths=(),
            container=tab,
            info_var=info_var,
            text_widget=text_widget,
        )
        self._sessions[str(tab)] = session
        self.session_notebook.select(tab)
        self._set_active_session(session)
        self.status_var.set(f"Created {label}.")
        return session

    # ── Import ────────────────────────────────────────────────

    def _open_scan_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Open PDFs or QR images",
            filetypes=[
                ("Scan files", "*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"),
                ("PDF files", "*.pdf"),
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"),
                ("All files", "*"),
            ],
        )
        if paths:
            self._import_scan_sources(paths, source_label="selected scan files")

    def _open_scan_folder(self) -> None:
        path = filedialog.askdirectory(title="Open folder of PDFs/images")
        if path:
            self._import_scan_sources([path], source_label="scan folder")

    def _session_title_for_scan_files(
        self, scan_files: Sequence[Path], *, source_label: str
    ) -> str:
        if not scan_files:
            return source_label
        if len(scan_files) == 1:
            return scan_files[0].name
        return f"{scan_files[0].name} +{len(scan_files) - 1} more"

    def _import_scan_sources(self, paths: Sequence[str | Path], *, source_label: str) -> None:
        try:
            scan_files = _collect_scan_files(paths)
        except Exception as exc:
            messagebox.showerror("Import Scan Files", str(exc))
            self.status_var.set(f"Import failed: {exc}")
            return

        try:
            payload_text, warnings = _payload_text_from_scan_paths(scan_files)
        except Exception as exc:
            self.status_var.set(f"Import failed: {exc}")
            batch_entries = [
                batch_entry_from_result(
                    source_label=source_label,
                    source_path=None,
                    result=None,
                    error=exc,
                )
            ]
            self.batch_report_text, self.batch_report_json = build_batch_report(batch_entries)
            self._set_text(self.batch_text_widget, self.batch_report_text)
            self._set_text(self.batch_json_text_widget, self.batch_report_json)
            return

        session = self._target_session_for_import()
        if not session.source_paths and not session.text_widget.get("1.0", END).strip():
            title = self._session_title_for_scan_files(scan_files, source_label=source_label)
            session.title = title
            session.source_label = title
            self.session_notebook.tab(session.container, text=title)
        self._merge_session_sources(session, *(str(scan_file) for scan_file in scan_files))
        self._append_session_text(session, payload_text)
        result = self._inspect_session_text(session)

        batch_entries = [
            batch_entry_from_result(
                source_label=source_label,
                source_path=None,
                result=result,
                error=None,
            )
        ]
        self.batch_report_text, self.batch_report_json = build_batch_report(batch_entries)
        self._set_text(self.batch_text_widget, self.batch_report_text)
        self._set_text(self.batch_json_text_widget, self.batch_report_json)
        self.session_notebook.select(session.container)
        self._display_session(session)

        status = f"Added {len(scan_files)} file(s) to {session.title}."
        if warnings:
            status += f" {len(warnings)} scan warning(s)."
        self.status_var.set(status)

    def _paste_screenshot_into_new_session(self) -> None:
        try:
            payload_result = _payload_text_from_clipboard_image(allow_missing=False)
        except Exception as exc:
            messagebox.showerror("Paste Screenshot", str(exc))
            self.status_var.set(f"Clipboard import failed: {exc}")
            return
        if payload_result is None:
            return
        payload_text, warnings = payload_result
        session = self._target_session_for_import()
        if not session.source_paths and not session.text_widget.get("1.0", END).strip():
            session.title = "Clipboard"
            session.source_label = session.title
            self.session_notebook.tab(session.container, text=session.title)
        self._merge_session_sources(session, "clipboard image")
        self._append_session_text(session, payload_text)
        result = self._inspect_session_text(session)
        status = f"Added clipboard image to {session.title}."
        if warnings:
            status += f" {len(warnings)} warning(s)."
        self.status_var.set(status)
        entry = batch_entry_from_result(
            source_label=session.title,
            source_path=None,
            result=result,
            error=None,
        )
        self.batch_report_text, self.batch_report_json = build_batch_report([entry])
        self._set_text(self.batch_text_widget, self.batch_report_text)
        self._set_text(self.batch_json_text_widget, self.batch_report_json)

    def _paste_screenshot_shortcut(self, _event=None) -> str:
        self._paste_screenshot_into_new_session()
        return "break"

    def _on_text_paste(self, _event=None):
        try:
            payload_result = _payload_text_from_clipboard_image(allow_missing=True)
        except Exception as exc:
            self.status_var.set(f"Clipboard image decode failed: {exc}")
            return "break"
        if payload_result is None:
            return None
        payload_text, warnings = payload_result
        session = self._current_session() or self._new_session()
        self._merge_session_sources(session, "clipboard image")
        self._append_session_text(session, payload_text)
        self._inspect_session_text(session)
        status = f"Added clipboard image to {session.title}."
        if warnings:
            status += f" {len(warnings)} warning(s)."
        self.status_var.set(status)
        return "break"

    # ── Drag-and-drop ─────────────────────────────────────────

    def _enable_drop_target(self, widget) -> bool:
        if DND_FILES is None:
            return False
        if not hasattr(widget, "drop_target_register") or not hasattr(widget, "dnd_bind"):
            return False
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._handle_drop_event)
        except (AttributeError, TclError):
            return False
        return True

    def _handle_drop_event(self, event):
        return self._handle_drop_data(getattr(event, "data", ""))

    def _handle_drop_data(self, data: str) -> str:
        try:
            raw_paths = self.root.tk.splitlist(data)
            if not raw_paths:
                raise ValueError("drop did not contain any file paths")
        except TclError as exc:
            self.status_var.set(f"Drop import failed: {exc}")
            return "break"
        self._import_scan_sources(raw_paths, source_label="dropped scan files")
        return "break"

    # ── Inspection ────────────────────────────────────────────

    def _on_session_changed(self, _event=None) -> None:
        session = self._current_session()
        if session is None:
            self._set_default_outputs()
            return
        self._set_active_session(session)
        self._display_session(session)

    def _inspect_session_text(self, session: SessionState) -> InspectionResult:
        result = inspect_pasted_text(
            session.text_widget.get("1.0", END),
            selected_mode=self.mode_var.get(),
            passphrase=self.passphrase_var.get() or None,
            source_label=session.source_label,
        )
        session.result = result
        self._display_session(session)
        return result

    def _parse_current_session(self) -> None:
        session = self._current_session() or self._new_session()
        try:
            self._inspect_session_text(session)
        except Exception as exc:
            session.result = None
            self._set_default_outputs()
            self.status_var.set(f"Parse failed: {exc}")
            self._set_text(self.summary_text, f"Parse failed:\n{exc}\n")
            return
        self.status_var.set(f"Parsed {session.title}.")

    def _display_session(self, session: SessionState) -> None:
        self._set_active_session(session)
        result = session.result
        if result is None:
            self._set_default_outputs()
            self._set_text(self.summary_text, "No parsed data yet for this session.\n")
            self._set_text(self.report_json_text, "{}\n")
            self._set_active_session(session)
            return

        self._set_text(self.summary_text, result.summary_text)
        self._set_text(self.diagnostics_text, result.diagnostics_text)
        self._set_text(self.manifest_text_widget, result.manifest_text)
        self._set_text(
            self.payloads_text,
            result.normalized_payload_text or "No normalized payloads available.\n",
        )
        self._set_text(
            self.fallback_text_widget,
            result.combined_fallback_text or "No fallback text available.\n",
        )
        self._set_text(self.report_json_text, result.report_json)

        for tree in (self.frame_tree, self.file_tree, self.secret_tree):
            for item in tree.get_children():
                tree.delete(item)

        for index, record in enumerate(result.frame_records):
            self.frame_tree.insert(
                "",
                END,
                iid=str(index),
                values=(
                    frame_type_name(record.frame.frame_type),
                    record.frame.doc_id.hex(),
                    record.frame.index,
                    record.frame.total,
                    len(record.frame.data),
                ),
            )
        if result.frame_records:
            self.frame_tree.selection_set("0")
            self._on_frame_selected()
        else:
            for widget, text in (
                (self.frame_detail_text, "No frames parsed.\n"),
                (self.frame_raw_text, "No frames parsed.\n"),
                (self.frame_cbor_text, "No frames parsed.\n"),
                (self.frame_payload_text, "No frames parsed.\n"),
                (self.frame_fallback_text, "No frames parsed.\n"),
            ):
                self._set_text(widget, text)

        for index, record in enumerate(result.files):
            self.file_tree.insert(
                "",
                END,
                iid=str(index),
                values=(record.path, record.size, record.preview_kind),
            )
        if result.files:
            self.file_tree.selection_set("0")
            self._on_file_selected()
        else:
            self._set_text(self.file_preview_text, "No decrypted file previews available.\n")

        for index, record in enumerate(result.recovered_secrets):
            self.secret_tree.insert("", END, iid=str(index), values=(record.label, record.status))
        if result.recovered_secrets:
            self.secret_tree.selection_set("0")
            self._on_secret_selected()
        else:
            self._set_text(self.secret_detail_text, "No reconstructed secrets available.\n")

    def _on_frame_selected(self, _event=None) -> None:
        session = self._current_session()
        if session is None or session.result is None:
            return
        selected = self.frame_tree.selection()
        if not selected:
            return
        record = session.result.frame_records[int(selected[0])]
        self._set_text(self.frame_detail_text, record.detail_text)
        self._set_text(self.frame_raw_text, record.raw_text)
        self._set_text(self.frame_cbor_text, record.cbor_text)
        self._set_text(self.frame_payload_text, record.payload_text)
        self._set_text(self.frame_fallback_text, record.fallback_text)

    def _on_file_selected(self, _event=None) -> None:
        session = self._current_session()
        if session is None or session.result is None:
            return
        selected = self.file_tree.selection()
        if not selected:
            return
        record = session.result.files[int(selected[0])]
        header = (
            f"Path: {record.path}\n"
            f"Size: {record.size}\n"
            f"SHA256: {record.sha256}\n"
            f"Preview: {record.preview_kind}\n\n"
        )
        self._set_text(self.file_preview_text, header + record.preview)

    def _on_secret_selected(self, _event=None) -> None:
        session = self._current_session()
        if session is None or session.result is None:
            return
        selected = self.secret_tree.selection()
        if not selected:
            return
        record = session.result.recovered_secrets[int(selected[0])]
        self._set_text(self.secret_detail_text, f"{record.summary}\n\n{record.detail_text}")

    # ── Session lifecycle ─────────────────────────────────────

    def _clear_current_session(self) -> None:
        session = self._current_session()
        if session is None:
            return
        tab_id = str(session.container)
        self.session_notebook.forget(session.container)
        self._sessions.pop(tab_id, None)
        session.container.destroy()

        if self._sessions:
            next_tab_id = self.session_notebook.select()
            next_session = self._sessions.get(next_tab_id)
            if next_session is not None:
                self._display_session(next_session)
        else:
            self._new_session()
            self.status_var.set(f"Closed {session.title}. Created a fresh session.")
            return

        self.status_var.set(f"Closed {session.title}.")

    # ── Export ────────────────────────────────────────────────

    def _require_result_for_export(
        self, title: str
    ) -> tuple[SessionState, InspectionResult] | None:
        session = self._current_session()
        if session is None or session.result is None:
            messagebox.showinfo(title, "Parse a session first.")
            return None
        return session, session.result

    def _export_current_json(self) -> None:
        exported = self._require_result_for_export("Export JSON")
        if exported is None:
            return
        session, result = exported
        path = filedialog.asksaveasfilename(
            title="Export report JSON",
            defaultextension=".json",
            initialfile=f"{session.title.replace(' ', '_').lower()}_report.json",
        )
        if path:
            Path(path).write_text(result.report_json, encoding="utf-8")
            self.status_var.set(f"Exported report JSON to {path}.")

    def _export_current_payloads(self) -> None:
        exported = self._require_result_for_export("Export Payloads")
        if exported is None:
            return
        session, result = exported
        if not result.normalized_payload_text:
            messagebox.showinfo("Export Payloads", "No normalized payloads are available.")
            return
        path = filedialog.asksaveasfilename(
            title="Export normalized payloads",
            defaultextension=".txt",
            initialfile=f"{session.title.replace(' ', '_').lower()}_payloads.txt",
        )
        if path:
            Path(path).write_text(result.normalized_payload_text, encoding="utf-8")
            self.status_var.set(f"Exported payloads to {path}.")

    def _export_current_fallback(self) -> None:
        exported = self._require_result_for_export("Export Fallback")
        if exported is None:
            return
        session, result = exported
        if not result.combined_fallback_text:
            messagebox.showinfo("Export Fallback", "No fallback text is available.")
            return
        path = filedialog.asksaveasfilename(
            title="Export fallback text",
            defaultextension=".txt",
            initialfile=f"{session.title.replace(' ', '_').lower()}_fallback.txt",
        )
        if path:
            Path(path).write_text(result.combined_fallback_text, encoding="utf-8")
            self.status_var.set(f"Exported fallback text to {path}.")

    def _export_current_manifest(self) -> None:
        exported = self._require_result_for_export("Export Manifest")
        if exported is None:
            return
        session, result = exported
        if result.manifest_json_text is None:
            messagebox.showinfo(
                "Export Manifest",
                "No manifest JSON is available. Reassemble MAIN frames and provide "
                "the passphrase first.",
            )
            return
        path = filedialog.asksaveasfilename(
            title="Export manifest JSON",
            defaultextension=".json",
            initialfile=f"{session.title.replace(' ', '_').lower()}_manifest.json",
        )
        if path:
            Path(path).write_text(result.manifest_json_text, encoding="utf-8")
            self.status_var.set(f"Exported manifest JSON to {path}.")

    def _export_current_files(self) -> None:
        exported = self._require_result_for_export("Export Files")
        if exported is None:
            return
        _session, result = exported
        if not result.files:
            messagebox.showinfo("Export Files", "No decrypted files are available to export.")
            return
        output_dir = filedialog.askdirectory(title="Export decrypted files")
        if not output_dir:
            return
        root = Path(output_dir)
        for record in result.files:
            target = root / record.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(record.data)
        self.status_var.set(f"Exported {len(result.files)} file(s) to {output_dir}.")

    def _export_batch_report(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export batch report JSON",
            defaultextension=".json",
            initialfile="batch_report.json",
        )
        if path:
            Path(path).write_text(self.batch_report_json, encoding="utf-8")
            self.status_var.set(f"Exported batch report to {path}.")


def main() -> int:
    root = TkinterDnD.Tk() if TkinterDnD is not None else Tk()
    InspectorApp(root)
    root.mainloop()
    return 0


__all__ = ["InspectorApp", "SessionState", "main"]

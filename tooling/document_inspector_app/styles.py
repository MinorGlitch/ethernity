from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from tkinter import Menu, TclError, Tk, font as tkfont, ttk
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover - Windows only
    winreg = None

from .bootstrap import SRC_ROOT as _SRC_ROOT  # noqa: F401


@dataclass(frozen=True)
class ThemePalette:
    name: str
    bg: str
    hero: str
    hero_panel: str
    panel: str
    panel_alt: str
    panel_subtle: str
    border: str
    border_strong: str
    text: str
    muted: str
    accent: str
    accent_active: str
    accent_soft: str
    accent_soft_text: str
    selection: str
    input_bg: str
    text_bg: str
    status_bg: str
    status_fg: str
    scrollbar: str


LIGHT_PALETTE = ThemePalette(
    name="light",
    bg="#f3f4f6",
    hero="#ffffff",
    hero_panel="#f9fafb",
    panel="#ffffff",
    panel_alt="#f5f6f8",
    panel_subtle="#ebedf1",
    border="#e5e7eb",
    border_strong="#d1d5db",
    text="#111827",
    muted="#6b7280",
    accent="#0d9488",
    accent_active="#0f766e",
    accent_soft="#ccfbf1",
    accent_soft_text="#115e59",
    selection="#dbeafe",
    input_bg="#ffffff",
    text_bg="#f9fafb",
    status_bg="#f9fafb",
    status_fg="#115e59",
    scrollbar="#d1d5db",
)


DARK_PALETTE = ThemePalette(
    name="dark",
    bg="#0f1117",
    hero="#181b23",
    hero_panel="#1f232d",
    panel="#181b23",
    panel_alt="#1f232d",
    panel_subtle="#282d38",
    border="#303643",
    border_strong="#434b5e",
    text="#e5e7eb",
    muted="#9ca3af",
    accent="#2dd4bf",
    accent_active="#14b8a6",
    accent_soft="#1a3a38",
    accent_soft_text="#5eead4",
    selection="#1e3a5f",
    input_bg="#13161d",
    text_bg="#14171f",
    status_bg="#181b23",
    status_fg="#5eead4",
    scrollbar="#3d4452",
)


def _detect_system_theme_name() -> str:
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            )
        except (OSError, subprocess.SubprocessError):
            return "light"
        return "dark" if result.returncode == 0 and "dark" in result.stdout.lower() else "light"

    if sys.platform.startswith("win") and winreg is not None:  # pragma: no branch
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _value_type = winreg.QueryValueEx(key, "AppsUseLightTheme")
        except OSError:
            return "light"
        return "light" if int(value) else "dark"

    gtk_theme = os.environ.get("GTK_THEME", "").lower()
    if gtk_theme:
        return "dark" if "dark" in gtk_theme else "light"

    if shutil.which("gsettings"):
        for command in (
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
        ):
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            output = result.stdout.strip().strip("'").lower()
            if not output:
                continue
            if output == "prefer-dark" or "dark" in output:
                return "dark"
        return "light"

    return "light"


def _choose_font(*candidates: str, fallback: str) -> str:
    families = {family.lower() for family in tkfont.families()}
    for family in candidates:
        if family.lower() in families:
            return family
    return fallback


class ThemeController:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._palette = LIGHT_PALETTE
        self._text_widgets: list[Any] = []
        self._menus: list[Menu] = []
        default_font_family = tkfont.nametofont("TkDefaultFont").actual("family")
        mono_font_family = tkfont.nametofont("TkFixedFont").actual("family")
        self.default_font_family = _choose_font(
            "SF Pro Text",
            "Avenir Next",
            "Segoe UI Variable",
            "Segoe UI",
            "Helvetica Neue",
            fallback=default_font_family,
        )
        self.title_font_family = _choose_font(
            "SF Pro Display",
            "Avenir Next Demi Bold",
            "Avenir Next",
            "Segoe UI Semibold",
            "Helvetica Neue",
            fallback=self.default_font_family,
        )
        self.mono_font_family = _choose_font(
            "SF Mono",
            "Menlo",
            "Consolas",
            "Monaco",
            fallback=mono_font_family,
        )
        self.refresh(force=True)

    @property
    def palette(self) -> ThemePalette:
        return self._palette

    @property
    def display_name(self) -> str:
        return f"System {self._palette.name}"

    def text_widget_options(self) -> dict[str, object]:
        palette = self._palette
        return {
            "background": palette.text_bg,
            "foreground": palette.text,
            "insertbackground": palette.accent,
            "selectbackground": palette.selection,
            "selectforeground": palette.text,
            "inactiveselectbackground": palette.selection,
            "borderwidth": 1,
            "highlightthickness": 1,
            "highlightbackground": palette.border,
            "highlightcolor": palette.accent,
            "relief": "flat",
            "padx": 10,
            "pady": 8,
            "spacing1": 2,
            "spacing3": 2,
        }

    def register_text_widget(self, widget: Any) -> None:
        self._text_widgets.append(widget)
        self._apply_text_widget(widget)

    def register_menu(self, menu: Menu) -> None:
        self._menus.append(menu)
        self._apply_menu(menu)

    def refresh(self, *, force: bool = False) -> bool:
        theme_name = _detect_system_theme_name()
        next_palette = DARK_PALETTE if theme_name == "dark" else LIGHT_PALETTE
        if not force and next_palette == self._palette:
            return False
        self._palette = next_palette
        self._apply_palette()
        return True

    def _apply_palette(self) -> None:
        palette = self._palette
        root = self.root
        style = self.style

        default_font = (self.default_font_family, 11)
        label_font = (self.default_font_family, 10)
        title_font = (self.title_font_family, 12, "bold")
        section_font = (self.title_font_family, 11, "bold")
        hero_title_font = (self.title_font_family, 25, "bold")
        hero_body_font = (self.default_font_family, 12)
        badge_font = (self.default_font_family, 10, "bold")
        status_font = (self.default_font_family, 10)
        notebook_font = (self.default_font_family, 10, "bold")
        heading_font = (self.title_font_family, 10, "bold")

        root.configure(background=palette.bg)
        root.option_add("*tearOff", False)
        root.option_add("*TCombobox*Listbox.background", palette.input_bg)
        root.option_add("*TCombobox*Listbox.foreground", palette.text)
        root.option_add("*TCombobox*Listbox.selectBackground", palette.selection)
        root.option_add("*TCombobox*Listbox.selectForeground", palette.text)

        # ── Frame styles ──────────────────────────────────────────
        style.configure("TFrame", background=palette.bg)
        style.configure("App.TFrame", background=palette.bg)
        style.configure("Hero.TFrame", background=palette.hero)
        style.configure(
            "HeroCard.TFrame",
            background=palette.hero_panel,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Surface.TFrame",
            background=palette.panel,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            borderwidth=1,
            relief="solid",
        )
        style.configure("NotebookPage.TFrame", background=palette.panel)
        style.configure("Card.TFrame", background=palette.panel, relief="flat")
        style.configure(
            "StatusCard.TFrame",
            background=palette.status_bg,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Header.TFrame",
            background=palette.hero,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            borderwidth=0,
            relief="flat",
        )
        style.configure(
            "ActionBar.TFrame",
            background=palette.panel_alt,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            borderwidth=0,
            relief="flat",
        )
        style.configure(
            "StatusBar.TFrame",
            background=palette.status_bg,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            borderwidth=1,
            relief="flat",
        )

        # ── Label styles ──────────────────────────────────────────
        style.configure("TLabel", background=palette.bg, foreground=palette.text, font=default_font)
        style.configure(
            "Card.TLabel",
            background=palette.panel,
            foreground=palette.text,
            font=default_font,
        )
        style.configure(
            "Muted.TLabel",
            background=palette.panel,
            foreground=palette.muted,
            font=label_font,
        )
        style.configure(
            "Title.TLabel",
            background=palette.panel,
            foreground=palette.text,
            font=title_font,
        )
        style.configure(
            "Meta.TLabel",
            background=palette.panel,
            foreground=palette.muted,
            font=(self.default_font_family, 10),
        )
        style.configure(
            "Status.TLabel",
            background=palette.status_bg,
            foreground=palette.status_fg,
            font=status_font,
        )
        style.configure(
            "Eyebrow.TLabel",
            background=palette.hero,
            foreground=palette.accent_active,
            font=badge_font,
        )
        style.configure(
            "HeroTitle.TLabel",
            background=palette.hero,
            foreground=palette.text,
            font=hero_title_font,
        )
        style.configure(
            "HeroBody.TLabel",
            background=palette.hero,
            foreground=palette.muted,
            font=hero_body_font,
        )
        style.configure(
            "HeroCardLabel.TLabel",
            background=palette.hero_panel,
            foreground=palette.muted,
            font=(self.default_font_family, 10, "bold"),
        )
        style.configure(
            "HeroCardValue.TLabel",
            background=palette.hero_panel,
            foreground=palette.text,
            font=(self.title_font_family, 12, "bold"),
        )
        style.configure(
            "HeroCardMeta.TLabel",
            background=palette.hero_panel,
            foreground=palette.muted,
            font=(self.default_font_family, 10),
        )
        style.configure(
            "SectionTitle.TLabel",
            background=palette.panel,
            foreground=palette.text,
            font=(self.title_font_family, 13, "bold"),
        )
        style.configure(
            "BarTitle.TLabel",
            background=palette.panel_alt,
            foreground=palette.text,
            font=(self.title_font_family, 13, "bold"),
        )
        style.configure(
            "HeaderTitle.TLabel",
            background=palette.hero,
            foreground=palette.text,
            font=(self.title_font_family, 14, "bold"),
        )
        style.configure(
            "HeaderSession.TLabel",
            background=palette.hero,
            foreground=palette.accent,
            font=(self.title_font_family, 11, "bold"),
        )
        style.configure(
            "HeaderMeta.TLabel",
            background=palette.hero,
            foreground=palette.muted,
            font=(self.default_font_family, 10),
        )
        style.configure(
            "ActionBar.TLabel",
            background=palette.panel_alt,
            foreground=palette.muted,
            font=(self.default_font_family, 10),
        )
        style.configure(
            "StatusBar.TLabel",
            background=palette.status_bg,
            foreground=palette.muted,
            font=(self.default_font_family, 10),
        )
        style.configure(
            "StatusSession.TLabel",
            background=palette.status_bg,
            foreground=palette.accent_active,
            font=(self.title_font_family, 10, "bold"),
        )
        style.configure(
            "StatusMeta.TLabel",
            background=palette.status_bg,
            foreground=palette.muted,
            font=(self.default_font_family, 10),
        )

        # ── LabelFrame styles ────────────────────────────────────
        style.configure(
            "ToolbarCard.TLabelframe",
            background=palette.panel,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            borderwidth=1,
            relief="solid",
            padding=16,
        )
        style.configure(
            "ToolbarCard.TLabelframe.Label",
            background=palette.panel,
            foreground=palette.accent_active,
            font=section_font,
        )

        # ── Button styles ────────────────────────────────────────
        style.configure(
            "TButton",
            background=palette.panel_alt,
            foreground=palette.text,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            focusthickness=0,
            focuscolor=palette.panel_alt,
            relief="flat",
            padding=(10, 6),
        )
        style.map(
            "TButton",
            background=[
                ("disabled", palette.panel_subtle),
                ("active", palette.panel_subtle),
                ("pressed", palette.selection),
            ],
            foreground=[("disabled", palette.muted)],
            bordercolor=[("active", palette.border_strong), ("focus", palette.accent)],
        )

        style.configure(
            "Primary.TButton",
            background=palette.accent,
            foreground="#ffffff",
            bordercolor=palette.accent,
            lightcolor=palette.accent,
            darkcolor=palette.accent,
            focuscolor=palette.accent,
            focusthickness=0,
            relief="flat",
            padding=(12, 6),
            font=(self.title_font_family, 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[
                ("disabled", palette.accent_active),
                ("active", palette.accent_active),
                ("pressed", palette.accent_active),
            ],
            foreground=[("disabled", "#f7fffe"), ("active", "#ffffff"), ("pressed", "#ffffff")],
            bordercolor=[("active", palette.accent_active), ("pressed", palette.accent_active)],
            lightcolor=[("active", palette.accent_active), ("pressed", palette.accent_active)],
            darkcolor=[("active", palette.accent_active), ("pressed", palette.accent_active)],
        )

        style.configure(
            "Toolbar.TMenubutton",
            background=palette.panel_alt,
            foreground=palette.text,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            padding=(10, 6),
            arrowcolor=palette.accent_active,
            relief="flat",
        )
        style.map(
            "Toolbar.TMenubutton",
            background=[("active", palette.panel_subtle), ("pressed", palette.selection)],
            bordercolor=[("active", palette.border_strong)],
            arrowcolor=[("active", palette.accent)],
        )

        # ── Input styles ─────────────────────────────────────────
        style.configure(
            "TEntry",
            fieldbackground=palette.input_bg,
            foreground=palette.text,
            insertcolor=palette.accent,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            padding=5,
            relief="flat",
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", palette.accent), ("active", palette.border_strong)],
            lightcolor=[("focus", palette.accent)],
            darkcolor=[("focus", palette.accent)],
        )

        style.configure(
            "TCombobox",
            fieldbackground=palette.input_bg,
            background=palette.input_bg,
            foreground=palette.text,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            arrowcolor=palette.accent_active,
            padding=5,
            relief="flat",
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette.input_bg)],
            background=[("readonly", palette.input_bg)],
            bordercolor=[("focus", palette.accent), ("active", palette.border_strong)],
            arrowcolor=[("active", palette.accent)],
        )

        # ── Notebook styles ──────────────────────────────────────
        style.configure(
            "TNotebook",
            background=palette.panel,
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=palette.panel_alt,
            foreground=palette.muted,
            padding=(12, 7),
            font=notebook_font,
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", palette.panel), ("active", palette.panel_subtle)],
            foreground=[("selected", palette.accent_active), ("active", palette.text)],
        )

        # ── Treeview styles ──────────────────────────────────────
        style.configure(
            "Treeview",
            background=palette.text_bg,
            fieldbackground=palette.text_bg,
            foreground=palette.text,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            rowheight=26,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", palette.selection)],
            foreground=[("selected", palette.text)],
        )
        style.configure(
            "Treeview.Heading",
            background=palette.panel_alt,
            foreground=palette.accent_active,
            font=heading_font,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            relief="flat",
            padding=(8, 6),
        )
        style.map("Treeview.Heading", background=[("active", palette.panel_subtle)])

        # ── Misc styles ──────────────────────────────────────────
        style.configure("TPanedwindow", background=palette.bg)
        style.configure("Sash", background=palette.border, sashthickness=6)
        style.configure("TSeparator", background=palette.border)

        for widget in list(self._text_widgets):
            self._apply_text_widget(widget)
        for menu in list(self._menus):
            self._apply_menu(menu)

    def _apply_text_widget(self, widget: Any) -> None:
        try:
            widget.configure(font=(self.mono_font_family, 11), **self.text_widget_options())
        except TclError:
            self._text_widgets = [
                candidate for candidate in self._text_widgets if candidate is not widget
            ]

    def _apply_menu(self, menu: Menu) -> None:
        palette = self._palette
        try:
            menu.configure(
                background=palette.panel,
                foreground=palette.text,
                activebackground=palette.selection,
                activeforeground=palette.text,
                selectcolor=palette.accent,
                relief="flat",
                borderwidth=0,
            )
        except TclError:
            self._menus = [candidate for candidate in self._menus if candidate is not menu]


def configure_styles(root: Tk) -> ThemeController:
    return ThemeController(root)


__all__ = ["ThemeController", "configure_styles"]

from __future__ import annotations

from tkinter import Tk, ttk

from .bootstrap import SRC_ROOT as _SRC_ROOT  # noqa: F401

BG = "#f3efe7"
SURFACE = "#fbf8f2"
SURFACE_ALT = "#f6f1e7"
BORDER = "#d5cec0"
TEXT = "#1f2933"
MUTED = "#6b7280"
ACCENT = "#1f6f66"
ACCENT_DARK = "#165750"
ACCENT_SOFT = "#d8ebe7"
SELECT = "#dcebe5"

TEXT_WIDGET = {
    "background": "#fffdf9",
    "foreground": TEXT,
    "insertbackground": ACCENT_DARK,
    "selectbackground": ACCENT_SOFT,
    "selectforeground": TEXT,
    "borderwidth": 1,
    "highlightthickness": 1,
    "highlightbackground": BORDER,
    "highlightcolor": ACCENT,
    "relief": "flat",
    "padx": 12,
    "pady": 10,
    "spacing1": 2,
    "spacing3": 2,
}


def configure_styles(root: Tk) -> ttk.Style:
    root.configure(background=BG)
    root.option_add("*tearOff", False)

    style = ttk.Style(root)
    style.theme_use("clam")

    default_font = ("Avenir Next", 12)
    title_font = ("Avenir Next Demi Bold", 12)
    section_font = ("Avenir Next Demi Bold", 11)
    status_font = ("Avenir Next Medium", 11)

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE, relief="flat")
    style.configure("TLabel", background=BG, foreground=TEXT, font=default_font)
    style.configure("Card.TLabel", background=SURFACE, foreground=TEXT, font=default_font)
    style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED, font=("Avenir Next", 11))
    style.configure("Title.TLabel", background=SURFACE, foreground=TEXT, font=title_font)
    style.configure("Meta.TLabel", background=SURFACE, foreground=MUTED, font=("Avenir Next", 10))
    style.configure(
        "Status.TLabel", background=SURFACE_ALT, foreground=ACCENT_DARK, font=status_font
    )

    style.configure(
        "ToolbarCard.TLabelframe",
        background=SURFACE,
        bordercolor=BORDER,
        borderwidth=1,
        relief="solid",
        padding=12,
    )
    style.configure(
        "ToolbarCard.TLabelframe.Label",
        background=SURFACE,
        foreground=ACCENT_DARK,
        font=section_font,
    )

    style.configure(
        "TButton",
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        focusthickness=0,
        focuscolor=SURFACE,
        padding=(12, 8),
    )
    style.map(
        "TButton",
        background=[("active", SURFACE_ALT), ("pressed", SELECT)],
        bordercolor=[("active", ACCENT_SOFT)],
    )

    style.configure(
        "Primary.TButton",
        background=ACCENT,
        foreground="#ffffff",
        bordercolor=ACCENT,
        padding=(14, 8),
    )
    style.map(
        "Primary.TButton",
        background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK)],
        foreground=[("active", "#ffffff"), ("pressed", "#ffffff")],
    )

    style.configure(
        "Toolbar.TMenubutton",
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        padding=(12, 8),
        arrowcolor=ACCENT_DARK,
    )
    style.map(
        "Toolbar.TMenubutton",
        background=[("active", SURFACE_ALT), ("pressed", SELECT)],
        bordercolor=[("active", ACCENT_SOFT)],
    )

    style.configure(
        "TEntry",
        fieldbackground="#fffdf9",
        foreground=TEXT,
        insertcolor=ACCENT_DARK,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=6,
    )
    style.configure(
        "TCombobox",
        fieldbackground="#fffdf9",
        background="#fffdf9",
        foreground=TEXT,
        bordercolor=BORDER,
        arrowcolor=ACCENT_DARK,
        padding=6,
    )

    style.configure(
        "TNotebook",
        background=BG,
        borderwidth=0,
        tabmargins=(0, 0, 0, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=SURFACE_ALT,
        foreground=MUTED,
        padding=(16, 10),
        font=("Avenir Next Medium", 11),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", SURFACE), ("active", SURFACE)],
        foreground=[("selected", ACCENT_DARK), ("active", TEXT)],
    )

    style.configure(
        "Treeview",
        background="#fffdf9",
        fieldbackground="#fffdf9",
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        rowheight=28,
    )
    style.map(
        "Treeview",
        background=[("selected", SELECT)],
        foreground=[("selected", TEXT)],
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE_ALT,
        foreground=ACCENT_DARK,
        font=("Avenir Next Demi Bold", 10),
        bordercolor=BORDER,
        relief="flat",
        padding=(8, 8),
    )
    style.map("Treeview.Heading", background=[("active", SURFACE)])

    style.configure("TPanedwindow", background=BG)
    style.configure("Sash", background=BORDER, sashthickness=8)

    return style


__all__ = ["TEXT_WIDGET", "configure_styles"]

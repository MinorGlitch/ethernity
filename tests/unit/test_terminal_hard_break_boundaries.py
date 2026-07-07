from __future__ import annotations

import re
from pathlib import Path

NEW_LAYER_ROOTS = (
    Path("src/ethernity/app"),
    Path("src/ethernity/run"),
    Path("src/ethernity/tasks"),
)
TERMINAL_THEME_PATH = Path("src/ethernity/app/theme.tcss")

FORBIDDEN_IMPORT_PATTERNS = (
    re.compile(r"^\s*(?:from|import)\s+typer\b", re.MULTILINE),
    re.compile(r"^\s*(?:from|import)\s+questionary\b", re.MULTILINE),
    re.compile(r"^\s*(?:from|import)\s+prompt_toolkit\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.bootstrap\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.bootstrap\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.features\.[^.]+\.command\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.features\.[^.]+\.command\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.shared\.ui\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.shared\.ui\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.shared\.ui_api\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.shared\.ui_api\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.shared\.recovery_prompts\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.shared\.recovery_prompts\b", re.MULTILINE),
)


def test_new_terminal_layer_does_not_import_old_interactive_cli() -> None:
    violations: list[str] = []
    for root in NEW_LAYER_ROOTS:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_IMPORT_PATTERNS:
                if pattern.search(source):
                    violations.append(f"{path}: {pattern.pattern}")

    assert violations == []


def test_source_tree_no_longer_imports_questionary_or_prompt_toolkit() -> None:
    violations: list[str] = []
    patterns = (
        re.compile(r"^\s*(?:from|import)\s+typer\b", re.MULTILINE),
        re.compile(r"^\s*(?:from|import)\s+questionary\b", re.MULTILINE),
        re.compile(r"^\s*(?:from|import)\s+prompt_toolkit\b", re.MULTILINE),
    )
    for path in sorted(Path("src/ethernity").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern.search(source):
                violations.append(f"{path}: {pattern.pattern}")

    assert violations == []


def test_old_prompt_and_typer_source_files_are_removed() -> None:
    removed_paths = (
        Path("src/ethernity/cli/bootstrap/app.py"),
        Path("src/ethernity/cli/bootstrap/__init__.py"),
        Path("src/ethernity/cli/bootstrap/entrypoint.py"),
        Path("src/ethernity/cli/bootstrap/registry.py"),
        Path("src/ethernity/cli/bootstrap/root_command.py"),
        Path("src/ethernity/cli/bootstrap/startup.py"),
        Path("src/ethernity/cli/__main__.py"),
        Path("src/ethernity/cli/shared/common.py"),
        Path("src/ethernity/cli/shared/recovery_prompts.py"),
        Path("src/ethernity/cli/shared/ui/home.py"),
        Path("src/ethernity/cli/shared/ui/picker.py"),
        Path("src/ethernity/cli/shared/ui/prompts.py"),
        Path("src/ethernity/cli/shared/ui/prompts_core.py"),
        Path("src/ethernity/cli/shared/ui/workspace.py"),
    )
    removed_globs = (
        Path("src/ethernity/cli/features").glob("*/command.py"),
        Path("src/ethernity/cli/features").glob("*/workspace.py"),
        Path("src/ethernity/cli/features").glob("*/wizard.py"),
        Path("src/ethernity/cli/features").glob("*/orchestrator.py"),
        Path("src/ethernity/cli/features").glob("*/input_collection.py"),
    )

    leftovers = [str(path) for path in removed_paths if path.exists()]
    for paths in removed_globs:
        leftovers.extend(str(path) for path in paths)

    assert sorted(leftovers) == []


def test_terminal_package_roots_are_not_compatibility_facades() -> None:
    package_roots = (
        Path("src/ethernity/app/__init__.py"),
        Path("src/ethernity/app/screens/__init__.py"),
        Path("src/ethernity/app/widgets/__init__.py"),
        Path("src/ethernity/cli/__init__.py"),
        Path("src/ethernity/run/__init__.py"),
        Path("src/ethernity/run/commands/__init__.py"),
        Path("src/ethernity/tasks/__init__.py"),
    )
    forbidden_snippets = ("__all__", "__getattr__", "import_module", "from ethernity.")

    violations: list[str] = []
    for path in package_roots:
        source = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in source:
                violations.append(f"{path}: {snippet}")

    assert violations == []


def test_new_terminal_facade_modules_are_removed() -> None:
    assert not Path("src/ethernity/app/main.py").exists()


def test_terminal_theme_uses_textual_palette_variables() -> None:
    stylesheet = TERMINAL_THEME_PATH.read_text(encoding="utf-8")

    assert re.findall(r"#[0-9a-fA-F]{6,8}", stylesheet) == []
    for token in ("$background", "$surface", "$text", "$border"):
        assert token in stylesheet

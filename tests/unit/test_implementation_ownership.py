from __future__ import annotations

import ast
import hashlib
import re
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "ethernity"
PYTHON_OWNERSHIP_ROOTS = (
    PACKAGE_ROOT / "app",
    PACKAGE_ROOT / "tasks",
    PACKAGE_ROOT / "workflows",
    PACKAGE_ROOT / "extensions",
    PACKAGE_ROOT / "render" / "direct_pdf",
)
JAVASCRIPT_OWNERSHIP_ROOTS = (
    PROJECT_ROOT / "kit" / "app",
    PROJECT_ROOT / "kit" / "lib",
)


def _python_paths() -> tuple[Path, ...]:
    return tuple(path for root in PYTHON_OWNERSHIP_ROOTS for path in sorted(root.rglob("*.py")))


def _implementation_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


def test_production_features_have_no_exact_duplicate_multistep_function_bodies() -> None:
    owners: defaultdict[str, list[str]] = defaultdict(list)
    for path in _python_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = _implementation_body(node)
            if len(body) < 2:
                continue
            normalized = ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)
            digest = hashlib.sha256(normalized.encode()).hexdigest()
            owners[digest].append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}:{node.name}")

    duplicates = [sites for sites in owners.values() if len(sites) > 1]
    assert duplicates == []


def test_feature_modules_do_not_create_simple_renaming_aliases() -> None:
    aliases: list[str] = []
    for path in _python_paths():
        if (PACKAGE_ROOT / "render" / "direct_pdf") in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue
            if not isinstance(value, (ast.Name, ast.Attribute)):
                continue
            value_name = ast.unparse(value)
            for target in targets:
                if isinstance(target, ast.Name) and target.id != value_name:
                    aliases.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                        f"{target.id} = {value_name}"
                    )

    assert aliases == []


def test_browser_duplicate_function_names_are_only_intentional_runtime_variants() -> None:
    pattern = re.compile(
        r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
        re.MULTILINE,
    )
    owners: defaultdict[str, list[str]] = defaultdict(list)
    for root in JAVASCRIPT_OWNERSHIP_ROOTS:
        for suffix in ("*.js", "*.jsx"):
            for path in sorted(root.rglob(suffix)):
                source = path.read_text(encoding="utf-8")
                for match in pattern.finditer(source):
                    owners[match.group(1)].append(path.relative_to(PROJECT_ROOT).as_posix())

    duplicates = {name: tuple(paths) for name, paths in owners.items() if len(paths) > 1}
    assert duplicates == {
        # Separate codec modules intentionally keep their comparisons private.
        "compareBytes": ("kit/lib/age_scrypt.js", "kit/lib/cbor.js"),
        # The build selects exactly one scanner-capability module.
        "useQrScannerRuntime": (
            "kit/app/hooks/useQrScannerRuntime.js",
            "kit/app/hooks/useQrScannerRuntime_jsqr.js",
        ),
    }


def test_created_timestamp_normalization_has_one_renderer_owner() -> None:
    owners: list[str] = []
    render_root = PACKAGE_ROOT / "render" / "direct_pdf"
    for path in render_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owners.extend(
            path.relative_to(PROJECT_ROOT).as_posix()
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "resolve_created_timestamp"
        )

    assert owners == ["src/ethernity/render/direct_pdf/document_inputs.py"]

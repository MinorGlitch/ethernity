from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "ethernity"


def test_tasks_and_workflows_do_not_import_cli_implementation() -> None:
    violations: list[str] = []
    for layer in ("tasks", "workflows"):
        for source_path in sorted((SOURCE_ROOT / layer).rglob("*.py")):
            module = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(module):
                imported_modules = _imported_modules(node)
                for imported_module in imported_modules:
                    if imported_module == "ethernity.cli" or imported_module.startswith(
                        "ethernity.cli."
                    ):
                        relative_path = source_path.relative_to(SOURCE_ROOT.parent)
                        violations.append(
                            f"{relative_path}:{node.lineno} imports {imported_module}"
                        )

    assert not violations, "layer boundary violations:\n" + "\n".join(violations)


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()

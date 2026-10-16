"""Keep disposable PDF workers independent of the rendering application."""

import json
import subprocess
import sys


def test_pdf_worker_does_not_load_renderer_or_config_editor() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys; import ethernity.render.pdf_appearance; "
            "print(json.dumps(sorted(sys.modules)))",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    loaded = set(json.loads(result.stdout))
    assert "pypdfium2" in loaded
    assert not {"fpdf", "pypdf", "ethernity.config", "ethernity.render.direct_pdf"} & loaded

import unittest

from ethernity.render.spec import resolve_doc_type


class TestRenderSpec(unittest.TestCase):
    def test_resolve_doc_type_context_override(self) -> None:
        context = {"doc_type": "kit"}
        resolved = resolve_doc_type("main_document.html.j2", context)
        self.assertEqual(resolved, "kit")

    def test_resolve_doc_type_template_fallback(self) -> None:
        resolved = resolve_doc_type("custom-kit-template.html.j2", {})
        self.assertEqual(resolved, "kit")


if __name__ == "__main__":
    unittest.main()

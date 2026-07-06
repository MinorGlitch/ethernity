import unittest
from pathlib import Path
from unittest import mock

from ethernity.render import html_to_pdf


class _FakeRequest:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakeRoute:
    def __init__(self) -> None:
        self.aborted = False
        self.fulfilled: dict[str, object] | None = None

    def abort(self) -> None:
        self.aborted = True

    def fulfill(self, **kwargs: object) -> None:
        self.fulfilled = kwargs


class _FakePage:
    def __init__(self, request_urls: tuple[str, ...] = ()) -> None:
        self.request_urls = request_urls
        self.route_pattern: str | None = None
        self.route_handler = None
        self.pdf_called = False
        self.closed = False

    def route(self, pattern: str, handler) -> None:
        self.route_pattern = pattern
        self.route_handler = handler

    def set_content(self, html: str, *, wait_until: str) -> None:
        _ = html
        self.wait_until = wait_until
        assert self.route_handler is not None
        for url in self.request_urls:
            self.route_handler(_FakeRoute(), _FakeRequest(url))

    def emulate_media(self, *, media: str) -> None:
        self.media = media

    def pdf(self, **kwargs: object) -> None:
        self.pdf_called = True
        self.pdf_kwargs = kwargs

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self.page = page

    def new_page(self) -> _FakePage:
        return self.page


class TestHtmlToPdfNetworkPolicy(unittest.TestCase):
    def test_render_html_to_pdf_registers_global_route_without_resources(self) -> None:
        page = _FakePage()
        with mock.patch.object(html_to_pdf, "_get_browser", return_value=_FakeBrowser(page)):
            html_to_pdf.render_html_to_pdf("<html />", Path("out.pdf"))

        self.assertEqual(page.route_pattern, "**/*")
        self.assertEqual(page.wait_until, "networkidle")
        self.assertEqual(page.media, "print")
        self.assertTrue(page.pdf_called)
        self.assertTrue(page.closed)

    def test_route_fulfills_exact_in_memory_resource(self) -> None:
        route = _FakeRoute()
        blocked_urls: list[str] = []

        html_to_pdf._route_resource(
            route,
            _FakeRequest("https://ethernity.local/assets/font.ttf"),
            {"https://ethernity.local/assets/font.ttf": ("font/ttf", b"font-bytes")},
            blocked_urls,
        )

        self.assertFalse(route.aborted)
        self.assertEqual(blocked_urls, [])
        self.assertEqual(
            route.fulfilled,
            {
                "status": 200,
                "body": b"font-bytes",
                "content_type": "font/ttf",
                "headers": {"Cache-Control": "no-store"},
            },
        )

    def test_render_blocks_unknown_synthetic_resource_before_pdf(self) -> None:
        page = _FakePage(("https://ethernity.local/assets/missing.ttf",))
        with mock.patch.object(html_to_pdf, "_get_browser", return_value=_FakeBrowser(page)):
            with self.assertRaisesRegex(RuntimeError, "blocked external resource request"):
                html_to_pdf.render_html_to_pdf("<html />", Path("out.pdf"))

        self.assertFalse(page.pdf_called)
        self.assertTrue(page.closed)

    def test_render_blocks_external_http_https_and_file_urls(self) -> None:
        for url in (
            "http://example.test/image.png",
            "https://example.test/font.woff2",
            "file:///tmp/secret.png",
        ):
            with self.subTest(url=url):
                page = _FakePage((url,))
                with mock.patch.object(
                    html_to_pdf, "_get_browser", return_value=_FakeBrowser(page)
                ):
                    with self.assertRaisesRegex(RuntimeError, url):
                        html_to_pdf.render_html_to_pdf("<html />", Path("out.pdf"))
                self.assertFalse(page.pdf_called)

    def test_render_allows_inline_content_that_makes_no_resource_request(self) -> None:
        page = _FakePage()
        with mock.patch.object(html_to_pdf, "_get_browser", return_value=_FakeBrowser(page)):
            html_to_pdf.render_html_to_pdf(
                '<img src="data:image/png;base64,AAAA" alt="">',
                Path("out.pdf"),
            )

        self.assertTrue(page.pdf_called)


if __name__ == "__main__":
    unittest.main()

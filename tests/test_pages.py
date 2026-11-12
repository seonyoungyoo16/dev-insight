from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from app import Handler, PAGES, PUBLIC, STATIC, Page


class PageNavigationTests(unittest.TestCase):
    def test_added_page_uses_shared_navigation_and_its_own_assets(self):
        with TemporaryDirectory() as folder:
            public = Path(folder)
            for filename in ("index.html", "shell.html", "shell.css"):
                (public / filename).write_bytes((PUBLIC / filename).read_bytes())
            (public / "events.html").write_text("<h1>행사 수집</h1>", encoding="utf-8")
            (public / "events.js").write_text('"use strict";', encoding="utf-8")
            pages = {**PAGES, "/events": Page("행사 & 밋업", "events.html", '행사 "검색"', scripts=("/events.js",))}
            static = {**STATIC, "/events.js": ("events.js", "application/javascript; charset=utf-8")}
            with patch("app.PUBLIC", public), patch("app.PAGES", pages), patch("app.STATIC", static):
                with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
                    thread = Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        origin = f"http://127.0.0.1:{server.server_port}"
                        home = self.read(origin + "/?view=default")
                        events = self.read(origin + "/events")
                        self.assertIn('<a href="/" aria-current="page">개발 공모전</a>', home)
                        self.assertIn('<a href="/events">행사 &amp; 밋업</a>', home)
                        self.assertIn('<a href="/events" aria-current="page">행사 &amp; 밋업</a>', events)
                        self.assertIn('<a href="/">개발 공모전</a>', events)
                        self.assertEqual(events.count('aria-current="page"'), 1)
                        self.assertIn("<h1>행사 수집</h1>", events)
                        self.assertIn('content="행사 &quot;검색&quot;"', events)
                        self.assertIn('href="/shell.css"', events)
                        self.assertIn('src="/board.js"', home)
                        self.assertNotIn('src="/board.js"', events)
                        self.assertIn('src="/events.js"', events)
                        self.assertNotIn('src="/events.js"', home)
                        self.assertEqual(self.read(origin + "/events.js"), '"use strict";')
                        self.assertIn(".app-nav", self.read(origin + "/shell.css"))
                        with self.assertRaises(HTTPError) as missing:
                            self.read(origin + "/missing")
                        missing.exception.close()
                        self.assertEqual(missing.exception.code, 404)
                    finally:
                        server.shutdown()
                        thread.join(timeout=2)

    @staticmethod
    def read(url):
        with urlopen(url, timeout=5) as response:
            return response.read().decode("utf-8")

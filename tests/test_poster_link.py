from datetime import datetime, timezone
import unittest
from urllib.parse import urlsplit
from unittest.mock import Mock

from playwright.sync_api import expect, sync_playwright

from app import PAGES, PUBLIC, STATIC, render_page
from collect import Collection, SEOUL, Source, collect_detizen


BOARD = "http://contest-board.test"
SOURCE = "https://example.org/contests/fixture"
POSTER = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


def serve_board(route):
    path = urlsplit(route.request.url).path
    if path in PAGES:
        route.fulfill(body=render_page(path), content_type="text/html; charset=utf-8")
    elif path in STATIC:
        filename, content_type = STATIC[path]
        route.fulfill(path=PUBLIC / filename, content_type=content_type)
    else:
        route.fulfill(status=404)


class PosterLinkTests(unittest.TestCase):
    def test_poster_link_and_missing_poster(self):
        state = {
            "today": "2026-11-12", "running": False, "sources": [],
            "contests": [
                {"name": "포스터 있는 공고", "poster": POSTER, "sourceUrl": SOURCE},
                {"name": "포스터 없는 공고", "poster": None, "sourceUrl": SOURCE},
            ],
        }

        with sync_playwright() as playwright, playwright.chromium.launch(channel="msedge") as browser:
            context = browser.new_context()
            context.route(BOARD + "/**", serve_board)
            context.route(BOARD + "/api/contests", lambda route: route.fulfill(json=state))
            context.route(SOURCE, lambda route: route.fulfill(body="공고 원문", content_type="text/plain; charset=utf-8"))
            page = context.new_page()
            page.goto(BOARD)
            link = page.get_by_role("link", name="포스터 있는 공고 공고 원문 열기")
            expect(link).to_have_attribute("href", SOURCE)
            expect(link).to_have_attribute("target", "_blank")
            with context.expect_page() as opened:
                link.press("Enter")
            detail = opened.value
            expect(detail).to_have_url(SOURCE)
            expect(detail.locator("body")).to_have_text("공고 원문")
            detail.close()

            missing = page.get_by_role("row").filter(has_text="포스터 없는 공고").locator("td").first
            expect(missing.get_by_role("link")).to_have_count(0)
            page.get_by_role("button", name="대표 이미지", exact=True).click()
            expect(page.get_by_role("checkbox", name="이미지 없음")).to_be_visible()


class BoardDeadlineTests(unittest.TestCase):
    def test_updates_an_open_tab_at_the_deadline_and_at_seoul_midnight(self):
        exact = {"name": "시각이 지정된 공고", "end": "2026-11-12", "closesAt": "2026-11-12T12:00:10+09:00"}
        date_only = {"name": "날짜만 지정된 공고", "end": "2026-11-12"}
        responses = iter([
            ("2026-11-12", [exact, date_only]),
            ("2026-11-12", [date_only]),
            ("2026-11-13", []),
        ])

        def contests(route):
            today, rows = next(responses)
            route.fulfill(json={"today": today, "running": False, "sources": [], "contests": rows})

        with sync_playwright() as playwright, playwright.chromium.launch(channel="msedge") as browser:
            page = browser.new_page()
            page.clock.install(time=datetime(2026, 11, 12, 3, tzinfo=timezone.utc))
            page.route(BOARD + "/**", serve_board)
            page.route(BOARD + "/api/contests", contests)
            page.goto(BOARD)
            exact_row = page.get_by_role("button", name=exact["name"], exact=True)
            date_row = page.get_by_role("button", name=date_only["name"], exact=True)
            expect(exact_row).to_be_visible()
            expect(date_row).to_be_visible()
            page.clock.fast_forward(11_000)
            expect(exact_row).to_have_count(0)
            expect(date_row).to_be_visible()
            page.clock.fast_forward(12 * 60 * 60 * 1000)
            expect(date_row).to_have_count(0)
            expect(page.get_by_role("button", name="수집 새로고침")).to_be_enabled()


class DetizenListingTests(unittest.TestCase):
    def test_similar_card_titles_open_their_own_details(self):
        source = Source("대티즌 테스트", "https://example.org/", frozenset({"example.org"}), frozenset())
        reader = Mock(source=source)
        reader.poster.return_value = None
        html = """<!doctype html><meta charset="utf-8"><button>공모전</button><main></main><script>
        const titles = {one: '서울 청년 앱 개발 공모전', two: '청년 앱 개발 공모전'};
        const period = '2026-11-12 ~ 2026-12-12';
        const main = document.querySelector('main');
        function showList() {
            history.pushState({}, '', '/');
            main.innerHTML = '<div class="__postGrid">' + Object.entries(titles).map(([id, title]) =>
                `<button class="__postCard" onclick="showDetail('${id}')"><img alt="${title}"><span>${title}</span><div>${period}</div></button>`
            ).join('') + '</div>';
        }
        function showDetail(id) {
            history.pushState({}, '', '/contests/' + id);
            main.innerHTML = `<button onclick="showList()">← 목록으로</button><article><div><h1>${titles[id]}</h1></div>
                <div class="__infoRow"><span class="__infoLabel">기간</span><span class="__infoValue">${period}</span></div></article>`;
        }
        showList();
        </script>"""
        with sync_playwright() as playwright, playwright.chromium.launch(channel="msedge") as browser:
            page = browser.new_page()
            page.route("https://example.org/**", lambda route: route.fulfill(body=html, content_type="text/html; charset=utf-8"))
            result = Collection()
            collect_detizen(page, reader, result, datetime(2026, 11, 12, 12, tzinfo=SEOUL))
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.candidates, 2)
        self.assertEqual(
            [row["sourceUrl"] for row in result.records],
            ["https://example.org/contests/one", "https://example.org/contests/two"],
        )


if __name__ == "__main__":
    unittest.main()

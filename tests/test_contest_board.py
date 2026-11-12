from datetime import datetime, timedelta
from http.client import RemoteDisconnected
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import MagicMock, Mock, patch

from scrapling import Selector

from app import Board, SOURCES
from collect import Collection, Reader, SEOUL, amount, collect_source, contestkorea, dates, image_kind, include_record, is_accepting, period_dates, prizes, source_url, wevity, wevity_list
from development import DEVELOPMENT_SCOPE, development_candidate, development_contest


class ParsingTests(unittest.TestCase):
    def test_korean_date_formats_and_invalid_date(self):
        self.assertEqual(dates("2026-08-03 ~ 2026-10-08 D+35"), ("2026-08-03", "2026-10-08"))
        self.assertEqual(dates("2026년 11월 11일 ~ 2026년 12월 11일"), ("2026-11-11", "2026-12-11"))
        self.assertEqual(dates("26.12.01~27.01.05"), ("2026-12-01", "2027-01-05"))
        self.assertEqual(dates("2026-02-30"), (None, None))
        self.assertEqual(dates("2026-12-05 ~ 2026-12-01"), (None, None))

    def test_uses_currency_amounts_for_numeric_sort(self):
        for label, value in [
            ("5천만원이상", 50_000_000), ("2,000만원", 20_000_000),
            ("1억 미만~5천만원 이상", 50_000_000), ("1억 2천만원", 120_000_000),
            ("상장 및 혜택", None), ("상금 120,000원", 120_000),
        ]:
            with self.subTest(label=label):
                self.assertEqual(amount(label), value)
        self.assertEqual(prizes("총상금 600만원\n- 대상(1) 상금 100만원\n- 대상(1) 상금 200만원"), ("600만원", "200만원"))
        self.assertEqual(prizes("마감일 2026-11-20\n최우수상 20만원"), (None, None))

    def test_validates_poster_format_and_source_url(self):
        self.assertEqual(image_kind(b"RIFF....WEBP"), "webp")
        self.assertIsNone(image_kind(b"<html>no poster</html>"))
        hosts = SOURCES["contestkorea"].hosts
        base = SOURCES["contestkorea"].list_url
        url = source_url("/admincenter/files/meet/공모전 포스터.jpg", base, hosts)
        self.assertIn("%20", url)
        self.assertNotIn("공모전", url)
        self.assertIsNone(source_url("//external.invalid/poster.jpg", base, hosts))
        self.assertIsNone(source_url("https://www.contestkorea.com:8080/private", base, hosts))

    def test_wevity_keeps_source_fields_and_blank_sponsor(self):
        doc = Selector("""
            <meta property="og:title" content="핀테크 앱 개발 공모전">
            <meta property="og:image" content="https://www.wevity.com/upload/contest/poster.jpg">
            <ul class="cd-info-list">
              <li><span class="tit">분야</span>기획/아이디어</li>
              <li><span class="tit">응모대상</span>제한없음</li>
              <li><span class="tit">주최/주관</span>가상 주최 기관</li>
              <li><span class="tit">후원/협찬</span></li>
              <li><span class="tit">접수기간</span>2026-08-03 ~ 2026-10-08 <span>D+34</span></li>
              <li><span class="tit">총 상금</span>5천만원이상</li>
              <li><span class="tit">1등 상금</span>2,000만원</li>
              <li><span class="tit">홈페이지</span><a href="https://example.org/contest">홈페이지</a></li>
            </ul>
        """)
        reader = Mock(source=SOURCES["wevity"])
        reader.poster.return_value = "/posters/example.jpg"
        row = wevity(reader, doc, SOURCES["wevity"].list_url)
        self.assertEqual((row["category"], row["audience"], row["end"]), ("기획/아이디어", "제한없음", "2026-10-08"))
        self.assertEqual(row["firstAmount"], 20_000_000)
        self.assertIsNone(row["sponsor"])
        self.assertEqual(row["homepage"], "https://example.org/contest")
        batch = Collection()
        include_record(batch, reader, row, datetime(2026, 9, 1, tzinfo=SEOUL))
        self.assertEqual(batch.records[0]["poster"], "/posters/example.jpg")

    def test_contestkorea_uses_own_poster_instead_of_global_banner(self):
        doc = Selector("""
            <meta property="og:image" content="http://www.contestkorea.com/admincenter/files/meet/actual.jpg">
            <img src="/admincenter/files/meet/unrelated.jpg" alt="사이트 홍보 배너">
            <h1>가상 웹 개발 공모전</h1>
            <table><tr><th scope="row">주최 . 주관</th><td>가상 기관</td></tr></table>
        """)
        reader = Mock(source=SOURCES["contestkorea"])
        url = "https://www.contestkorea.com/sub/view.php?str_no=1"
        row = contestkorea(reader, doc, url)
        self.assertEqual(row["organizer"], "가상 기관")
        include_record(Collection(), reader, row, datetime(2026, 11, 12, tzinfo=SEOUL), listed_open=True)
        reader.poster.assert_called_once_with("http://www.contestkorea.com/admincenter/files/meet/actual.jpg", url)


class DevelopmentTests(unittest.TestCase):
    def test_excludes_creative_ai_and_includes_technical_deliverables(self):
        self.assertFalse(development_candidate("광명역 AI 영상 공모전", "IT/AI/데이터"))
        self.assertFalse(development_contest("AI 영상 공모전", "웹/모바일/IT", "게임 개발에도 쓰이는 AI 도구"))
        self.assertFalse(development_candidate("AI 모델을 활용한 영상 공모전", "IT/AI/데이터"))
        self.assertFalse(development_contest("코딩 부트캠프 수강생 모집"))
        self.assertFalse(development_contest("위치정보 컨설팅 참여기업 모집", "IT/AI/데이터", "데이터 분석 지원"))
        self.assertFalse(development_contest("AI 아이디어 공모전", "IT/AI/데이터", "AI 모델을 활용한 아이디어 설명"))
        self.assertTrue(development_contest("차량용 앱 개발 공모전"))
        self.assertTrue(development_contest("성평등 AI 벤치마크 챌린지"))
        self.assertTrue(development_contest("조달청 AI 게임·콘텐츠 공모전", "사진/영상/UCC", "게임 실행 파일: exe, html"))

    def test_only_loads_development_candidates_and_their_posters(self):
        source = SOURCES["wevity"]
        listing = Selector("""
            <div class="tit"><a href="?ix=1">AI 숏폼 공모전</a><div class="sub-tit">웹/모바일/IT</div></div>
            <div class="tit"><a href="?ix=2">앱 개발 공모전</a></div>
        """)
        detail = Selector("""
            <meta property="og:title" content="앱 개발 공모전">
            <meta property="og:image" content="https://www.wevity.com/upload/contest/poster.jpg">
            <ul class="cd-info-list"><li><span class="tit">접수기간</span>2026-11-12 ~ 2026-11-20</li></ul>
        """)
        reader = Mock(source=source)
        reader.document.side_effect = [listing, detail]
        reader.poster.return_value = "/posters/app.jpg"
        with patch("collect.Reader", return_value=reader):
            result = collect_source("wevity", Path("."), datetime(2026, 11, 13, tzinfo=SEOUL))
        self.assertEqual((result.pages, result.candidates, result.failed), (1, 1, 0))
        self.assertEqual([record["name"] for record in result.records], ["앱 개발 공모전"])
        self.assertEqual(reader.document.call_count, 2)
        self.assertTrue(reader.document.call_args.args[0].endswith("ix=2"))
        reader.poster.assert_called_once()


class ActiveListingTests(unittest.TestCase):
    def test_transient_read_failure_is_retried_once(self):
        source = SOURCES["contestkorea"]
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"poster"
        response.__enter__.return_value.geturl.return_value = source.list_url
        opener = Mock()
        opener.open.side_effect = [RemoteDisconnected(), response]
        with patch("collect.build_opener", return_value=opener), patch("collect.sleep"):
            self.assertEqual(Reader(source, Path(".")).read(source.list_url, 50, source.hosts)[0], b"poster")
        self.assertEqual(opener.open.call_count, 2)

    def test_seoul_open_and_close_times_and_listing_status(self):
        start, opens, end, closes = period_dates("2026-11-10 09:00 ~ 2026-11-12 18:00")
        row = {"start": start, "opensAt": opens, "end": end, "closesAt": closes}
        self.assertFalse(is_accepting(row, datetime(2026, 11, 10, 8, 59, tzinfo=SEOUL)))
        self.assertTrue(is_accepting(row, datetime(2026, 11, 12, 17, 59, tzinfo=SEOUL)))
        self.assertFalse(is_accepting(row, datetime(2026, 11, 12, 18, tzinfo=SEOUL)))
        self.assertEqual(period_dates("2026-11-12 ~ 2026-11-12 24:00")[3], "2026-11-13T00:00:00+09:00")
        self.assertTrue(is_accepting({"listedOpen": True}, datetime(2026, 11, 12, tzinfo=SEOUL)))
        self.assertFalse(is_accepting({"start": "2026-11-13", "listedOpen": True}, datetime(2026, 11, 12, tzinfo=SEOUL)))

    def test_closed_detail_skips_poster_download(self):
        reader = Mock()
        batch = Collection()
        include_record(
            batch, reader, {"end": "2026-11-11", "sourceUrl": "https://example.org/closed", "image": "/image.jpg"},
            datetime(2026, 11, 12, tzinfo=SEOUL), listed_open=True,
        )
        self.assertEqual(batch.records, [])
        reader.poster.assert_not_called()

    @staticmethod
    def page(ids, next_page=False):
        items = "".join(f'<div class="tit"><a href="?ix={identifier}">공고</a></div>' for identifier in ids)
        pager = '<div class="list-navi"><a href="?gp=2&amp;mode=ing">&gt;</a></div>' if next_page else ""
        return Selector(items + pager)

    def test_follows_all_pages_and_deduplicates_overlapping_listings(self):
        reader = Mock(source=SOURCES["wevity"])
        reader.document.side_effect = [self.page(range(1, 13), True), self.page(range(12, 18))]
        batch, candidates = Collection(), {}
        wevity_list(reader, batch, candidates)
        self.assertEqual(batch.pages, 2)
        self.assertEqual(list(candidates), [str(identifier) for identifier in range(1, 18)])
        self.assertEqual(reader.document.call_count, 2)

    def test_repeated_page_does_not_count_as_completed(self):
        reader = Mock(source=SOURCES["wevity"])
        reader.document.return_value = self.page(range(1, 13), True)
        batch, candidates = Collection(), {}
        with self.assertRaisesRegex(ValueError, "did not advance"):
            wevity_list(reader, batch, candidates)
        self.assertEqual(batch.pages, 1)
        self.assertEqual(len(candidates), 12)


class BoardTests(unittest.TestCase):
    def test_failed_snapshot_keeps_previous_rows_and_allows_other_saves(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            board = Board(directory)
            end = (datetime.now(SEOUL).date() + timedelta(days=1)).isoformat()
            old = {"name": "이전 앱 개발 공고", "end": end}
            board.results["detizen"] = {"state": "ok", "scope": DEVELOPMENT_SCOPE, "contests": [old]}
            board.running = True
            board.pending = set(SOURCES)
            replace = Path.replace
            attempts = []

            def persist(path, target):
                attempts.append(target)
                if len(attempts) == 1:
                    raise PermissionError("snapshot locked")
                return replace(path, target)

            def collect(key, posters, now):
                return Collection(records=[{"name": key + " 앱 개발", "end": end}], pages=1, candidates=1)

            with patch("app.collect_source", side_effect=collect), patch("app.as_completed", side_effect=iter):
                with patch.object(Path, "replace", persist):
                    board.collect()
                failed = board.view()
                self.assertFalse(failed["running"])
                self.assertEqual(len(attempts), len(SOURCES))
                self.assertEqual(failed["sources"][0]["state"], "error")
                self.assertIn("저장하지 못했습니다", failed["sources"][0]["message"])
                self.assertIn(old, failed["contests"])
                self.assertNotIn({"name": "detizen 앱 개발", "end": end}, failed["contests"])
                self.assertTrue(all(site["state"] == "ok" for site in failed["sources"][1:]))
                self.assertEqual(Board(directory).view()["contests"], failed["contests"])

                board.collect()
                recovered = Board(directory).view()
                self.assertTrue(all(site["state"] == "ok" for site in recovered["sources"]))
                self.assertIn({"name": "detizen 앱 개발", "end": end}, recovered["contests"])
                self.assertNotIn(old, recovered["contests"])

    def test_single_refresh_and_persisted_results_after_source_error(self):
        with TemporaryDirectory() as folder:
            board = Board(Path(folder))
            today = datetime.now(SEOUL).date()
            end = (today + timedelta(days=1)).isoformat()
            old = {"name": "이전 앱 개발 공고", "source": SOURCES["detizen"].name, "poster": None, "end": end}
            board.results["detizen"] = {"contests": [old], "state": "ok", "scope": DEVELOPMENT_SCOPE}
            prior = {"name": "위비티 앱 개발 이전 공고", "source": SOURCES["wevity"].name, "poster": None, "end": end,
                     "sourceUrl": "https://www.wevity.com/?ix=1"}
            closed = {**prior, "name": "마감 공고", "end": (today - timedelta(days=1)).isoformat(),
                      "sourceUrl": "https://www.wevity.com/?ix=2"}
            board.results["wevity"] = {"contests": [prior, closed], "state": "ok"}
            gate = Event()

            def collect(key, posters, now):
                if not gate.wait(3):
                    raise TimeoutError()
                if key == "detizen":
                    raise ValueError("Unavailable")
                if key == "thinkcontest":
                    return Collection(pages=1)
                if key == "wevity":
                    fresh = {**prior, "name": "위비티 앱 개발 새 공고", "sourceUrl": "https://www.wevity.com/?ix=3"}
                    return Collection(records=[fresh], pages=2, candidates=1, listing_problem=True)
                return Collection(
                    records=[{"name": "새 앱 개발 공고", "source": SOURCES[key].name, "poster": "/posters/fixture.jpg", "end": end}],
                    pages=2, candidates=1,
                )

            with patch("app.collect_source", side_effect=collect):
                self.assertTrue(board.refresh())
                self.assertFalse(board.refresh())
                prior_view = {**prior, "sourceLinks": [
                    {"source": prior["source"], "url": prior["sourceUrl"], "title": prior["name"]},
                ]}
                self.assertEqual(board.view()["contests"], [old, prior_view])
                gate.set()
                deadline = monotonic() + 5
                while board.view()["running"] and monotonic() < deadline:
                    sleep(0.01)
            self.assertFalse(board.view()["running"])
            restored = Board(Path(folder)).view()
            self.assertEqual(restored["sources"][0]["state"], "error")
            self.assertIn(old, restored["contests"])
            self.assertEqual(restored["sources"][2]["state"], "partial")
            self.assertIn(prior_view, restored["contests"])
            self.assertNotIn(closed["sourceUrl"], [row.get("sourceUrl") for row in restored["contests"]])
            self.assertEqual(restored["sources"][-1]["state"], "ok")
            self.assertEqual(restored["sources"][-1]["count"], 0)
            self.assertEqual(len(restored["contests"]), 5)


if __name__ == "__main__":
    unittest.main()

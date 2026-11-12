from datetime import datetime
import unittest

from contest_groups import group_contests


NOW = datetime.fromisoformat("2026-11-13T12:00:00+09:00")


def listing(source, slug, **fields):
    return {
        "name": "2026 서울관광 프롬프톤", "organizer": "서울관광재단",
        "start": "2026-11-09", "end": "2026-11-29",
        "source": source, "sourceUrl": f"https://{source}.example/{slug}",
        **fields,
    }


class ContestGroupingTests(unittest.TestCase):
    def test_combines_title_and_date_variations_without_losing_urls(self):
        rows = [
            listing("first", "123", name="[2026 서울관광 프롬프톤] 참가자모집", organizer="서울관광재단/서울관광재단"),
            listing("second", "456", start="2026-11-10"),
            listing("third", "789", organizer="서울관광재", homepage="https://prompt2026.example/"),
            listing("first", "234", poster="/posters/fixture.jpg", homepage="http://prompt2026.example/?utm_source=first"),
        ]
        grouped = group_contests([*rows, rows[-1]], NOW)
        self.assertEqual(len(grouped), 1)
        row = grouped[0]
        self.assertEqual(row["name"], "2026 서울관광 프롬프톤")
        self.assertEqual(row["start"], "2026-11-09")
        self.assertEqual(row["poster"], "/posters/fixture.jpg")
        self.assertEqual(row["sourceUrl"], rows[-1]["sourceUrl"])
        self.assertEqual(row["sourceLinks"], [
            {"source": item["source"], "url": item["sourceUrl"], "title": item["name"]}
            for item in rows
        ])
        self.assertTrue(all("sourceLinks" not in item for item in rows))

    def test_keeps_editions_tracks_and_unrelated_announcements_separate(self):
        common = {"homepage": "https://organizer.example/", "organizer": "공모전협회"}
        titles = (
            "제1회 공모전협회 전국 앱 개발 경진대회",
            "제2회 공모전협회 전국 앱 개발 경진대회",
            "공모전협회 앱 개발 해커톤 고등부 트랙",
            "공모전협회 앱 개발 해커톤 대학생 트랙",
            "공모전협회 AI 데이터 분석 경진대회",
        )
        rows = [listing("first", str(index), name=title, **common) for index, title in enumerate(titles)]
        rows.append(listing("second", "later", **common, name=titles[0], end="2026-11-30"))
        rows.append(listing("third", "unrelated", name=titles[0], organizer="다른기관"))
        self.assertEqual(len(group_contests(rows, NOW)), len(rows))

    def test_keeps_all_links_until_the_published_deadline(self):
        closes = "2026-11-13T18:00:00+09:00"
        rows = [
            listing("first", "123", end="2026-11-13"),
            listing("second", "456", end="2026-11-13", closesAt=closes),
        ]
        [group] = group_contests(rows, NOW)
        self.assertEqual(group["closesAt"], closes)
        self.assertEqual(len(group["sourceLinks"]), 2)
        self.assertEqual(group_contests(rows, datetime.fromisoformat(closes)), [])

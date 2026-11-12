"""Verify a running local board against the five public sites in Microsoft Edge."""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


def original_urls(rows):
    return rows.evaluate_all("""rows => rows.map(row =>
        [...row.querySelectorAll("td:last-child a")].map(link => link.href))""")


def open_detail(link, page):
    destination = urlsplit(link.get_attribute("href"))
    with page.context.expect_page(timeout=15_000) as opened:
        link.click()
    detail = opened.value
    try:
        detail.wait_for_load_state("domcontentloaded", timeout=15_000)
        actual = urlsplit(detail.url)
        assert actual.hostname.removeprefix("www.") == destination.hostname.removeprefix("www.")
        assert actual.path.rstrip("/") == destination.path.rstrip("/")
    finally:
        detail.close()


def verify(page, url, data, screenshots, refresh):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url, wait_until="domcontentloaded")
    reload_button = page.get_by_role("button", name="수집 새로고침")
    expect(page.get_by_role("heading", name="개발 공모전")).to_be_visible()
    navigation = page.get_by_role("navigation", name="수집 페이지")
    current_page = navigation.get_by_role("link", name="개발 공모전")
    expect(current_page).to_have_attribute("aria-current", "page")
    expect(current_page).to_have_attribute("href", "/")
    onoffmix = page.get_by_role("link", name="온오프믹스 목록")
    onoffmix_url = urlsplit(onoffmix.get_attribute("href"))
    assert onoffmix_url.hostname in {"onoffmix.com", "www.onoffmix.com"}
    assert parse_qs(onoffmix_url.query).get("c") == ["105"]
    if refresh:
        expect(reload_button).to_be_enabled(timeout=120_000)
        with page.expect_response(lambda response: response.url.endswith("/api/refresh")) as response:
            reload_button.click()
        assert response.value.status == 202
        expect(reload_button).to_be_disabled()
    expect(reload_button).to_be_enabled(timeout=120_000)
    state = page.request.get(url + "api/contests").json()
    assert not state["running"]
    assert {site["key"] for site in state["sources"]} == {"detizen", "contestkorea", "wevity", "allforyoung", "thinkcontest"}
    assert len(state["contests"]) > 0
    assert not any(row["name"] == "SPECIAL PICK" for row in state["contests"])
    assert any(site["pages"] > 1 for site in state["sources"]), "전체 페이지 수집을 확인할 표본이 없습니다."
    now = datetime.now(timezone(timedelta(hours=9)))
    for row in state["contests"]:
        assert not row.get("start") or row["start"] <= state["today"], row["name"]
        assert row.get("end", None) is not None or row.get("listedOpen"), row["name"]
        assert not row.get("end") or row["end"] >= state["today"], row["name"]
        assert not row.get("opensAt") or datetime.fromisoformat(row["opensAt"]) <= now, row["name"]
        assert not row.get("closesAt") or datetime.fromisoformat(row["closesAt"]) > now, row["name"]
    saved = json.loads((data / "contests.json").read_text(encoding="utf-8"))
    table = page.get_by_role("table", name="공모전 목록")
    search = page.get_by_role("searchbox", name="공모전 검색")
    rows = table.locator("tbody tr")
    expect(rows).to_have_count(len(state["contests"]))
    assert Counter(tuple(urls) for urls in original_urls(rows)) == Counter(
        tuple(link["url"] for link in item["sourceLinks"]) for item in state["contests"]
    )

    for site in state["sources"]:
        assert site["state"] == "ok" and site["failed"] == 0 and site["pages"] > 0, site
        snapshot = saved[site["key"]]
        assert snapshot["scope"] == "accepting-development"
        assert len(snapshot["contests"]) <= site["candidates"], site
        items = [
            row for row in state["contests"]
            if any(link["source"] == site["name"] for link in row["sourceLinks"])
        ]
        urls = {link["url"] for item in items for link in item["sourceLinks"] if link["source"] == site["name"]}
        assert urls <= {item["sourceUrl"] for item in snapshot["contests"]}
        if not items:
            continue
        with_poster = [item for item in items if item["poster"]]
        assert any(item["organizer"] and item["end"] for item in with_poster), site
        assert all((data / item["poster"].lstrip("/")).is_file() for item in with_poster)

        table.get_by_role("button", name="사이트출처", exact=True).click()
        menu = page.get_by_role("region", name="사이트출처", exact=True)
        for option in menu.get_by_role("checkbox").all():
            if option.locator("..").inner_text().strip() != site["name"]:
                option.uncheck()
        menu.get_by_role("button", name="필터 적용").click()
        expect(rows).to_have_count(len(items))
        assert Counter(tuple(urls) for urls in original_urls(rows)) == Counter(
            tuple(link["url"] for link in item["sourceLinks"]) for item in items
        ), site
        displayed = rows.locator("img")
        expect(displayed).to_have_count(len(with_poster))
        sizes = displayed.evaluate_all("""async images => {
            return await Promise.all(images.slice(0, 3).map(async img => {
                img.loading = "eager";
                await img.decode();
                return img.naturalWidth * img.naturalHeight;
            }));
        }""")
        assert all(size > 0 for size in sizes), site
        posters = rows.locator("td:first-child a")
        assert sorted(posters.evaluate_all("links => links.map(link => link.getAttribute('href'))")) == sorted(
            item["sourceUrl"] for item in with_poster
        ), site
        original = rows.locator("td:last-child").get_by_role("link", name=site["name"] + " 공고 원문 열기").first
        open_detail(original, page)
        if page.get_by_role("button", name="필터 초기화").is_visible():
            page.get_by_role("button", name="필터 초기화").click()
        print(f"{site['name']}: 수집 공고 {site['count']}건, 표시 {len(items)}행, 원문 링크 이동 확인", flush=True)

    open_detail(rows.locator("td:first-child a").first, page)

    quick_filter = page.get_by_role("combobox", name="출처", exact=True)
    merged = next((item for item in state["contests"] if len(item["sourceLinks"]) > 1), None)
    if merged:
        site = merged["sourceLinks"][-1]["source"]
        quick_filter.select_option(site)
        expect(rows.filter(has_text=merged["name"]).locator("td:last-child a")).to_have_count(len(merged["sourceLinks"]))
        page.get_by_role("button", name="필터 초기화").click()

    sample = next(row for row in state["contests"] if row["name"] and row["organizer"])
    search.fill(sample["name"])
    expect(table.get_by_role("button", name=sample["name"], exact=True).first).to_be_visible()
    search.fill("일치불가-테스트-7c69f")
    expect(table.get_by_text("조건에 맞는 공모전이 없습니다.")).to_be_visible()
    page.get_by_role("button", name="필터 초기화").click()

    category = table.get_by_role("columnheader", name="분야")
    expect(category).to_be_hidden()
    page.get_by_role("button", name="전체 열", exact=True).click()
    expect(category).to_be_visible()
    cell = rows.locator('td[data-key="category"] button').first
    cell.click()
    expect(page.get_by_role("region", name="분야", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("region", name="분야", exact=True)).to_be_hidden()
    page.get_by_role("button", name="주요 열", exact=True).click()
    expect(category).to_be_hidden()

    prizes = {tuple(link["url"] for link in row["sourceLinks"]): row["totalAmount"] for row in state["contests"]}
    total = table.get_by_role("button", name="총 상금", exact=True)
    for descending, name in [(False, "↑ 오름차순"), (True, "↓ 내림차순")]:
        total.click()
        page.get_by_role("button", name=name, exact=True).click()
        actual = [prizes[tuple(urls)] for urls in original_urls(rows) if prizes[tuple(urls)] is not None]
        assert len(set(actual)) >= 2
        assert actual == sorted(actual, reverse=descending), "금액 숫자 정렬"

    page.reload(wait_until="domcontentloaded")
    expect(rows).to_have_count(len(state["contests"]))
    for width, height in [(1440, 900), (1024, 768), (851, 768), (850, 768), (820, 1180), (768, 1024), (390, 844), (320, 760)]:
        page.set_viewport_size({"width": width, "height": height})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
        expect(current_page).to_be_in_viewport()
        sidebar = page.locator(".app-sidebar").bounding_box()
        content = page.get_by_role("main").bounding_box()
        if width > 850:
            assert sidebar["x"] + sidebar["width"] <= content["x"], width
        else:
            assert sidebar["y"] + sidebar["height"] <= content["y"], width
        scroll = page.get_by_role("region", name="공모전 표 가로 스크롤")
        assert scroll.evaluate("node => node.scrollWidth <= node.clientWidth"), width
        if screenshots and width in (1440, 390):
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=screenshots / f"contest-board-{width}.png")
    page.get_by_role("button", name="전체 열", exact=True).click()
    expect(category).to_be_visible()
    assert scroll.evaluate("node => node.scrollWidth > node.clientWidth")
    page.get_by_role("button", name="주요 열", exact=True).click()
    expect(category).to_be_hidden()
    mobile_sort = page.get_by_role("button", name="마감 가까운 순")
    mobile_sort.click()
    expect(page.get_by_role("button", name="마감 먼 순")).to_be_visible()
    dates = rows.locator("time").evaluate_all("dates => dates.map(date => date.dateTime)")
    assert dates == sorted(dates, reverse=True)
    page.emulate_media(color_scheme="dark")
    current_page.focus()
    expect(current_page).to_be_focused()
    with page.expect_navigation(wait_until="domcontentloaded"):
        current_page.press("Enter")
    expect(current_page).to_be_in_viewport()
    expect(rows).to_have_count(len(state["contests"]))
    assert not errors, errors
    print("통합 통과 · 수집 메뉴 및 화면 폭 8종, 전체 열, 검색, 출처와 셀 필터, 정렬, 포스터, 원문 링크, 저장 스냅샷")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8768/")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--use-cache", action="store_true")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        with playwright.chromium.launch(channel="msedge", headless=True) as browser:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            verify(page, args.url, args.data, args.screenshots, refresh=not args.use_cache)


if __name__ == "__main__":
    main()

from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import re
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from playwright.sync_api import Error as BrowserError, sync_playwright
from scrapling import Selector

from development import development_candidate, development_contest


@dataclass(frozen=True)
class Source:
    name: str
    list_url: str
    hosts: frozenset[str]
    image_hosts: frozenset[str]


SOURCES = {
    "detizen": Source("대티즌", "https://www.detizen.com/", frozenset({"www.detizen.com", "detizen.com"}), frozenset({"images.potionworks.com"})),
    "contestkorea": Source("콘테스트코리아", "https://www.contestkorea.com/sub/list.php?int_gbn=1&Txt_sortkey=a.str_aedate&Txt_sortword=asc", frozenset({"www.contestkorea.com", "contestkorea.com"}), frozenset()),
    "wevity": Source("위비티", "https://www.wevity.com/?c=find&s=1&gub=1&mode=ing", frozenset({"www.wevity.com", "wevity.com"}), frozenset()),
    "allforyoung": Source("요즘것들", "https://www.allforyoung.com/posts/contest", frozenset({"www.allforyoung.com", "allforyoung.com"}), frozenset({"cdn.allforyoung.com"})),
    "thinkcontest": Source("씽굿", "https://www.thinkcontest.com/thinkgood/user/contest/index.do", frozenset({"www.thinkcontest.com", "thinkcontest.com"}), frozenset()),
}

USER_AGENT = "ContestBoard/0.1"
HTML_LIMIT = 4 * 1024 * 1024
POSTER_LIMIT = 8 * 1024 * 1024
SEOUL = timezone(timedelta(hours=9))
DATE = re.compile(r"(?<!\d)(\d{4}|\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})(?!\d)")
CLOCK = re.compile(r"^\s*(?:일\s*)?(?:\([^)]*\)\s*)?(\d{1,2}):(\d{2})(?!\d)")
MONEY = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:억(?:\s*\d[\d,]*(?:\.\d+)?\s*[천백십]?만)?|[천백십]?만|[천백십])\s*원?|\d[\d,]*(?:\.\d+)?\s*원")


def source_url(value, base, allowed):
    if not value:
        return None
    try:
        url = urljoin(base, value.strip()).split("#", 1)[0]
        parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.hostname in allowed and parsed.port in (None, 443) and not parsed.username:
            path = quote(parsed.path, safe="/%:@!$&'()*+,;=-._~")
            query = quote(parsed.query, safe="/%:@!$&'()*+,;=?-._~")
            return parsed._replace(path=path, query=query).geturl()
    except ValueError:
        pass
    return None


def external_url(value):
    if value:
        try:
            url = value.strip()
            parsed = urlsplit(url)
            if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
                return url
        except ValueError:
            pass
    return None


class SourceRedirect(HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not source_url(newurl, req.full_url, self.hosts):
            raise ValueError("Redirect outside source")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Reader:
    def __init__(self, source, posters):
        self.source = source
        self.posters = posters
        self.last_request = 0.0
        self.images = {}

    def read(self, url, limit, hosts, referer=None):
        url = source_url(url, self.source.list_url, hosts)
        if not url:
            raise ValueError("URL outside source")
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"}
        if referer:
            headers["Referer"] = referer
        opener = build_opener(SourceRedirect(hosts))
        for attempt in range(2):
            sleep(max(0, 0.65 - (monotonic() - self.last_request)))
            self.last_request = monotonic()
            try:
                with opener.open(Request(url, headers=headers), timeout=12) as response:
                    payload = response.read(limit + 1)
                    if len(payload) > limit:
                        raise ValueError("Response exceeded size limit")
                    return payload, response.geturl()
            except OSError as error:
                if attempt or (isinstance(error, HTTPError) and error.code not in {502, 504}):
                    raise
                sleep(1.5)

    def document(self, url):
        payload, resolved = self.read(url, HTML_LIMIT, self.source.hosts)
        return Selector(payload, url=resolved)

    def poster(self, url, referer):
        if url and url.startswith("http://"):
            url = "https://" + url[7:]
        hosts = self.source.hosts | self.source.image_hosts
        url = source_url(url, referer, hosts)
        if not url or re.search(r"(?:no[_-]?image|noimg|og-default|favicon|main_img16|default[_-]?poster)", url, re.I):
            return None
        if url not in self.images:
            try:
                content, _ = self.read(url, POSTER_LIMIT, hosts, referer=referer)
                kind = image_kind(content)
                if not kind:
                    return None
                name = sha256(content).hexdigest()[:32] + "." + kind
                path = self.posters / name
                if not path.exists():
                    temporary = path.with_suffix("." + self.source.name + ".tmp")
                    temporary.write_bytes(content)
                    temporary.replace(path)
                self.images[url] = "/posters/" + name
            except (OSError, ValueError) as error:
                print(f"{self.source.name}: poster unavailable ({type(error).__name__})", flush=True)
                self.images[url] = None
        return self.images[url]


def image_kind(content):
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "webp"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if content[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    return None


def clean(value):
    value = " ".join((value or "").replace("\ufeff", "").replace("\u200b", "").split()).strip()
    return value if value not in {"", "-", "—", "미기재", "미정"} else None


def node_text(node):
    return clean(node.get_all_text()) if node else None


def css_text(doc, selector):
    return node_text(doc.css(selector).first)


def attr(doc, selector, name):
    return doc.css(selector + f"::attr({name})").get()


def meta(doc, name):
    return attr(doc, f'meta[property="og:{name}"]', "content")


def fields_by_label(doc, row_selector, label_selector, value_selector=None):
    result = {}
    for row in doc.css(row_selector):
        label = css_text(row, label_selector)
        if not label:
            continue
        value = css_text(row, value_selector) if value_selector else clean((node_text(row) or "").removeprefix(label))
        result[re.sub(r"[\s./·:]", "", label)] = (value, row)
    return result


def field(fields, *labels):
    for label in labels:
        value, _ = fields.get(label, (None, None))
        if value:
            return value
    return None


def field_link(fields, *labels):
    for label in labels:
        _, row = fields.get(label, (None, None))
        if row:
            url = external_url(attr(row, "a[val2]", "val2") or attr(row, "a[href^=http]", "href"))
            if url:
                return url
    return None


def combine(*values):
    return " / ".join(dict.fromkeys(value for value in values if value)) or None


def period_dates(value):
    value = value or ""
    found = []
    for match in DATE.finditer(value):
        year, month, day = match.groups()
        year = int(year)
        try:
            day = date(year + 2000 if year < 100 else year, int(month), int(day))
        except ValueError:
            continue
        exact = None
        if clock := CLOCK.match(value[match.end():]):
            hour, minute = map(int, clock.groups())
            if hour == 24 and minute == 0:
                exact = datetime.combine(day + timedelta(days=1), time.min, SEOUL)
            elif hour < 24 and minute < 60:
                exact = datetime.combine(day, time(hour, minute), SEOUL)
        found.append((day.isoformat(), exact.isoformat() if exact else None))
        if len(found) == 2:
            return (*found[0], *found[1]) if found[0][0] <= found[1][0] else (None, None, None, None)
    return (None, None, *found[0]) if found else (None, None, None, None)


def dates(value):
    start, _, end, _ = period_dates(value)
    return start, end


def is_accepting(row, now):
    today = now.date().isoformat()
    start, end = row.get("start"), row.get("end")
    if (start and start > today) or (end and end < today):
        return False
    opens, closes = row.get("opensAt"), row.get("closesAt")
    if (opens and now < datetime.fromisoformat(opens)) or (closes and now >= datetime.fromisoformat(closes)):
        return False
    return bool(end or row.get("listedOpen"))


@dataclass
class Collection:
    records: list = dataclass_field(default_factory=list)
    pages: int = 0
    candidates: int = 0
    failed: int = 0
    listing_problem: bool = False


def amount(value):
    values = []
    for match in MONEY.finditer(value or ""):
        text = re.sub(r"[\s,원]", "", match[0])
        total = Decimal(0)
        for number, unit in re.findall(r"(\d+(?:\.\d+)?)(억|천만|백만|십만|만|천|백|십)?", text):
            total += Decimal(number) * {"억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "십만": 100_000, "만": 10_000, "천": 1000, "백": 100, "십": 10, "": 1}[unit]
        values.append(int(total))
    return min(values) if values else None


def copy_lines(node):
    return node.get_all_text(separator="\n", strip=True) if node else ""


def prizes(description):
    total = re.search(r"(?:총\s*상금|총\s*시상금|총\s*상금\s*규모)\s*[:：]?\s*(" + MONEY.pattern + ")", description)
    first = []
    for line in description.splitlines():
        award = re.search(r"(?:^|[\s:：\-])(?:대상|1등|1위)(?=\s|[:：(·])[^\n]{0,70}", line.strip())
        if award:
            money = MONEY.search(award[0])
            if money and "원" in money[0]:
                first.append(money[0])
    return (clean(total[1]) if total else None, clean(max(first, key=lambda value: amount(value) or 0)) if first else None)


def contest(reader, url, name, *, image=None, category=None, audience=None, organizer=None,
            sponsor=None, period=None, total=None, first=None, homepage=None, description=""):
    name = clean(name)
    if not name:
        raise ValueError("Missing contest title")
    start, opens, end, closes = period_dates(period)
    total_from_text, first_from_text = prizes(description)
    total = total or total_from_text
    first = first or first_from_text
    return {
        "name": name, "category": clean(category), "audience": clean(audience), "organizer": clean(organizer),
        "sponsor": clean(sponsor), "start": start, "end": end, "opensAt": opens, "closesAt": closes, "total": clean(total),
        "totalAmount": amount(total), "first": clean(first), "firstAmount": amount(first),
        "homepage": external_url(homepage), "source": reader.source.name, "sourceUrl": url,
        "image": image, "_development": development_contest(name, category, description),
    }


def include_record(result, reader, record, now, listed_open=False):
    record["listedOpen"] = listed_open
    if is_accepting(record, now) and record.pop("_development", False):
        record["poster"] = reader.poster(record.pop("image"), record["sourceUrl"])
        result.records.append(record)


def browser_context(playwright):
    browser = playwright.chromium.launch(channel="msedge", headless=True)
    context = browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul")
    context.set_default_timeout(12000)
    context.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "media", "font"} else route.continue_())
    return browser, context


def links_from(doc, css, source, key, labels):
    found = {}
    for link in doc.css(css):
        url = source_url(link.attrib.get("href"), source.list_url, source.hosts)
        if url and (identifier := key(url)) is not None:
            found.setdefault(identifier, (url, *labels(link)))
    return found


def query(url, key):
    return parse_qs(urlsplit(url).query).get(key, [None])[0]


def wevity(reader, doc, url):
    fields = fields_by_label(doc, ".cd-info-list > li", ".tit")
    return contest(
        reader, url, meta(doc, "title"),
        image=attr(doc, '.thumb img[src*="/upload/contest/"]', "src") or meta(doc, "image"),
        category=field(fields, "분야"), audience=field(fields, "응모대상"), organizer=field(fields, "주최주관"),
        sponsor=field(fields, "후원협찬"), period=field(fields, "접수기간"),
        total=field(fields, "총상금"), first=field(fields, "1등상금"), homepage=field_link(fields, "홈페이지"),
        description=copy_lines(doc.css("#viewContents").first),
    )


def contestkorea(reader, doc, url):
    fields = fields_by_label(doc, "tr:has(th[scope=row])", "th", "td")
    reward = field(fields, "시상내역")
    title = css_text(doc, "h1") or meta(doc, "title")
    image = meta(doc, "image")
    if not image or "/admincenter/files/meet/" not in image:
        image = next(
            (img.attrib.get("src") for img in doc.css('img[src*="/admincenter/files/meet/"][alt]') if clean(img.attrib["alt"]) == title),
            None,
        )
    return contest(
        reader, url, title, image=image,
        category=field(fields, "대표분야", "분야"), audience=field(fields, "참가대상", "응모대상"),
        organizer=field(fields, "주최주관"), sponsor=field(fields, "후원협찬", "후원", "협찬"),
        period=field(fields, "접수기간"), total=field(fields, "총상금"),
        first=field(fields, "1등상금"), homepage=field_link(fields, "홈페이지"),
        description=copy_lines(doc.css(".view_detail_area .txt").first) or reward or "",
    )


def thinkcontest(reader, doc, url):
    fields = fields_by_label(doc, ".info > div:has(.tit)", ".tit", ".txt")
    reward = field(fields, "시상종류", "시상내역")
    return contest(
        reader, url, css_text(doc, ".view-title"),
        image=meta(doc, "image"), category=field(fields, "응모분야", "분야"),
        audience=field(fields, "참가자격", "응모대상"),
        organizer=combine(field(fields, "주최"), field(fields, "주관")),
        sponsor=field(fields, "후원협찬", "후원", "협찬"), period=field(fields, "접수기간"),
        total=field(fields, "총상금") or (reward if amount(reward) is not None else None),
        first=field(fields, "1등상금"), homepage=field_link(fields, "홈페이지"),
        description=copy_lines(doc.css("#detailForm .view-tab").first),
    )


def adjacent_text(doc, selector, label):
    for node in doc.css(selector):
        if node_text(node) == label:
            content = node_text(node.parent)
            return clean(content.removeprefix(label)) if content else None
    return None


def named_line(description, label):
    match = re.search(r"(?m)^[ \t]*(?:[■□●◆○-][ \t]*)?(?:" + label + r")(?=[\s:：])[ \t]*[:：]?[ \t]*(?:\n[ \t]*[-·]?[ \t]*)?([^\n]+)", description)
    if match:
        text = clean(match[1])
        if text and len(text) <= 180:
            return text.lstrip("-· ")
    return None


def allforyoung(reader, doc, url):
    title = doc.css("main h1").first
    summary = title.parent.parent if title else None
    tags = []
    if summary:
        for tag in summary.css('[data-slot="badge"]'):
            label = node_text(tag)
            if label and label.startswith("#"):
                tags.append(label.lstrip("#"))
    description = copy_lines(doc.css("main .tiptap-content").first)
    return contest(
        reader, url, node_text(title),
        image=meta(doc, "image"), category=", ".join(dict.fromkeys(tags)) or named_line(description, r"공모\s*분야"),
        audience=named_line(description, r"참가\s*대상|지원\s*대상|응모\s*대상|참가\s*자격|지원\s*자격"),
        organizer=adjacent_text(doc, "main p", "주최/주관"),
        sponsor=named_line(description, r"후원\s*/\s*협찬|후원사?|협찬사?"),
        period=css_text(doc, "main time"), homepage=attr(doc, 'main a[aria-label="지원하기"]', "href"),
        description=description,
    )


def detizen(reader, doc, url, poster, name):
    fields = fields_by_label(doc, '[class*="__infoRow"]', '[class*="__infoLabel"]', '[class*="__infoValue"]')
    heading = doc.css("h1").last
    organizer = css_text(heading.parent.parent, "p") if heading else None
    reward = field(fields, "시상내역")
    description = "\n".join(copy_lines(section) for section in doc.css('section[class*="ContestDetailView"][class*="__section"]'))
    return contest(
        reader, url, node_text(heading) or name, image=poster,
        category=field(fields, "분야", "공모분야"), audience=field(fields, "대상", "응모대상"),
        organizer=field(fields, "주최주관", "주최") or organizer,
        sponsor=field(fields, "후원협찬", "후원", "협찬") or named_line(description, r"후원\s*/\s*협찬|후원|협찬"),
        period=field(fields, "기간", "접수기간"), total=field(fields, "총상금") or (reward if amount(reward) is not None else None),
        first=field(fields, "1등상금"), homepage=field_link(fields, "홈페이지"),
        description=description,
    )


PARSERS = {"wevity": wevity, "contestkorea": contestkorea, "thinkcontest": thinkcontest, "allforyoung": allforyoung}
NO_LISTINGS = re.compile(r"(?:등록된|검색된|조건에 맞는)\s*(?:공모전|공고|게시물|내역|데이터|결과|목록)(?:이|가)?\s*없|검색 결과가 없")
DETAIL_ERRORS = (BrowserError, OSError, ValueError)


def contest_id(key, url):
    parameters = {"wevity": "ix", "contestkorea": "str_no", "thinkcontest": "contest_pk"}
    if key in parameters:
        return query(url, parameters[key])
    return urlsplit(url).path.rstrip("/")


def add_page(result, candidates, entries, signature_history, empty=False):
    signature = tuple(entries)
    if signature in signature_history or (not signature and not empty):
        raise ValueError("Listing did not advance or returned an unexpected empty page")
    signature_history.add(signature)
    result.pages += 1
    for identifier, candidate in entries.items():
        candidates.setdefault(identifier, candidate)


def wevity_list(reader, result, candidates):
    source = reader.source
    url = source.list_url
    signatures = set()
    while url:
        doc = reader.document(url)
        links = links_from(
            doc, '.tit > a[href*="ix="]', source, lambda url: contest_id("wevity", url),
            lambda link: (node_text(link), css_text(link.parent, ".sub-tit")),
        )
        entries = {identifier: (link, True, title, category) for identifier, (link, title, category) in links.items()}
        add_page(result, candidates, entries, signatures, bool(NO_LISTINGS.search(node_text(doc) or "")))
        raw = next((a.attrib.get("href") for a in doc.css(".list-navi a") if node_text(a) == ">"), None)
        url = source_url(raw, url, source.hosts)
        if raw and not url:
            raise ValueError("Unexpected next listing link")


def contestkorea_list(reader, result, candidates):
    source = reader.source
    signatures = set()
    number = 1
    while True:
        url = source.list_url + f"&page={number}"
        doc = reader.document(url)
        links = doc.css('.list_style_2 .title a[href*="str_no="]')
        entries = {}
        for link in links:
            detail = source_url(link.attrib["href"], url, source.hosts)
            if not detail or query(detail, "int_gbn") != "1":
                continue
            state = css_text(link.parent.parent, ".condition")
            if state not in {"접수중", "마감임박", "오늘마감"}:
                raise ValueError("Open-list status was not confirmed")
            entries[contest_id("contestkorea", detail)] = (detail, True, css_text(link, ".txt"), css_text(link, ".category"))
        pager = doc.css(".pagination").first
        page_links = pager.css('a[href*="page="]') if pager else []
        page_size = next((int(size) for link in page_links if (size := query(link.attrib["href"], "displayrow")) and size.isdecimal()), 12)
        empty = not entries and bool(NO_LISTINGS.search(node_text(doc) or ""))
        if not entries and not empty and number > 1 and pager:
            final = max((int(value) for link in page_links if (value := query(link.attrib["href"], "page")) and value.isdecimal()), default=0)
            empty = 0 < final < number
        if not entries and empty and number > 1:
            break
        add_page(result, candidates, entries, signatures, empty)
        if len(links) < page_size:
            break
        number += 1


def allforyoung_list(page, source, result, candidates):
    url = source.list_url
    signatures = set()
    while url:
        response = page.goto(url, wait_until="domcontentloaded")
        if not response or not response.ok:
            raise ValueError("Listing did not load")
        page.wait_for_function("Array.from(document.links).some(link => /^\\/posts\\/\\d+$/.test(link.pathname)) || /검색 결과가 없|등록된 공고가 없/.test(document.body.innerText)")
        doc = Selector(page.content(), url=page.url)
        links = links_from(
            doc, 'a[href^="/posts/"]', source,
            lambda url: urlsplit(url).path if re.fullmatch(r"/posts/\d+", urlsplit(url).path) else None,
            lambda link: (css_text(link, "h3"), " ".join(node_text(tag) or "" for tag in link.css('[data-slot="badge"]'))),
        )
        entries = {identifier: (link, False, title, category) for identifier, (link, title, category) in links.items()}
        add_page(result, candidates, entries, signatures, bool(NO_LISTINGS.search(node_text(doc) or "")))
        raw = attr(doc, 'nav[data-slot="pagination"] a[aria-label="Go to next page"]:not([aria-disabled="true"])', "href")
        url = source_url(raw, url, source.hosts)
        if raw and not url:
            raise ValueError("Unexpected next listing link")


def thinkcontest_list(page, source, result, candidates):
    page.goto(source.list_url, wait_until="domcontentloaded")
    rows = page.locator('tr[data-reg_type="contest"][data-contest_pk]')
    rows.first.wait_for()

    def change_listing(control):
        with page.expect_response(lambda response: urlsplit(response.url).path == "/thinkgood/user/contest/subList.do") as listing:
            control.click()
        if not listing.value.ok:
            raise ValueError("Listing update failed")

    change_listing(page.locator('.tabMailList[data-search_value="ING"]'))
    signatures = set()
    number = 1
    while True:
        page.wait_for_function("number => document.querySelector('#pagination1 a.on')?.textContent.trim() === number", arg=str(number))
        rows.first.wait_for()
        items = rows.evaluate_all("""rows => rows.map(row => [
            row.getAttribute('data-contest_pk'),
            row.querySelector('.titTd .d-flex > .tit')?.textContent,
            row.querySelector('.category p')?.textContent
        ])""")
        entries = {
            identifier: (urljoin(source.list_url, "view.do?contest_pk=" + identifier), True, title, category)
            for identifier, title, category in items if identifier and re.fullmatch(r"\d+", identifier)
        }
        add_page(result, candidates, entries, signatures)
        next_page = page.locator("#pagination1 a.next")
        if not next_page.count():
            break
        change_listing(next_page)
        number += 1


DETIZEN_CARDS = 'div[class*="__postGrid"] button[class*="__postCard"]'
DETIZEN_PAGER = 'div[class*="__pagination"]:visible'
DETIZEN_CARD_FIELDS = r"""card => {
    const image = card.querySelector("img[alt]");
    const lines = card.innerText.split("\n").map(line => line.trim()).filter(Boolean);
    const period = lines.findLast(line => /\d{4}[-./]\d{1,2}[-./]\d{1,2}/.test(line));
    const name = image?.alt || lines.find(line => line !== period && /[\p{L}\d]/u.test(line));
    return [name, image?.getAttribute("src"), period];
}"""


def detizen_cards(page):
    cards = page.locator(DETIZEN_CARDS).filter(visible=True)
    cards.first.wait_for()
    return cards


def detizen_page(page, number):
    pager = page.locator(DETIZEN_PAGER).first
    active = pager.locator('[class*="__pageBtnActive"]')
    current = (active.inner_text() if active.count() else "1").strip()
    if current == str(number):
        return True
    button = pager.get_by_role("button", name=str(number), exact=True)
    if not button.count():
        return False
    cards = detizen_cards(page)
    previous = cards.all_text_contents()
    button.press("Enter")
    page.wait_for_function(
        "args => { const cards = [...document.querySelectorAll(args.selector)].filter(el => el.getClientRects().length); return cards.length && JSON.stringify(cards.map(el => el.textContent)) !== JSON.stringify(args.previous); }",
        arg={"selector": DETIZEN_CARDS, "previous": previous},
    )
    return True


def collect_detizen(page, reader, result, now):
    page.goto(reader.source.list_url, wait_until="domcontentloaded")
    page.get_by_role("button", name="공모전", exact=True).last.press("Enter")
    signatures = set()
    visited = set()
    number = 1
    while detizen_page(page, number):
        cards = detizen_cards(page)
        entries = cards.evaluate_all(f"cards => cards.map({DETIZEN_CARD_FIELDS})")
        signature = tuple((name, period) for name, _, period in entries)
        if signature in signatures:
            raise ValueError("Listing returned the same page")
        signatures.add(signature)
        result.pages += 1
        for index, entry in enumerate(entries):
            name, poster, period = entry
            if not name:
                continue
            start, end = dates(period)
            if end and not is_accepting({"start": start, "end": end}, now):
                continue
            result.candidates += 1
            try:
                cards = detizen_cards(page)
                current_entries = cards.evaluate_all(f"cards => cards.map({DETIZEN_CARD_FIELDS})")
                if current_entries == entries:
                    card = cards.nth(index)
                elif current_entries.count(entry) == 1 and entries.count(entry) == 1:
                    card = cards.nth(current_entries.index(entry))
                else:
                    raise ValueError("Contest card changed while reading the listing")
                card.press("Enter")
                page.wait_for_url(re.compile(r"/contests/[^/]+/?$"))
                page.locator('[class*="__infoRow"]').first.wait_for()
                url = source_url(page.url, reader.source.list_url, reader.source.hosts)
                if not url or not re.fullmatch(r"/contests/[^/]+/?", urlsplit(url).path):
                    raise ValueError("Unexpected contest detail URL")
                if url not in visited:
                    visited.add(url)
                    record = detizen(reader, Selector(page.content(), url=url), url, poster, name)
                    include_record(result, reader, record, now, bool(start and end))
                else:
                    result.candidates -= 1
            except DETAIL_ERRORS as error:
                result.failed += 1
                print(f"{reader.source.name}: detail unavailable ({type(error).__name__})", flush=True)
            if not page.locator(DETIZEN_CARDS).filter(visible=True).count():
                page.get_by_role("button", name="← 목록으로", exact=True).press("Enter")
                detizen_cards(page)
                if not detizen_page(page, number):
                    raise ValueError("Could not restore listing page")
        number += 1


def collect_source(key, posters, now):
    source = SOURCES[key]
    reader = Reader(source, posters)
    result = Collection()
    candidates = {}
    try:
        if key == "wevity":
            wevity_list(reader, result, candidates)
        elif key == "contestkorea":
            contestkorea_list(reader, result, candidates)
        else:
            with sync_playwright() as playwright:
                browser, context = browser_context(playwright)
                try:
                    page = context.new_page()
                    if key == "detizen":
                        collect_detizen(page, reader, result, now)
                    elif key == "thinkcontest":
                        thinkcontest_list(page, source, result, candidates)
                    else:
                        allforyoung_list(page, source, result, candidates)
                finally:
                    browser.close()
    except DETAIL_ERRORS as error:
        if not result.pages:
            raise
        result.listing_problem = True
        print(f"{source.name}: listing stopped after {result.pages} pages ({type(error).__name__})", flush=True)
    if key != "detizen":
        selected = [(url, listed_open) for url, listed_open, title, category in candidates.values()
                    if development_candidate(title, category)]
        result.candidates = len(selected)
        print(f"{source.name}: {result.pages} listing pages, {result.candidates} detail candidates", flush=True)
        for index, (url, listed_open) in enumerate(selected, 1):
            try:
                record = PARSERS[key](reader, reader.document(url), url)
                include_record(result, reader, record, now, listed_open)
            except DETAIL_ERRORS as error:
                result.failed += 1
                print(f"{source.name}: detail unavailable ({type(error).__name__})", flush=True)
            if index % 50 == 0:
                print(f"{source.name}: {index}/{result.candidates} details checked", flush=True)
    return result

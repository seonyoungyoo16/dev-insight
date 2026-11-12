from collections import Counter, defaultdict
from datetime import date, datetime
from difflib import SequenceMatcher
import re
from unicodedata import normalize
from urllib.parse import parse_qsl, unquote, urlsplit

from collect import is_accepting


YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
LEADING_YEAR = re.compile(r"^\[?20\d{2}(?:년)?\s+")
EDITION = re.compile(r"(?<!\d)(\d+)\s*(회차|회|기)(?![가-힣])|(?:시즌|season)\s*(\d+)", re.I)
RECRUITING = re.compile(r"\s*(?:참가(?:자|팀)\s*모집|참가\s*신청)\s*$")
ENGLISH_SUBTITLE = re.compile(r"\s+[-–—]\s+([A-Za-z][A-Za-z '\u2019!?,.&-]{9,})$")
TRACK = re.compile(r"\b([가-힣A-Za-z0-9]+)\s*(?:부문|트랙|track)\b", re.I)


def compact(value):
    return "".join(character for character in value.casefold() if character.isalnum())


def official_page(url):
    if not url:
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return None
        query = tuple(sorted(
            (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
        ))
        return parts.hostname.removeprefix("www."), unquote(parts.path).rstrip("/"), query
    except ValueError:
        return None


class Listing:
    def __init__(self, row):
        self.row = row
        self.organizers = frozenset(
            compact(name) for name in re.split(r"[/,·;|]", normalize("NFKC", row.get("organizer") or ""))
            if compact(name)
        )
        title = normalize("NFKC", row.get("name") or "").strip()
        self.years = set(YEAR.findall(title))
        self.editions = {(unit.removesuffix("차") or "시즌", int(number or season))
                         for number, unit, season in EDITION.findall(title)}
        self.tracks = set(TRACK.findall(title.casefold()))
        label = re.match(r"^\[([^\]]+)\]\s*", title)
        if label and compact(label[1]) in self.organizers:
            title = title[label.end():]
        title = LEADING_YEAR.sub("", RECRUITING.sub("", title)).strip("[] ")
        self.title = title
        self.title_key = compact(title)
        self.words = re.findall(r"[^\W_]+", title.casefold())
        subtitle = ENGLISH_SUBTITLE.search(title)
        self.main_title = compact(title[:subtitle.start()]) if subtitle else None
        self.homepage = official_page(row.get("homepage"))
        self.start = date.fromisoformat(row["start"]) if row.get("start") else None


def same_contest(left, right):
    if not left.title_key or not right.title_key:
        return False
    for a, b in ((left.years, right.years), (left.editions, right.editions)):
        if a and b and a != b:
            return False
    if left.tracks != right.tracks:
        return False

    shared_homepage = left.homepage is not None and left.homepage == right.homepage
    same_organizer = bool(left.organizers & right.organizers)
    same_title = left.title_key == right.title_key
    start_difference = abs((left.start - right.start).days) if left.start and right.start else None

    if same_title:
        # A source can truncate the organizer by one character.
        similar_organizer = any(
            min(len(a), len(b)) >= 5 and abs(len(a) - len(b)) == 1 and (a.startswith(b) or b.startswith(a))
            for a in left.organizers for b in right.organizers
        )
        return (
            (same_organizer and start_difference in (0, 1))
            or (similar_organizer and start_difference in (0, 1))
            or (shared_homepage and (start_difference is None or start_difference <= 14))
        )

    if not same_organizer:
        return False
    if start_difference == 0 and (left.main_title == right.title_key or right.main_title == left.title_key):
        return True

    shorter, longer = sorted((left.title_key, right.title_key), key=len)
    if shared_homepage and start_difference is not None and start_difference <= 14:
        short_words, long_words = sorted((left.words, right.words), key=len)
        remaining = iter(long_words)
        if len(shorter) >= 10 and (shorter in longer or (len(short_words) >= 4
                                                       and all(word in remaining for word in short_words))):
            return True

    if start_difference == 0:
        if left.title.startswith(("「", "『")) != right.title.startswith(("「", "『")):
            return SequenceMatcher(None, shorter, longer, autojunk=False).ratio() >= 0.78
        left_prefix, separator, left_subject = left.title.partition(":")
        right_prefix, _, right_subject = right.title.partition(":")
        subject = compact(left_subject)
        # A shared subtitle and challenge name can identify the same event when an issuer is abbreviated.
        return bool(separator and len(subject) >= 12 and subject == compact(right_subject)
                    and compact(left_prefix)[-7:] == compact(right_prefix)[-7:]
                    and len(compact(left_prefix)) >= 7)
    return False


def summarize(group, now):
    active = [row for row in group if is_accepting(row, now)]
    if not active:
        return None

    # A published deadline time takes precedence over copies that only list the date.
    deadlines = [datetime.fromisoformat(row["closesAt"]) for row in group if row.get("closesAt")]
    deadline = max(deadlines, default=None)
    if deadline and deadline <= now:
        return None

    starts = Counter(row.get("start") for row in active if row.get("start"))
    preferred = min(active, key=lambda row: (
        not row.get("poster"), -starts[row.get("start")], len(row.get("name") or ""),
    ))
    links = {}
    for row in group:
        if row.get("source") and row.get("sourceUrl"):
            key = (row["source"], row["sourceUrl"])
            links.setdefault(key, {"source": key[0], "url": key[1], "title": row["name"]})

    result = dict(preferred)
    if len(group) > 1:
        result["name"] = min((row["name"] for row in group), key=len)
    if deadline:
        result["closesAt"] = deadline.isoformat()
    if links:
        result["sourceLinks"] = list(links.values())
    if len(group) > 1 and not result.get("homepage"):
        result["homepage"] = next((row["homepage"] for row in active if row.get("homepage")), None)
    return result


def group_contests(records, now):
    by_end = defaultdict(list)
    groups = []
    for row in records:
        listing = Listing(row)
        end = row.get("end")
        candidates = [
            group for group in by_end[end]
            if all(same_contest(listing, member) for member in group)
        ] if end else []
        if len(candidates) == 1:
            candidates[0].append(listing)
        else:
            # Require agreement with the whole group and leave ambiguous matches separate.
            group = [listing]
            groups.append(group)
            if end:
                by_end[end].append(group)
    return [result for group in groups if (result := summarize([member.row for member in group], now))]

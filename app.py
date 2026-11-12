import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from string import Template
from threading import Lock, Thread

from collect import SEOUL, SOURCES, collect_source, contest_id, is_accepting
from contest_groups import group_contests
from development import DEVELOPMENT_SCOPE, development_candidate, development_contest


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"


@dataclass(frozen=True)
class Page:
    title: str
    template: str
    description: str
    stylesheets: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()


PAGES = {
    "/": Page("개발 공모전", "index.html", "접수 중인 개발 공모전, 포스터, 접수기간과 상금 검색",
              ("/board.css",), ("/board.js",)),
}
STATIC = {
    "/shell.css": ("shell.css", "text/css; charset=utf-8"),
    "/board.css": ("board.css", "text/css; charset=utf-8"),
    "/board.js": ("board.js", "application/javascript; charset=utf-8"),
}
IMAGE_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif", "avif": "image/avif"}


def render_page(path):
    page = PAGES[path]
    links = []
    for url, entry in PAGES.items():
        current = ' aria-current="page"' if url == path else ""
        links.append(f'<li><a href="{escape(url)}"{current}>{escape(entry.title)}</a></li>')
    stylesheets = [f'<link rel="stylesheet" href="{escape(url)}">' for url in page.stylesheets]
    scripts = [f'<script defer src="{escape(url)}"></script>' for url in page.scripts]
    shell = Template((PUBLIC / "shell.html").read_text(encoding="utf-8"))
    return shell.substitute(
        title=escape(page.title), description=escape(page.description),
        navigation="\n".join(links), assets="\n".join([*stylesheets, *scripts]),
        content=(PUBLIC / page.template).read_text(encoding="utf-8"),
    )


class Board:
    def __init__(self, directory):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.posters = directory / "posters"
        self.posters.mkdir(exist_ok=True)
        self.snapshot_path = directory / "contests.json"
        self.lock = Lock()
        self.running = False
        self.pending = set()
        self.results = {}
        if self.snapshot_path.is_file():
            try:
                snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
                self.results = {key: snapshot[key] for key in SOURCES if key in snapshot}
                for result in self.results.values():
                    matches = development_candidate if result.get("scope") == DEVELOPMENT_SCOPE else development_contest
                    result["contests"] = [
                        row for row in result.get("contests", [])
                        if matches(row.get("name"), row.get("category"))
                    ]
            except (OSError, ValueError, TypeError) as error:
                print(f"Could not load the local snapshot: {type(error).__name__}", flush=True)

    def view(self):
        now = datetime.now(SEOUL)
        with self.lock:
            statuses = []
            contests = []
            for key, source in SOURCES.items():
                result = self.results.get(key, {})
                records = result.get("contests", [])
                contests.extend(records)
                accepting = [record for record in records if is_accepting(record, now)]
                statuses.append({
                    "key": key,
                    "name": source.name,
                    "url": source.list_url,
                    "count": len(accepting),
                    "images": sum(bool(record.get("poster")) for record in accepting),
                    "state": "collecting" if key in self.pending else result.get("state", "pending"),
                    "message": None if key in self.pending else result.get("message"),
                    "collected_at": result.get("collected_at"),
                    "pages": result.get("pages"),
                    "candidates": result.get("candidates"),
                    "failed": result.get("failed"),
                })
            running = self.running
        return {
            "sources": statuses, "contests": group_contests(contests, now), "running": running,
            "today": now.date().isoformat(),
        }

    def refresh(self):
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.pending = set(SOURCES)
        Thread(target=self.collect, daemon=True).start()
        return True

    def collect(self):
        started = datetime.now(SEOUL)
        try:
            with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
                futures = {pool.submit(collect_source, key, self.posters, started): key for key in SOURCES}
                for future in as_completed(futures):
                    key = futures[future]
                    previous = self.results.get(key, {})
                    try:
                        batch = future.result()
                        incomplete = batch.listing_problem or batch.failed > 0
                        contests = batch.records
                        message = []
                        if batch.listing_problem:
                            message.append("목록을 끝까지 확인하지 못했습니다.")
                        if batch.failed:
                            message.append(f"상세 공고 {batch.failed}건 수집 실패.")
                        if incomplete:
                            current = {contest_id(key, record["sourceUrl"]) for record in contests}
                            cached = [
                                record for record in previous.get("contests", [])
                                if is_accepting(record, started) and contest_id(key, record["sourceUrl"]) not in current
                            ]
                            contests = contests + cached
                            if cached:
                                message.append(f"이전 공고 {len(cached)}건을 함께 표시합니다.")
                        result = {
                            "contests": contests, "state": "partial" if incomplete else "ok", "scope": DEVELOPMENT_SCOPE,
                            "message": " ".join(message) or None,
                            "collected_at": datetime.now(SEOUL).isoformat(timespec="seconds"),
                            "pages": batch.pages, "candidates": batch.candidates, "failed": batch.failed,
                        }
                    except Exception as error:
                        print(f"{key}: {type(error).__name__}: {error}", flush=True)
                        result = {
                            **previous, "state": "error",
                            "message": "이전 수집 결과를 표시합니다." if previous.get("contests") else "공고를 가져오지 못했습니다.",
                        }
                    temporary = self.snapshot_path.with_suffix(".tmp")
                    try:
                        next_results = {**self.results, key: result}
                        temporary.write_text(json.dumps(next_results, ensure_ascii=False), encoding="utf-8")
                        temporary.replace(self.snapshot_path)
                    except OSError as error:
                        print(f"{key}: Could not save snapshot ({type(error).__name__})", flush=True)
                        result = {
                            **previous, "state": "error",
                            "message": "새 공고를 저장하지 못했습니다. 이전 목록을 표시합니다." if previous.get("contests")
                            else "새 공고를 저장하지 못했습니다. 다시 수집해 주세요.",
                        }
                    else:
                        print(
                            f"{key}: {result['state']} · {result.get('pages', 0)} pages, "
                            f"{len(result.get('contests', []))} saved records",
                            flush=True,
                        )
                    with self.lock:
                        self.results[key] = result
                        self.pending.discard(key)
        finally:
            with self.lock:
                self.pending.clear()
                self.running = False


class Handler(BaseHTTPRequestHandler):
    def send_body(self, status, media_type, body, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, value):
        self.send_body(status, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False).encode())

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/contests":
            self.send_json(200, self.server.board.view())
            return
        if path in PAGES:
            self.send_body(200, "text/html; charset=utf-8", render_page(path).encode("utf-8"))
            return
        if path in STATIC:
            filename, media_type = STATIC[path]
            self.send_body(200, media_type, (PUBLIC / filename).read_bytes())
            return
        image = re.fullmatch(r"/posters/([a-f0-9]{32}\.(jpg|png|webp|gif|avif))", path)
        if image:
            file = self.server.board.posters / image[1]
            if file.is_file():
                self.send_body(200, IMAGE_TYPES[image[2]], file.read_bytes(), "public, max-age=31536000, immutable")
                return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/refresh":
            self.send_error(404)
            return
        port = self.server.server_port
        hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in hosts or (origin and origin not in {f"http://{host}" for host in hosts}):
            self.send_error(403)
            return
        if self.headers.get("Content-Type") != "application/json" or self.headers.get("Content-Length") != "2":
            self.send_error(415)
            return
        self.rfile.read(2)
        self.server.board.refresh()
        self.send_json(202, self.server.board.view())

    def log_message(self, format, *args):
        if len(args) >= 2 and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description="공모전 모아보기")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    board = Board(args.data)
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.board = board
        print(f"공모전 모아보기 http://127.0.0.1:{server.server_port}/", flush=True)
        if any(board.results.get(key, {}).get("scope") != DEVELOPMENT_SCOPE for key in SOURCES):
            board.refresh()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

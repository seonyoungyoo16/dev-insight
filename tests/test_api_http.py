from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import Board, Handler


@contextmanager
def serve_fixture():
    with TemporaryDirectory() as folder, ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.board = Board(Path(folder))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", server.board
        finally:
            server.shutdown()
            thread.join(timeout=2)


class ContestHttpTests(unittest.TestCase):
    def test_contests_get_returns_current_board_state(self):
        with serve_fixture() as (origin, board):
            with urlopen(origin + "/api/contests", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "application/json")
                payload = json.load(response)
            self.assertEqual(payload, board.view())
            self.assertEqual(set(payload), {"sources", "contests", "running", "today"})
            self.assertEqual(payload["contests"], [])
            self.assertTrue(payload["sources"])

    def test_refresh_post_preserves_accepted_and_invalid_content_responses(self):
        with serve_fixture() as (origin, board), patch.object(board, "refresh", return_value=True) as refresh:
            valid = Request(origin + "/api/refresh", data=b"{}", headers={"Content-Type": "application/json"})
            with urlopen(valid, timeout=5) as response:
                self.assertEqual(response.status, 202)
                self.assertEqual(json.load(response), board.view())
            invalid = Request(origin + "/api/refresh", data=b"{}", headers={"Content-Type": "text/plain"})
            with self.assertRaises(HTTPError) as error:
                urlopen(invalid, timeout=5)
            error.exception.close()
            self.assertEqual(error.exception.code, 415)
            refresh.assert_called_once_with()

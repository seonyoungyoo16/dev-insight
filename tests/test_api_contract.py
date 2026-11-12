import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from test_api_http import serve_fixture
from tools.api_contract import ADAPTER, GENERATED, ROOT, SPEC, check, operations


class ContestContractTests(unittest.TestCase):
    def test_contract_matches_live_http_handlers(self):
        with serve_fixture() as (origin, board), patch.object(board, "refresh", return_value=True):
            for operation, (options, _code, statuses, _type_name, _schema) in operations().items():
                with self.subTest(operation=operation):
                    body = options.get("body")
                    request = Request(
                        origin + options["path"],
                        data=json.dumps(body).encode("utf-8") if body is not None else None,
                        headers={"Content-Type": "application/json"} if body is not None else {},
                        method=options["method"],
                    )
                    with urlopen(request, timeout=5) as response:
                        self.assertIn(str(response.status), statuses)
                        self.assertEqual(response.headers.get_content_type(), "application/json")
                        self.assertEqual(set(json.load(response)), set(options["responseFields"]))

    def test_rejects_stale_generation_and_direct_fetch(self):
        self.assertEqual(check(), [])
        with TemporaryDirectory() as folder:
            root = Path(folder)
            sources = {Path(value.split(":", 1)[0]) for _options, entries, *_ in operations().values()
                       for value in entries.values()}
            for relative in {SPEC, GENERATED, ADAPTER, Path("tools/api_contract.py"), *sources}:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            self.assertEqual(check(root), [])
            generated = root / GENERATED
            generated.write_text(generated.read_text(encoding="utf-8") + "// stale\n", encoding="utf-8")
            screen = root / "public/board.js"
            with screen.open("a", encoding="utf-8") as handle:
                handle.write('\nfetch("/api/contests");\n')
            errors = check(root)
            self.assertEqual(len(errors), 2)
            self.assertIn("regenerate", errors[0])
            self.assertIn("use the contest API adapter", errors[1])
            result = subprocess.run(
                [sys.executable, str(root / "tools/api_contract.py"), "check"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("regenerate", result.stderr)
            self.assertIn("use the contest API adapter", result.stderr)

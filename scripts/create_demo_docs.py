#!/usr/bin/env python3
"""Create demo documents on a running Palimpsest webapp via POST /api/documents.

stdlib-only HTTP client (urllib) -- no requests/httpx needed for a one-shot
demo-prep loader. Reads one or more ready-to-POST payload JSON files (see
data/seed/demo_docs/*.json for the shape: title/sourceLang/targetLang/
translate/precompute/paragraphs, matching CreateDocumentBody in
src/palimpsest/webapp/app.py:282-288) and POSTs each to the target server.
With --poll, then tracks each created document's live translation +
terminology extraction to completion.

Usage:
    uv run python scripts/create_demo_docs.py data/seed/demo_docs/*.json --poll
    uv run python scripts/create_demo_docs.py \\
        --payload data/seed/demo_docs/mesopotamia-2.json \\
        --payload data/seed/demo_docs/qin-state.json \\
        --base-url http://prod-host:8000 --poll
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000"
POLL_INTERVAL_S = 5.0
POLL_TIMEOUT_S = 15 * 60.0
_TERMINAL_STATUSES = {"done", "failed"}


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_document(base_url: str, payload_path: Path) -> dict[str, Any]:
    """POST one payload file to /api/documents.

    Raises urllib.error.HTTPError (server's JSON error body already printed
    to stderr) on a non-2xx response.
    """
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    url = f"{base_url.rstrip('/')}/api/documents"
    try:
        doc = _post_json(url, payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"FAILED to create document from {payload_path}: HTTP {exc.code} {detail}",
              file=sys.stderr)
        raise
    print(f"Created doc id={doc['id']} title={doc['title']!r} (from {payload_path.name})")
    return doc


def _is_terminal(doc: dict[str, Any]) -> bool:
    """True once no further server-side state change is possible for `doc`.

    translate:true documents only launch terminology extraction at a
    *successful* end of translation (app.py's _terms_launch_after_translate
    is invoked from translate.py's _run() solely in the `status = "done"`
    branch) -- so a failed translation permanently pins termsStatus at
    "none"; it is structurally never scheduled to change. Waiting for
    termsStatus to leave "none" in that branch would spin until the timeout
    for no reason, so a failed translation is terminal on its own.

    translate:false payloads have no translation phase at all (`doc
    ["translation"]` is None -- translate.status_for() never ran for that
    doc_id); termsStatus alone is then the whole signal.
    """
    translation = doc.get("translation")
    if translation is not None:
        trans_status = translation.get("status")
        if trans_status not in _TERMINAL_STATUSES:
            return False
        if trans_status == "failed":
            return True
    return doc.get("termsStatus") in _TERMINAL_STATUSES


def _succeeded(doc: dict[str, Any]) -> bool:
    translation = doc.get("translation")
    if translation is not None and translation.get("status") != "done":
        return False
    return doc.get("termsStatus") == "done"


def poll_document(
    base_url: str, doc_id: int, *, interval: float = POLL_INTERVAL_S, timeout: float = POLL_TIMEOUT_S
) -> bool:
    """Poll GET /api/documents/{doc_id} every `interval` seconds, printing
    translation progress + termsStatus, until both reach a terminal state or
    `timeout` seconds elapse. Returns True iff translation and terminology
    extraction both finished successfully ("done").
    """
    url = f"{base_url.rstrip('/')}/api/documents/{doc_id}"
    start = time.monotonic()
    while True:
        doc = _get_json(url)
        translation = doc.get("translation") or {}
        t_status = translation.get("status", "n/a")
        t_done, t_total = translation.get("done", "?"), translation.get("total", "?")
        terms_status = doc.get("termsStatus", "?")
        elapsed = time.monotonic() - start
        print(f"[t={elapsed:5.0f}s] doc {doc_id}: translation={t_status} "
              f"({t_done}/{t_total}) termsStatus={terms_status}")

        if _is_terminal(doc):
            ok = _succeeded(doc)
            reason = translation.get("errorReason")
            extra = f" errorReason={reason}" if reason else ""
            print(f"doc {doc_id}: {'OK' if ok else 'FAILED'}{extra}")
            return ok
        if elapsed > timeout:
            print(f"doc {doc_id}: TIMEOUT after {timeout:.0f}s "
                  f"(translation={t_status} termsStatus={terms_status})", file=sys.stderr)
            return False
        time.sleep(interval)


def _gather_payload_paths(args: argparse.Namespace) -> list[Path]:
    paths = [Path(p) for p in args.payloads] + [Path(p) for p in (args.payload or [])]
    if not paths:
        raise SystemExit("no payload files given (pass them positionally or via --payload)")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("payloads", nargs="*", metavar="PAYLOAD",
                         help="payload JSON file(s), positional form")
    parser.add_argument("--payload", action="append", metavar="PAYLOAD",
                         help="payload JSON file (repeatable)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                         help=f"webapp base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--poll", action="store_true",
                         help="poll each created document until translation + terminology "
                              "extraction finish, or a 15 min per-document timeout")
    args = parser.parse_args(argv)

    payload_paths = _gather_payload_paths(args)
    for path in payload_paths:
        if not path.is_file():
            parser.error(f"payload file not found: {path}")

    created: list[dict[str, Any]] = []
    failures = 0
    for path in payload_paths:
        try:
            created.append(create_document(args.base_url, path))
        except urllib.error.HTTPError:
            failures += 1
        except (urllib.error.URLError, OSError) as exc:
            print(f"FAILED to reach {args.base_url}: {exc}", file=sys.stderr)
            failures += 1

    if args.poll:
        for doc in created:
            if not poll_document(args.base_url, doc["id"]):
                failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

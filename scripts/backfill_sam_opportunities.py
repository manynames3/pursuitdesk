#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List


DEFAULT_ENDPOINT = "https://api.sam.gov/opportunities/v2/search"
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


def prefer_ipv4_for_local_fetches() -> None:
    def getaddrinfo_ipv4_first(*args: Any, **kwargs: Any) -> List[Any]:
        results = list(_ORIGINAL_GETADDRINFO(*args, **kwargs))
        return sorted(results, key=lambda item: 0 if item[0] == socket.AF_INET else 1)

    socket.getaddrinfo = getaddrinfo_ipv4_first


def main() -> int:
    prefer_ipv4_for_local_fetches()
    parser = argparse.ArgumentParser(description="Backfill live SAM.gov opportunities through the VPC ingest Lambda.")
    parser.add_argument("--function-name", default="govcon-captureos-demo-ingest")
    parser.add_argument("--days", type=int, default=int(os.getenv("GSA_BACKFILL_DAYS", "30")))
    parser.add_argument("--limit", type=int, default=int(os.getenv("SAM_PAGE_LIMIT", "1000")))
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("GSA_BACKFILL_MAX_PAGES", "10")))
    parser.add_argument("--chunk-size", type=int, default=200)
    args = parser.parse_args()

    api_key = os.getenv("SAM_API_KEY")
    if not api_key:
        print("SAM_API_KEY is required.", file=sys.stderr)
        return 64

    posted_to = datetime.now(timezone.utc).date()
    posted_from = posted_to - timedelta(days=max(1, args.days))
    total_seen = 0
    total_written = 0

    for page_index, page in enumerate(fetch_pages(api_key, posted_from, posted_to, args.limit, args.max_pages), start=1):
        records = page.get("opportunitiesData") or []
        total_records = int(page.get("totalRecords") or len(records))
        print(f"Fetched page {page_index}: {len(records)} records of {total_records} total.")
        total_seen += len(records)
        for chunk in chunked(records, args.chunk_size):
            result = invoke_upsert(args.function_name, chunk, total_records, posted_from, posted_to)
            total_written += int(result.get("writtenRecords") or 0)
            print(f"  Upserted {result.get('writtenRecords', 0)} records.")

    print(json.dumps({"fetched": total_seen, "written": total_written}, indent=2))
    return 0


def fetch_pages(api_key: str, posted_from, posted_to, limit: int, max_pages: int) -> Iterable[Dict[str, Any]]:
    offset = 0
    for _ in range(max_pages):
        params = {
            "api_key": api_key,
            "postedFrom": posted_from.strftime("%m/%d/%Y"),
            "postedTo": posted_to.strftime("%m/%d/%Y"),
            "limit": min(max(limit, 1), 1000),
            "offset": offset,
            "ptype": ["o", "k", "p", "r"],
            "status": "active",
        }
        request = urllib.request.Request(
            f"{DEFAULT_ENDPOINT}?{urllib.parse.urlencode(params, doseq=True)}",
            headers={"Accept": "application/json", "User-Agent": "GovConCaptureOS/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.loads(response.read().decode("utf-8"))
        records = page.get("opportunitiesData") or []
        yield page
        if not records:
            break
        total_records = int(page.get("totalRecords") or 0)
        offset += 1
        if offset * params["limit"] >= total_records:
            break


def invoke_upsert(function_name: str, records: List[Dict[str, Any]], total_records: int, posted_from, posted_to) -> Dict[str, Any]:
    event = {
        "mode": "upsert_sam_records",
        "source_mode": "live_api",
        "total_records": total_records,
        "ingest_window": {
            "posted_from": posted_from.isoformat(),
            "posted_to": posted_to.isoformat(),
            "filters": {"ptype": ["o", "k", "p", "r"], "status": "active"},
        },
        "records": records,
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        json.dump(event, handle, separators=(",", ":"))
        payload_path = handle.name
    try:
        completed = subprocess.run(
            [
                "aws",
                "lambda",
                "invoke",
                "--function-name",
                function_name,
                "--cli-binary-format",
                "raw-in-base64-out",
                "--payload",
                f"file://{payload_path}",
                "/tmp/captureos-sam-upsert-response.json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        try:
            os.unlink(payload_path)
        except FileNotFoundError:
            pass
    metadata = json.loads(completed.stdout or "{}")
    with open("/tmp/captureos-sam-upsert-response.json", "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if "FunctionError" in metadata:
        raise RuntimeError(json.dumps(payload))
    return payload


def chunked(records: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    for index in range(0, len(records), size):
        yield records[index : index + size]


if __name__ == "__main__":
    raise SystemExit(main())

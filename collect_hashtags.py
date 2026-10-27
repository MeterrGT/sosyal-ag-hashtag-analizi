#!/usr/bin/env python3
"""Collect Turkish-language Bluesky post hashtags from the public Jetstream stream.

Privacy design: post text is used in memory only for language/hashtag extraction.
The CSV stores only a timestamp and the extracted hashtags, not post text or account IDs.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from langdetect import DetectorFactory, LangDetectException, detect
from websocket import create_connection, WebSocketConnectionClosedException, WebSocketTimeoutException

# Repeatable language-detection behavior where fallback detection is needed.
DetectorFactory.seed = 42

DURATION_HOURS = float(os.getenv("COLLECT_HOURS", "48"))
OUT_FILE = Path(os.getenv("OUT_FILE", "data/posts_hashtags.csv"))
BASE_URL = "wss://jetstream1.us-east.bsky.network/subscribe"
PARAMS = {
    "wantedCollections": "app.bsky.feed.post",
    "wantedCommitOperations": "create",
}
WS_URL = BASE_URL + "?" + urlencode(PARAMS)
HASHTAG_RE = re.compile(r"(?<!\w)#([\w]+)", re.UNICODE)


def event_timestamp(event: dict) -> str:
    """Use the event's microsecond timestamp; fall back to current UTC time."""
    time_us = event.get("time_us")
    try:
        dt = datetime.fromtimestamp(float(time_us) / 1_000_000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        dt = datetime.now(timezone.utc)
    return dt.isoformat()


def is_turkish(record: dict, text: str) -> bool:
    """Prefer the post's declared language; detect in memory when it is missing."""
    langs = record.get("langs") or []
    if isinstance(langs, list) and langs:
        return "tr" in [str(lang).lower() for lang in langs]
    if len(text.strip()) < 20:
        return False
    try:
        return detect(text) == "tr"
    except LangDetectException:
        return False


def parse_event(event: dict):
    """Return (timestamp, hashtags) or None. Supports the legacy Jetstream frame."""
    if event.get("kind") != "commit":
        return None
    commit = event.get("commit") or {}
    if commit.get("operation") != "create":
        return None
    if commit.get("collection") != "app.bsky.feed.post":
        return None
    record = commit.get("record") or {}
    text = record.get("text") or ""
    if not text or not is_turkish(record, text):
        return None

    # Store only hashtags. Deduplicate repeated tags within the same post.
    tags = list(dict.fromkeys(tag.casefold() for tag in HASHTAG_RE.findall(text)))
    if not tags:
        return None
    return event_timestamp(event), tags


def main() -> None:
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    is_new = not OUT_FILE.exists() or OUT_FILE.stat().st_size == 0
    start = time.monotonic()
    deadline = start + DURATION_HOURS * 3600
    saved_posts = 0
    received_events = 0
    reconnects = 0

    with OUT_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp_utc", "hashtags"])
        if is_new:
            writer.writeheader()
            f.flush()

        print(f"Collecting for {DURATION_HOURS:g} hours. Output: {OUT_FILE.resolve()}")
        print("Only timestamps + hashtags are saved; post text and user IDs are not stored.")
        print("Keep the computer awake and the network connected during collection.")

        while time.monotonic() < deadline:
            ws = None
            try:
                ws = create_connection(WS_URL, timeout=30, enable_multithread=True)
                print("Connected to Bluesky Jetstream.")
                while time.monotonic() < deadline:
                    try:
                        raw = ws.recv()
                    except WebSocketTimeoutException:
                        continue
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    received_events += 1
                    result = parse_event(event)
                    if result:
                        timestamp, tags = result
                        writer.writerow({"timestamp_utc": timestamp, "hashtags": "|".join(tags)})
                        f.flush()
                        saved_posts += 1
                    if received_events % 5000 == 0:
                        elapsed_h = (time.monotonic() - start) / 3600
                        print(f"Events: {received_events:,} | hashtag posts saved: {saved_posts:,} | elapsed: {elapsed_h:.2f} h")
            except KeyboardInterrupt:
                print("Stopped by user. The CSV is saved; note that collection is shorter than planned.")
                break
            except (OSError, WebSocketConnectionClosedException, Exception) as exc:
                reconnects += 1
                print(f"Connection interrupted ({type(exc).__name__}). Reconnecting in 5 seconds...")
                time.sleep(5)
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass

    elapsed = (time.monotonic() - start) / 3600
    print(f"Finished. Events: {received_events:,}; hashtag posts saved: {saved_posts:,}; reconnects: {reconnects}; elapsed: {elapsed:.2f} h")
    print("Important: fewer than 48 hours of runtime means this is not a full 48-hour collection.")


if __name__ == "__main__":
    main()

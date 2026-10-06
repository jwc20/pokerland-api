"""Helpers for tracker tests: a sample hand and requests shaped like the trackers'."""

import gzip
import hashlib
import uuid

HAND = (
    "﻿PokerStars Hand #260883422541:  Hold'em No Limit (100/200) - 2026/05/21 18:31:27 UTC\n"
    "Table 'Gertrud VIII' 6-max (Play Money) Seat #2 is the button\n"
    "Seat 1: Alice (20000 in chips)\n"
    "*** SUMMARY ***\n"
    "Total pot 400 | Rake 0\n"
    "\n\n\n\n"
).encode()
FIRST_LINE = HAND.split(b"\n", 1)[0] + b"\n"
FINGERPRINT = hashlib.sha256(FIRST_LINE).hexdigest()
STREAM_NAMESPACE = uuid.UUID("6f1e7c1e-5a0b-4d3e-9b1a-2f3c4d5e6f70")
STREAM_ID = str(uuid.uuid5(STREAM_NAMESPACE, FINGERPRINT))
UA = "pokerland-tracker/0.1.0 (macos; arm64)"


def register_stream(client, stream_id=STREAM_ID, **overrides):
    data = {
        "source": "pokerstars",
        "platform": "macos",
        "client_version": "0.1.0",
        "path_hint": "Alice/HH20260521 Gertrud VIII.txt",
        "fingerprint": FINGERPRINT,
        **overrides,
    }
    return client.put(f"/api/tracker/streams/{stream_id}/", data, format="json")


def upload(client, start, data, stream_id=STREAM_ID, end=None, sha256=None, body=None):
    return client.put(
        f"/api/tracker/streams/{stream_id}/chunks/{start}/",
        gzip.compress(data) if body is None else body,
        content_type="application/gzip",
        HTTP_X_CHUNK_END=str(len(data) + start if end is None else end),
        HTTP_X_CHUNK_SHA256=sha256 or hashlib.sha256(data).hexdigest(),
    )

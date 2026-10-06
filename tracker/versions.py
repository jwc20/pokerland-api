"""The tracker's version, from its User-Agent: `pokerland-tracker/1.2.3 (macos; arm64)`."""

import re

USER_AGENT = re.compile(r"^pokerland-tracker/(\d+)\.(\d+)\.(\d+)")


def parse_version(text):
    """`"1.2.3"` or `"1.2.3-beta.1"` to `(1, 2, 3)`; None when it is not a version."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(part) for part in match.groups()) if match else None


def tracker_version(request):
    match = USER_AGENT.match(request.headers.get("User-Agent", ""))
    return tuple(int(part) for part in match.groups()) if match else None


def is_supported(version, min_version):
    return version is not None and version >= parse_version(min_version)

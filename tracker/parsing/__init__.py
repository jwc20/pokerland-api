"""Turns uploaded hand-history bytes into data, one chunk at a time.

tasks.drain feeds chunks here strictly in file order and persists the returned
state between calls, so a hand split across two chunks is seen whole.

This is a placeholder: it only counts hands. The real parser keeps the same
contract and grows in three layers:

1. a framer that splits the bytes into complete hands, carrying a partial hand
   over in `state["partial"]`;
2. extractors that turn a hand's text into typed events;
3. a reducer that writes Hand/Action/Result rows.

PARSER_VERSION is stored on each stream, so a new parser can find streams that
need re-parsing (`manage.py tracker_drain --reparse`).
"""

PARSER_VERSION = 1

HAND_START = b"PokerStars Hand #"


def parse(data, state):
    """Consumes `data`, the next bytes of a stream, and returns the new state.

    Must not import Django models: it is meant to run on fixture files offline.
    """
    state = dict(state)
    state["hands_seen"] = state.get("hands_seen", 0) + data.count(HAND_START)
    state["bytes_seen"] = state.get("bytes_seen", 0) + len(data)
    return state

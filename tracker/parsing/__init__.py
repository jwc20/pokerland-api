"""Turns uploaded hand-history bytes into hands, one chunk at a time.

tasks.drain feeds chunks here strictly in file order and persists the returned
state between calls, so a hand split across two chunks is seen whole:

1. the framer below splits the text into complete hands, carrying the last,
   still incomplete one over in `state["partial"]`;
2. `pokerstars.extract` reads a hand with PokerKit into the PHH notation and
   replays it into data: seats, events, results;
3. `hands.store.store_hands` writes the hands to the database.

PARSER_VERSION is stored on each stream, so a new parser can find streams that
need re-parsing (`manage.py tracker_drain --reparse`).
"""

import logging
import re

from tracker.parsing import pokerstars

PARSER_VERSION = 3

HAND_START = re.compile(r"^PokerStars (?:Zoom |Home Game )?(?:Hand|Game) #", re.MULTILINE)
SUMMARY = "*** SUMMARY ***"
# A hand is a few kilobytes; text this long without a complete hand is not one.
MAX_PARTIAL_CHARS = 1024 * 1024

logger = logging.getLogger(__name__)


def parse(data, state):
    """Consumes `data`, the next bytes of a stream. Returns the new state and the hands completed.

    Must not import Django models: it is meant to run on fixture files offline.
    A hand that cannot be read, such as a game PokerKit does not play, is logged
    and counted in `hands_failed`, and the rest of the stream is still parsed:
    hands do not depend on one another.
    """
    state = {"hands_seen": 0, "hands_failed": 0, "bytes_seen": 0, "partial": "", **state}
    text = state["partial"] + decode(data)
    starts = [match.start() for match in HAND_START.finditer(text)]
    hands = []
    state["partial"] = ""
    for start, end in zip(starts, [*starts[1:], len(text)]):
        block = text[start:end]
        if end == len(text) and not is_complete(block):
            if len(block) <= MAX_PARTIAL_CHARS:
                state["partial"] = block
            else:
                logger.warning("Dropping %d characters that never completed a hand", len(block))
            break
        state["hands_seen"] += 1
        try:
            hands.append(pokerstars.extract(block))
        except pokerstars.HandError as error:
            state["hands_failed"] += 1
            logger.warning("Skipping a hand: %s", error)
        except Exception:
            state["hands_failed"] += 1
            logger.exception("Could not read hand %r", block.split("\n", 1)[0])
    state["bytes_seen"] += len(data)
    return state, hands


def decode(data):
    """Hand-history bytes as text: UTF-8 (with a BOM at the start of the file), \\n line endings."""
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\ufeff", "")


def is_complete(block):
    """PokerStars writes a hand at once, ending its summary with blank lines."""
    summary = block.find(SUMMARY)
    return summary != -1 and "\n\n" in block[summary:]

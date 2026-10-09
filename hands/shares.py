"""Hand write-ups and share links (E2 of the feature ideas).

A share is a public, read-only link to one of the user's hands with the write-up they published with it, so they can
show it to others [MIT 1; JHU 4]. By default it is anonymized (`anonymized`): every player goes by their position and
the hero by "Hero", in the replay and in its PHH text alike, and the table, the hand's number and the tournament are
left out. Opponents' names and statistics are never shared (feature ideas, section 7.6). A revoked share's link stops
working.
"""

import copy
import secrets

from pokerkit import HandHistory

from hands.models import HandShare

HERO = "Hero"


def new_slug():
    """A share's slug: 16 URL-safe characters, too many to guess."""
    while True:
        slug = secrets.token_urlsafe(12)
        if not HandShare.objects.filter(slug=slug).exists():
            return slug


def anonymized(hand):
    """A copy of a stored hand with every player named by their position and the hero as "Hero", and without its
    table, number and tournament. The copy isn't saved."""
    names = {
        player["name"]: HERO if player["name"] == hand.hero else player["position"] or f"Seat {player['seat']}"
        for player in hand.replay.get("players", [])
    }
    shown = copy.copy(hand)
    replay = dict(hand.replay)
    replay["players"] = [{**player, "name": names[player["name"]]} for player in hand.replay.get("players", [])]
    replay["events"] = [
        {**event, "player": names.get(event["player"], event["player"])} if "player" in event else event
        for event in hand.replay.get("events", [])
    ]
    shown.replay = replay
    shown.hero = HERO if hand.hero else ""
    shown.hand_id = ""
    shown.table = ""
    shown.tournament_id = ""
    facts = dict(hand.facts or {})
    if facts.get("preflop_aggressor"):
        facts["preflop_aggressor"] = names.get(facts["preflop_aggressor"], facts["preflop_aggressor"])
    facts.pop("tournament", None)
    facts.pop("board_reader", None)
    shown.facts = facts
    shown.phh = anonymous_phh(hand.phh, names)
    return shown


def anonymous_phh(text, names):
    """A hand's PHH text with its players renamed and its event, table and number left out."""
    if not text:
        return text
    history = HandHistory.loads(text)
    history.players = [names.get(name, name) for name in history.players]
    history.event = history.table = history.hand = None
    return history.dumps()

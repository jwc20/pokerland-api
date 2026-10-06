"""Writes the hands tracker.parsing reads from a stream."""

from hands.models import Hand

# Hand fields that come straight from the parser; the rest of a parsed hand goes in `replay`.
COLUMNS = (
    "site",
    "hand_id",
    "played_at",
    "game",
    "currency",
    "play_money",
    "small_blind",
    "big_blind",
    "tournament_id",
    "table",
    "hero",
    "hero_position",
    "hero_cards",
    "hero_net",
    "final_street",
)
REPLAY = ("max_seats", "button_seat", "ante", "total_pot", "rake", "boards", "players", "events")


def store_hands(stream, hands):
    """Saves hands parsed from `stream`, updating any already saved, e.g. by an earlier parse."""
    by_id = {(hand["site"], hand["hand_id"]): hand for hand in hands}  # one row per hand, as the upsert requires
    rows = [
        Hand(
            user_id=stream.user_id,
            stream=stream,
            **{name: hand[name] for name in COLUMNS},
            replay={name: hand[name] for name in REPLAY},
        )
        for hand in by_id.values()
    ]
    Hand.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=("user", "site", "hand_id"),
        update_fields=("stream", *COLUMNS[2:], "replay"),
    )

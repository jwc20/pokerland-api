"""Writes the hands tracker.parsing reads from a stream."""

from django.db import transaction

from hands import opponents, results, sessions, tournaments
from hands.models import Hand, HandBet, HandPlayer

# Hand fields that come straight from the parser; the rest of a parsed hand goes in `replay`, with the pot and
# the rake again, which the replay shows.
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
    "total_pot",
    "rake",
    "phh",
)
REPLAY = ("max_seats", "button_seat", "ante", "total_pot", "rake", "board", "players", "events")
# Hand fields from tracker.parsing.facts.
FACT_COLUMNS = (
    "hero_combo",
    "players_dealt",
    "pot_type",
    "hero_situation",
    "hero_first_action",
    "effective_bb",
    "hero_m",
    "level",
    "facts",
)


def store_hands(stream, hands):
    """Saves hands parsed from `stream`, updating any already saved, e.g. by an earlier parse.

    Each hand's HandPlayer and HandBet rows are replaced, and the sessions around the hands rebuilt
    (hands.sessions), in the same transaction; so are the tournaments the hands were played in (hands.tournaments)
    and the counts of the opponents dealt into them (hands.opponents). The results kept from the user's hands
    (hands.results) are out of date from the same commit.
    """
    by_id = {(hand["site"], hand["hand_id"]): hand for hand in hands}  # one row per hand, as the upsert requires
    rows = [
        Hand(
            user_id=stream.user_id,
            stream=stream,
            **{name: hand[name] for name in COLUMNS},
            **hand["facts"]["hand"],
            replay={name: hand[name] for name in REPLAY},
        )
        for hand in by_id.values()
    ]
    with transaction.atomic():
        Hand.objects.bulk_create(
            rows,
            update_conflicts=True,
            unique_fields=("user", "site", "hand_id"),
            update_fields=("stream", *COLUMNS[2:], *FACT_COLUMNS, "replay"),
        )
        # The upsert doesn't report ids on every database, so they are looked up.
        saved = Hand.objects.filter(user_id=stream.user_id, hand_id__in=[hand_id for _, hand_id in by_id])
        ids = {(site, hand_id): pk for site, hand_id, pk in saved.values_list("site", "hand_id", "id")}
        stored = [ids[key] for key in by_id]
        HandPlayer.objects.filter(hand_id__in=stored).delete()
        HandPlayer.objects.bulk_create(
            HandPlayer(hand_id=ids[key], user_id=stream.user_id, is_hero=row["name"] == hand["hero"], **row)
            for key, hand in by_id.items()
            for row in hand["facts"]["players"]
        )
        HandBet.objects.filter(hand_id__in=stored).delete()
        HandBet.objects.bulk_create(
            HandBet(hand_id=ids[key], user_id=stream.user_id, is_hero=row["name"] == hand["hero"], **row)
            for key, hand in by_id.items()
            for row in hand["facts"].get("bets", [])
        )
        sessions.assign(stream.user_id, [hand["played_at"] for hand in by_id.values()])
        tournaments.refresh(
            stream.user_id, {(hand["site"], hand["tournament_id"]) for hand in by_id.values() if hand["tournament_id"]}
        )
        opponents.refresh(
            stream.user_id,
            {
                (hand["site"], player["name"])
                for hand in by_id.values()
                for player in hand["players"]
                if player["name"] != hand["hero"]
            },
        )
        results.changed(stream.user_id)

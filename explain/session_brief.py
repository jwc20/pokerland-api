"""The brief for one of the user's sessions (pokerland-llm-reports.md, 3.4): its numbers, the preflop and postflop
checks it broke, and its most telling hands, each a line with the playbook's verdicts on its decisions.

A long session would make a long brief, so it describes TELLING hands at most: the biggest results and the all-ins,
each anonymized as a hand brief is.
"""

from explain.hand_brief import CHECK_RULES, move_words, verdict_of
from hands.leaks import CHECKS, broken_counts, presets_of
from hands.models import HandPlayer
from hands.shares import anonymized
from practice.rules import evaluate
from practice.sets import SKILLS, hand_data, house_playbook
from practice.spots import decisions

TELLING = 10


def build(session):
    """The brief's input for a session; it has no decisions of its own, and links to the skills and broken rules."""
    hands = list(session.hand_set.order_by("played_at", "id"))
    rows = {row.hand_id: row for row in HandPlayer.objects.filter(hand__in=hands, is_hero=True)}
    presets = presets_of(session.user_id)
    counts = broken_counts(HandPlayer.objects.filter(hand__in=hands, is_hero=True), presets)
    rules = house_playbook().rules
    cards = {rule["id"]: rule for rule in rules}

    def weight(hand):
        row = rows.get(hand.pk)
        return abs(hand.hero_net / hand.big_blind) + (15 if row and row.allin_equity is not None else 0)

    telling = sorted(hands, key=weight, reverse=True)[:TELLING]
    broken_rules = []
    lines = []
    for hand in sorted(telling, key=lambda found: (found.played_at, found.pk)):
        shown = anonymized(hand)
        bb = hand.big_blind
        made = []
        for context in decisions(hand_data(shown)):
            advice = evaluate(context, rules)
            verdict = verdict_of(advice, context["move"])
            card = cards.get(advice["rule"])
            if verdict == "broke" and card:
                broken_rules.append(card["id"])
            made.append(
                {
                    "street": context["street"],
                    "move": move_words(context["move"], bb),
                    "verdict": verdict,
                    **({"rule": card["number"]} if card and verdict != "none" else {}),
                }
            )
        row = rows.get(hand.pk)
        line = {
            "position": hand.hero_position,
            "cards": hand.hero_cards,
            "board": shown.replay.get("board", []),
            "pot_type": hand.pot_type,
            "result_bb": round(hand.hero_net / bb, 2),
            "showdown": hand.final_street == "showdown",
            "decisions": made,
        }
        if row and row.allin_equity is not None:
            line["all_in"] = {
                "street": row.allin_street,
                "equity": f"{round(row.allin_equity * 100)}%",
                "expected_bb": round(row.ev_net_bb, 2),
            }
        lines.append(line)
    minutes = round((session.end - session.start).total_seconds() / 60)
    links = [*dict.fromkeys(f"rule:{rule}" for rule in broken_rules)] + [f"skill:{skill}" for skill in SKILLS]
    data = {
        "kind": "session",
        "session": {
            "hands": session.hands,
            "minutes": minutes,
            "tables": session.tables,
            "most_tables_at_once": session.most_tables,
            "result_bb": round(session.net_bb, 2),
            "all_in_adjusted_bb": round(session.ev_net_bb, 2),
            "biggest_pot_bb": round(session.biggest_pot_bb, 1),
        },
        "checks_broken": [
            {"check": key, "rule": CHECK_RULES[key](presets), "times": counts[key]} for key in CHECKS if counts[key]
        ],
        "telling_hands": lines,
        "playbook": "Verdicts come from the starter heads-up playbook, so many decisions in bigger pots have none.",
        "practice_links": links,
    }
    return {"input": data, "decisions": {}, "links": links}


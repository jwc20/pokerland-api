"""The debrief after a coached match (pokerland-practice-mode-additional.md, 4.6), in this order, the result last:

1. one thing to fix: the rule family with the most misses, and the hand that shows it best;
2. three hands to look at: the biggest departure from the playbook, the best decision, the closest one;
3. by the book: each rule, how often it applied and how often it was kept, with its range;
4. the read against the truth: the bot's style and leak beside the card, what was found, by which hand;
5. luck and play apart: the chips won, the chips expected when the money went in, the gap in plain words; a hand
   played by the book that still lost a stack is a cooler;
6. what moved: the rule families that went up or down a stage;
7. sent to practice: the decisions that left a rule come back in the daily sets.
"""

import datetime

from django.db import transaction
from django.utils import timezone

from hands.stats import proportion
from practice import bots, coach, reads
from practice.matches import HERO, LEVELS, VILLAIN, read_card, table_hand
from practice.models import RuleProgress, Scenario
from practice.playbook import FAMILIES
from practice.rules import check
from practice.sets import BOXES, again_later, legal_of
from practice.spots import HAND_NAMES
from tracker.parsing.equity import all_in

COOLER_BB = 20  # a stack's worth lost, by the book, makes a cooler


def debrief(match):
    """Everything the debrief shows, worked out from the match's decisions and hands."""
    decisions = list(match.decisions.select_related("hand").order_by("hand__number", "step"))
    cards = {rule["id"]: rule for rule in match.playbook.rules}
    hands = {row.number: row for row in match.table.hands.filter(finished=True)}
    luck = luck_and_play(match, hands, decisions)
    fix = one_thing(decisions, cards)
    return {
        "fix": fix,
        "hands": three_hands(decisions, hands, cards, fix),
        "book": by_the_book(decisions, match.playbook.rules),
        "read": against_the_truth(match),
        "luck": luck,
        "pinned": match.coach.isdigit(),
        "moved": what_moved(match, decisions),
        "sent": send_to_practice(match, decisions),
        "result_bb": match.result_bb,
        "hands_played": match.table.hands_played,
    }


def one_thing(decisions, cards):
    """The family with the most misses of a clear rule, and its biggest miss; None after a clean match."""
    misses = [d for d in decisions if d.followed is False]
    if not misses:
        return None
    by_family = {}
    for decision in misses:
        by_family.setdefault(decision.advice["family"], []).append(decision)
    family, missed = max(by_family.items(), key=lambda item: (len(item[1]), item[0]))
    worst = max(missed, key=lambda decision: decision.context["pot_bb"])
    card = cards.get(worst.advice["rule"])
    return {
        "family": family,
        "label": FAMILIES[family],
        "misses": len(missed),
        "rule": card,
        "decision": _decision(worst, cards),
    }


def three_hands(decisions, hands, cards, fix=None):
    """The biggest departure, the best decision (a good fold, or a good call that lost), and the closest.

    The departure is the next biggest after the one the fix already shows.
    """
    picked = []
    shown = fix and (fix["decision"]["hand"], fix["decision"]["step"])
    missed = [d for d in decisions if d.followed is False and (d.hand.number, d.step) != shown]
    if missed:
        picked.append(("departure", max(missed, key=lambda decision: decision.context["pot_bb"])))
    kept = [d for d in decisions if d.followed]
    good = [d for d in kept if d.move["action"] == "fold" or _net_bb(hands, d) < 0]
    if good or kept:
        picked.append(("best", max(good or kept, key=lambda decision: decision.context["pot_bb"])))
    close = [d for d in decisions if d.advice["verdict"] != "clear" and d.move]
    if close:
        picked.append(("closest", max(close, key=lambda decision: decision.context["pot_bb"])))
    return [{"kind": kind, **_decision(decision, cards)} for kind, decision in picked]


def by_the_book(decisions, rules):
    """Each default rule that applied in the match: how often it was kept, with its 95% range."""
    found = {}
    for decision in decisions:
        if not decision.move:
            continue
        for result in check(decision.context, decision.move, rules):
            found.setdefault(result["rule"], []).append(result["followed"])
    order = [rule["id"] for rule in rules]
    return [
        {"rule": rule, **proportion(sum(kept), len(kept))}
        for rule, kept in sorted(found.items(), key=lambda item: order.index(item[0]))
    ]


def against_the_truth(match):
    """The bot revealed beside the read card: its style and leak, the card's label and reads, and what was found."""
    bot = next(seat for seat in match.table.seats if seat["name"] == VILLAIN)
    card = read_card(match)
    leak_tag = reads.FINDS[bot["leak"]]
    history = list(match.read_notes.order_by("created", "id"))
    found = next((note for note in history if note.tag == leak_tag and note.kind in ("read", "showdown")), None)
    label = card["accepted"]
    first_label = next((note for note in history if note.kind == "label" and note.tag == bot["style"]), None)
    return {
        "style": bot["style"],
        "leak": bot["leak"],
        "leak_label": bots.LEAKS[bot["leak"]],
        "leak_tag": leak_tag,
        "label": label.tag if label else None,
        "label_right": bool(label and label.tag == bot["style"]),
        "label_hand": first_label.hand_number if first_label else None,
        "reads": [note.tag for note in card["reads"]],
        "found": bool(found),
        "found_hand": found.hand_number if found else None,
        "found_by": found.by if found else None,
        "wrong": [reads.TAGS[note.tag][0] for note in card["reads"] if note.tag != leak_tag],
    }


def luck_and_play(match, hands, decisions):
    """The chips won against the chips expected when the money went in, by all-in equity, in starting big blinds.

    In a hand where both players were all-in before the river and both hands were shown, the expected result is
    the hero's equity at that moment times the pot, less what they put in [FND-2]. Every other hand counts as it
    went. A hand lost by a stack or more with every decision by the book is a cooler: "everything he did was fine
    and he still lost" [JHU 5].
    """
    expected = actual = 0.0
    swings = []
    coolers = []
    by_hand = {}
    for decision in decisions:
        by_hand.setdefault(decision.hand.number, []).append(decision)
    bb = LEVELS[0][1]  # in starting big blinds, as the match's result is
    for number, row in sorted(hands.items()):
        net = _net(row) / bb
        actual += net
        equity = all_in_equity(row)
        if equity is None:
            expected += net
        else:
            fair = (equity["expected"] - equity["invested"]) / bb
            expected += fair
            swings.append(
                {
                    "hand": number,
                    "equity": round(equity["equity"], 3),
                    "expected_bb": round(fair, 2),
                    "net_bb": round(net, 2),
                }
            )
        mine = by_hand.get(number, [])
        if _net(row) / row.big_blind <= -COOLER_BB and mine and all(d.followed is not False for d in mine):
            coolers.append(number)
    return {
        "actual_bb": round(actual, 2),
        "expected_bb": round(expected, 2),
        "luck_bb": round(actual - expected, 2),
        "all_ins": swings,
        "coolers": coolers,
    }


def all_in_equity(row):
    """The hero's equity, expected chips and chips put in when the money went in before the river, from the hand's
    replay, which holds both players' cards (tracker.parsing.equity.all_in); None for any other hand."""
    hand = {**row.replay, "game": "Hold'em No Limit", "site": "practice", "hand_id": row.pk}
    return (all_in(hand) or {}).get(HERO)


def what_moved(match, decisions):
    """Each rule family's stage when the match began and now; nothing when the coach was pinned to a stage."""
    if match.coach.isdigit():
        return []
    first = {}
    for decision in decisions:
        first.setdefault(decision.advice["family"], decision.stage)
    now = {
        row.family: row.stage
        for row in RuleProgress.objects.filter(user=match.user, playbook_key=match.playbook.key, family__in=first)
    }
    return [
        {"family": family, "label": FAMILIES[family], "from": stage, "to": now.get(family, stage)}
        for family, stage in first.items()
    ]


@transaction.atomic
def send_to_practice(match, decisions):
    """The decisions that left a clear rule, saved as spots that come back in the daily sets. Once only."""
    sent = []
    today = timezone.localdate()
    for decision in decisions:
        if decision.followed is not False:
            continue
        scenario = Scenario.objects.filter(owner=match.user, source="match", origin__decision=decision.pk).first()
        if scenario is None:
            scenario = _scenario(match, decision)
            again_later(match.user, scenario, today)
        sent.append(scenario.pk)
    return {"count": len(sent), "due": str(today + datetime.timedelta(days=BOXES[1]))}


def _scenario(match, decision):
    """A spot from a match decision that left a rule: what do you do here? Graded by the rule it left."""
    replay = decision.hand.replay
    players = [
        {**player, "cards": player["cards"] if player["name"] == HERO else [], "won": 0, "net": 0}
        for player in replay["players"]
    ]
    hand = {
        "game": "Hold'em No Limit",
        "currency": "",
        "small_blind": decision.hand.small_blind,
        "big_blind": decision.hand.big_blind,
        "ante": 0,
        "tournament_id": "",
        "button_seat": decision.hand.button_seat,
        "max_seats": 2,
        "hero": HERO,
        "players": players,
        "events": replay["events"][: decision.step],
    }
    card = next((rule for rule in match.playbook.rules if rule["id"] == decision.advice["rule"]), None)
    return Scenario.objects.create(
        owner=match.user,
        source="match",
        topic="action",
        origin={"match": match.pk, "hand": decision.hand.number, "decision": decision.pk},
        spec={
            "hand": hand,
            "labels": "names",
            "revealed": {},
            "question": {"kind": "action", "prompt": "What do you do?"},
            "legal": legal_of(decision.context),
            "panel": True,
        },
        answer={
            "advice": decision.advice,
            "rule": card and {key: card.get(key) for key in _CARD},
            "context": {key: decision.context.get(key) for key in _NUMBERS},
            "you_did": decision.move,
        },
        grading="rule",
        skills=["preflop" if decision.context["street"] == "preflop" else "postflop"],
        tier=2,
    )


_CARD = ("id", "number", "family", "rule", "why", "scope", "source")
_NUMBERS = (
    "street", "facing", "bettor", "bet", "pot_before", "to_call", "pot", "pot_if_call", "equity_needed", "mdf",
    "effective_bb", "spr", "players", "position", "hand_class", "made", "draws", "in_front", "big_blind",
)


def _decision(decision, cards):
    """A decision as the debrief lists it: the table at it, what it faced, what the coach said, and what was done."""
    context = decision.context
    table = table_hand(decision.hand)
    table["events"] = table["events"][: decision.step]
    table["players"] = [
        {**player, "cards": player["cards"] if player["name"] == HERO else [], "won": 0, "net": 0}
        for player in table["players"]
    ]
    return {
        "table": table,
        "line": coach.advice_line(decision.advice, cards, context),
        "hand": decision.hand.number,
        "step": decision.step,
        "street": context["street"],
        "holding": HAND_NAMES.get(context["made"], "") if context["made"] else "",
        "cards": context["cards"],
        "pot_bb": context["pot_bb"],
        "advice": decision.advice,
        "move": decision.move,
        "followed": decision.followed,
        "departure": decision.departure,
        "asked": decision.asked,
    }


def _net(row):
    return next(player["net"] for player in row.replay["players"] if player["name"] == HERO)


def _net_bb(hands, decision):
    row = hands.get(decision.hand.number)
    return _net(row) / row.big_blind if row else 0

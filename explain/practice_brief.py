"""Briefs for practice (pokerland-llm-reports.md, 3.4): an answered spot, a coach's line, a match's debrief, and an
aptitude test.

Each holds only what the page already showed: a spot's answer once it was answered (a test's once the test is over),
a coach's line once it was given, a bot's style and leak once the match is over. Own-hand spots name their players
by position, as hand briefs do: their questions and the templates' wording carry screen names, so those are
replaced too. Generated and library spots have no real names to replace.
"""

import re

from explain.hand_brief import bb_text, percent, streets_of
from hands.shares import HERO
from practice import aptitude
from practice.coach import advice_line, move_text
from practice.debrief import against_the_truth, by_the_book, luck_and_play, one_thing, three_hands, what_moved
from practice.playbook import FAMILIES
from practice.serializers import FixSerializer, LuckSerializer, PickedHandSerializer, TruthSerializer
from practice.sets import SKILLS
from practice.spots import HAND_NAMES

# How a practice grade reads as the engine's verdict on the answer.
GRADE_VERDICTS = {"good": "kept", "acceptable": "close", "poor": "broke", "ungraded": "none"}
GRADINGS = {
    "exact": "exact maths from stated inputs",
    "reference": "a published reference chart",
    "rule": "a playbook rule of thumb, which counts half",
    "reflection": "nothing firm: a spot to reflect on, not graded",
}
STYLES = {
    "tag": "tight-aggressive",
    "lag": "loose-aggressive",
    "station": "a calling station",
    "rock": "a rock",
}
PLACEHOLDER = re.compile(r"\{(a\d+)\}")
MISSES = 8  # a test's missed spots the brief describes, at most


def names_of(table):
    """What a spot's table calls each player in the brief: the hero "Hero", the rest by position."""
    hero = table.get("hero")
    return {
        player["name"]: HERO if player["name"] == hero else player.get("position") or f"Seat {player['seat']}"
        for player in table.get("players", [])
    }


def wording(text, names, amounts, bb):
    """A spot's text with its amounts in big blinds and its players named as the brief names them."""
    if not text:
        return text
    text = PLACEHOLDER.sub(lambda m: bb_text(amounts[m.group(1)], bb) if m.group(1) in amounts else m.group(0), text)
    for name in sorted(names, key=len, reverse=True):
        if name and name != names[name]:
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", names[name], text)
    return text


def move_words(move, bb):
    """A move as the brief says it: "fold", "call", "raise to 7.5 bb"."""
    if not move:
        return None
    action = move.get("action", "")
    if action in ("bet", "raise") and move.get("to"):
        return f"{action} to {bb_text(move['to'], bb)}"
    if action in ("call", "bet") and move.get("amount"):
        return f"{action} {bb_text(move['amount'], bb)}"
    return action


def numbers_of(context, names, bb):
    """The decision panel's numbers for a spot, as hand briefs give them."""
    if not context:
        return {}
    found = {"street": context.get("street")}
    if context.get("position"):
        found["position"] = "in position" if context["position"] == "in" else "out of position"
    if context.get("facing") not in (None, "none") and context.get("equity_needed") is not None:
        bettor = names.get(context.get("bettor"), context.get("bettor"))
        found["facing"] = f"{bettor}'s {context['facing']} of {bb_text(context['bet'], bb)}"
        found["price"] = (
            f"{bb_text(context['to_call'], bb)} to win a pot of {bb_text(context['pot_if_call'], bb)}: "
            f"a call needs {percent(context['equity_needed'])}"
        )
    if context.get("mdf") is not None:
        found["minimum_defense"] = percent(context["mdf"])
    if context.get("spr") is not None:
        found["spr"] = round(context["spr"], 1)
    if context.get("made"):
        found["holding"] = HAND_NAMES.get(context["made"], context["made"])
    if context.get("draws"):
        found["draws"] = [draw.replace("_", " ") for draw in context["draws"]]
    if context.get("cards"):
        found["cards"] = context["cards"]
    if context.get("board"):
        found["board"] = context["board"]
    return found


def rule_of(card):
    return {"number": card["number"], "says": card["rule"], "why": card["why"]} if card else None


def spot_of(scenario, attempt):
    """A practice spot and its answer, as the brief tells it: the question, the table so far, the player's answer and
    the reference, in big blinds and with nobody's screen name."""
    spec, answer = scenario.spec, scenario.answer
    table = spec.get("hand") or {}
    bb = table.get("big_blind") or (answer.get("context") or {}).get("big_blind") or 1
    names = names_of(table) if spec.get("labels") == "names" else {}
    hero = table.get("hero")
    seat_names = {**{player["name"]: player["name"] for player in table.get("players", [])}, **names}
    if hero:
        seat_names[hero] = HERO
    question = spec.get("question", {})
    amounts = answer.get("amounts") or question.get("amounts") or {}

    def say(text):
        return wording(text, names, amounts, bb)

    spot = {
        "skills": [SKILLS.get(skill, skill) for skill in scenario.skills],
        "graded_by": GRADINGS.get(scenario.grading, scenario.grading),
        "question": say(question.get("prompt", "")),
    }
    if table:
        events = [
            {**event, "player": seat_names.get(event["player"], event["player"])} if "player" in event else event
            for event in table.get("events", [])
        ]
        spot["table"] = {
            "game": table.get("game"),
            "seats": [
                {
                    "player": seat_names.get(player["name"], player["name"]),
                    "position": player.get("position"),
                    "stack_bb": round(player["stack"] / bb, 1),
                    **({"cards": player["cards"]} if player.get("cards") else {}),
                }
                for player in table.get("players", [])
            ],
            "streets": streets_of(events, bb),
        }
    kind = question.get("kind")
    if kind == "choice":
        options = [say(option) for option in question.get("options", [])]
        spot["options"] = options
        if attempt and attempt.choice is not None and attempt.choice < len(options):
            spot["your_answer"] = options[attempt.choice]
        if "correct" in answer and answer["correct"] < len(options):
            spot["correct_answer"] = options[answer["correct"]]
    elif kind == "range":
        spot["your_answer"] = attempt.hand_range if attempt else None
        spot["stated_range"] = answer.get("range")
    else:
        if attempt:
            spot["your_answer"] = move_words({"action": attempt.action, "to": attempt.amount}, bb)
        if answer.get("best"):
            spot["best"] = answer["best"]
        if answer.get("acceptable"):
            spot["acceptable"] = answer["acceptable"]
        if answer.get("ev_bb"):
            spot["ev_bb"] = answer["ev_bb"]
        if answer.get("advice"):
            spot["playbook_move"] = move_text(answer["advice"])
        if answer.get("rule"):
            spot["rule"] = rule_of(answer["rule"])
    for key in ("assumptions", "explanation", "formula"):
        if answer.get(key):
            spot[key] = say(answer[key])
    if answer.get("equity") is not None:
        spot["equity"] = percent(answer["equity"])
    if answer.get("chart"):
        chart = answer["chart"]
        spot["chart"] = {key: chart.get(key) for key in ("label", "tier_label", "range", "source")}
    if answer.get("context"):
        spot["numbers"] = numbers_of(answer["context"], seat_names, bb)
    if answer.get("they_did"):
        spot["they_did"] = move_words(answer["they_did"], bb)
    if answer.get("their_hand"):
        spot["their_hand"] = answer["their_hand"]
    if attempt:
        spot["grade"] = attempt.grade
        if attempt.ev_lost_bb is not None:
            spot["ev_lost_bb"] = attempt.ev_lost_bb
    # Shown last on the feedback card, so the result doesn't sway the review.
    if answer.get("you_did"):
        spot["you_did_at_the_table"] = move_words(answer["you_did"], bb)
    if (answer.get("result") or {}).get("net_bb") is not None:
        spot["hand_result_bb"] = answer["result"]["net_bb"]
    return spot


def skill_links(skills):
    return [f"skill:{skill}" for skill in skills if skill in SKILLS] or [f"skill:{skill}" for skill in SKILLS]


def attempt_brief(attempt):
    """An answered practice spot: why the reference answer, and what the player's answer gave up."""
    scenario = attempt.scenario
    spot = spot_of(scenario, attempt)
    verdict = GRADE_VERDICTS.get(attempt.grade, "none")
    card = scenario.answer.get("rule")
    links = skill_links(scenario.skills) + ([f"rule:{card['id']}"] if card else [])
    decision = {
        "verdict": verdict,
        "step": None,
        "street": (scenario.answer.get("context") or {}).get("street"),
        "move": spot.get("your_answer") or "your answer",
        "rule": card["number"] if card else None,
    }
    data = {
        "kind": "attempt",
        "spot": spot,
        "decisions": [{"ref": "d0", "verdict": verdict, "your_answer": decision["move"]}],
        "practice_links": links,
    }
    return {"input": data, "decisions": {"d0": decision}, "links": links}


def advice_verdict(advice, followed):
    """The engine's verdict on a decision at a practice table, from the coach's advice and whether it was followed."""
    if advice.get("basis") == "none":
        return "none"
    if advice.get("verdict") in ("close", "your_call"):
        return advice["verdict"]
    return "kept" if followed else "broke"


def decision_brief(decision):
    """A coach's line at a practice table, once the player has acted on it: why the playbook says what it says."""
    match = decision.match
    cards = {rule["id"]: rule for rule in match.playbook.rules}
    context = decision.context
    bb = context.get("big_blind") or 1
    verdict = advice_verdict(decision.advice, decision.followed)
    card = cards.get(decision.advice.get("rule"))
    move = move_words(decision.move, bb)
    links = [f"rule:{card['id']}"] if card else []
    links += ["skill:postflop" if context.get("street") != "preflop" else "skill:preflop"]
    data = {
        "kind": "decision",
        "match": {"opponent": "a bot, heads-up", "coach_stage": decision.stage, "playbook": match.playbook.name},
        "spot": numbers_of(context, {}, bb),
        "coach_said": advice_line(decision.advice, cards, context),
        "playbook_move": move_text(decision.advice),
        "rule": rule_of(card),
        "decisions": [{"ref": "d0", "verdict": verdict, "you_did": move}],
        **({"your_reason": decision.reason} if decision.reason else {}),
        **({"why_you_left_the_rule": decision.departure} if decision.departure else {}),
        "practice_links": links,
    }
    meta = {"verdict": verdict, "step": None, "street": context.get("street"), "move": move}
    meta["rule"] = rule_of_number(card)
    return {"input": data, "decisions": {"d0": meta}, "links": links}


def rule_of_number(card):
    return card["number"] if card else None


def debrief_brief(match):
    """A finished coached match: what to fix, the hands that show it, by the book, the read, and luck against play.
    Built from the debrief's own parts, without sending anything to practice (practice.debrief.send_to_practice)."""
    decisions = list(match.decisions.select_related("hand").order_by("hand__number", "step"))
    cards = {rule["id"]: rule for rule in match.playbook.rules}
    hands = {row.number: row for row in match.table.hands.filter(finished=True)}
    fix = one_thing(decisions, cards)
    picked = PickedHandSerializer(three_hands(decisions, hands, cards, fix), many=True).data
    luck = LuckSerializer(luck_and_play(match, hands, decisions)).data
    read = TruthSerializer(against_the_truth(match)).data
    fixed = FixSerializer(fix).data if fix else None
    numbers = {rule["id"]: rule for rule in match.playbook.rules}
    book = [
        {
            "rule": numbers[row["rule"]]["number"],
            "says": numbers[row["rule"]]["rule"],
            "kept": row["did"],
            "of": row["could"],
        }
        for row in by_the_book(decisions, match.playbook.rules)
        if row["rule"] in numbers and row["could"]
    ]
    moved = [
        {"family": FAMILIES.get(row["family"], row["family"]), "from_stage": row["from"], "to_stage": row["to"]}
        for row in what_moved(match, decisions)
    ]
    kept, entries = {}, []
    for index, hand in enumerate(picked):
        ref = f"d{index}"
        bb = hand["table"]["big_blind"] or 1
        verdict = advice_verdict(hand["advice"], hand["followed"])
        card = cards.get(hand["advice"].get("rule"))
        move = move_words(hand["move"], bb)
        events = [
            {**event, "player": HERO if event.get("player") == hand["table"]["hero"] else event.get("player")}
            for event in hand["table"]["events"]
        ]
        entries.append(
            {
                "ref": ref,
                "picked_as": {"departure": "your biggest departure", "best": "your best decision"}.get(
                    hand["kind"], "your closest decision"
                ),
                "hand_number": hand["hand"],
                "streets": streets_of(events, bb),
                "street": hand["street"],
                "holding": hand.get("holding"),
                "cards": hand.get("cards"),
                "coach_said": hand.get("line"),
                "you_did": move,
                "verdict": verdict,
                "rule": rule_of(card),
            }
        )
        kept[ref] = {"verdict": verdict, "step": None, "street": hand["street"], "move": move}
        kept[ref]["rule"] = rule_of_number(card)
    links = [f"rule:{fixed['rule']['id']}"] if fixed and fixed.get("rule") else []
    links += [f"skill:{skill}" for skill in ("preflop", "postflop", "arithmetic")]
    data = {
        "kind": "debrief",
        "match": {
            "hands_played": match.table.hands_played,
            "result_bb": match.result_bb,
            "opponent_style": STYLES.get(read["style"], read["style"]),
            "opponent_leak": read["leak_label"],
            "your_label": STYLES.get(read["label"], read["label"]),
            "label_right": read["label_right"],
            "leak_found": read["found"],
        },
        "one_thing_to_fix": (
            {"family": fixed["label"], "misses": fixed["misses"], "rule": rule_of(fixed["rule"])} if fixed else None
        ),
        "by_the_book": book,
        "luck": {key: luck[key] for key in ("actual_bb", "expected_bb", "luck_bb")} | {"coolers": len(luck["coolers"])},
        "families_moved": moved,
        "decisions": entries,
        "practice_links": links,
    }
    return {"input": data, "decisions": kept, "links": links}


def test_brief(test):
    """A finished aptitude test: each skill's accuracy and its range, and the spots missed."""
    report = aptitude.report(test)
    skills = [
        {
            "skill": row["label"],
            "spots": row["spots"],
            "accuracy": f"{row['pct']}%" if row["pct"] is not None else None,
            "range": f"{row['ci_low']}% to {row['ci_high']}%" if row["ci_low"] is not None else None,
            "in_words": row["words"],
        }
        for row in report["skills"]
        if row["spots"]
    ]
    missed = [row for row in report["spots"] if row["attempt"] and row["attempt"].grade == "poor"][:MISSES]
    entries, kept = [], {}
    for index, row in enumerate(missed):
        ref = f"d{index}"
        spot = spot_of(row["scenario"], row["attempt"])
        spot.pop("table", None)  # the question says enough for a test's review
        entries.append({"ref": ref, "verdict": "broke", **spot})
        street = (row["scenario"].answer.get("context") or {}).get("street")
        kept[ref] = {"verdict": "broke", "step": None, "street": street, "move": spot.get("your_answer"), "rule": None}
    links = [f"skill:{skill}" for skill in SKILLS]
    data = {
        "kind": "test",
        "test": {"answered": report["answered"], "planned": report["planned"], "minutes": report["minutes"]},
        "skills": skills,
        "decisions": entries,
        "practice_links": links,
    }
    return {"input": data, "decisions": kept, "links": links}

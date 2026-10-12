"""The brief for one of the user's hands (pokerland-llm-reports.md, 5.2).

The hand as the replay shows it, with every player named by their position and the hero as "Hero" (as a share link
has it, hands.shares.anonymized); amounts in big blinds; each of the hero's decisions with the decision panel's
numbers (practice.spots) and the starter playbook's verdict on it (practice.rules); the preflop checks the hand broke
(hands.leaks); all-in equity against the result (A4); and the player's own notes, tags and bet purposes.
"""

from hands.leaks import broken_in, presets_of
from hands.models import HandNote, HandPlayer, Opponent
from hands.opponents import effective_label
from hands.shares import HERO, anonymized
from practice.coach import move_text, size_text
from practice.rules import evaluate, follows
from practice.sets import SKILLS, hand_data, house_playbook
from practice.spots import HAND_NAMES, POSTFLOP, decisions

STYLES = {
    "tag": "tight-aggressive",
    "lag": "loose-aggressive",
    "rock": "tight and passive (a rock)",
    "station": "loose and passive (a calling station)",
}
# The preflop and postflop checks (hands.leaks.CHECKS), each as a rule in words, from the user's presets.
CHECK_RULES = {
    "open_limp": lambda p: "Never open-limp: raise or fold when the pot is folded to you.",
    "open_size": lambda p: (
        f"Open to {p['open_bb']:g} bb, plus {p['limper_bb']:g} bb for each limper; in tournaments, "
        f"{p['tournament_open_bb']:g} bb."
    ),
    "three_bet_size": lambda p: f"3-bet to {p['three_bet_x']:g} times the raise, plus one more for each caller.",
    "short_stack_raise": lambda p: (
        f"With {p['short_stack_bb']:g} bb or less effective, move in rather than raise small."
    ),
    "premium_limp": lambda p: "Raise queens or better and ace-king: don't limp them into a pot four or more see.",
    "short_buy_in": lambda p: f"Start every cash-game hand with at least {p['buy_in_bb']:g} bb.",
    "folded_strong": lambda p: "Don't fold a set, or two pair using both cards, to a bet on a dry, unpaired board.",
    "missed_thin_value": lambda p: "Checked to you on the river in position with a hand that wins: bet it for value.",
    "multiway_bluff": lambda p: (
        f"Don't bluff into {p['bluff_opponents']:g} or more opponents, or c-bet into {p['cbet_opponents']:g} or more."
    ),
    "big_pot_small_hand": lambda p: (
        f"Don't put {p['big_pot_bb']:g} bb or more in with one pair below top pair at {p['deep_bb']:g} bb deep."
    ),
}
PLAYBOOK_NOTE = (
    "Verdicts come from the starter heads-up playbook. Its rules are written for heads-up play, so many decisions in "
    "pots with more players have no verdict."
)


def build(hand):
    """The brief's input for a hand, its decisions with their verdicts, and the links "Practise it" may use."""
    shown = anonymized(hand)
    bb = hand.big_blind
    rules = house_playbook().rules
    notes = list(HandNote.objects.filter(hand=hand).order_by("kind", "street", "bet"))
    hero_row = HandPlayer.objects.filter(hand=hand, is_hero=True).first()
    decided = described(hand_data(shown), rules, notes, bb)
    links = [*dict.fromkeys(f"rule:{entry['rule']['id']}" for entry in decided if "rule" in entry)]
    links += [f"skill:{skill}" for skill in SKILLS]
    presets = presets_of(hand.user_id)
    data = {
        "kind": "hand",
        "hand": {
            "game": hand.game,
            "format": format_of(hand),
            "blinds_bb": blinds_of(hand),
            "players_dealt": len(shown.replay.get("players", [])),
            "seats": seats_of(hand, shown, bb),
            "streets": streets_of(shown.replay.get("events", []), bb),
            "result": result_of(hand, hero_row, bb),
        },
        "decisions": decided,
        "checks_broken": [{"check": key, "rule": CHECK_RULES[key](presets)} for key in broken_in(hand, presets)],
        "notes": [
            {"on": note.street or "the whole hand", "text": note.text}
            for note in notes
            if note.kind == HandNote.Kind.NOTE and note.text
        ],
        "tags": [note.value for note in notes if note.kind == HandNote.Kind.TAG],
        "playbook": PLAYBOOK_NOTE,
        "practice_links": links,
    }
    kept = {
        entry["ref"]: {
            "verdict": entry["verdict"],
            "step": entry["step"],
            "street": entry["street"],
            "move": entry["move"],
            "rule": entry["rule"]["number"] if "rule" in entry else None,
        }
        for entry in decided
    }
    return {"input": data, "decisions": kept, "links": links}


def bb_text(chips, bb):
    """Chips in big blinds, to a tenth: "2.5 bb", "6 bb"."""
    return f"{round(chips / bb, 1):g} bb"


def percent(share):
    return f"{round(share * 100)}%"


def format_of(hand):
    kind = "tournament" if hand.tournament_id else "cash"
    money = "play money" if hand.play_money else hand.currency or "chips"
    return f"{kind}, {money}"


def blinds_of(hand):
    blinds = {"small": round(hand.small_blind / hand.big_blind, 2), "big": 1}
    if hand.replay.get("ante"):
        blinds["ante"] = round(hand.replay["ante"] / hand.big_blind, 2)
    return blinds


def seats_of(hand, shown, bb):
    """Each player by position, with their stack, their cards if they were shown, and the user's read on them."""
    labels = {
        player["name"]: HERO if player["name"] == hand.hero else player["position"] or f"Seat {player['seat']}"
        for player in hand.replay.get("players", [])
    }
    reads = {}
    opponents = [name for name in labels if name != hand.hero]
    for opponent in Opponent.objects.filter(user=hand.user_id, site=hand.site, name__in=opponents):
        if style := effective_label(opponent):
            whose = "your label" if opponent.manual_label else f"{opponent.confidence or 'low'} confidence"
            reads[labels[opponent.name]] = f"{STYLES[style]} ({whose}), {opponent.hands} hands seen"
    seats = []
    for player in shown.replay.get("players", []):
        seat = {"player": player["name"], "position": player.get("position") or None}
        seat["stack_bb"] = round(player["stack"] / bb, 1)
        if player["name"] == HERO:
            seat["hero"] = True
        if player.get("cards"):
            seat["cards"] = player["cards"]
        if player["name"] in reads:
            seat["read"] = reads[player["name"]]
        seats.append(seat)
    return seats


def streets_of(events, bb):
    """The action street by street, in words, with the board and the pot as each street after the first began."""
    streets = [{"street": "preflop", "actions": []}]
    put_in = 0
    for event in events:
        kind = event["type"]
        if kind == "street":
            street = {"street": event["street"], "pot_bb": round(put_in / bb, 1), "actions": []}
            if event.get("board"):
                street["board"] = event["board"]
            streets.append(street)
            continue
        if kind in ("post", "call", "bet", "raise"):
            put_in += event.get("amount", 0)
        elif kind == "return":
            put_in -= event.get("amount", 0)
        if text := action_text(event, bb):
            streets[-1]["actions"].append(text)
    return streets


def action_text(event, bb):
    """One action in words, or None for what the replay shows but a reader needn't: posts, deals, returned bets."""
    who, kind = event.get("player", ""), event["type"]
    if kind in ("fold", "check"):
        text = f"{who} {kind}s"
    elif kind in ("call", "bet"):
        text = f"{who} {kind}s {bb_text(event.get('amount', 0), bb)}"
    elif kind == "raise":
        text = f"{who} raises to {bb_text(event.get('to', event.get('amount', 0)), bb)}"
    elif kind == "show":
        text = f"{who} shows {' '.join(event.get('cards', []))}"
        if event.get("description"):
            text += f" ({event['description']})"
    elif kind == "muck":
        text = f"{who} mucks {' '.join(event.get('cards', []))}".rstrip()
    elif kind == "collect":
        text = f"{who} wins {bb_text(event.get('amount', 0), bb)}"
    else:
        return None
    return f"{text}, all-in" if event.get("all_in") else text


def result_of(hand, hero_row, bb):
    """How the hand went for the hero, and, when the money went in before the river, what they could expect."""
    result = {"hero_net_bb": round(hand.hero_net / bb, 2), "showdown": hand.final_street == "showdown"}
    if hero_row and hero_row.allin_equity is not None:
        result["all_in"] = {
            "street": hero_row.allin_street,
            "equity": percent(hero_row.allin_equity),
            "expected_bb": round(hero_row.ev_net_bb, 2),
            "actual_bb": round(hero_row.net_bb, 2),
        }
    return result


def described(data, rules, notes, bb):
    """Each of the hero's decisions with its numbers, what they said it was for, and the playbook's verdict."""
    cards = {rule["id"]: rule for rule in rules}
    purposes = {note.bet: note.value for note in notes if note.kind == HandNote.Kind.PURPOSE}
    found = []
    bet_number = 0  # purposes are kept by the hero's bets and raises, counted from 0 (hands.notes)
    for index, context in enumerate(decisions(data)):
        move = context["move"]
        advice = evaluate(context, rules)
        verdict = verdict_of(advice, move)
        entry = {"ref": f"d{index}", "step": context["step"], "street": context["street"]}
        entry["move"] = move_words(move, bb)
        if move["action"] in ("bet", "raise"):
            if purpose := purposes.get(bet_number):
                entry["your_purpose"] = purpose.replace("_", " ")
            bet_number += 1
        entry.update(numbers(context, advice, bb))
        entry["verdict"] = verdict
        card = cards.get(advice["rule"])
        if card and verdict != "none":
            entry["basis"] = advice["basis"]
            entry["rule"] = {"id": card["id"], "number": card["number"], "says": card["rule"], "why": card["why"]}
            entry["playbook_move"] = move_text(advice)
        found.append(entry)
    return found


def verdict_of(advice, move):
    """The engine's verdict on a decision already made: kept, broke, close, your_call, or none where no card speaks."""
    if advice["basis"] == "none":
        return "none"
    if advice["verdict"] in ("close", "your_call"):
        return advice["verdict"]
    return "kept" if follows(advice, move) else "broke"


def move_words(move, bb):
    """What the hero did, in words: "call 1.8 bb", "bet 3 bb (half the pot)", "raise to 7.5 bb, all-in"."""
    action = move["action"]
    if action == "call":
        text = f"call {bb_text(move['amount'], bb)}"
    elif action == "bet":
        text = f"bet {bb_text(move['amount'], bb)}"
        if move.get("size"):
            text += f" ({size_text(move['size'])})"
    elif action == "raise":
        text = f"raise to {bb_text(move['to'], bb)}"
    else:
        text = action
    return f"{text}, all-in" if move.get("all_in") else text


def numbers(context, advice, bb):
    """The decision panel's numbers for a decision (A1), in words where words read better."""
    found = {
        "players_in": context["players"],
        "pot_bb": round(context["pot_bb"], 1),
        "effective_stack_bb": round(context["effective_bb"], 1),
    }
    if context["position"]:
        found["position"] = "in position" if context["position"] == "in" else "out of position"
    if context["street"] == "preflop" and context["situation"]:
        found["facing_preflop"] = context["situation"]
    if context["facing"] != "none" and context["equity_needed"] is not None:
        bet = bb_text(context["bet"], bb)
        before = bb_text(context["pot_before"], bb)
        found["facing"] = f"{context['bettor']}'s {context['facing']} of {bet} into {before}"
        found["price"] = (
            f"{bb_text(context['to_call'], bb)} to win a pot of {bb_text(context['pot_if_call'], bb)}: "
            f"a call needs {percent(context['equity_needed'])}"
        )
    if context["mdf"] is not None:
        found["minimum_defense"] = percent(context["mdf"])
    if context["spr"] is not None:
        found["spr"] = round(context["spr"], 1)
    if context["street"] in POSTFLOP:
        found["holding"] = HAND_NAMES.get(context["made"], context["made"] or "nothing")
        if context["draws"]:
            found["draws"] = [draw.replace("_", " ") for draw in context["draws"]]
        if context["hand_class"]:
            found["hand_class"] = context["hand_class"].replace("_", " ")
        if advice.get("outs"):
            found["outs"] = advice["outs"]
            found["chance_to_improve"] = percent(advice["draw_equity"])
    return found

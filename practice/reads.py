"""The read card: a notebook on the opponent in a coached match (pokerland-practice-mode-additional.md, 4.5).

- **Counts**, kept from the action everyone sees: "Raises the button 5 of 5", "Folds to a flop bet 0 of 3". A
  count with no chance behind it says so.
- **Showdown notes.** A hand that shows their cards is read backwards, from the cards to the line [JHU 4], and
  asks one question: what did that tell you? The tags it offers fit what they did.
- **Reads**: what the player (or, at stages 1 and 2, the coach) decides the opponent does, each with the
  evidence behind it. A read with thin evidence unlocks its adjustment for close decisions only; strong evidence
  unlocks it for clear ones [MIT 8].
- **A label**, proposed once the counts allow, from the same quadrant as the style bots [MIT 1].

The bot's settings never come in: only what the table showed.
"""

from practice.spots import HAND_NAMES, decisions
from tracker.parsing.facts import hand_facts

# Reads the card can hold, by tag: what they say, and the playbook read (practice.playbook.READS) each unlocks.
TAGS = {
    "doesnt_fold": ("Doesn't fold", "doesnt_fold"),
    "folds_to_second_bet": ("Folds to a second bet", None),
    "bets_big_weak": ("Bets big with weak hands", "big_bets_weak"),
    "raises_strong": ("Raises only with strong hands", None),
    "raises_every_button": ("Raises every button", None),
    "river_bets_strong": ("Never bluffs the river", None),
}
# The tags that find each of practice.bots.LEAKS.
FINDS = {
    "never_folds_pair": "doesnt_fold",
    "folds_to_second_bet": "folds_to_second_bet",
    "bets_big_weak": "bets_big_weak",
    "raises_only_nuts": "raises_strong",
    "raises_every_button": "raises_every_button",
    "never_bluffs_river": "river_bets_strong",
}
ONE_OFF = {"just_once": "Just this once", "not_sure": "Not sure"}
BIG_BET = 0.75  # of the pot: a big bet, as the coach's rules have it
LABEL_HANDS = 12  # hands before the card proposes a label
LABEL_MOVES = 10  # and moves after the flop, for the aggression it is drawn on
# Evidence behind a read: a count backs it with its chances once it has COUNT_EVIDENCE of them at a telling share,
# and a showdown note that says it with SHOWDOWN_WEIGHT. THIN_EVIDENCE makes it a read; STRONG_EVIDENCE a strong one.
COUNT_EVIDENCE = 4
SHOWDOWN_WEIGHT = 2
THIN_EVIDENCE, STRONG_EVIDENCE = 3, 8
# Hands too weak to call bets down with, for a read that the opponent doesn't fold.
WEAK_CALLS = {"high_card", "overcards", "underpair", "bottom_pair"}
# Where the style quadrant splits, as My game draws it (pokerland-client's src/playerStats.ts).
LOOSE_VPIP, AGGRESSIVE = 25, 40


def opponent_view(hands, hero, villain):
    """What the table showed of the opponent: their decisions in each finished hand, with their cards if shown."""
    seen = []
    for number, data in hands:
        shown = next((player["cards"] for player in data["players"] if player["name"] == villain), [])
        moves = decisions({**data, "hero": villain}, villain)  # their cards, when shown, come from the seat row
        seen.append({"number": number, "data": data, "moves": moves, "shown": shown})
    return seen


def counts(seen, hero, villain):
    """The card's counts, each {"key", "label", "did", "could"}, from the public action in finished hands."""
    totals = {key: [0, 0] for key in ("button", "defend", "bets_checked", "folds_flop", "folds_second", "river")}

    def tally(key, did):
        totals[key][0] += bool(did)
        totals[key][1] += 1

    for hand in seen:
        facts = {row["name"]: row for row in hand_facts(_extracted(hand["data"]), with_equity=False)["players"]}
        them = facts.get(villain)
        if not them:
            continue
        if them["position"] == "BTN" and them["rfi_could"]:
            tally("button", them["rfi_did"])
        if them["bb_defend_could"]:
            tally("defend", them["bb_defend_did"])
        faced = 0
        for move in hand["moves"]:
            if move["street"] == "preflop":
                continue
            if move["facing"] == "none" and move["street"] == "flop" and move["checks"]:
                tally("bets_checked", move["move"]["action"] in ("bet", "raise"))
            if move["facing"] != "none":
                if move["street"] == "flop" and faced == 0:
                    tally("folds_flop", move["move"]["action"] == "fold")
                if faced == 1:
                    tally("folds_second", move["move"]["action"] == "fold")
                faced += 1
            if move["street"] == "river" and move["facing"] == "none":
                tally("river", move["move"]["action"] in ("bet", "raise"))
    labels = {
        "button": "Raises the button",
        "defend": "Defends the big blind against a raise",
        "bets_checked": "Bets the flop when checked to",
        "folds_flop": "Folds to a flop bet",
        "folds_second": "Folds to a second bet",
        "river": "Bets the river when it can",
    }
    return [{"key": key, "label": labels[key], "did": did, "could": could} for key, (did, could) in totals.items()]


def showdowns(seen):
    """Every hand that showed the opponent's cards, read backwards: their biggest move, what they held, and tags."""
    found = []
    for hand in seen:
        if len(hand["shown"]) != 2:
            continue
        moves = [
            move
            for move in hand["moves"]
            if move["move"]["action"] in ("bet", "raise") and move["street"] != "preflop"
        ]
        if not moves:
            line, offer = _passive_line(hand)
        else:
            biggest = max(moves, key=lambda move: move["move"].get("size") or 0)
            line, offer = _aggressive_line(biggest)
        found.append({"number": hand["number"], "cards": hand["shown"], "line": line, "offer": [*offer, *ONE_OFF]})
    return found


def _aggressive_line(move):
    size = move["move"].get("size") or 0
    verb = "Raised" if move["move"]["action"] == "raise" else "Bet"
    sized = "the pot or more" if size >= 1 else f"{round(size * 100)}% of the pot"
    line = f"{verb} {sized} on the {move['street']} with {HAND_NAMES.get(move['made'], 'nothing')}"
    weak = move["hand_class"] in ("nothing", "showdown_value", "draw")
    if size >= BIG_BET and weak:
        offer = ["bets_big_weak"]
    elif move["move"]["action"] == "raise" and not weak:
        offer = ["raises_strong"]
    elif move["street"] == "river" and not weak:
        offer = ["river_bets_strong"]
    else:
        offer = []
    return line, offer


def _passive_line(hand):
    calls = [move for move in hand["moves"] if move["move"]["action"] == "call" and move["street"] != "preflop"]
    if not calls:
        return "Checked it down", []
    last = calls[-1]
    bets = "a bet" if len(calls) == 1 else f"{len(calls)} bets"
    line = f"Called {bets} after the flop with {HAND_NAMES.get(last['made'], 'nothing')}"
    # Calling bets down tells something only with a hand that beats little.
    telling = last["made"] in WEAK_CALLS or any((call["facing_pot"] or 0) >= BIG_BET for call in calls)
    return line, ["doesnt_fold"] if telling and last["hand_class"] != "strong" else []


def label(seen, villain):
    """The style the counts propose once there are hands enough: VPIP and aggression, as the quadrant splits them."""
    vpip = [0, 0]
    aggression = [0, 0]
    for hand in seen:
        row = next(row for row in hand_facts(_extracted(hand["data"]), with_equity=False)["players"] if row["name"] == villain)
        vpip[0] += row["vpip_did"]
        vpip[1] += row["vpip_could"]
        aggressive = row["postflop_bets"] + row["postflop_raises"]
        aggression[0] += aggressive
        aggression[1] += aggressive + row["postflop_calls"] + row["postflop_folds"]
    if len(seen) < LABEL_HANDS or not vpip[1] or aggression[1] < LABEL_MOVES:
        return None
    loose = 100 * vpip[0] / vpip[1] >= LOOSE_VPIP
    bold = 100 * aggression[0] / aggression[1] >= AGGRESSIVE
    style = ("lag" if loose else "tag") if bold else ("station" if loose else "rock")
    return {
        "style": style,
        "vpip": round(100 * vpip[0] / vpip[1]),
        "aggression": round(100 * aggression[0] / aggression[1]),
        "hands": len(seen),
    }


def evidence(tag, card_counts, notes):
    """How strong the evidence for a read is: "strong", "thin", or None when too little backs it.

    "1 showdown" reads differently from "6 of 7" [MIT 2]: a count backs a read only with chances enough, and only
    at a share that says it (a quarter or less for folding, nine in ten or more for the rest).
    """
    backing = SHOWDOWN_WEIGHT * sum(1 for note in notes if note.tag == tag and note.kind == "showdown")
    by_count = {"doesnt_fold": "folds_flop", "folds_to_second_bet": "folds_second", "raises_every_button": "button"}
    count = next((row for row in card_counts if row["key"] == by_count.get(tag)), None)
    if count and count["could"] >= COUNT_EVIDENCE:
        share = count["did"] / count["could"]
        if (share <= 0.25) if tag == "doesnt_fold" else (share >= 0.9):
            backing += count["could"]
    if backing >= STRONG_EVIDENCE:
        return "strong"
    return "thin" if backing >= THIN_EVIDENCE else None


def unlocked(reads, card_counts, notes, hands, label_accepted):
    """The playbook reads (practice.playbook.READS) the card unlocks, with their evidence: {read: "thin"|"strong"}.

    `reads` are the card's current read notes. "An opponent you can't read yet" holds until a label is accepted
    and the card has seen hands enough.
    """
    found = {}
    for note in reads:
        playbook_read = TAGS.get(note.tag, (None, None))[1]
        if playbook_read:
            strength = evidence(note.tag, card_counts, notes) or "thin"
            found[playbook_read] = max(found.get(playbook_read, "thin"), strength, key=("thin", "strong").index)
    if not label_accepted or hands < LABEL_HANDS:
        found["unknown"] = "strong"
    return found


def _extracted(data):
    """A practice hand's replay as tracker.parsing.facts reads a parsed one."""
    return {**data, "site": "practice", "hand_id": "", "tournament_id": ""}

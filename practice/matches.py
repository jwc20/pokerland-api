"""Coached matches: a short heads-up match against a bot with a leak, and a coach who hands over.

A match is a PracticeTable with two seats, "You" and "Villain", playing PracticeHands in turn: 30 hands from 40 big
blinds, the blinds going up every six hands so the stacks get short (pokerland-practice-mode-additional.md, 4.1).
Each of the player's decisions is a MatchDecision: what it faced (practice.spots), what the playbook says
(practice.rules, with the reads the card unlocks), the stage the coach was at, and what the player did. The
coach (practice.coach) speaks according to the stage of the decision's rule family; the bot (practice.bots)
moves as soon as it is its turn.

From stage 2 up, the advice for a decision isn't sent until the player has committed to theirs: an intent at
stage 2, a move at 3 and 4, or a question to the coach, which is counted.
"""

import random

from django.db import transaction
from django.utils import timezone

from practice import bots, coach, reads, rules
from practice.models import CoachedMatch, MatchDecision, PracticeHand, PracticeTable, ReadNote, RuleProgress
from practice.spots import pending
from practice.table import TableHand, shuffled_deck

HERO, VILLAIN = "You", "Villain"
STARTING_BB = 40
LEVELS = [(50, 100), (75, 150), (100, 200), (150, 300), (200, 400), (300, 600), (400, 800), (600, 1200)]
HANDS_PER_LEVEL = 6
FREE_SECONDS = 8  # a decision's own time before the match's time bank runs, as online [JHU 2]


class MatchError(ValueError):
    """Something the match can't do now, such as acting when it isn't the player's turn."""


@transaction.atomic
def start(user, playbook, opponent="mystery", coach_setting="progress", rng=None):
    """A new match: the bot's style (random for a mystery) and its leak (always random) stay hidden until it ends."""
    rng = rng or random.SystemRandom()
    style = rng.choice(sorted(bots.STYLES)) if opponent == "mystery" else opponent
    leak = rng.choice(sorted(bots.LEAKS))
    small, big = LEVELS[0]
    stack = STARTING_BB * big
    table = PracticeTable.objects.create(
        user=user,
        seats=[
            {"seat": 1, "name": HERO, "stack": stack},
            {"seat": 2, "name": VILLAIN, "stack": stack, "style": style, "leak": leak},
        ],
        small_blind=small,
        big_blind=big,
        button_seat=rng.choice((1, 2)),
    )
    match = CoachedMatch.objects.create(
        user=user, table=table, playbook=playbook, opponent=opponent, coach=coach_setting, starting_bb=STARTING_BB
    )
    deal(match, rng)
    return match


def level(number):
    """The blinds for a hand of the match: up a level every HANDS_PER_LEVEL hands."""
    return LEVELS[min((number - 1) // HANDS_PER_LEVEL, len(LEVELS) - 1)]


def deal(match, rng=None):
    """Deals the next hand, and plays the bot's moves until it is the player's turn or the hand is over."""
    table = match.table
    number = table.hands_played + 1
    small, big = level(number)
    seats = [{key: seat[key] for key in ("seat", "name", "stack")} for seat in table.seats]
    row = PracticeHand.objects.create(
        table=table,
        number=number,
        small_blind=small,
        big_blind=big,
        button_seat=table.button_seat,
        stacks=[seat["stack"] for seat in seats],
        deck=shuffled_deck(rng),
    )
    advance(match, row, rebuild(row), rng)
    return row


def rebuild(row):
    """A practice hand's PokerKit state, from its deck and moves."""
    seats = [{key: seat[key] for key in ("seat", "name")} for seat in row.table.seats]
    for seat, stack in zip(seats, row.stacks, strict=True):
        seat["stack"] = stack
    return TableHand(seats, row.button_seat, row.small_blind, row.big_blind, row.deck, row.moves)


def current_hand(match):
    return match.table.hands.order_by("-number").first()


def advance(match, row, hand, rng=None):
    """Plays the bot until the player is to act or the hand is over; saves the hand; opens the player's decision."""
    rng = rng or random.SystemRandom()
    bot = next(seat for seat in match.table.seats if seat["name"] == VILLAIN)
    while hand.actor == VILLAIN:
        context = pending(hand.replay(VILLAIN))
        hand.act(VILLAIN, *bots.decide(context, hand.legal(), bot["style"], bot["leak"], rng))
    row.moves = hand.moves
    row.replay = hand.replay(HERO)
    if hand.finished:
        finish_hand(match, row, hand)
    else:
        row.save()
        open_decision(match, row)


def open_decision(match, row):
    """Records the decision the player now faces, with the playbook's advice, unless it is already open."""
    step = len(row.replay["events"])
    if MatchDecision.objects.filter(hand=row, step=step).exists():
        return
    context = pending(row.replay)
    card = read_card(match)
    advice = rules.evaluate(context, match.playbook.rules, card["unlocked"])
    MatchDecision.objects.create(
        match=match,
        hand=row,
        step=step,
        context=context,
        advice=advice,
        stage=stage_for(match, advice["family"]),
    )


def stage_for(match, family):
    """The coach's stage for a rule family in this match: the one it was pinned to, or the player's progress."""
    if match.coach.isdigit():
        return int(match.coach)
    row = RuleProgress.objects.filter(user=match.user, playbook_key=match.playbook.key, family=family).first()
    return row.stage if row else 1


def open_decision_of(match):
    """The decision the player is to make now, or None."""
    row = current_hand(match)
    if row is None or row.finished:
        return None
    return MatchDecision.objects.filter(hand=row, move__isnull=True).order_by("-step").first()


def as_move(decision, action, amount):
    """A move as practice.spots describes one, from what the player chose: a bet's chips against the pot."""
    move = {"action": action}
    if action in ("bet", "raise") and amount:
        context = decision.context
        put_in = amount - context["in_front"]
        move.update(amount=put_in, to=amount, size=round(put_in / context["pot"], 3) if context["pot"] else None)
    elif action == "call":
        move["amount"] = decision.context["to_call"]
    return move


@transaction.atomic
def say_intent(match, action, amount=None, reason=None):
    """Stage 2: what the player would do, and why. Returns the decision, with the coach's verdict."""
    decision = _open(match)
    if decision.stage != 2 or decision.intent:
        raise MatchError("The coach isn't asking.")
    move = as_move(decision, action, amount)
    kept = rules.follows(decision.advice, move)
    fits, note = coach.reason_note(reason, action, decision.context)
    decision.intent = {
        "action": action,
        "amount": amount,
        "reason": reason or "",
        "kept": kept,
        "line": coach.verdict_line(decision.advice, move, kept),
        "reason_fits": fits,
        "reason_note": note,
    }
    decision.save(update_fields=["intent"])
    return decision


@transaction.atomic
def ask_coach(match):
    """"Ask the coach", at stage 3 or 4: the advice now, and the decision counted as helped."""
    decision = _open(match)
    decision.asked = True
    decision.save(update_fields=["asked"])
    return decision


@transaction.atomic
def act(match, action, amount=None, time_taken=None, reason=None):
    """The player's move. Records it against the playbook, moves their stage, and plays on."""
    decision = _open(match)
    row = decision.hand
    hand = rebuild(row)
    move = as_move(decision, action, amount)
    try:
        hand.act(HERO, action, amount)
    except ValueError as error:
        raise MatchError(str(error)) from None
    decision.move = move
    decision.reason = reason or (decision.intent or {}).get("reason", "")
    decision.time_taken = time_taken
    clear = decision.advice["verdict"] == "clear"
    decision.followed = rules.follows(decision.advice, move) if clear else None
    decision.save()
    if clear and match.coach == "progress":  # a pinned coach plays at its own stage, not the player's
        progress(match, decision)
    if decision.stage >= 3 and time_taken:
        match.time_bank = max(0.0, match.time_bank - max(0.0, time_taken - FREE_SECONDS))
        match.save(update_fields=["time_bank"])
    advance(match, row, hand)
    return decision


def progress(match, decision):
    """Moves the decision's family a stage up or down, by whether the player kept the playbook unhelped.

    At stage 1 the coach names every move, so pressing it is watching: eight of ten move the family on to stage 2.
    From there on only the decisions the player got right on their own count.
    """
    if decision.stage == 2:
        kept = bool(decision.intent and decision.intent["kept"])  # called it right before hearing the advice
    else:
        kept = bool(decision.followed) and not decision.asked
    row, _ = RuleProgress.objects.get_or_create(
        user=match.user, playbook_key=match.playbook.key, family=decision.advice["family"]
    )
    coach.record(row, kept)
    row.save()


@transaction.atomic
def explain_departure(match, hand_number, step, why):
    """Why the player left a rule, asked once: a read, the price, the stack depth, or "felt like it"."""
    decision = MatchDecision.objects.filter(match=match, hand__number=hand_number, step=step).first()
    if decision is None or decision.followed is not False or decision.departure:
        raise MatchError("There's nothing to explain.")
    decision.departure = why
    decision.save(update_fields=["departure"])
    return decision


def finish_hand(match, row, hand):
    """Ends a hand: the stacks carry over, the button moves, and the match ends after its last hand or a bust."""
    row.finished = True
    row.phh = hand.hand_history().dumps()
    row.save()
    table = match.table
    stacks = hand.stacks()
    for seat in table.seats:
        seat["stack"] = stacks[seat["name"]]
    table.hands_played = row.number
    table.button_seat = next(seat["seat"] for seat in table.seats if seat["seat"] != row.button_seat)
    table.save()
    coach_notes(match, row)
    if table.hands_played >= match.hands_planned or any(seat["stack"] == 0 for seat in table.seats):
        end(match)


def end(match):
    """Ends the match: its result in starting big blinds. The debrief works out the rest."""
    hero = next(seat for seat in match.table.seats if seat["name"] == HERO)
    start_stack = match.starting_bb * LEVELS[0][1]
    match.result_bb = round((hero["stack"] - start_stack) / LEVELS[0][1], 2)
    match.finished = timezone.now()
    match.save(update_fields=["result_bb", "finished"])


@transaction.atomic
def next_hand(match):
    """Deals the next hand once the last is over."""
    row = current_hand(match)
    if match.finished or (row and not row.finished):
        raise MatchError("The hand isn't over." if not match.finished else "The match is over.")
    return deal(match)


@transaction.atomic
def resign(match):
    """Ends the match early, as it stands."""
    if not match.finished:
        end(match)


def _open(match):
    if match.finished:
        raise MatchError("The match is over.")
    decision = open_decision_of(match)
    if decision is None:
        raise MatchError("It isn't your turn.")
    return decision


# The read card ----------------------------------------------------------------------------------------------


def finished_hands(match):
    return [(row.number, row.replay) for row in match.table.hands.filter(finished=True).order_by("number")]


def read_card(match):
    """The read card as it stands: counts, showdowns with their notes, reads, a label, and what they unlock."""
    seen = reads.opponent_view(finished_hands(match), HERO, VILLAIN)
    counts = reads.counts(seen, HERO, VILLAIN)
    notes = list(match.read_notes.filter(replaced_by=None, withdrawn=False))
    showdown_notes = {note.hand_number: note for note in notes if note.kind == "showdown"}
    read_notes = [note for note in notes if note.kind == "read"]
    accepted = next((note for note in notes if note.kind == "label"), None)
    showdowns = [{**found, "note": showdown_notes.get(found["number"])} for found in reads.showdowns(seen)]
    return {
        "hands": len(seen),
        "counts": counts,
        "showdowns": showdowns,
        "notes": notes,
        "reads": read_notes,
        "label": reads.label(seen, VILLAIN),
        "accepted": accepted,
        "unlocked": reads.unlocked(read_notes, counts, notes, len(seen), accepted is not None),
    }


def coach_notes(match, row):
    """At stages 1 and 2 the coach fills the read card in aloud: a note on a showdown, and the read it backs."""
    if stage_for(match, "adjustments") > 2:
        return
    card = read_card(match)
    found = next((found for found in card["showdowns"] if found["number"] == row.number), None)
    if found and not found["note"]:
        tag = next((tag for tag in found["offer"] if tag in reads.TAGS), "just_once")
        ReadNote.objects.create(match=match, hand_number=row.number, kind="showdown", tag=tag, by="coach")
        card = read_card(match)
    # The coach holds reads loosely [MIT 8]: it writes one down only once the evidence is strong.
    for tag in reads.TAGS:
        held = any(note.tag == tag for note in card["reads"])
        if not held and reads.evidence(tag, card["counts"], card["notes"]) == "strong":
            ReadNote.objects.create(match=match, hand_number=row.number, kind="read", tag=tag, by="coach")
    if card["label"] and not card["accepted"]:
        ReadNote.objects.create(
            match=match, hand_number=row.number, kind="label", tag=card["label"]["style"], by="coach"
        )


@transaction.atomic
def note(match, kind, tag, hand_number=None):
    """A note on the read card by the player: a showdown's lesson, a read, or a label. It replaces the note it
    revises; the card keeps the history."""
    old = match.read_notes.filter(kind=kind, replaced_by=None, withdrawn=False)
    if kind == "showdown":
        old = old.filter(hand_number=hand_number)
    elif kind == "read":
        old = old.filter(tag=tag)
    new = ReadNote.objects.create(match=match, hand_number=hand_number, kind=kind, tag=tag, by="user")
    old.exclude(pk=new.pk).update(replaced_by=new)
    return new


@transaction.atomic
def withdraw(match, tag):
    """Takes a read off the card; the card keeps it in its history."""
    match.read_notes.filter(kind="read", tag=tag, replaced_by=None).update(withdrawn=True)


# What the client sees -------------------------------------------------------------------------------------------

STAGE_NAMES = {1: "Watch", 2: "Call it", 3: "Play, then hear it", 4: "Solo"}


def state(match):
    """The match as the player sees it: the hand so far, their moves, what the coach may say now, and the card."""
    row = current_hand(match)
    decision = open_decision_of(match)
    cards = {rule["id"]: rule for rule in match.playbook.rules}
    hero = next(seat for seat in match.table.seats if seat["name"] == HERO)
    start_stack = match.starting_bb * LEVELS[0][1]
    hand_over = row.finished
    return {
        "id": match.pk,
        "opponent": match.opponent,
        "coach": match.coach,
        "playbook": match.playbook_id,
        "started": match.started,
        "finished": match.finished,
        "hand_number": row.number,
        "hands_planned": match.hands_planned,
        "small_blind": row.small_blind,
        "big_blind": row.big_blind,
        "next_level_in": HANDS_PER_LEVEL - (row.number - 1) % HANDS_PER_LEVEL,
        "hand": table_hand(row),
        "hand_over": hand_over,
        "hand_net_bb": round(_net(row) / row.big_blind, 2) if hand_over else None,
        "legal": rebuild(row).legal() if decision else None,
        "decision": decision_view(decision, cards) if decision else None,
        "after_hand": after_hand_view(match, row, cards) if hand_over else None,
        "departure": departure_view(match, row),
        "read": card_view(match),
        "time_bank": round(match.time_bank, 1),
        "result_bb": round((hero["stack"] - start_stack) / LEVELS[0][1], 2),  # as of the last hand over
    }


def table_hand(row):
    """A practice hand as the client's replay draws it: the hero's cards, and the bot's once shown."""
    replay = row.replay
    return {
        "game": "Hold'em No Limit",
        "currency": "",
        "small_blind": row.small_blind,
        "big_blind": row.big_blind,
        "ante": 0,
        "tournament_id": "",
        "button_seat": row.button_seat,
        "max_seats": 2,
        "hero": HERO,
        "players": [{**player, "won": player["won"], "net": player["net"]} for player in replay["players"]],
        "events": replay["events"],
    }


def decision_view(decision, cards):
    """The open decision, and as much of the coach's advice as its stage allows yet."""
    stage = decision.stage
    shown = stage == 1 or (stage == 2 and decision.intent) or decision.asked
    advice = decision.advice
    view = {
        "step": decision.step,
        "stage": stage,
        "stage_name": STAGE_NAMES[stage],
        "family": advice["family"],
        "family_label": coach.family_label(advice["family"]),
        "situation": coach.situation(decision.context),
        "prompt": None,
        "advice": advice if shown else None,
        "rule": cards.get(advice["rule"]) if shown else None,
        "intent": decision.intent,
        "asked": decision.asked,
    }
    if stage == 1 or decision.asked:
        view["prompt"] = coach.advice_line(advice, cards, decision.context)
    elif stage == 2:
        view["prompt"] = (
            coach.advice_line(advice, cards, decision.context) if decision.intent else "What are you thinking here?"
        )
    return view


def after_hand_view(match, row, cards):
    """At stage 3, once the hand is over, the coach's one comment on it."""
    return coach.after_hand(list(row.decisions.order_by("step")), cards)


def departure_view(match, row):
    """The last decision that left a clear rule at stage 2 or above, if the coach hasn't yet asked why."""
    decision = (
        MatchDecision.objects.filter(match=match, hand=row, followed=False, departure="", stage__gte=2)
        .order_by("-step")
        .first()
    )
    if decision is None:
        return None
    return {
        "hand": row.number,
        "step": decision.step,
        "rule": decision.advice["rule"],
        "street": decision.context["street"],
    }


def card_view(match):
    """The read card as the client shows it: counts, showdowns with notes, reads with evidence, the label."""
    card = read_card(match)
    return {
        "hands": card["hands"],
        "counts": card["counts"],
        "showdowns": [
            {
                **{key: found[key] for key in ("number", "cards", "line", "offer")},
                "note": {"tag": found["note"].tag, "by": found["note"].by} if found["note"] else None,
            }
            for found in card["showdowns"]
        ],
        "reads": [
            {
                "tag": note.tag,
                "label": reads.TAGS[note.tag][0],
                "by": note.by,
                "hand": note.hand_number,
                "evidence": reads.evidence(note.tag, card["counts"], card["notes"]),
            }
            for note in card["reads"]
        ],
        "label": card["label"],
        "accepted": {"style": card["accepted"].tag, "by": card["accepted"].by} if card["accepted"] else None,
        "tags": [{"tag": tag, "label": label} for tag, (label, _) in reads.TAGS.items()],
    }


def _net(row):
    return next(player["net"] for player in row.replay["players"] if player["name"] == HERO)

"""Tournaments (FND-8, D1 and D2 of the feature ideas): each tournament the user played, read from its hands; what
it returned; and the hero's stack through it.

`refresh` rebuilds the tournaments a batch of stored hands was played in, from all of their hands, so a reparse
leaves them right: the buy-in from the hands' first lines, the hands, levels and times, and the hero's finish, prize,
re-entries and bounties from the lines PokerStars writes when a player busts or wins (tracker.parsing.tournaments).
What the user entered (the field size, the payouts, or a finish, prize or entries of their own) is left alone, and
counts over what was read (`result`).

A tournament's net is its prize and bounties less what its entries cost, and its ROI that net over the cost
[MIT 1; MIT 2]: (prizes + bounties − buy-ins − fees) ÷ (buy-ins + fees).
"""

from collections import Counter, defaultdict

from django.db.models import F, OuterRef, Subquery

from hands.models import Hand, HandPlayer, Tournament
from hands.stats import M_ZONES, proportion


def refresh(user_id, keys):
    """Rebuilds `user_id`'s tournaments `keys`, (site, tournament id) pairs, from their hands."""
    for site, tournament_id in keys:
        hands = list(
            Hand.objects.filter(user_id=user_id, site=site, tournament_id=tournament_id)
            .order_by("played_at", "id")
            .values("played_at", "hero", "game", "level", "replay__max_seats", "facts__tournament")
        )
        if not hands:
            Tournament.objects.filter(user_id=user_id, site=site, tournament_id=tournament_id).delete()
            continue
        Tournament.objects.update_or_create(
            user_id=user_id, site=site, tournament_id=tournament_id, defaults=_read(hands)
        )


def _read(hands):
    """A tournament's fields from its hands, oldest first."""
    info = next((hand["facts__tournament"] for hand in reversed(hands) if hand["facts__tournament"]), None) or {}
    names = Counter(hand["hero"] for hand in hands if hand["hero"])
    hero = names.most_common(1)[0][0] if names else ""
    finishes = []
    bounties = knockouts = 0
    for i, hand in enumerate(hands):
        lines = hand["facts__tournament"] or {}
        finishes += [(i, line) for line in lines.get("finishes", []) if line["player"] == hero]
        for knockout in lines.get("knockouts", []):
            if knockout["player"] == hero:
                bounties += knockout["amount"]
                knockouts += 1

    def played_on(i):
        return any(hand["hero"] == hero for hand in hands[i + 1 :])

    # A bust the hero played on from was followed by a re-entry; the last one, if they never played on, is their finish.
    entries = 1 + sum(1 for i, _ in finishes if played_on(i))
    final = finishes[-1][1] if finishes and not played_on(finishes[-1][0]) else None
    seats = [hand["replay__max_seats"] for hand in hands if hand["replay__max_seats"]]
    levels = [hand["level"] for hand in hands if hand["level"]]
    return {
        "game": hands[0]["game"],
        "hero": hero,
        "currency": info.get("currency", ""),
        "play_money": info.get("play_money", False),
        "freeroll": info.get("freeroll", False),
        "buy_in": info.get("buy_in", 0),
        "fee": info.get("fee", 0),
        "bounty": info.get("bounty", 0),
        "first_hand": hands[0]["played_at"],
        "last_hand": hands[-1]["played_at"],
        "hands": len(hands),
        "max_seats": max(seats) if seats else None,
        "top_level": max(levels) if levels else None,
        "entries": entries,
        "finish": final["place"] if final else None,
        "prize": final["prize"] if final else None,
        "bounties_won": bounties,
        "knockouts": knockouts,
    }


def result(tournament):
    """What a tournament returned, with the user's entries counting over what was read: {entries, finish, prize,
    cost, net, roi, in_the_money, percentile}.

    The prize is the one entered, else the one read, else the payout for the finish when the user entered payouts.
    It is in the money with a prize, or a finish among the payouts. `percentile` is the finish as a share of the
    field (0 the winner, 1 the first out), once the field size is known.
    """
    t = tournament
    entries = t.entered_entries or t.entries
    finish = t.entered_finish or t.finish
    paid = [payout for payout in t.payouts if payout]
    prize = t.entered_prize if t.entered_prize is not None else t.prize
    if prize is None and finish and finish <= len(paid):
        prize = paid[finish - 1]
    prize = prize or 0
    cost = entries * (t.buy_in + t.fee + t.bounty)
    net = prize + t.bounties_won - cost
    field = t.field_size
    placed = finish and field and field > 1 and finish <= field
    return {
        "entries": entries,
        "finish": finish,
        "prize": prize,
        "cost": cost,
        "net": net,
        "roi": round(net / cost, 4) if cost else None,
        "in_the_money": prize > 0 or bool(finish and finish <= len(paid)),
        "percentile": round((finish - 1) / (field - 1), 3) if placed else None,
    }


def kind_of(tournament):
    """A tournament's format, as the summary groups them: its table size, and whether it has bounties."""
    seats = tournament.max_seats
    size = "heads-up" if seats == 2 else f"{seats}-max" if seats else "table"
    return f"{size} knockout" if tournament.bounty else size


def summary(tournaments):
    """Totals over `tournaments`, apart by money (play money and each currency never mix), then by buy-in and
    format: each group's tournaments, entries, cost, prizes, bounties and net, its ROI, its in-the-money share
    with a 95% range, its average finish percentile where fields are known, and the fees paid."""
    groups = defaultdict(lambda: defaultdict(list))
    for tournament in tournaments:
        money = "play_money" if tournament.play_money else tournament.currency or "chips"
        buy_in = tournament.buy_in + tournament.fee + tournament.bounty
        groups[money][(buy_in, kind_of(tournament))].append(tournament)
        groups[money]["all"].append(tournament)
    rows = []
    for money, by_kind in groups.items():
        for key, members in by_kind.items():
            buy_in, kind = (None, "all") if key == "all" else key
            rows.append({"money": money, "buy_in": buy_in, "kind": kind, **_totals(members)})
    rows.sort(key=lambda row: (row["money"], row["kind"] != "all", row["buy_in"] or 0, row["kind"]))
    return rows


def _totals(tournaments):
    results = [(tournament, result(tournament)) for tournament in tournaments]
    cost = sum(outcome["cost"] for _, outcome in results)
    prizes = sum(outcome["prize"] for _, outcome in results)
    bounties = sum(tournament.bounties_won for tournament in tournaments)
    net = prizes + bounties - cost
    finished = [outcome for _, outcome in results if outcome["finish"]]
    places = [outcome["percentile"] for _, outcome in results if outcome["percentile"] is not None]
    return {
        "tournaments": len(tournaments),
        "entries": sum(outcome["entries"] for _, outcome in results),
        "cost": cost,
        "fees": sum(outcome["entries"] * tournament.fee for tournament, outcome in results),
        "prizes": prizes,
        "bounties": bounties,
        "net": net,
        "roi": round(net / cost, 4) if cost else None,
        "in_the_money": proportion(sum(outcome["in_the_money"] for outcome in finished), len(finished)),
        "average_percentile": round(sum(places) / len(places), 3) if places else None,
    }


def zone(m):
    """The MIT course's zone for an M [MIT 5] (hands.stats.M_ZONES)."""
    return next(name for name, low, high in M_ZONES if (low is None or m >= low) and (high is None or m < high))


def timeline(tournament):
    """The hero's hands in a tournament, oldest first, for the stack chart (D2): each hand's level, blinds and
    ante, the hero's stack in chips and big blinds and their M at its start, the players dealt and the table's
    average stack, and what happened: the net, the pot, an all-in, a steal."""
    hero = HandPlayer.objects.filter(hand=OuterRef("pk"), is_hero=True)
    hands = (
        Hand.objects.filter(user=tournament.user, site=tournament.site, tournament_id=tournament.tournament_id)
        .exclude(hero="")
        .annotate(
            stack_bb=Subquery(hero.values("stack_bb")[:1]),
            allin_street=Subquery(hero.values("allin_street")[:1]),
            steal=Subquery(hero.values("steal_did")[:1]),
            ev_net_bb=Subquery(hero.values("ev_net_bb")[:1]),
        )
        .order_by("played_at", "id")
        .values(
            "id",
            "hand_id",
            "played_at",
            "level",
            "small_blind",
            "big_blind",
            "players_dealt",
            "hero_m",
            "hero_net",
            "total_pot",
            "stack_bb",
            "allin_street",
            "steal",
            "ev_net_bb",
            "hero",
            ante=F("replay__ante"),
            players=F("replay__players"),
        )
    )
    points = []
    for hand in hands:
        seats = hand.pop("players") or []
        name = hand.pop("hero")
        stacks = [player["stack"] for player in seats]
        points.append(
            {
                **hand,
                "stack": next((player["stack"] for player in seats if player["name"] == name), None),
                "table_average": round(sum(stacks) / len(stacks)) if stacks else None,
                "zone": zone(hand["hero_m"]) if hand["hero_m"] is not None else None,
                "all_in": bool(hand.pop("allin_street")),
                "steal": bool(hand["steal"]),
            }
        )
    return points

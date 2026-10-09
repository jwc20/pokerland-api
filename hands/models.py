from django.conf import settings
from django.db import models


class Hand(models.Model):
    """One hand from a user's hand histories, parsed from a stream their tracker uploaded.

    Amounts are integers: chips, or cents when `currency` is set. The columns
    are what the game history lists; `replay` holds the seats, events and
    boards the replay steps through, and `phh` the hand in the PHH notation, as
    PokerKit read it (see tracker.parsing.pokerstars).
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hands")
    stream = models.ForeignKey("tracker.LogStream", on_delete=models.CASCADE, related_name="hands")
    site = models.CharField(max_length=32)  # e.g. "pokerstars"
    hand_id = models.CharField(max_length=32)  # the site's hand number
    played_at = models.DateTimeField()
    game = models.CharField(max_length=64)  # e.g. "Hold'em No Limit"
    currency = models.CharField(max_length=3, blank=True)  # empty for chips
    play_money = models.BooleanField(default=False)
    small_blind = models.BigIntegerField()
    big_blind = models.BigIntegerField()
    tournament_id = models.CharField(max_length=32, blank=True)
    table = models.CharField(max_length=64)
    # The player the history deals cards to: the user, under their screen name on the site.
    hero = models.CharField(max_length=64, blank=True)
    hero_position = models.CharField(max_length=8, blank=True)
    hero_cards = models.JSONField(default=list, blank=True)
    hero_net = models.BigIntegerField(default=0)
    final_street = models.CharField(max_length=32)
    # Also in `replay`; columns so the rake can be summed without reading every replay.
    total_pot = models.BigIntegerField(default=0)  # every chip put in, the rake included
    rake = models.BigIntegerField(default=0)  # what the house took from the pot
    replay = models.JSONField(default=dict)
    phh = models.TextField(blank=True)
    # What the hero's decisions faced (tracker.parsing.facts). `facts` holds the pot, the stacks and the
    # board's texture on each street, and what the hero held on each.
    hero_combo = models.CharField(max_length=4, blank=True)  # "AKs", "T9o", "88"; empty in Omaha
    players_dealt = models.PositiveSmallIntegerField(default=0)
    pot_type = models.CharField(max_length=16, blank=True)  # walk, limped, single_raised, 3bet, 4bet+
    hero_situation = models.CharField(max_length=16, blank=True)  # unopened, limped, raised, 3bet, 4bet+
    hero_first_action = models.CharField(max_length=8, blank=True)  # fold, check, call or raise
    effective_bb = models.FloatField(null=True, blank=True)  # the most the hero could lose, in big blinds
    hero_m = models.FloatField(null=True, blank=True)  # Harrington's M, in tournaments
    level = models.PositiveSmallIntegerField(null=True, blank=True)  # a tournament's blind level
    facts = models.JSONField(default=dict, blank=True)
    # The session it belongs to (hands.sessions), whole hours since that began, and how many tables the user was
    # playing at once then. Null for a hand the user sat out.
    session = models.ForeignKey("Session", null=True, blank=True, on_delete=models.SET_NULL, related_name="hand_set")
    session_hour = models.PositiveSmallIntegerField(null=True, blank=True)
    tables_open = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            # A reparse updates its hands in place, so their ids (and replay links) survive it.
            models.UniqueConstraint(fields=("user", "site", "hand_id"), name="unique_hand_per_user"),
        ]
        indexes = [
            models.Index(fields=("user", "-played_at", "-id"), name="hand_history"),
            models.Index(fields=("user", "hero_combo"), name="hand_combo"),
            models.Index(fields=("user", "hero_situation"), name="hand_situation"),
        ]
        ordering = ("-played_at", "-id")

    def __str__(self):
        return f"{self.site} #{self.hand_id}"


def counter():
    """A count in one hand: a statistic's chances, the chances the player took, or their moves of a kind."""
    return models.PositiveSmallIntegerField(default=0)


class HandPlayer(models.Model):
    """One player's part in a hand: the facts behind their statistics, from tracker.parsing.facts.

    Each statistic is a pair of columns, <stat>_could and <stat>_did, summed over
    hands into PokerTracker's "how often they did it ÷ how often they could
    have" [MIT 2]. tracker.parsing.facts.STATS defines them. A reparse replaces a
    hand's rows.
    """

    hand = models.ForeignKey(Hand, on_delete=models.CASCADE, related_name="seats")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hand_players")
    seat = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=64)
    is_hero = models.BooleanField(default=False)
    position = models.CharField(max_length=8)  # BTN, SB, BB, UTG, ...
    stack_bb = models.FloatField()  # at the start of the hand
    cards = models.JSONField(default=list, blank=True)  # when the history shows them
    situation = models.CharField(max_length=16, blank=True)  # what their first decision faced: unopened, limped, ...
    first_action = models.CharField(max_length=8, blank=True)

    # Before the flop
    vpip_could = counter()
    vpip_did = counter()
    pfr_could = counter()
    pfr_did = counter()
    rfi_could = counter()
    rfi_did = counter()
    limp_could = counter()
    limp_did = counter()
    cold_call_could = counter()
    cold_call_did = counter()
    three_bet_could = counter()
    three_bet_did = counter()
    fold_to_three_bet_could = counter()
    fold_to_three_bet_did = counter()
    four_bet_could = counter()
    four_bet_did = counter()
    squeeze_could = counter()
    squeeze_did = counter()
    # Steals and the blinds
    steal_could = counter()
    steal_did = counter()
    fold_to_steal_could = counter()
    fold_to_steal_did = counter()
    call_vs_steal_could = counter()
    call_vs_steal_did = counter()
    three_bet_vs_steal_could = counter()
    three_bet_vs_steal_did = counter()
    bb_defend_could = counter()
    bb_defend_did = counter()
    # After the flop
    cbet_flop_could = counter()
    cbet_flop_did = counter()
    cbet_turn_could = counter()
    cbet_turn_did = counter()
    cbet_river_could = counter()
    cbet_river_did = counter()
    fold_to_cbet_flop_could = counter()
    fold_to_cbet_flop_did = counter()
    fold_to_cbet_turn_could = counter()
    fold_to_cbet_turn_did = counter()
    fold_to_cbet_river_could = counter()
    fold_to_cbet_river_did = counter()
    donk_flop_could = counter()
    donk_flop_did = counter()
    check_raise_could = counter()
    check_raise_did = counter()
    # Showdowns
    saw_flop_could = counter()
    saw_flop_did = counter()
    went_to_showdown_could = counter()
    went_to_showdown_did = counter()
    won_at_showdown_could = counter()
    won_at_showdown_did = counter()

    # Moves after the flop, for the aggression frequency
    postflop_bets = counter()
    postflop_raises = counter()
    postflop_calls = counter()
    postflop_checks = counter()
    postflop_folds = counter()

    invested_bb = models.FloatField(default=0)
    net_bb = models.FloatField(default=0)
    allin_street = models.CharField(max_length=16, blank=True)
    # Raises before the flop, for the discipline checks (hands.leaks): the open (the first raise, over any
    # limpers) in big blinds and its limpers; a 3-bet as a multiple of the raise it re-raised, and that raise's
    # callers; whether the first raise was all-in. Null without such a raise.
    open_bb = models.FloatField(null=True, blank=True)
    open_limpers = models.PositiveSmallIntegerField(null=True, blank=True)
    three_bet_x = models.FloatField(null=True, blank=True)
    three_bet_callers = models.PositiveSmallIntegerField(null=True, blank=True)
    first_raise_all_in = models.BooleanField(null=True, blank=True)
    # After the flop, for the leak alerts (hands.leaks, B5): facing a bet with a set or two pair (both hole cards) on
    # a dry, unpaired board, and folding [JHU 8]; checked to in position on the river, and checking back to win the
    # showdown, value missed [JHU 9]. Known for the hero, and for others only when their cards were shown.
    strong_fold_could = counter()
    strong_fold_did = counter()
    thin_value_could = counter()
    thin_value_did = counter()
    # When the money went in before the river with every live hand shown (tracker.parsing.equity.all_in): the
    # player's share of the pots they could win, and the net they could expect then, rake taken, in big blinds.
    # Null in every other hand, whose expected net is the net.
    allin_equity = models.FloatField(null=True, blank=True)
    ev_net_bb = models.FloatField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)  # action counts by street, bet sizes, M

    class Meta:
        constraints = [models.UniqueConstraint(fields=("hand", "seat"), name="unique_seat_per_hand")]
        indexes = [
            models.Index(fields=("user", "is_hero", "position"), name="hand_player_hero"),
            models.Index(fields=("user", "name"), name="hand_player_name"),
        ]

    def __str__(self):
        return f"{self.name} in {self.hand}"


class HandBet(models.Model):
    """A bet or raise in a hand, by anyone (tracker.parsing.facts): its size, what its maker held when their cards
    are known, and how it was answered. Sizing tells (B4), the spots' bet sizes (FND-3) and the multiway-bluff leak
    (B5) read these. A reparse replaces a hand's rows."""

    class Strength(models.TextChoices):
        NOTHING = "nothing"
        DRAW = "draw"  # eight outs or more: a flush draw, an open-ended or double gutshot
        WEAK = "weak"  # a pair below top pair: it beats bluffs and little else
        STRONG = "strong"  # top pair or better
        NUTS = "nuts"  # nothing beat it then

    hand = models.ForeignKey(Hand, on_delete=models.CASCADE, related_name="bets")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hand_bets")
    seat = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=64)
    is_hero = models.BooleanField(default=False)
    street = models.CharField(max_length=16)
    order = models.PositiveSmallIntegerField()  # in the hand, from 0
    kind = models.CharField(max_length=8)  # bet or raise
    amount_bb = models.FloatField()  # chips put in with it, in big blinds
    pot_bb = models.FloatField()  # everything in the middle before it: the pot and the bets in front of the players
    size = models.FloatField(null=True, blank=True)  # amount ÷ what was in the middle; null without anything there
    to_bb = models.FloatField()  # the player's bet on the street after it
    opponents = models.PositiveSmallIntegerField()  # the others still in the hand
    all_in = models.BooleanField(default=False)
    cbet = models.BooleanField(default=False)
    made = models.CharField(max_length=24, blank=True)  # the made hand (tracker.parsing.facts.made_hand), if known
    strength = models.CharField(max_length=8, choices=Strength, blank=True)  # empty before the flop, or if unknown
    wetness = models.PositiveSmallIntegerField(null=True, blank=True)  # the board's, 0 (dry) to 3; null before the flop
    outcome = models.CharField(max_length=8)  # folded (nobody called or raised it), called or raised
    hero_response = models.CharField(max_length=8, blank=True)  # the hero's answer: fold, call or raise

    class Meta:
        constraints = [models.UniqueConstraint(fields=("hand", "order"), name="unique_bet_order")]
        indexes = [models.Index(fields=("user", "is_hero", "street"), name="hand_bet_street")]

    def __str__(self):
        return f"{self.name} {self.kind}s {self.size} on the {self.street} in {self.hand}"


class Session(models.Model):
    """A stretch of play (F1): a user's hands with no gap longer than hands.sessions.GAP between one and the next,
    at any table. hands.sessions builds it as hands are stored, and keeps its counts."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions")
    start = models.DateTimeField()  # the first hand's start
    end = models.DateTimeField()  # the last hand's start
    hands = models.PositiveIntegerField(default=0)
    tables = models.PositiveSmallIntegerField(default=0)  # tables played at
    most_tables = models.PositiveSmallIntegerField(default=0)  # the most at once
    net_bb = models.FloatField(default=0)
    net_bb_squares = models.FloatField(default=0)  # for the spread of the results
    ev_net_bb = models.FloatField(default=0)  # adjusted for all-in equity, as hands.stats counts it
    biggest_pot_bb = models.FloatField(default=0)

    class Meta:
        indexes = [models.Index(fields=("user", "-start"), name="session_start")]
        ordering = ("-start", "-id")

    def __str__(self):
        return f"Session of {self.user} at {self.start:%Y-%m-%d %H:%M}"


class Tournament(models.Model):
    """A tournament the user played (FND-8), read from its hands alone: the buy-in from their first lines, and the
    finish, prize and bounties from the lines PokerStars writes when a player busts or wins. hands.tournaments keeps
    it as hands are stored. Amounts are cents for a buy-in with a currency, chips for play money.

    What the hands can't tell, the field size and the payouts, the user can enter, along with a finish, a prize or
    a number of entries of their own, which then count instead of what was read.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tournaments")
    site = models.CharField(max_length=32)
    tournament_id = models.CharField(max_length=32)
    game = models.CharField(max_length=64)
    hero = models.CharField(max_length=64, blank=True)  # the screen name the user played under
    currency = models.CharField(max_length=3, blank=True)  # the buy-in's; empty for play money and freerolls
    play_money = models.BooleanField(default=False)
    freeroll = models.BooleanField(default=False)
    buy_in = models.BigIntegerField(default=0)  # each entry's part of the prize pool
    fee = models.BigIntegerField(default=0)
    bounty = models.BigIntegerField(default=0)  # each entry's bounty, in a knockout tournament
    first_hand = models.DateTimeField()
    last_hand = models.DateTimeField()
    hands = models.PositiveIntegerField(default=0)
    max_seats = models.PositiveSmallIntegerField(null=True, blank=True)
    top_level = models.PositiveSmallIntegerField(null=True, blank=True)  # the highest blind level played
    entries = models.PositiveSmallIntegerField(default=1)  # one, plus a re-entry for each bust played on from
    finish = models.PositiveIntegerField(null=True, blank=True)  # the hero's place, once they busted or won
    prize = models.BigIntegerField(null=True, blank=True)  # what they received for it; null when no prize was read
    bounties_won = models.BigIntegerField(default=0)
    knockouts = models.PositiveIntegerField(default=0)
    # Entered by the user.
    field_size = models.PositiveIntegerField(null=True, blank=True)
    payouts = models.JSONField(default=list, blank=True)  # the prize for each place, first place first
    entered_finish = models.PositiveIntegerField(null=True, blank=True)
    entered_prize = models.BigIntegerField(null=True, blank=True)
    entered_entries = models.PositiveSmallIntegerField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "site", "tournament_id"), name="unique_tournament_per_user")
        ]
        indexes = [models.Index(fields=("user", "-first_hand"), name="tournament_start")]
        ordering = ("-first_hand", "-id")

    def __str__(self):
        return f"{self.site} tournament #{self.tournament_id}"


class Opponent(models.Model):
    """A player the user has played with on a site (FND-6): their statistics from every hand they were dealt into
    with the user, summed from their HandPlayer rows, and a label for their style.

    hands.opponents recomputes the counts of the players a batch of stored hands touched, so a reparse leaves them
    right. The label is automatic, from the statistics and how sure they are, unless the user set one. Only the user
    who played the hands sees any of it.
    """

    class Label(models.TextChoices):
        TAG = "tag"  # tight-aggressive
        LAG = "lag"  # loose-aggressive
        ROCK = "rock"  # tight-passive
        STATION = "station"  # loose-passive: a calling station

    class Confidence(models.TextChoices):
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opponents")
    site = models.CharField(max_length=32)
    name = models.CharField(max_length=64)
    hands = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    # Every statistic's _could and _did summed (tracker.parsing.facts.STATS), their moves after the flop, their net
    # and what they put in, in big blinds, and their showdowns.
    counters = models.JSONField(default=dict, blank=True)
    vpip = models.FloatField(null=True, blank=True)  # in percent, for sorting; null without a chance
    pfr = models.FloatField(null=True, blank=True)
    aggression = models.FloatField(null=True, blank=True)
    label = models.CharField(max_length=8, choices=Label, blank=True)  # empty: too few hands to say
    confidence = models.CharField(max_length=8, choices=Confidence, blank=True)
    manual_label = models.CharField(max_length=8, choices=Label, blank=True)  # the user's, over the automatic one
    note = models.TextField(blank=True)
    # The hero-versus-villain ledger (C2): the hands where both put money in by choice, or both saw the flop, and
    # the hero's net in them.
    shared_hands = models.PositiveIntegerField(default=0)
    hero_net_bb = models.FloatField(default=0)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "site", "name"), name="unique_opponent_per_user")]
        indexes = [
            models.Index(fields=("user", "-hands"), name="opponent_hands"),
            models.Index(fields=("user", "-last_seen"), name="opponent_last_seen"),
        ]

    def __str__(self):
        return f"{self.name} ({self.site}) for {self.user}"


class Spot(models.Model):
    """A filter the user saved under a name (FND-3, B7): a spec of conditions grouped with all, any and not, which
    hands.spots turns into the hands it matches. A share code lets others import a copy, without its opponents."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="spots")
    name = models.CharField(max_length=80)
    spec = models.JSONField(default=dict)
    share_code = models.CharField(max_length=16, null=True, blank=True, unique=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")

    def __str__(self):
        return self.name


class SavedRange(models.Model):
    """A starting-hand range the user built on the range grid and named (FND-5): "TT+, AQs+, AKo", say, for the
    preflop grids' overlay or a spot's hole cards."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ranges")
    name = models.CharField(max_length=80)
    hands = models.TextField()  # in range notation, as hands.ranges reads it
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name", "id")

    def __str__(self):
        return self.name


class LeakReview(models.Model):
    """When the user last marked a leak check reviewed (B5): its hands from before then count as seen."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leak_reviews")
    key = models.CharField(max_length=32)  # a check in hands.leaks.CHECKS
    reviewed = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "key"), name="one_review_per_leak")]

    def __str__(self):
        return f"{self.key} reviewed by {self.user}"


class CoachPresets(models.Model):
    """A user's thresholds for the leak checks, where they differ from the course values in hands.leaks.PRESETS."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coach_presets")
    values = models.JSONField(default=dict, blank=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Coach presets of {self.user}"


class HandNote(models.Model):
    """What a user wrote on one of their hands (FND-7 of the feature ideas): a note, a tag, the hand's review
    state, or why they made one of their bets or raises (E1).

    Notes hang on the hand's row, which a reparse updates in place, so they outlast it; deleting the hand deletes
    them. A hand has one note per street (and one on the whole hand), each tag once, one review state, and one
    purpose per bet.
    """

    class Kind(models.TextChoices):
        NOTE = "note"  # `text`, on one `street`, or on the whole hand when it is empty
        TAG = "tag"  # `value`: "cooler", "misclick", or a tag of the user's own
        REVIEW = "review"  # `value`: to_review, then reviewed
        PURPOSE = "purpose"  # `value`: why the hero made their bet or raise number `bet`; `street` is its street
        WRITEUP = "writeup"  # `text`: the hand written up to show others (E2), one a hand

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hand_notes")
    hand = models.ForeignKey(Hand, on_delete=models.CASCADE, related_name="notes")
    kind = models.CharField(max_length=16, choices=Kind)
    street = models.CharField(max_length=16, blank=True)
    # Which of the hero's bets and raises a purpose is for, counted from 0 in the order they made them: unlike a
    # replay step, it stays put if a new parser adds events.
    bet = models.PositiveSmallIntegerField(null=True, blank=True)
    value = models.CharField(max_length=32, blank=True)
    text = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("hand", "street"), condition=models.Q(kind="note"), name="one_note_per_street"
            ),
            models.UniqueConstraint(fields=("hand", "value"), condition=models.Q(kind="tag"), name="each_tag_once"),
            models.UniqueConstraint(fields=("hand",), condition=models.Q(kind="review"), name="one_review_state"),
            models.UniqueConstraint(
                fields=("hand", "bet"), condition=models.Q(kind="purpose"), name="one_purpose_per_bet"
            ),
            models.UniqueConstraint(fields=("hand",), condition=models.Q(kind="writeup"), name="one_writeup_per_hand"),
        ]
        indexes = [models.Index(fields=("user", "kind", "value"), name="hand_note_value")]

    def __str__(self):
        return f"{self.kind} on {self.hand}"


class HandShare(models.Model):
    """A hand shared by a read-only public link (E2): the replay and the write-up the user published with it.

    With `anonymize`, the public page names every player by their position, the hero as "Hero", and leaves out the
    table and the hand's number. A revoked share's link stops working.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shares")
    hand = models.ForeignKey(Hand, on_delete=models.CASCADE, related_name="shares")
    slug = models.CharField(max_length=24, unique=True)
    write_up = models.TextField(blank=True)
    anonymize = models.BooleanField(default=True)
    revoked = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created", "-id")

    def __str__(self):
        return f"{self.hand} shared as {self.slug}"

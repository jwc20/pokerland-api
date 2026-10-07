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
    facts = models.JSONField(default=dict, blank=True)

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
    extra = models.JSONField(default=dict, blank=True)  # action counts by street, bet sizes, M

    class Meta:
        constraints = [models.UniqueConstraint(fields=("hand", "seat"), name="unique_seat_per_hand")]
        indexes = [
            models.Index(fields=("user", "is_hero", "position"), name="hand_player_hero"),
            models.Index(fields=("user", "name"), name="hand_player_name"),
        ]

    def __str__(self):
        return f"{self.name} in {self.hand}"

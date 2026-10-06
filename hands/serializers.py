from rest_framework import serializers

from hands.models import Hand

EVENT_TYPES = [
    "post",
    "deal",
    "fold",
    "check",
    "call",
    "bet",
    "raise",
    "street",
    "return",
    "collect",
    "show",
    "muck",
]


class HandSummarySerializer(serializers.ModelSerializer):
    """A row of the game history. Amounts are chips, or cents when `currency` is set."""

    hero_cards = serializers.ListField(child=serializers.CharField())

    class Meta:
        model = Hand
        fields = (
            "id",
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
        )
        read_only_fields = fields  # so the schema marks them all as present


class HandPlayerSerializer(serializers.Serializer):
    seat = serializers.IntegerField()
    name = serializers.CharField()
    stack = serializers.IntegerField(help_text="Chips at the start of the hand.")
    position = serializers.CharField(help_text="BTN, SB, BB, UTG, ...")
    cards = serializers.ListField(child=serializers.CharField(), help_text="Hole cards, when the history shows them.")
    won = serializers.IntegerField(help_text="Chips collected from the pot.")
    net = serializers.IntegerField(help_text="Chips won minus chips put in.")


class HandEventSerializer(serializers.Serializer):
    """One line of the hand. Fields other than `type` and `street` appear only where they apply."""

    type = serializers.ChoiceField(choices=EVENT_TYPES)
    street = serializers.CharField(help_text="The betting round: preflop, flop, turn, river, showdown, ...")
    player = serializers.CharField(required=False)
    amount = serializers.IntegerField(
        required=False,
        help_text="Chips the player puts in (post, call, bet, raise) or gets back (return, collect).",
    )
    dead = serializers.IntegerField(required=False, help_text="post: the part that is not a bet, e.g. an ante.")
    to = serializers.IntegerField(required=False, help_text="raise: the player's bet on this street afterwards.")
    by = serializers.IntegerField(required=False, help_text="raise: how much higher than the bet before.")
    all_in = serializers.BooleanField(required=False)
    blind = serializers.CharField(required=False, help_text="post: small blind, big blind, ante, dead small blind, ...")
    cards = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="deal, show, muck: the player's cards. street: the new board cards.",
    )
    board = serializers.ListField(child=serializers.CharField(), required=False, help_text="street: the whole board.")
    pot = serializers.CharField(
        required=False, help_text="collect: pot, or main pot, side pot-1, ... when there are several."
    )
    description = serializers.CharField(
        required=False, help_text="show: the hand as PokerKit ranks it, e.g. Three of a kind."
    )


class HandDetailSerializer(HandSummarySerializer):
    """A hand with everything its replay needs."""

    max_seats = serializers.IntegerField(source="replay.max_seats", allow_null=True)
    button_seat = serializers.IntegerField(source="replay.button_seat")
    ante = serializers.IntegerField(source="replay.ante")
    total_pot = serializers.IntegerField(source="replay.total_pot")
    rake = serializers.IntegerField(source="replay.rake")
    board = serializers.ListField(child=serializers.CharField(), source="replay.board")
    players = HandPlayerSerializer(many=True, source="replay.players", help_text="The players dealt in, in seat order.")
    events = HandEventSerializer(many=True, source="replay.events")
    phh = serializers.CharField(
        help_text="The hand in the PHH notation (https://phh.readthedocs.io), as PokerKit read it."
    )

    class Meta(HandSummarySerializer.Meta):
        fields = (
            *HandSummarySerializer.Meta.fields,
            "max_seats",
            "button_seat",
            "ante",
            "total_pot",
            "rake",
            "board",
            "players",
            "events",
            "phh",
        )
        read_only_fields = fields

from rest_framework import serializers

from hands.filters import HAND_RESULTS, HAND_SORTS, TAG_GROUPS, tag_filter, zone
from hands.models import Hand
from hands.stats import STAT_GROUPINGS
from tracker.parsing.facts import STATS

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


class TimeZoneField(serializers.CharField):
    """An IANA time zone name, e.g. "Europe/London", read as a ZoneInfo."""

    def to_internal_value(self, data):
        try:
            return zone(super().to_internal_value(data))
        except ValueError:
            raise serializers.ValidationError("Not a time zone.") from None


class TagField(serializers.CharField):
    """A tag's `key` in /api/hands/tags/, e.g. "position:BTN"."""

    def to_internal_value(self, data):
        key = super().to_internal_value(data)
        try:
            tag_filter(key)
        except ValueError:
            raise serializers.ValidationError("Not a tag.") from None
        return key


class HandFilterSerializer(serializers.Serializer):
    """Which of the user's hands to count. Any filter leaves out the hands they sat out."""

    tag = serializers.ListField(
        child=TagField(),
        required=False,
        help_text="Only the hands every one of these tags counts: their `key`s in /api/hands/tags/. Repeatable.",
    )
    since = serializers.DateField(required=False, help_text="Only the hands played from this day on, in `tz`.")
    until = serializers.DateField(
        required=False, help_text="Only the hands played up to the end of this day, in `tz`."
    )
    tz = TimeZoneField(
        required=False,
        help_text='The IANA time zone days and months are counted in, e.g. "Europe/London"; UTC if left out.',
    )

    def validate(self, attrs):
        if "since" in attrs and "until" in attrs and attrs["since"] > attrs["until"]:
            raise serializers.ValidationError({"since": "After `until`."})
        return attrs


class HandListQuerySerializer(HandFilterSerializer):
    """What the game history can be narrowed down to, and sorted by."""

    date = serializers.DateField(required=False, help_text="Only the hands played on this day in `tz`.")
    stat = serializers.ChoiceField(
        choices=[*STATS, "aggression"],
        required=False,
        help_text="Only the hands that gave the hero a chance at this statistic, as /api/stats/ counts them.",
    )
    did = serializers.BooleanField(
        required=False,
        allow_null=True,  # else DRF reads a missing query parameter as false
        help_text="With `stat`: only the hands where the hero took the chance (true) or let it go (false).",
    )
    result = serializers.ChoiceField(
        choices=HAND_RESULTS, required=False, help_text="Only the hands the hero won, lost or broke even in."
    )
    sort = serializers.ChoiceField(
        choices=HAND_SORTS,
        default="newest",
        help_text="Newest or oldest first, or by the hero's result in big blinds: the biggest wins or losses first.",
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("did") is not None and "stat" not in attrs:
            raise serializers.ValidationError({"did": "Only with `stat`."})
        return attrs


class HandDaysQuerySerializer(serializers.Serializer):
    tz = TimeZoneField(help_text='The IANA time zone days begin and end in, e.g. "Europe/London".')


class HandDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    hands = serializers.IntegerField()
    net_bb = serializers.FloatField(help_text="The day's result in big blinds.")


class HandCalendarSerializer(serializers.Serializer):
    """The days a user played on, in their time zone, and their runs of consecutive days."""

    days = HandDaySerializer(many=True, help_text="The days with hands, oldest first.")
    current_streak = serializers.IntegerField(
        help_text="Consecutive days up to today, or up to yesterday while today has no hands yet."
    )
    best_streak = serializers.IntegerField(help_text="The longest run of consecutive days.")
    played_today = serializers.BooleanField()


class TagStakesSerializer(serializers.Serializer):
    currency = serializers.CharField(allow_blank=True, help_text="Empty for chips; the blinds are cents otherwise.")
    small_blind = serializers.IntegerField()
    big_blind = serializers.IntegerField()


class HandTagSerializer(serializers.Serializer):
    """Hands that share a position, game, cash-game stakes or format, and how they went."""

    key = serializers.CharField(help_text='What /api/hands/?tag= takes: "<group>:<value>", or "all".')
    group = serializers.ChoiceField(choices=TAG_GROUPS)
    value = serializers.CharField(
        allow_blank=True,
        help_text='BTN, Hold\'em No Limit, USD:5:10 (currency:small blind:big blind), cash, ...; empty for "all".',
    )
    stakes = TagStakesSerializer(allow_null=True, help_text="A stakes tag's blinds; null for the other groups.")
    hands = serializers.IntegerField()
    won = serializers.IntegerField(help_text="Hands with a positive result.")
    lost = serializers.IntegerField(help_text="Hands with a negative result.")
    net_bb = serializers.FloatField(help_text="Their results summed in big blinds.")
    bb_stdev = serializers.FloatField(
        allow_null=True,
        help_text=(
            "How much a hand's result varies: the sample standard deviation of their results in big blinds, "
            "from which bb/100's standard error is 100 × bb_stdev ÷ √hands. Null for fewer than two hands."
        ),
    )


class StatsQuerySerializer(HandFilterSerializer):
    """Which of the hero's hands /api/stats/ counts, and how it groups them. It leaves out hands they sat out."""

    group_by = serializers.ChoiceField(
        choices=STAT_GROUPINGS,
        default="none",
        help_text="One group of all the hands, or one per position, or one per month in `tz`.",
    )


class StatSerializer(serializers.Serializer):
    """How often the hero did something out of how often they could have, with its 95% Wilson interval."""

    did = serializers.IntegerField()
    could = serializers.IntegerField()
    pct = serializers.FloatField(allow_null=True, help_text="did ÷ could, in percent; null without a chance.")
    ci_low = serializers.FloatField(allow_null=True, help_text="Where the 95% interval begins, in percent.")
    ci_high = serializers.FloatField(allow_null=True, help_text="Where the 95% interval ends, in percent.")


# A field per statistic, each described as tracker.parsing.facts.STATS describes it.
StatSetSerializer = type(
    "StatSetSerializer",
    (serializers.Serializer,),
    {
        "__module__": __name__,
        "__doc__": "Every statistic in tracker.parsing.facts.STATS, and the aggression frequency.",
        **{stat: StatSerializer(help_text=text) for stat, text in STATS.items()},
        "aggression": StatSerializer(
            help_text="Bet or raised after the flop: (bets + raises) ÷ (bets + raises + calls + folds)."
        ),
    },
)


class StatGroupSerializer(serializers.Serializer):
    """The hero's statistics over a group of their hands: all of them, a position's, or a month's."""

    key = serializers.CharField(help_text='"all", a position such as "BTN", or a month such as "2026-10".')
    hands = serializers.IntegerField()
    net_bb = serializers.FloatField(help_text="Their results summed in big blinds.")
    bb_stdev = serializers.FloatField(
        allow_null=True,
        help_text=(
            "How much a hand's result varies: the sample standard deviation of their results in big blinds. "
            "Null for fewer than two hands."
        ),
    )
    stats = StatSetSerializer()

from rest_framework import serializers

from hands.filters import HAND_RESULTS, HAND_SORTS, TAG_GROUPS, tag_filter, zone
from hands.leaks import CHECKS, LEAK_GROUPS, LEAK_KEYS, PRESETS, presets_of
from hands.models import Hand, HandNote, Session
from hands.notes import NOTE_LENGTH, NOTE_STREETS, PURPOSES, REVIEW_STATES, TAG_LENGTH, bets
from hands.stats import STAT_GROUPINGS, sample_stdev
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
    hero_allin_equity = serializers.FloatField(
        allow_null=True,
        help_text=(
            "The hero's share of the pots they could win when the money went in before the river, every live hand "
            "shown; null in every other hand."
        ),
    )
    hero_ev_net_bb = serializers.FloatField(
        allow_null=True, help_text="The hero's net in big blinds expected then, rake taken; null when equity is."
    )

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
            "hero_allin_equity",
            "hero_ev_net_bb",
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
    review = serializers.ChoiceField(
        choices=REVIEW_STATES, required=False, help_text="Only the hands flagged to review, or those reviewed."
    )
    note_tag = serializers.CharField(
        required=False, max_length=TAG_LENGTH, help_text="Only the hands the user tagged with this, e.g. cooler."
    )
    leak = serializers.ChoiceField(
        choices=tuple(CHECKS),
        required=False,
        help_text="Only the hands in which the hero broke this check's rule, as /api/leaks/ counts it.",
    )
    session = serializers.IntegerField(required=False, help_text="Only the hands of this session, by its id.")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("did") is not None and "stat" not in attrs:
            raise serializers.ValidationError({"did": "Only with `stat`."})
        return attrs


class HandNoteSerializer(serializers.ModelSerializer):
    """Something the user wrote on a hand: a note, a tag, its review state, or why they made a bet or raise."""

    class Meta:
        model = HandNote
        fields = ("id", "kind", "street", "bet", "value", "text", "updated")
        read_only_fields = fields
        extra_kwargs = {
            "street": {"help_text": "note: its street, empty for the whole hand. purpose: the bet's street."},
            "bet": {"help_text": "purpose: which of the hero's bets and raises, counted from 0 in the order made."},
            "value": {"help_text": "tag: the tag. review: to_review or reviewed. purpose: value, bluff, ..."},
            "text": {"help_text": "note: what the user wrote."},
        }


class HandNoteWriteSerializer(serializers.Serializer):
    """A note to add to a hand, or to change the one it takes the place of: the street's note, the same tag, the
    review state, or the bet's purpose. Each kind takes its own fields."""

    kind = serializers.ChoiceField(choices=HandNote.Kind.choices)
    street = serializers.ChoiceField(
        choices=NOTE_STREETS,
        required=False,
        allow_blank=True,
        help_text="note: the street it is on; empty or left out for the whole hand.",
    )
    text = serializers.CharField(required=False, max_length=NOTE_LENGTH, help_text="note: what to say.")
    tag = serializers.CharField(required=False, max_length=TAG_LENGTH, help_text="tag: a word or two, e.g. cooler.")
    review = serializers.ChoiceField(choices=REVIEW_STATES, required=False, help_text="review: the hand's state.")
    bet = serializers.IntegerField(
        required=False, min_value=0, help_text="purpose: which of the hero's bets and raises, counted from 0."
    )
    purpose = serializers.ChoiceField(choices=PURPOSES, required=False, help_text="purpose: why they made it.")

    def validate(self, attrs):
        kind = attrs["kind"]
        if kind == HandNote.Kind.NOTE:
            text = attrs.get("text", "").strip()
            if not text:
                raise serializers.ValidationError({"text": "Write something, or delete the note."})
            return {"kind": kind, "street": attrs.get("street", ""), "text": text}
        if kind == HandNote.Kind.TAG:
            tag = " ".join(attrs.get("tag", "").split()).lower()
            if not tag:
                raise serializers.ValidationError({"tag": "Give the tag a word."})
            return {"kind": kind, "value": tag}
        if kind == HandNote.Kind.REVIEW:
            if "review" not in attrs:
                raise serializers.ValidationError({"review": "Say to_review or reviewed."})
            return {"kind": kind, "value": attrs["review"]}
        if "purpose" not in attrs:
            raise serializers.ValidationError({"purpose": "Say why the bet was made."})
        hand = self.context["hand"]
        made = bets(hand.replay.get("events", []), hand.hero) if hand.hero else []
        if attrs.get("bet") is None or attrs["bet"] >= len(made):
            raise serializers.ValidationError({"bet": "Not one of the hero's bets or raises in this hand."})
        return {"kind": kind, "bet": attrs["bet"], "street": made[attrs["bet"]]["street"], "value": attrs["purpose"]}


class ReviewHandSerializer(HandSummarySerializer):
    """A hand in the review queue."""

    flagged = serializers.DateTimeField(help_text="When it was flagged to review.")

    class Meta(HandSummarySerializer.Meta):
        fields = (*HandSummarySerializer.Meta.fields, "flagged")
        read_only_fields = fields


class NoteTagSerializer(serializers.Serializer):
    tag = serializers.CharField()
    hands = serializers.IntegerField()


class ReviewQueueSerializer(serializers.Serializer):
    """The user's review queue: the hands that nag them, which they flagged to look at again [JHU 4]."""

    to_review = serializers.IntegerField(help_text="Hands flagged to review.")
    reviewed = serializers.IntegerField(help_text="Hands reviewed since.")
    queue = ReviewHandSerializer(many=True, help_text="The latest hands flagged to review, the latest first: up to 5.")
    tags = NoteTagSerializer(many=True, help_text="The user's own tags, the most used first.")
    suggested_tags = serializers.ListField(child=serializers.CharField(), help_text="Tags to offer anyone.")


class HandDaysQuerySerializer(serializers.Serializer):
    tz = TimeZoneField(help_text='The IANA time zone days begin and end in, e.g. "Europe/London".')


class DaySessionSerializer(serializers.Serializer):
    """A session that was played on a day, in part or whole."""

    id = serializers.IntegerField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    hands = serializers.IntegerField()
    net_bb = serializers.FloatField()


class HandDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    hands = serializers.IntegerField()
    net_bb = serializers.FloatField(help_text="The day's result in big blinds.")
    sessions = DaySessionSerializer(many=True, help_text="The sessions played that day, the first first.")


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
        help_text=(
            "One group of all the hands, or one per position, one per month in `tz`, or one per cash-game stakes "
            "(leaving out tournaments, whose blinds go up every level)."
        ),
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
    """The hero's statistics over a group of their hands: all of them, a position's, a month's, or a stakes'."""

    key = serializers.CharField(
        help_text=(
            '"all", a position such as "BTN", a month such as "2026-10", or stakes as a stakes tag\'s value: '
            '"USD:5:10" (currency:small blind:big blind), ":100:200" for chips.'
        )
    )
    hands = serializers.IntegerField()
    net_bb = serializers.FloatField(help_text="Their results summed in big blinds.")
    bb_stdev = serializers.FloatField(
        allow_null=True,
        help_text=(
            "How much a hand's result varies: the sample standard deviation of their results in big blinds. "
            "Null for fewer than two hands."
        ),
    )
    rake_bb = serializers.FloatField(
        help_text=(
            "The hero's share of the rake, in big blinds: each pot's rake split by what the players put in, "
            "so some is paid in pots lost too."
        )
    )
    ev_net_bb = serializers.FloatField(
        help_text=(
            "net_bb adjusted for all-in equity: in a hand where the money went in before the river with every live "
            "hand shown, the net the hero could expect then; else the net."
        )
    )
    all_ins = serializers.IntegerField(help_text="Hands whose net is adjusted for all-in equity.")
    net_before_rake_bb = serializers.FloatField(
        help_text="net_bb with the rake taken from the pots the hero won added back: their results had there been none."
    )
    stats = StatSetSerializer()


class PurposeStatSerializer(serializers.Serializer):
    """How the hero's bets and raises of one purpose went on one street."""

    purpose = serializers.ChoiceField(choices=PURPOSES)
    street = serializers.CharField()
    bets = serializers.IntegerField()
    took_pot = StatSerializer(help_text="Bets nobody called or raised, taking the pot at once, out of all of them.")
    called = serializers.IntegerField(help_text="Bets called, and not raised.")
    raised = serializers.IntegerField()
    size = serializers.FloatField(
        allow_null=True, help_text="Their average size, as a share of everything in the middle before them."
    )
    needed = serializers.FloatField(
        allow_null=True,
        help_text="The share of folds a pure bluff of the average size needs to break even: size ÷ (1 + size).",
    )


class LeakQuerySerializer(HandFilterSerializer):
    """Which of the hero's hands /api/leaks/ checks, and which checks."""

    group = serializers.ChoiceField(choices=LEAK_GROUPS, default="preflop", help_text="The checks before the flop.")


class LeakMonthSerializer(serializers.Serializer):
    month = serializers.CharField(help_text='A month such as "2026-10".')
    did = serializers.IntegerField(help_text="Times the rule was broken; for hands per orbit, the hands played.")
    could = serializers.IntegerField(allow_null=True, help_text="The chances to keep it; null for hands per orbit.")
    rate = serializers.FloatField(allow_null=True, help_text="Hands per orbit; null for the other checks.")


class LeakSerializer(serializers.Serializer):
    """A leak check over the hero's hands: how often they broke one of the lectures' rules of thumb (B3)."""

    key = serializers.ChoiceField(choices=LEAK_KEYS)
    group = serializers.ChoiceField(choices=LEAK_GROUPS)
    share = StatSerializer(
        allow_null=True, help_text="Times the rule was broken out of the chances to keep it; null for hands per orbit."
    )
    rate = serializers.FloatField(
        allow_null=True,
        help_text="hands_per_orbit: hands played (VPIP) per orbit, an orbit being as many hands as players dealt in.",
    )
    average = serializers.FloatField(
        allow_null=True, help_text="open_size: the average open in big blinds. three_bet_size: in raises."
    )
    below = serializers.IntegerField(allow_null=True, help_text="Sizes: the chances taken smaller than the standard.")
    above = serializers.IntegerField(allow_null=True, help_text="Sizes: the chances taken bigger than the standard.")
    net_broken_bb = serializers.FloatField(allow_null=True, help_text="The net, in big blinds, of the hands broken.")
    net_kept_bb = serializers.FloatField(allow_null=True, help_text="The net, in big blinds, of the other chances.")
    months = LeakMonthSerializer(many=True, help_text="The trend: each month with chances, the oldest first.")


class PresetSerializer(serializers.Serializer):
    """A threshold of the leak checks: the user's value, the course value, and the range it may be set in."""

    key = serializers.ChoiceField(choices=tuple(PRESETS))
    value = serializers.FloatField()
    default = serializers.FloatField(help_text="The course value.")
    min = serializers.FloatField()
    max = serializers.FloatField()
    label = serializers.CharField()
    source = serializers.CharField(allow_blank=True, help_text="The lectures it comes from, e.g. JHU 3.")


def _validate_presets(self, attrs):
    values = presets_of(self.context["user"]) | {
        name: value for name, value in attrs.items() if value is not None
    }
    if values["orbit_min"] > values["orbit_max"]:
        raise serializers.ValidationError({"orbit_min": "More than orbit_max."})
    return attrs


# A field per preset, within its range; null puts it back to the course value.
PresetsUpdateSerializer = type(
    "PresetsUpdateSerializer",
    (serializers.Serializer,),
    {
        "__module__": __name__,
        "__doc__": "New values for some of the leak checks' presets; null puts one back to the course value.",
        **{
            name: serializers.FloatField(
                required=False,
                allow_null=True,
                min_value=preset["min"],
                max_value=preset["max"],
                help_text=preset["label"],
            )
            for name, preset in PRESETS.items()
        },
        "validate": _validate_presets,
    },
)


class SessionSerializer(serializers.ModelSerializer):
    """A stretch of play: the user's hands with no gap of more than half an hour between one and the next (F1)."""

    minutes = serializers.SerializerMethodField(help_text="From the first hand's start to the last's.")
    bb_stdev = serializers.SerializerMethodField(
        help_text="The sample standard deviation of its hands' results in big blinds; null for fewer than two."
    )
    flagged = serializers.IntegerField(help_text="Its hands flagged to review.")
    noted = serializers.IntegerField(help_text="Its hands with any note, tag, review state or purpose.")

    class Meta:
        model = Session
        fields = (
            "id",
            "start",
            "end",
            "minutes",
            "hands",
            "tables",
            "most_tables",
            "net_bb",
            "bb_stdev",
            "ev_net_bb",
            "biggest_pot_bb",
            "flagged",
            "noted",
        )
        read_only_fields = fields
        extra_kwargs = {
            "tables": {"help_text": "Tables played at."},
            "most_tables": {"help_text": "The most tables played at once."},
            "net_bb": {"help_text": "The result in big blinds."},
            "ev_net_bb": {"help_text": "The result adjusted for all-in equity, as /api/stats/ counts it."},
            "biggest_pot_bb": {"help_text": "The biggest pot, in big blinds."},
        }

    def get_minutes(self, session) -> int:
        return round((session.end - session.start).total_seconds() / 60)

    def get_bb_stdev(self, session) -> float | None:
        stdev = sample_stdev(session.hands, session.net_bb, session.net_bb_squares)
        return None if stdev is None else round(stdev, 2)


class SessionQuerySerializer(serializers.Serializer):
    """Which sessions to list: those that began within these days, in `tz`."""

    since = serializers.DateField(required=False, help_text="Only the sessions begun from this day on.")
    until = serializers.DateField(required=False, help_text="Only the sessions begun up to the end of this day.")
    tz = TimeZoneField(required=False, help_text="The IANA time zone days are counted in; UTC if left out.")


class SessionGroupSerializer(serializers.Serializer):
    """The hero's hands in one part of their sessions, and how they went."""

    key = serializers.CharField()
    hands = serializers.IntegerField()
    net_bb = serializers.FloatField(help_text="Their results summed in big blinds.")
    bb_stdev = serializers.FloatField(
        allow_null=True, help_text="The sample standard deviation of their results in big blinds."
    )
    ev_net_bb = serializers.FloatField(help_text="net_bb adjusted for all-in equity.")


class SessionPatternsSerializer(serializers.Serializer):
    """The hero's results set against when and how they played (F1)."""

    hours_in = SessionGroupSerializer(
        many=True, help_text='By whole hours into the session: "0" is the first hour, then "1", "2" and "3+".'
    )
    time_of_day = SessionGroupSerializer(
        many=True, help_text="By the part of the day, in `tz`: night (0-6), morning, afternoon, evening (18-24)."
    )
    weekday = SessionGroupSerializer(many=True, help_text='By the day of the week, in `tz`: "1" is Monday, "7" Sunday.')
    tables = SessionGroupSerializer(many=True, help_text='By the tables played at once: "1", "2", "3" or "4+".')

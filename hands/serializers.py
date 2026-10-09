from django.db.models import Q
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from hands.cards import HAND_KINDS
from hands.filters import HAND_RESULTS, HAND_SORTS, TAG_GROUPS, UTC, tag_filter, zone
from hands.leaks import CHECKS, LEAK_GROUPS, LEAK_KEYS, PRESETS, presets_of
from hands.models import Hand, HandNote, HandShare, LeakReview, Opponent, SavedRange, Session, Spot, Tournament
from hands.notes import NOTE_LENGTH, NOTE_STREETS, PURPOSES, REVIEW_STATES, TAG_LENGTH, WRITEUP_LENGTH, bets
from hands.opponents import AGGRESSIVE, LOOSE_VPIP, OPPONENT_SORTS, POT_SIZES, core_stats, effective_label, hands_with
from hands.ranges import parse as parse_range
from hands.spots import SpotError, spot_filter
from hands.spots import parse as parse_spec
from hands.stats import BET_SIZE_KEYS, FIRST_ACTIONS, STAT_GROUPINGS, proportion, sample_stdev
from hands.tournaments import kind_of, result
from tracker.parsing.equity import CARDS
from tracker.parsing.facts import SIZING_FLAGS, STATS, TEXTURES

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


class TextureSerializer(serializers.Serializer):
    """How a board reads (tracker.parsing.facts.board_texture)."""

    paired = serializers.BooleanField()
    suited = serializers.IntegerField(help_text="The most cards of one suit: 1 rainbow, 2 two-tone, 3 or more.")
    straight_possible = serializers.BooleanField(help_text="Three of its ranks fit in a straight.")
    high_card = serializers.CharField()
    wetness = serializers.IntegerField(help_text="0 (dry) to 3: a flush draw or flush, and a straight's ranks.")


class StreetFactsSerializer(serializers.Serializer):
    pot_bb = serializers.FloatField(help_text="The pot as the street began, in big blinds.")
    players = serializers.IntegerField(help_text="Players still in as it began.")
    effective_bb = serializers.FloatField(help_text="The most that could still go in: the second-biggest stack in.")
    texture = TextureSerializer()


class HeroLineSerializer(serializers.Serializer):
    """How the hero played a street after the flop."""

    role = serializers.CharField(help_text="Their part before the flop: raised (last), called, or limped (no raise).")
    ip = serializers.BooleanField(allow_null=True, help_text="Whether they acted last; null when nobody else could.")
    players = serializers.IntegerField()
    texture = serializers.CharField(help_text="monotone, paired, wet or dry.")
    first = serializers.CharField(allow_null=True, help_text="Their first move with nothing to call: bet or check.")
    faced = serializers.CharField(allow_null=True, help_text="Their answer to the first bet they faced.")
    outcome = serializers.CharField(allow_null=True, help_text="What came of their first bet: folded, called, raised.")


class HeroFactsSerializer(serializers.Serializer):
    group = serializers.CharField(help_text="The JHU starting-hand group; empty in Omaha.")
    spr = serializers.FloatField(allow_null=True, help_text="The hero's stack-to-pot ratio at the flop.")
    made = serializers.DictField(child=serializers.CharField(), help_text="The made hand on each street seen.")
    draws = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))
    final = serializers.CharField(allow_null=True, required=False, help_text="The made hand on the last street seen.")
    lines = serializers.DictField(child=HeroLineSerializer(), required=False)
    flags = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="What their bets' sizes gave away (B4)."
    )


class TournamentFactsSerializer(serializers.Serializer):
    """What a tournament hand's text says of its tournament (FND-8). Amounts are cents with a currency."""

    buy_in = serializers.IntegerField()
    fee = serializers.IntegerField()
    bounty = serializers.IntegerField()
    currency = serializers.CharField(allow_blank=True)
    level = serializers.IntegerField(allow_null=True)


class HandFactsSerializer(serializers.Serializer):
    """The decision context of a hand (tracker.parsing.facts): the pot, stacks and board on each street, and the
    hero's hand and lines. Hands parsed by an older parser have fewer of them."""

    preflop_aggressor = serializers.CharField(allow_null=True)
    players_at_flop = serializers.IntegerField()
    spr = serializers.FloatField(allow_null=True)
    streets = serializers.DictField(child=StreetFactsSerializer())
    hero = HeroFactsSerializer(required=False)
    tournament = TournamentFactsSerializer(required=False)


class HandOpponentSerializer(serializers.Serializer):
    """An opponent in the hand, with their profile's id and label (C1)."""

    name = serializers.CharField()
    id = serializers.IntegerField()
    label = serializers.CharField(allow_blank=True)


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
    facts = HandFactsSerializer()
    level = serializers.IntegerField(allow_null=True, help_text="A tournament's blind level.")
    tournament = serializers.IntegerField(
        source="tournament_pk", allow_null=True, help_text="The id of the tournament it was played in, if any."
    )
    opponents = HandOpponentSerializer(
        many=True, source="opponent_rows", help_text="The opponents dealt in who have a profile, by name."
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
            "facts",
            "level",
            "tournament",
            "opponents",
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
    """Which of the user's hands to count. Any filter leaves out the hands they sat out.

    The spot, spec, opponent and tournament are the user's own, so the serializer needs the user in its context.
    """

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
    spot = serializers.IntegerField(required=False, help_text="Only the hands one of the user's spots matches.")
    spec = serializers.CharField(
        required=False,
        help_text=(
            'Only the hands a spot spec matches, as JSON: {"all": [...]}, {"any": [...]}, {"not": spec} or a '
            'condition such as {"field": "position", "value": ["BTN"]}. /api/spots/fields/ lists the conditions.'
        ),
    )
    opponent = serializers.IntegerField(required=False, help_text="Only the hands this opponent was dealt into.")
    tournament = serializers.IntegerField(required=False, help_text="Only the hands of this tournament, by its id.")

    def validate(self, attrs):
        if "since" in attrs and "until" in attrs and attrs["since"] > attrs["until"]:
            raise serializers.ValidationError({"since": "After `until`."})
        where = []
        user = self.context.get("user")
        tz = attrs.get("tz", UTC)
        if "spot" in attrs:
            spot = Spot.objects.filter(user=user, pk=attrs["spot"]).first() if user else None
            if spot is None:
                raise serializers.ValidationError({"spot": "Not one of your spots."})
            where.append(spot_filter(spot.spec, user, tz))
        if "spec" in attrs:
            try:
                spec = parse_spec(attrs["spec"])
            except SpotError as error:
                raise serializers.ValidationError({"spec": str(error)}) from None
            where.append(spot_filter(spec, user, tz))
        if "opponent" in attrs:
            opponent = Opponent.objects.filter(user=user, pk=attrs["opponent"]).first() if user else None
            if opponent is None:
                raise serializers.ValidationError({"opponent": "Not one of your opponents."})
            where.append(hands_with(opponent) & Q(site=opponent.site))
        if "tournament" in attrs:
            tournament = Tournament.objects.filter(user=user, pk=attrs["tournament"]).first() if user else None
            if tournament is None:
                raise serializers.ValidationError({"tournament": "Not one of your tournaments."})
            where.append(Q(site=tournament.site, tournament_id=tournament.tournament_id))
        if where:
            attrs["where"] = where
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
    review state, the bet's purpose, or the hand's write-up. Each kind takes its own fields."""

    kind = serializers.ChoiceField(choices=HandNote.Kind.choices)
    street = serializers.ChoiceField(
        choices=NOTE_STREETS,
        required=False,
        allow_blank=True,
        help_text="note: the street it is on; empty or left out for the whole hand.",
    )
    text = serializers.CharField(
        required=False,
        max_length=WRITEUP_LENGTH,
        help_text=f"note: what to say, up to {NOTE_LENGTH} characters. writeup: the hand written up for others.",
    )
    tag = serializers.CharField(required=False, max_length=TAG_LENGTH, help_text="tag: a word or two, e.g. cooler.")
    review = serializers.ChoiceField(choices=REVIEW_STATES, required=False, help_text="review: the hand's state.")
    bet = serializers.IntegerField(
        required=False, min_value=0, help_text="purpose: which of the hero's bets and raises, counted from 0."
    )
    purpose = serializers.ChoiceField(choices=PURPOSES, required=False, help_text="purpose: why they made it.")

    def validate(self, attrs):
        kind = attrs["kind"]
        if kind in (HandNote.Kind.NOTE, HandNote.Kind.WRITEUP):
            text = attrs.get("text", "").strip()
            if not text:
                raise serializers.ValidationError({"text": "Write something, or delete the note."})
            if kind == HandNote.Kind.WRITEUP:
                return {"kind": kind, "text": text}
            if len(text) > NOTE_LENGTH:
                raise serializers.ValidationError({"text": f"At most {NOTE_LENGTH} characters."})
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
            "One group of all the hands, or one per: position; month in `tz`; cash-game stakes (leaving out "
            "tournaments, whose blinds go up every level); preflop situation; effective stack (0-10, 10-20, 20-40, "
            "40-100 or 100+ big blinds); M zone (tournaments); starting-hand group or combo (hold'em); the size of "
            "the hero's biggest bet or raise after the flop (hands without one left out); or opponent dealt in, "
            "a hand counting for each of its opponents."
        ),
    )
    limit = serializers.IntegerField(
        default=50,
        min_value=1,
        max_value=500,
        help_text="group_by=opponent: the opponents the hero played most hands with, so many of them.",
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


# A field per first move, "raise" among them, which a class body can't name.
FirstActionsSerializer = type(
    "FirstActionsSerializer",
    (serializers.Serializer,),
    {
        "__module__": __name__,
        "__doc__": "How the hero's first decision before the flop went: each move's share of the group's hands.",
        **{action: StatSerializer() for action in FIRST_ACTIONS},
    },
)


class StatGroupSerializer(serializers.Serializer):
    """The hero's statistics over a group of their hands: all of them, or one key's of /api/stats/'s `group_by`."""

    key = serializers.CharField(
        help_text=(
            '"all"; a position such as "BTN"; a month such as "2026-10"; stakes as a stakes tag\'s value, "USD:5:10" '
            '(currency:small blind:big blind) or ":100:200" for chips; a situation (unopened, limped, raised, 3bet, '
            "4bet+, none); an effective stack (0-10, 10-20, 20-40, 40-100, 100+); an M zone (dead, push_fold, "
            "restealing, value, set_mining); a starting-hand group (premium, big_pair, ...) or combo (AKs); a bet "
            "size (under_third, third_half, half_three_quarters, three_quarters_pot, pot_plus); or an opponent's "
            "screen name."
        )
    )
    hands = serializers.IntegerField()
    first_actions = FirstActionsSerializer(help_text="The hero's first decision before the flop.")
    shove = StatSerializer(help_text="Raises before the flop that moved in, out of the hands the hero raised in.")
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

    group = serializers.ChoiceField(
        choices=LEAK_GROUPS,
        default="preflop",
        help_text="The checks before the flop (B3's discipline checks), or after it (B5's leak alerts).",
    )


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
    reviewed = serializers.DateTimeField(allow_null=True, help_text="When the user last marked the check reviewed.")
    new = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Times broken in hands played since it was reviewed, or ever if it never was; null for hands per orbit."
        ),
    )
    months = LeakMonthSerializer(many=True, help_text="The trend: each month with chances, the oldest first.")


class LeakReviewSerializer(serializers.ModelSerializer):
    """When the user last marked a leak check reviewed."""

    class Meta:
        model = LeakReview
        fields = ("key", "reviewed")
        read_only_fields = fields


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


# Reports: bet sizing (B4), lines after the flop (B6) and the statistics' dictionary (E5).


class StrengthsSerializer(serializers.Serializer):
    """Bets by how strong the hand was (tracker.parsing.facts.STRENGTHS)."""

    nothing = serializers.IntegerField()
    draw = serializers.IntegerField(help_text="Eight outs or more, and no pair.")
    weak = serializers.IntegerField(help_text="A pair below top pair.")
    strong = serializers.IntegerField(help_text="Top pair or better.")
    nuts = serializers.IntegerField(help_text="Nothing beat it then.")


class SizeBucketSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=BET_SIZE_KEYS)
    bets = serializers.IntegerField()
    strengths = StrengthsSerializer()
    strong = StatSerializer(help_text="Bets with top pair or better, the nuts included, out of them all.")


class SizingTellSerializer(serializers.Serializer):
    """The size whose share of strong hands sits furthest from the street's: what it says about the hand."""

    bucket = serializers.ChoiceField(choices=BET_SIZE_KEYS)
    strong = StatSerializer()
    gap = serializers.FloatField(help_text="Its share of strong hands less the street's, in percentage points.")


class SizingStreetSerializer(serializers.Serializer):
    street = serializers.CharField()
    bets = serializers.IntegerField()
    strong = StatSerializer(help_text="Bets with top pair or better, out of all the street's.")
    tell = SizingTellSerializer(allow_null=True, help_text="Null until two sizes have ten bets each.")
    buckets = SizeBucketSerializer(many=True, help_text="Sizes with bets, the smallest first.")


class SizingFlagSerializer(serializers.Serializer):
    flag = serializers.ChoiceField(choices=SIZING_FLAGS)
    hands = serializers.IntegerField(help_text="Hands with it.")
    of = serializers.IntegerField(help_text="Hands with any bet or raise by the hero after the flop.")


class SizingReportSerializer(serializers.Serializer):
    """The hero's bets and raises after the flop by street and size, split by hand strength (B4)."""

    streets = SizingStreetSerializer(many=True)
    flags = SizingFlagSerializer(many=True)


# A street's moves, "raise" among them, which a class body can't name.
LineMovesSerializer = type(
    "LineMovesSerializer",
    (serializers.Serializer,),
    {
        "__module__": __name__,
        "__doc__": "What the hero did on a street: bet when they could bet first, and answered a bet.",
        "hands": serializers.IntegerField(),
        "bet": StatSerializer(help_text="Bet, out of the times they could bet first: nothing to call."),
        **{
            move: StatSerializer(help_text=f"{done}, out of the times they faced a bet.")
            for move, done in (("fold", "Folded"), ("call", "Called"), ("raise", "Raised"))
        },
    },
)


class LineTextureSerializer(LineMovesSerializer):
    texture = serializers.ChoiceField(choices=TEXTURES)


class LineSpotSerializer(LineMovesSerializer):
    role = serializers.CharField(help_text="The hero's part before the flop: raised, called or limped.")
    ip = serializers.BooleanField(allow_null=True, help_text="In position; null when nobody else could act.")
    textures = LineTextureSerializer(many=True)


class LineStreetSerializer(serializers.Serializer):
    street = serializers.CharField()
    spots = LineSpotSerializer(many=True)


class SizeCountSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=BET_SIZE_KEYS)
    bets = serializers.IntegerField()


class BarrelSerializer(serializers.Serializer):
    """The street after a c-bet that was called [JHU 8]."""

    street = serializers.CharField()
    hands = serializers.IntegerField()
    barrel = StatSerializer(help_text="Bet again, out of the times they acted.")
    checked_behind = StatSerializer(help_text="Checked last, in position.")
    gave_up = StatSerializer(help_text="Checked first, then folded to a bet, out of the checks first.")
    check_call = StatSerializer()
    check_raise = StatSerializer()
    sizes = SizeCountSerializer(many=True, help_text="river: the third barrel's sizes.")


class LinesReportSerializer(serializers.Serializer):
    """How the hero played the flop, turn and river by their part before the flop and position, and by texture;
    then the turn and the river after a called c-bet (B6)."""

    streets = LineStreetSerializer(many=True)
    barrels = BarrelSerializer(many=True)


class StatDefinitionSerializer(serializers.Serializer):
    """A statistic and exactly what it counts: the stat dictionary (E5)."""

    key = serializers.CharField()
    definition = serializers.CharField()


# Spots (FND-3, B7) and saved ranges (FND-5).


class SpecField(serializers.JSONField):
    """A spot spec: conditions grouped with all, any and not (hands.spots), checked and tidied."""

    def to_internal_value(self, data):
        try:
            return parse_spec(super().to_internal_value(data))
        except SpotError as error:
            raise serializers.ValidationError(str(error)) from None


class SavedSpotSerializer(serializers.ModelSerializer):
    """A spot the user saved: a named filter."""

    spec = SpecField(help_text="Its conditions; /api/spots/fields/ lists them.")

    class Meta:
        model = Spot
        fields = ("id", "name", "spec", "share_code", "created", "updated")
        read_only_fields = ("id", "share_code", "created", "updated")
        extra_kwargs = {"share_code": {"help_text": "Others import a copy with it; null until shared."}}


class SpotFieldSerializer(serializers.Serializer):
    """A condition a spot can hold, and the parameters it takes."""

    field = serializers.CharField()
    params = serializers.ListField(child=serializers.CharField())
    required = serializers.ListField(child=serializers.CharField())
    choices = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        help_text="The choices of each parameter that has a fixed set of them.",
    )


class SpotCountRequestSerializer(serializers.Serializer):
    spec = SpecField()
    tz = TimeZoneField(required=False)


class SpotCountSerializer(serializers.Serializer):
    hands = serializers.IntegerField(help_text="The hands the spec matches, leaving out those the hero sat out.")


class SharedSpotSerializer(serializers.Serializer):
    """A spot someone shared: its name and conditions, without any that name a player."""

    name = serializers.CharField()
    spec = serializers.JSONField()
    code = serializers.CharField()


class SpotImportSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=16)


class SavedRangeSerializer(serializers.ModelSerializer):
    """A range the user built and named, in range notation: "TT+, AQs+, AKo"."""

    class Meta:
        model = SavedRange
        fields = ("id", "name", "hands", "created")
        read_only_fields = ("id", "created")

    def validate_hands(self, value):
        try:
            if not parse_range(value):
                raise ValueError("No hands.")
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from None
        return value


# Opponents (FND-6, C1 and C2).


class OpponentQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, help_text="Only the names that contain this.")
    label = serializers.ChoiceField(
        choices=Opponent.Label.choices, required=False, help_text="Only the players with this label."
    )
    sort = serializers.ChoiceField(
        choices=OPPONENT_SORTS,
        default="hands",
        help_text="Most hands together, the hero's best or worst net against them, or the most recently seen.",
    )
    min_hands = serializers.IntegerField(default=1, min_value=1, help_text="Only the players with this many hands.")


class OpponentSerializer(serializers.ModelSerializer):
    """A player the user has played with: their core statistics, label and the user's net against them."""

    shown_label = serializers.SerializerMethodField(
        help_text="The label that counts: the user's own, else the automatic one."
    )

    class Meta:
        model = Opponent
        fields = (
            "id",
            "site",
            "name",
            "hands",
            "first_seen",
            "last_seen",
            "vpip",
            "pfr",
            "aggression",
            "label",
            "confidence",
            "manual_label",
            "shown_label",
            "note",
            "shared_hands",
            "hero_net_bb",
        )
        read_only_fields = fields
        extra_kwargs = {
            "vpip": {"help_text": "In percent; null without a chance."},
            "label": {"help_text": "The automatic label; empty with too few hands to say."},
            "shared_hands": {"help_text": "Hands where both put money in by choice, or both saw the flop."},
            "hero_net_bb": {"help_text": "The hero's net in those hands, in big blinds."},
        }

    def get_shown_label(self, opponent) -> str:
        return effective_label(opponent)


class OpponentPositionSerializer(serializers.Serializer):
    position = serializers.CharField()
    hands = serializers.IntegerField()
    vpip = StatSerializer()
    pfr = StatSerializer()


class OpponentDetailSerializer(OpponentSerializer):
    """An opponent's profile: every statistic with its sample, their play by position, and the label's lines."""

    stats = serializers.SerializerMethodField()
    positions = OpponentPositionSerializer(many=True, source="position_rows")
    loose_vpip = serializers.SerializerMethodField(help_text="The VPIP from which a player is loose, in percent.")
    aggressive = serializers.SerializerMethodField(help_text="The aggression from which a player is aggressive.")

    class Meta(OpponentSerializer.Meta):
        fields = (*OpponentSerializer.Meta.fields, "stats", "positions", "loose_vpip", "aggressive")
        read_only_fields = fields

    @extend_schema_field(StatSetSerializer)
    def get_stats(self, opponent):
        counters = opponent.counters
        stats = {stat: proportion(counters.get(f"{stat}_did", 0), counters.get(f"{stat}_could", 0)) for stat in STATS}
        return {**stats, "aggression": core_stats(counters)["aggression"]}

    def get_loose_vpip(self, opponent) -> float:
        return LOOSE_VPIP

    def get_aggressive(self, opponent) -> float:
        return AGGRESSIVE


class OpponentUpdateSerializer(serializers.Serializer):
    """The user's own label for an opponent (empty for the automatic one) and their note on them."""

    manual_label = serializers.ChoiceField(choices=Opponent.Label.choices, required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=NOTE_LENGTH)


class OpponentShowdownSerializer(serializers.Serializer):
    """A hand in which an opponent's cards were shown, and what they had done with them [JHU 4]."""

    hand = serializers.IntegerField(help_text="The hand's id, for its replay.")
    played_at = serializers.DateTimeField()
    position = serializers.CharField()
    line = serializers.CharField(help_text='Before the flop, in words: "3-bet", "raised first in", "limped", ...')
    cards = serializers.ListField(child=serializers.CharField())
    combo = serializers.CharField(allow_null=True, help_text="Hold'em only: AKs, T9o, 88.")
    shown = serializers.CharField(allow_null=True, help_text="Their hand as shown, e.g. Three of a kind.")
    board = serializers.ListField(child=serializers.CharField())
    net_bb = serializers.FloatField()
    surprise = serializers.FloatField(help_text="How strong the line, how weak the cards: higher is more surprising.")
    actions = serializers.DictField(
        child=serializers.DictField(child=serializers.IntegerField()),
        help_text="Their moves on each street, counted: bets, raises, calls, checks, folds.",
    )


class LedgerPotSerializer(serializers.Serializer):
    size = serializers.ChoiceField(choices=[name for name, _, _ in POT_SIZES], help_text="small <10 BB, ... huge 100+.")
    hands = serializers.IntegerField()
    net_bb = serializers.FloatField()
    bb_stdev = serializers.FloatField(allow_null=True)


class LedgerHandSerializer(serializers.Serializer):
    hand = serializers.IntegerField()
    played_at = serializers.DateTimeField()
    net_bb = serializers.FloatField()
    pot_bb = serializers.FloatField()


class LedgerSerializer(serializers.Serializer):
    """The hero against an opponent (C2): hands where both put money in by choice or both saw the flop."""

    hands = serializers.IntegerField()
    net_bb = serializers.FloatField(help_text="The hero's whole result in those hands, in big blinds.")
    pots = LedgerPotSerializer(many=True)
    biggest_won = LedgerHandSerializer(many=True)
    biggest_lost = LedgerHandSerializer(many=True)


# Tournaments (FND-8, D1 and D2).


class TournamentResultSerializer(serializers.Serializer):
    """What a tournament returned, the user's entries counting over what was read."""

    entries = serializers.IntegerField()
    finish = serializers.IntegerField(allow_null=True)
    prize = serializers.IntegerField()
    cost = serializers.IntegerField(help_text="Entries × (buy-in + fee + bounty).")
    net = serializers.IntegerField(help_text="Prize and bounties less the cost.")
    roi = serializers.FloatField(allow_null=True, help_text="Net ÷ cost; null for a freeroll.")
    in_the_money = serializers.BooleanField()
    percentile = serializers.FloatField(allow_null=True, help_text="The finish in the field: 0 won, 1 first out.")


class TournamentSerializer(serializers.ModelSerializer):
    """A tournament the user played, read from its hands (FND-8), with what it returned (D1). Amounts are cents for
    a buy-in with a currency, chips otherwise."""

    result = serializers.SerializerMethodField()
    kind = serializers.SerializerMethodField(help_text="Its table size, and whether it has bounties.")

    class Meta:
        model = Tournament
        fields = (
            "id",
            "site",
            "tournament_id",
            "game",
            "hero",
            "currency",
            "play_money",
            "freeroll",
            "buy_in",
            "fee",
            "bounty",
            "first_hand",
            "last_hand",
            "hands",
            "max_seats",
            "top_level",
            "entries",
            "finish",
            "prize",
            "bounties_won",
            "knockouts",
            "field_size",
            "payouts",
            "entered_finish",
            "entered_prize",
            "entered_entries",
            "note",
            "kind",
            "result",
        )
        read_only_fields = fields

    @extend_schema_field(TournamentResultSerializer)
    def get_result(self, tournament):
        return result(tournament)

    def get_kind(self, tournament) -> str:
        return kind_of(tournament)


class TimelinePointSerializer(serializers.Serializer):
    """One of the hero's hands in a tournament, for the stack chart (D2)."""

    id = serializers.IntegerField()
    hand_id = serializers.CharField()
    played_at = serializers.DateTimeField()
    level = serializers.IntegerField(allow_null=True)
    small_blind = serializers.IntegerField()
    big_blind = serializers.IntegerField()
    ante = serializers.IntegerField(allow_null=True)
    players_dealt = serializers.IntegerField()
    stack = serializers.IntegerField(allow_null=True, help_text="The hero's chips at the start of the hand.")
    stack_bb = serializers.FloatField(allow_null=True)
    hero_m = serializers.FloatField(allow_null=True)
    zone = serializers.CharField(allow_null=True, help_text="The M zone [MIT 5].")
    table_average = serializers.IntegerField(allow_null=True, help_text="The table's average stack, for Q.")
    hero_net = serializers.IntegerField()
    total_pot = serializers.IntegerField()
    all_in = serializers.BooleanField()
    steal = serializers.BooleanField()
    ev_net_bb = serializers.FloatField(allow_null=True)


class TournamentDetailSerializer(TournamentSerializer):
    timeline = TimelinePointSerializer(many=True, source="points")

    class Meta(TournamentSerializer.Meta):
        fields = (*TournamentSerializer.Meta.fields, "timeline")
        read_only_fields = fields


class TournamentUpdateSerializer(serializers.Serializer):
    """What the hands can't tell, or tell wrongly: the field size, the payouts, and a finish, prize or entries."""

    field_size = serializers.IntegerField(required=False, allow_null=True, min_value=2)
    payouts = serializers.ListField(
        child=serializers.IntegerField(min_value=0), required=False, max_length=1000, help_text="First place first."
    )
    entered_finish = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    entered_prize = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    entered_entries = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=1000)
    note = serializers.CharField(required=False, allow_blank=True, max_length=NOTE_LENGTH)


class TournamentQuerySerializer(serializers.Serializer):
    since = serializers.DateField(required=False, help_text="Only the tournaments begun from this day on.")
    until = serializers.DateField(required=False, help_text="Only the tournaments begun up to the end of this day.")
    tz = TimeZoneField(required=False)


class TournamentTotalsSerializer(serializers.Serializer):
    """Totals over a group of tournaments: all of one kind of money, or one buy-in and format's."""

    money = serializers.CharField(help_text='"play_money", "chips", or a currency such as "USD".')
    buy_in = serializers.IntegerField(allow_null=True, help_text="The whole buy-in; null for all of the money's.")
    kind = serializers.CharField(help_text='"all", or a format such as "9-max" or "6-max knockout".')
    tournaments = serializers.IntegerField()
    entries = serializers.IntegerField()
    cost = serializers.IntegerField()
    fees = serializers.IntegerField(help_text="The fees in that cost: what the house took.")
    prizes = serializers.IntegerField()
    bounties = serializers.IntegerField()
    net = serializers.IntegerField()
    roi = serializers.FloatField(allow_null=True)
    in_the_money = StatSerializer(help_text="Finishes in the money, out of the tournaments with a finish.")
    average_percentile = serializers.FloatField(allow_null=True, help_text="Where fields are known.")


# Reading the cards (A2, A3) and the equity calculator.


class OutCardSerializer(serializers.Serializer):
    card = serializers.CharField()
    kind = serializers.ChoiceField(choices=("out", "split", "dirty", "danger", "counterfeit"))


class OutsCountsSerializer(serializers.Serializer):
    out = serializers.IntegerField(required=False)
    split = serializers.IntegerField(required=False)
    dirty = serializers.IntegerField(required=False)
    danger = serializers.IntegerField(required=False)
    counterfeit = serializers.IntegerField(required=False)


class KnownHandSerializer(serializers.Serializer):
    name = serializers.CharField()
    cards = serializers.ListField(child=serializers.CharField())


class OutsDecisionSerializer(serializers.Serializer):
    """The hero's outs at one of their decisions on the flop or turn (A2)."""

    event = serializers.IntegerField(help_text="The decision's index in the hand's events: its replay step.")
    street = serializers.CharField()
    board = serializers.ListField(child=serializers.CharField())
    villains = KnownHandSerializer(many=True, help_text="The live opponents whose cards were shown.")
    unknown = serializers.IntegerField(help_text="Live opponents whose cards weren't.")
    cards_to_come = serializers.IntegerField()
    equity = serializers.FloatField(allow_null=True, help_text="The hero's share of the pot as the board runs out.")
    exact = serializers.BooleanField(required=False)
    next_card = serializers.FloatField(allow_null=True, help_text="Their share after the next card alone.")
    standing = serializers.CharField(allow_null=True, help_text="ahead, tied or behind, before the next card.")
    outs = OutCardSerializer(many=True, help_text="The cards to come that matter, and what each does.")
    counts = OutsCountsSerializer()
    rule = serializers.FloatField(allow_null=True, help_text="The rule of 2 and 4's estimate, in percent.")


class BoardTextureSerializer(serializers.Serializer):
    flush_possible = serializers.BooleanField()
    straight_possible = serializers.BooleanField()
    full_house_possible = serializers.BooleanField()
    wetness = serializers.IntegerField()


class BoardClassSerializer(serializers.Serializer):
    category = serializers.CharField()
    description = serializers.CharField(help_text='The best hand of the kind: "three nines", "an ace-high flush".')
    cards = serializers.ListField(child=serializers.CharField(), help_text="Two cards that make it.")
    combos = serializers.IntegerField(help_text="Two-card combos that make a hand of the kind.")


class BeatenBySerializer(serializers.Serializer):
    description = serializers.CharField()
    combos = serializers.IntegerField()


class BoardHeroSerializer(serializers.Serializer):
    description = serializers.CharField()
    category = serializers.CharField()
    better = serializers.IntegerField(help_text="Holdings left that beat the hero's hand.")
    equal = serializers.IntegerField()
    worse = serializers.IntegerField()
    beats = serializers.FloatField(allow_null=True, help_text="The share of holdings it beats, ties counting half.")
    beaten_by = BeatenBySerializer(many=True, help_text="What beats it, the strongest first.")
    sampled = serializers.BooleanField(help_text="Omaha: from sampled holdings, there being too many to count.")
    warnings = serializers.ListField(
        child=serializers.ChoiceField(choices=("not_the_nut_flush", "low_straight", "counterfeit_risk"))
    )


class BoardStreetSerializer(serializers.Serializer):
    """One street's board read (A3)."""

    street = serializers.CharField()
    board = serializers.ListField(child=serializers.CharField())
    texture = BoardTextureSerializer()
    nuts = BoardClassSerializer()
    classes = BoardClassSerializer(many=True, help_text="The three best kinds of hand possible.")
    hero = BoardHeroSerializer(allow_null=True)


class CardField(serializers.CharField):
    def to_internal_value(self, data):
        card = super().to_internal_value(data)
        if card not in CARDS:
            raise serializers.ValidationError(f"Not a card: {card!r}.")
        return card


class VillainSerializer(serializers.Serializer):
    """Who the hand is against: their cards, a range, or a kind of hand on the board. Give one."""

    cards = serializers.ListField(child=CardField(), required=False, min_length=2, max_length=2)
    range = serializers.CharField(required=False, help_text='Range notation, e.g. "TT+, AQs+, AKo".')
    kind = serializers.ChoiceField(choices=HAND_KINDS, required=False)

    def validate(self, attrs):
        if len(attrs) != 1:
            raise serializers.ValidationError("Give one of cards, range or kind.")
        if "range" in attrs:
            try:
                parse_range(attrs["range"])
            except ValueError as error:
                raise serializers.ValidationError({"range": str(error)}) from None
        return attrs


class EquityRequestSerializer(serializers.Serializer):
    """A hold'em hand against an opponent, on a board of nothing yet, a flop, turn or river."""

    hero = serializers.ListField(child=CardField(), min_length=2, max_length=2)
    board = serializers.ListField(child=CardField(), max_length=5, default=list)
    villain = VillainSerializer()
    dead = serializers.ListField(child=CardField(), default=list, help_text="Other cards known to be out.")

    def validate(self, attrs):
        cards = [*attrs["hero"], *attrs["board"], *attrs["dead"], *attrs["villain"].get("cards", [])]
        if len(set(cards)) != len(cards):
            raise serializers.ValidationError("A card is used twice.")
        if len(attrs["board"]) in (1, 2):
            raise serializers.ValidationError({"board": "No cards, a flop, a turn or a river."})
        if attrs["villain"].get("kind", "any") != "any" and len(attrs["board"]) < 3:
            raise serializers.ValidationError({"villain": "A kind of hand needs a board."})
        return attrs


class EquityResultSerializer(serializers.Serializer):
    equity = serializers.FloatField(help_text="The hero's share of the pot, ties split.")
    stderr = serializers.FloatField(help_text="Its standard error when sampled; 0 when exact.")
    exact = serializers.BooleanField()
    combos = serializers.IntegerField(help_text="The opponent's holdings counted.")


# Write-ups and share links (E2).


class HandShareSerializer(serializers.ModelSerializer):
    """A hand shared by a public, read-only link."""

    class Meta:
        model = HandShare
        fields = ("id", "hand", "slug", "write_up", "anonymize", "revoked", "created", "updated")
        read_only_fields = ("id", "slug", "created", "updated")
        extra_kwargs = {
            "hand": {"help_text": "The id of one of the user's hands."},
            "slug": {"help_text": "The link is the web app's /s/<slug>."},
            "anonymize": {
                "help_text": "Name players by position, the hero as Hero, and leave out the table and hand number."
            },
        }

    def validate_hand(self, hand):
        if hand.user_id != self.context["user"].pk:
            raise serializers.ValidationError("Not one of your hands.")
        return hand

    def validate_write_up(self, text):
        if len(text) > WRITEUP_LENGTH:
            raise serializers.ValidationError(f"At most {WRITEUP_LENGTH} characters.")
        return text


class PublicHandSerializer(HandDetailSerializer):
    """A shared hand as anyone with its link sees it: the replay without the owner's notes or opponents."""

    tournament = None
    opponents = None

    class Meta(HandDetailSerializer.Meta):
        fields = tuple(
            name for name in HandDetailSerializer.Meta.fields if name not in ("opponents", "tournament", "table")
        )
        read_only_fields = fields


class PublicShareSerializer(serializers.Serializer):
    slug = serializers.CharField()
    write_up = serializers.CharField(allow_blank=True)
    anonymized = serializers.BooleanField()
    created = serializers.DateTimeField()
    hand = PublicHandSerializer()

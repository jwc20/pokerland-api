from rest_framework import serializers

from hands.models import Hand
from leagues.models import Assignment, League, Membership
from practice.models import Playbook
from practice.serializers import BookRuleSerializer, FamilyStageSerializer, SkillScoreSerializer


class LeagueSerializer(serializers.ModelSerializer):
    """A class you're in."""

    role = serializers.ChoiceField(choices=list(Membership.ROLES), help_text="Your role in it.")
    owner_name = serializers.CharField(source="owner.username", help_text="Who made it.")
    member_count = serializers.IntegerField(help_text="Everyone in it, coaches included.")
    assignment_count = serializers.IntegerField(help_text="Playbooks and hands before it now.")

    class Meta:
        model = League
        fields = ("id", "name", "owner_name", "role", "member_count", "assignment_count", "created")
        read_only_fields = fields


class LeagueCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=League._meta.get_field("name").max_length)

    def validate_name(self, name):
        if not name.strip():
            raise serializers.ValidationError("A class needs a name.")
        return name.strip()


class JoinSerializer(serializers.Serializer):
    code = serializers.CharField(
        max_length=32, help_text="The class's invite code; spaces, dashes and case don't matter."
    )


class LeagueUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=League._meta.get_field("name").max_length, required=False)
    new_invite = serializers.BooleanField(
        required=False, help_text="A new invite code: the old one stops working. Nobody already in it is affected."
    )


class MemberSerializer(serializers.ModelSerializer):
    """Someone in a class. Coaches see everyone; a member sees the coaches."""

    name = serializers.CharField(source="user.username")
    you = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField(help_text="Made the class: always a coach, and can't leave it.")

    class Meta:
        model = Membership
        fields = ("id", "name", "role", "shares_progress", "joined", "you", "owner")
        read_only_fields = fields

    def get_you(self, member) -> bool:
        return member.user_id == self.context["request"].user.pk

    def get_owner(self, member) -> bool:
        return member.user_id == member.league.owner_id


class AssignedPlaybookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Playbook
        fields = ("id", "name", "version", "description")
        read_only_fields = fields


class AssignedHandSerializer(serializers.Serializer):
    """A shared hand as the class sees it: anonymized, so its stakes and when, but no names, table or number."""

    own_hand = serializers.SerializerMethodField(help_text="Your own hand's id, for its replay; null for others'.")
    game = serializers.CharField(source="share.hand.game")
    stakes = serializers.SerializerMethodField()
    played_at = serializers.DateTimeField(source="share.hand.played_at")
    write_up = serializers.CharField(source="share.write_up")

    def get_own_hand(self, assignment) -> int | None:
        share = assignment.share
        return share.hand_id if share.user_id == self.context["request"].user.pk else None

    def get_stakes(self, assignment) -> str:
        hand = assignment.share.hand
        unit = f"{hand.currency} " if hand.currency else ""
        return f"{unit}{hand.small_blind}/{hand.big_blind}".strip()


class AssignmentSerializer(serializers.ModelSerializer):
    """A playbook or hand before a class."""

    by_name = serializers.CharField(source="by.username", help_text="Who assigned or shared it.")
    playbook = AssignedPlaybookSerializer(allow_null=True)
    hand = serializers.SerializerMethodField()
    can_withdraw = serializers.SerializerMethodField(help_text="You put it there, or you're a coach.")

    class Meta:
        model = Assignment
        fields = ("id", "kind", "by_name", "playbook", "hand", "note", "created", "can_withdraw")
        read_only_fields = fields

    def get_hand(self, assignment) -> AssignedHandSerializer(allow_null=True):
        return AssignedHandSerializer(assignment, context=self.context).data if assignment.kind == "hand" else None

    def get_can_withdraw(self, assignment) -> bool:
        return assignment.by_id == self.context["request"].user.pk or self.context["role"] == "coach"


class LeagueDetailSerializer(serializers.ModelSerializer):
    """A class: its playbooks and hands, and who's in it. A coach also sees its invite code and every member."""

    role = serializers.ChoiceField(choices=list(Membership.ROLES), help_text="Your role in it.")
    owner_name = serializers.CharField(source="owner.username")
    invite_code = serializers.SerializerMethodField(help_text="Coaches only; null for a member.")
    shares_progress = serializers.BooleanField(help_text="You show the coaches your practice progress.")
    member_count = serializers.IntegerField()
    members = MemberSerializer(
        source="shown_members", many=True, help_text="Coaches see everyone; a member sees the coaches and themselves."
    )
    assignments = AssignmentSerializer(source="active_assignments", many=True)

    class Meta:
        model = League
        fields = (
            "id", "name", "owner_name", "role", "invite_code", "shares_progress", "member_count", "members",
            "assignments", "created",
        )  # fmt: skip
        read_only_fields = fields

    def get_invite_code(self, league) -> str | None:
        return league.invite_code if league.role == "coach" else None


class MembershipUpdateSerializer(serializers.Serializer):
    shares_progress = serializers.BooleanField(
        help_text="Show the class's coaches your practice accuracy, playbook stages and by-the-book rates. Never your "
        "hands."
    )


class RoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=list(Membership.ROLES))


class AssignmentRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=list(Assignment.KINDS))
    playbook = serializers.PrimaryKeyRelatedField(
        queryset=Playbook.objects.all(), required=False, help_text="A playbook of your own: coaches only."
    )
    hand = serializers.PrimaryKeyRelatedField(
        queryset=Hand.objects.all(),
        required=False,
        help_text="One of your hands, shared anonymized: by your live link to it if you have one, else a new one.",
    )
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        field = "playbook" if attrs["kind"] == "playbook" else "hand"
        if field not in attrs:
            raise serializers.ValidationError({field: f"A {attrs['kind']} assignment needs its {field}."})
        return attrs


class PlaybookProgressSerializer(serializers.Serializer):
    playbook = serializers.IntegerField()
    name = serializers.CharField()
    families = FamilyStageSerializer(many=True, help_text="Their stage in each of its rule families.")
    book = BookRuleSerializer(
        many=True, required=False, help_text="One member's: how often their own hands kept each of its rules."
    )


class MemberProgressSerializer(serializers.Serializer):
    """What a coach sees of a member who shares their progress: totals only, never their hands."""

    member = serializers.IntegerField(help_text="Their membership's id.")
    name = serializers.CharField()
    skills = SkillScoreSerializer(many=True)
    playbooks = PlaybookProgressSerializer(many=True)

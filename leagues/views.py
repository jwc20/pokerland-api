from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from leagues import classes
from leagues.models import Assignment, Membership
from leagues.serializers import (
    AssignmentRequestSerializer,
    AssignmentSerializer,
    JoinSerializer,
    LeagueCreateSerializer,
    LeagueDetailSerializer,
    LeagueSerializer,
    LeagueUpdateSerializer,
    MemberProgressSerializer,
    MemberSerializer,
    MembershipUpdateSerializer,
    RoleSerializer,
)


class ClassView(APIView):
    """A classes endpoint: 404 for everyone while classes aren't open (settings.CLASSES_ENABLED)."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not settings.CLASSES_ENABLED:
            raise NotFound("Classes aren't open yet.")


def member_of(request, pk, coach=False):
    """The signed-in user's membership of a class: 404 if they aren't in it, 403 if it takes a coach and they aren't
    one."""
    member = Membership.objects.filter(league_id=pk, user=request.user).select_related("league").first()
    if not member:
        raise Http404
    if coach and member.role != "coach":
        raise PermissionDenied("Only the class's coaches can do that.")
    return member


def refused(error):
    return ValidationError({"detail": str(error)})


def detail(request, member):
    league = member.league
    members = league.memberships.select_related("user", "league")
    league.role = member.role
    league.shares_progress = member.shares_progress
    league.member_count = members.count()
    league.shown_members = (
        members if member.role == "coach" else members.filter(role="coach") | members.filter(pk=member.pk)
    )
    league.active_assignments = classes.active(league)
    context = {"request": request, "role": member.role}
    return LeagueDetailSerializer(league, context=context).data


class LeagueListView(ClassView):
    """The classes the signed-in user is in; and a new one, which they own and coach."""

    @extend_schema(responses=LeagueSerializer(many=True))
    def get(self, request):
        leagues = list(classes.mine(request.user).select_related("owner"))
        roles = dict(Membership.objects.filter(user=request.user).values_list("league_id", "role"))
        for league in leagues:
            league.role = roles[league.pk]
        return Response(LeagueSerializer(leagues, many=True).data)

    @extend_schema(request=LeagueCreateSerializer, responses={status.HTTP_201_CREATED: LeagueDetailSerializer})
    def post(self, request):
        query = LeagueCreateSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        league = classes.create(request.user, query.validated_data["name"])
        return Response(detail(request, member_of(request, league.pk)), status=status.HTTP_201_CREATED)


class JoinView(ClassView):
    """Joins a class by its invite code, as a member. Joining one you're in already changes nothing."""

    @extend_schema(request=JoinSerializer, responses=LeagueDetailSerializer)
    def post(self, request):
        query = JoinSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        try:
            league = classes.join(request.user, query.validated_data["code"])
        except classes.ClassError as error:
            raise ValidationError({"code": str(error)}) from None
        return Response(detail(request, member_of(request, league.pk)))


class LeagueDetailView(ClassView):
    """A class: its playbooks and hands, and who's in it. A coach can rename it or give it a new invite code."""

    @extend_schema(responses=LeagueDetailSerializer)
    def get(self, request, pk):
        return Response(detail(request, member_of(request, pk)))

    @extend_schema(request=LeagueUpdateSerializer, responses=LeagueDetailSerializer)
    def patch(self, request, pk):
        member = member_of(request, pk, coach=True)
        query = LeagueUpdateSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        league = member.league
        if data.get("name", "").strip():
            league.name = data["name"].strip()
            league.save(update_fields=["name"])
        if data.get("new_invite"):
            classes.new_invite(league)
        return Response(detail(request, member))


class MyMembershipView(ClassView):
    """The signed-in user in a class: whether they show the coaches their progress; or leaving it."""

    @extend_schema(request=MembershipUpdateSerializer, responses=LeagueDetailSerializer)
    def patch(self, request, pk):
        member = member_of(request, pk)
        query = MembershipUpdateSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        member.shares_progress = query.validated_data["shares_progress"]
        member.save(update_fields=["shares_progress"])
        return Response(detail(request, member))

    @extend_schema(responses={status.HTTP_204_NO_CONTENT: None})
    def delete(self, request, pk):
        try:
            classes.leave(member_of(request, pk))
        except classes.ClassError as error:
            raise refused(error) from None
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberView(ClassView):
    """A coach makes someone in their class a coach or a member, or takes them out of it."""

    def member(self, request, pk, member_pk):
        member_of(request, pk, coach=True)
        return get_object_or_404(Membership.objects.select_related("league", "user"), pk=member_pk, league_id=pk)

    @extend_schema(request=RoleSerializer, responses=MemberSerializer)
    def patch(self, request, pk, member_pk):
        member = self.member(request, pk, member_pk)
        query = RoleSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        try:
            classes.set_role(member, query.validated_data["role"])
        except classes.ClassError as error:
            raise refused(error) from None
        return Response(MemberSerializer(member, context={"request": request}).data)

    @extend_schema(responses={status.HTTP_204_NO_CONTENT: None})
    def delete(self, request, pk, member_pk):
        member = self.member(request, pk, member_pk)
        try:
            classes.leave(member)
        except classes.ClassError as error:
            raise refused(error) from None
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssignmentListView(ClassView):
    """Puts something before a class: a coach assigns one of their playbooks; anyone shares one of their hands."""

    @extend_schema(request=AssignmentRequestSerializer, responses={status.HTTP_201_CREATED: AssignmentSerializer})
    def post(self, request, pk):
        member = member_of(request, pk)
        query = AssignmentRequestSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        try:
            if data["kind"] == "playbook":
                assignment = classes.assign_playbook(member, data["playbook"], data["note"])
            else:
                assignment = classes.share_hand(member, data["hand"], data["note"])
        except classes.ClassError as error:
            raise ValidationError({data["kind"]: str(error)}) from None
        context = {"request": request, "role": member.role}
        return Response(AssignmentSerializer(assignment, context=context).data, status=status.HTTP_201_CREATED)


class AssignmentDetailView(ClassView):
    """Withdraws something from a class: by whoever put it there, or a coach. A withdrawn hand leaves future sets."""

    @extend_schema(responses={status.HTTP_204_NO_CONTENT: None})
    def delete(self, request, pk, assignment_pk):
        member = member_of(request, pk)
        assignment = get_object_or_404(Assignment, pk=assignment_pk, league_id=pk, withdrawn=False)
        try:
            classes.withdraw(member, assignment)
        except classes.ClassError as error:
            raise PermissionDenied(str(error)) from None
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProgressView(ClassView):
    """For a class's coaches: each member who shares their progress, with their practice accuracy and their stage in
    each assigned playbook's rule families. Totals only, never their hands."""

    @extend_schema(responses=MemberProgressSerializer(many=True))
    def get(self, request, pk):
        member = member_of(request, pk, coach=True)
        return Response(MemberProgressSerializer(classes.progress(member.league), many=True).data)


class MemberProgressView(ClassView):
    """For a class's coaches: one sharing member's progress, with how their own hands kept each assigned playbook's
    rules (by the book), which reads up to a thousand of their hands."""

    @extend_schema(responses=MemberProgressSerializer)
    def get(self, request, pk, member_pk):
        member = member_of(request, pk, coach=True)
        found = get_object_or_404(classes.sharing(member.league), pk=member_pk)
        return Response(MemberProgressSerializer(classes.member_progress(found)).data)

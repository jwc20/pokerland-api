from django.contrib import admin

from leagues.models import Assignment, League, Membership


class MembershipInline(admin.TabularInline):
    model = Membership
    fields = ("user", "role", "shares_progress", "joined")
    readonly_fields = ("joined",)
    extra = 0


class AssignmentInline(admin.TabularInline):
    model = Assignment
    fields = ("kind", "by", "playbook", "share", "note", "withdrawn", "created")
    readonly_fields = ("created",)
    extra = 0


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "owner", "invite_code", "created")
    search_fields = ("name", "owner__username")
    inlines = (MembershipInline, AssignmentInline)

from django.contrib import admin

from practice.models import (
    Attempt,
    CoachedMatch,
    MatchDecision,
    Playbook,
    PracticeHand,
    ReadNote,
    Review,
    RuleProgress,
    Scenario,
    ScenarioSet,
    SetItem,
)


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "topic", "grading", "owner", "tier", "created")
    list_filter = ("source", "grading", "topic")
    search_fields = ("owner__username",)
    readonly_fields = ("owner", "hand", "step", "spec", "answer", "origin")


class SetItemInline(admin.TabularInline):
    model = SetItem
    fields = ("position", "scenario", "review")
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(ScenarioSet)
class ScenarioSetAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "kind", "day", "created", "finished")
    list_filter = ("kind",)
    search_fields = ("user__username",)
    inlines = (SetItemInline,)


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "scenario", "grade", "score", "weight", "rule", "created")
    list_filter = ("grade",)
    search_fields = ("user__username",)
    readonly_fields = ("user", "scenario", "set")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("user", "scenario", "box", "due")
    search_fields = ("user__username",)


@admin.register(Playbook)
class PlaybookAdmin(admin.ModelAdmin):
    """A version's cards are kept as they were: change the code's preset and raise its version instead."""

    list_display = ("name", "key", "version", "owner", "created")
    readonly_fields = ("rules",)


@admin.register(RuleProgress)
class RuleProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "playbook_key", "family", "stage", "updated")
    list_filter = ("family", "stage")
    search_fields = ("user__username",)


class MatchDecisionInline(admin.TabularInline):
    model = MatchDecision
    fields = ("hand", "step", "stage", "followed", "asked", "departure", "reason")
    readonly_fields = fields
    extra = 0
    can_delete = False


class ReadNoteInline(admin.TabularInline):
    model = ReadNote
    fields = ("hand_number", "kind", "tag", "by", "withdrawn", "replaced_by")
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(CoachedMatch)
class CoachedMatchAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "opponent", "coach", "result_bb", "started", "finished")
    list_filter = ("opponent", "coach")
    search_fields = ("user__username",)
    readonly_fields = ("table", "playbook")
    inlines = (MatchDecisionInline, ReadNoteInline)


@admin.register(PracticeHand)
class PracticeHandAdmin(admin.ModelAdmin):
    list_display = ("table", "number", "small_blind", "big_blind", "finished")
    readonly_fields = ("table", "deck", "moves", "replay", "phh")

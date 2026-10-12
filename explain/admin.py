from django.contrib import admin

from explain.models import Explanation, ExplanationTurn


class TurnInline(admin.TabularInline):
    model = ExplanationTurn
    fields = ("question", "answer", "provider", "model", "cost", "created")
    readonly_fields = fields
    extra = 0


@admin.register(Explanation)
class ExplanationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "kind", "provider", "model", "cost", "useful", "created")
    list_filter = ("kind", "provider", "useful")
    search_fields = ("user__username",)
    readonly_fields = (
        "user", "kind", "hand", "attempt", "decision", "debrief", "test", "session", "period_start", "period_end",
        "prompt_version", "brief_hash", "provider", "model", "effort", "content", "usage", "cost", "request_id",
    )
    inlines = [TurnInline]

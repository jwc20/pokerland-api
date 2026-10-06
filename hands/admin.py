from django.contrib import admin

from hands.models import Hand


@admin.register(Hand)
class HandAdmin(admin.ModelAdmin):
    list_display = ("hand_id", "played_at", "user", "hero", "game", "table", "hero_position", "hero_net")
    list_filter = ("site", "play_money", "game")
    search_fields = ("hand_id", "hero", "table", "user__username")
    readonly_fields = ("user", "stream")
    date_hierarchy = "played_at"

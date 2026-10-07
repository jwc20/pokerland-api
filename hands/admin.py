from django.contrib import admin

from hands.models import Hand, HandPlayer


class HandPlayerInline(admin.TabularInline):
    """Each player's facts, as the parser saw them; a reparse rewrites them."""

    model = HandPlayer
    fields = ("seat", "name", "position", "is_hero", "situation", "first_action", "vpip_did", "pfr_did", "net_bb")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Hand)
class HandAdmin(admin.ModelAdmin):
    list_display = ("hand_id", "played_at", "user", "hero", "game", "table", "hero_position", "hero_net")
    list_filter = ("site", "play_money", "game")
    search_fields = ("hand_id", "hero", "table", "user__username")
    readonly_fields = ("user", "stream")
    date_hierarchy = "played_at"
    inlines = (HandPlayerInline,)

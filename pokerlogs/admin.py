from django.contrib import admin

from .models import ErrorLog, GameLog


@admin.register(GameLog)
class GameLogAdmin(admin.ModelAdmin):
    list_display = ["id", "client", "client_version", "submitted_at", "created_at"]
    list_filter = ["client"]
    readonly_fields = ["id", "payload", "created_at"]


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = ["id", "client", "client_version", "submitted_at", "created_at"]
    list_filter = ["client"]
    readonly_fields = ["id", "payload", "created_at"]

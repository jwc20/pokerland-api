from django.contrib import admin

from tracker.models import LogChunk, LogStream


class LogChunkInline(admin.TabularInline):
    model = LogChunk
    fields = ("start_offset", "end_offset", "compressed_size", "status", "received_at", "parsed_at", "error")
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(LogStream)
class LogStreamAdmin(admin.ModelAdmin):
    list_display = ("path_hint", "user", "platform", "client_version", "acked_offset", "parsed_offset", "last_chunk_at")
    list_filter = ("platform", "source")
    search_fields = ("path_hint", "user__username", "stream_id")
    readonly_fields = ("stream_id", "fingerprint", "acked_offset", "parsed_offset", "parser_state", "parser_version")
    inlines = [LogChunkInline]


@admin.register(LogChunk)
class LogChunkAdmin(admin.ModelAdmin):
    list_display = ("stream", "start_offset", "end_offset", "status", "received_at", "parsed_at")
    list_filter = ("status",)
    readonly_fields = ("stream", "start_offset", "end_offset", "sha256", "compressed_size", "storage_key")

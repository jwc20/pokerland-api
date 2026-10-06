from django.core.management.base import BaseCommand

from tracker.models import LogChunk, LogStream
from tracker.tasks import drain, reparse


class Command(BaseCommand):
    help = "Parse waiting chunks synchronously; with --reparse, rewind the streams and parse everything again."

    def add_arguments(self, parser):
        parser.add_argument("stream_ids", nargs="*", help="stream UUIDs; default: every stream with waiting chunks")
        parser.add_argument(
            "--reparse", action="store_true", help="rewind to byte zero first (e.g. after a parser fix)"
        )
        parser.add_argument(
            "--all", action="store_true", help="with --reparse: every stream, not only those with waiting chunks"
        )

    def handle(self, *args, **options):
        streams = LogStream.objects.all()
        if options["stream_ids"]:
            streams = streams.filter(stream_id__in=options["stream_ids"])
        elif not (options["reparse"] and options["all"]):
            streams = streams.filter(chunks__status=LogChunk.Status.RECEIVED).distinct()

        for stream in streams:
            if options["reparse"]:
                reparse(stream.pk)
            drain(stream.pk)
            stream.refresh_from_db()
            self.stdout.write(f"{stream}: parsed to {stream.parsed_offset} of {stream.acked_offset}")

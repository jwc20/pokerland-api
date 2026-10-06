"""Parsing runs outside the upload request, as a Zappa async task.

Locally (no AWS_LAMBDA_FUNCTION_NAME) `@task` runs the function inline, so a
dev server parses each chunk as it arrives.
"""

import gzip
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from zappa.asynchronous import task

from tracker import parsing
from tracker.models import LogChunk, LogStream
from tracker.storage import raw_storage

logger = logging.getLogger(__name__)


@task
def process_stream(stream_pk):
    drain(stream_pk)


def drain(stream_pk):
    """Parses every chunk that continues from the stream's parsed offset, in order.

    The stream row is locked while a chunk is parsed, so concurrent invocations
    (two uploads, or an upload and the sweeper) queue up instead of parsing the
    same chunk twice. A failed chunk stops the drain: skipping it would corrupt
    the parser state for everything after it.
    """
    while True:
        with transaction.atomic():
            stream = LogStream.objects.select_for_update().get(pk=stream_pk)
            chunk = stream.chunks.filter(start_offset=stream.parsed_offset, status=LogChunk.Status.RECEIVED).first()
            if chunk is None:
                return
            try:
                data = gzip.decompress(raw_storage().get(chunk.storage_key))
                state = parsing.parse(data, stream.parser_state)
            except Exception as error:
                logger.exception("Parsing chunk %s failed", chunk)
                chunk.status = LogChunk.Status.FAILED
                chunk.error = f"{type(error).__name__}: {error}"[:2000]
                chunk.save(update_fields=["status", "error"])
                return
            stream.parser_state = state
            stream.parsed_offset = chunk.end_offset
            stream.parser_version = parsing.PARSER_VERSION
            stream.save(update_fields=["parser_state", "parsed_offset", "parser_version", "updated"])
            chunk.status = LogChunk.Status.PARSED
            chunk.parsed_at = timezone.now()
            chunk.save(update_fields=["status", "parsed_at"])


def reparse(stream_pk):
    """Rewinds a stream so the next drain parses it again from byte zero."""
    with transaction.atomic():
        stream = LogStream.objects.select_for_update().get(pk=stream_pk)
        stream.parsed_offset = 0
        stream.parser_state = {}
        stream.save(update_fields=["parsed_offset", "parser_state", "updated"])
        stream.chunks.update(status=LogChunk.Status.RECEIVED, error="", parsed_at=None)


def stale_stream_pks(now=None):
    """Streams with chunks that have waited longer than a lost async invocation should take."""
    cutoff = (now or timezone.now()) - timedelta(seconds=settings.TRACKER["STALE_CHUNK_SECONDS"])
    chunks = LogChunk.objects.filter(status=LogChunk.Status.RECEIVED, received_at__lt=cutoff)
    return list(chunks.values_list("stream_id", flat=True).distinct())


def sweep_stale_streams(event=None, context=None):
    """Re-triggers parsing for streams whose async invocation was lost.

    Zappa runs this on the schedule in zappa_settings.json (`events`), passing
    the Lambda event and context.
    """
    pks = stale_stream_pks()
    for pk in pks:
        process_stream(pk)
    return {"streams": len(pks)}

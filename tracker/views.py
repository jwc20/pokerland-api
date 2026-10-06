import hashlib
import zlib

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Sum
from django.db.models.fields import IntegerField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, ParseError, ValidationError
from rest_framework.parsers import BaseParser
from rest_framework.response import Response
from rest_framework.views import APIView

from tracker import versions
from tracker.authentication import ClientTokenAuthentication
from tracker.models import LogChunk, LogStream
from tracker.serializers import (
    ChunkAckSerializer,
    ChunkRejectedSerializer,
    ConfigSerializer,
    MeSerializer,
    StreamAckSerializer,
    StreamRegistrationSerializer,
    TrackerStatusSerializer,
)
from tracker.storage import chunk_key, raw_storage
from tracker.tasks import process_stream


class UpgradeRequired(APIException):
    status_code = status.HTTP_426_UPGRADE_REQUIRED
    default_detail = "This tracker version is no longer supported. Please update."


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Conflict."


class PayloadTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = "Chunk too large."


def client_config():
    config = settings.TRACKER
    return {
        "min_version": config["MIN_CLIENT_VERSION"],
        "poll_interval_seconds": config["POLL_INTERVAL_SECONDS"],
        "flush_interval_seconds": config["FLUSH_INTERVAL_SECONDS"],
        "flush_bytes": config["FLUSH_BYTES"],
        "max_read_bytes": config["MAX_READ_BYTES"],
        "max_chunk_bytes": config["MAX_CHUNK_BYTES"],
    }


class TrackerView(APIView):
    """Base for the endpoints the trackers call: client-token auth, then a version gate."""

    authentication_classes = [ClientTokenAuthentication]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)  # 401 comes before 426
        if not versions.is_supported(versions.tracker_version(request), settings.TRACKER["MIN_CLIENT_VERSION"]):
            raise UpgradeRequired(
                {"detail": UpgradeRequired.default_detail, "min_version": settings.TRACKER["MIN_CLIENT_VERSION"]}
            )


class MeView(TrackerView):
    """Checks the client token and names its user."""

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response({"username": request.user.get_username()})


class ConfigView(TrackerView):
    """Tunables the trackers fetch at startup and every few hours."""

    @extend_schema(responses=ConfigSerializer)
    def get(self, request):
        return Response(client_config())


class StreamView(TrackerView):
    """Registers a hand-history file, or tells a tracker where it left off."""

    @extend_schema(request=StreamRegistrationSerializer, responses={200: StreamAckSerializer, 201: StreamAckSerializer})
    def put(self, request, stream_id):
        serializer = StreamRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = serializer.validated_data
        with transaction.atomic():
            stream, created = LogStream.objects.select_for_update().get_or_create(
                user=request.user, stream_id=stream_id, defaults=fields
            )
            if not created:
                if stream.fingerprint != fields["fingerprint"]:
                    raise Conflict("Stream id is registered with a different fingerprint.")
                for name in ("platform", "client_version", "path_hint"):
                    setattr(stream, name, fields[name])
                stream.save(update_fields=["platform", "client_version", "path_hint", "updated"])
        data = {"stream_id": stream.stream_id, "acked_offset": stream.acked_offset}
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class GzipParser(BaseParser):
    """Hands the gzipped request body to the view as bytes."""

    media_type = "application/gzip"

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read()


def gunzip_limited(data, max_size):
    """Decompresses `data`, refusing output beyond `max_size` (a decompression bomb)."""
    decompressor = zlib.decompressobj(wbits=31)  # 31: expect a gzip header
    try:
        output = decompressor.decompress(data, max_size)
    except zlib.error:
        raise ParseError("Body is not valid gzip.") from None
    if decompressor.unconsumed_tail or not decompressor.eof:
        raise PayloadTooLarge(f"Uncompressed chunk exceeds {max_size} bytes or is truncated.")
    return output


class ChunkView(TrackerView):
    """Stores bytes [start, end) of a stream and queues them for parsing."""

    parser_classes = [GzipParser]

    @extend_schema(
        request={"application/gzip": OpenApiTypes.BINARY},
        parameters=[
            OpenApiParameter("X-Chunk-End", OpenApiTypes.INT, OpenApiParameter.HEADER, required=True),
            OpenApiParameter("X-Chunk-Sha256", OpenApiTypes.STR, OpenApiParameter.HEADER, required=True),
        ],
        responses={
            200: ChunkAckSerializer,
            202: ChunkAckSerializer,
            409: ChunkRejectedSerializer,
        },
    )
    def put(self, request, stream_id, start):
        config = settings.TRACKER
        if int(request.headers.get("Content-Length") or 0) > config["MAX_CHUNK_BYTES"]:
            raise PayloadTooLarge(f"Compressed chunk exceeds {config['MAX_CHUNK_BYTES']} bytes.")
        try:
            end = int(request.headers["X-Chunk-End"])
            sha256 = request.headers["X-Chunk-Sha256"].lower()
        except KeyError, ValueError:
            raise ValidationError({"detail": "X-Chunk-End and X-Chunk-Sha256 headers are required."}) from None
        if end <= start:
            raise ValidationError({"detail": "X-Chunk-End must be greater than the start offset."})

        compressed = request.data
        if not isinstance(compressed, bytes) or not compressed:
            raise ParseError("Expected a gzipped body with Content-Type: application/gzip.")
        data = gunzip_limited(compressed, config["MAX_UNCOMPRESSED_BYTES"])
        if len(data) != end - start:
            raise ValidationError({"detail": f"Uncompressed length {len(data)} does not match the offsets."})
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValidationError({"detail": "X-Chunk-Sha256 does not match the uncompressed bytes."})
        if not data.endswith(b"\n"):
            raise ValidationError({"detail": "A chunk must end at a newline."})

        with transaction.atomic():
            try:
                stream = LogStream.objects.select_for_update().get(user=request.user, stream_id=stream_id)
            except LogStream.DoesNotExist:
                raise NotFound("Unknown stream; register it first.") from None
            if start != stream.acked_offset:
                # A retry of a chunk the server already has is fine; anything else is a gap or overlap.
                if stream.chunks.filter(start_offset=start, end_offset=end, sha256=sha256).exists():
                    return Response({"acked_offset": stream.acked_offset})
                return Response(
                    {"detail": f"Expected offset {stream.acked_offset}.", "acked_offset": stream.acked_offset},
                    status=status.HTTP_409_CONFLICT,
                )
            key = chunk_key(stream, start, end)
            raw_storage().put(key, compressed)
            LogChunk.objects.create(
                stream=stream,
                start_offset=start,
                end_offset=end,
                sha256=sha256,
                compressed_size=len(compressed),
                storage_key=key,
            )
            stream.acked_offset = end
            stream.last_chunk_at = timezone.now()
            stream.save(update_fields=["acked_offset", "last_chunk_at", "updated"])
            transaction.on_commit(lambda: process_stream(stream.pk))
        return Response({"acked_offset": end}, status=status.HTTP_202_ACCEPTED)


class TrackerStatusView(APIView):
    """What the signed-in user's trackers have uploaded, for the web app (JWT auth)."""

    @extend_schema(responses=TrackerStatusSerializer)
    def get(self, request):
        streams = LogStream.objects.filter(user=request.user)
        totals = streams.aggregate(
            last_upload_at=Max("last_chunk_at"),
            hands_seen=Sum(Cast(KeyTextTransform("hands_seen", "parser_state"), IntegerField())),
        )
        return Response(
            {
                "last_upload_at": totals["last_upload_at"],
                "file_count": streams.count(),
                "hands_seen": totals["hands_seen"] or 0,
                "platforms": sorted(set(streams.values_list("platform", flat=True))),
                "client_versions": sorted(set(streams.values_list("client_version", flat=True))),
            }
        )

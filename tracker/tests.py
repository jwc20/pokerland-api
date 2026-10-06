import gzip
import hashlib
import tempfile
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from hands.models import Hand
from pokerlandapi.tests import register
from tracker import parsing, tasks
from tracker.models import LogChunk, LogStream
from tracker.tests_support import HAND, STREAM_ID, UA, register_stream, upload

User = get_user_model()


class TrackerTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.client = APIClient(HTTP_AUTHORIZATION=f"Token {self.user.client_token.key}", HTTP_USER_AGENT=UA)
        self.raw_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.raw_dir.cleanup)
        patched = {**self._tracker_settings(), "RAW_LOCAL_DIR": self.raw_dir.name}
        overrides = override_settings(TRACKER=patched)
        overrides.enable()
        self.addCleanup(overrides.disable)

    def upload(self, start, data, **kwargs):
        """Uploads and parses: on_commit hooks do not fire inside a test transaction on their own."""
        with self.captureOnCommitCallbacks(execute=True):
            return upload(self.client, start, data, **kwargs)

    @staticmethod
    def _tracker_settings():
        from django.conf import settings

        return dict(settings.TRACKER)


class AuthTests(TrackerTests):
    def test_me_names_the_token_owner(self):
        response = self.client.get("/api/tracker/me/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"username": "alice"})

    def test_an_unknown_token_is_rejected(self):
        client = APIClient(HTTP_AUTHORIZATION="Token 0123456789abcdef0123456789abcdef", HTTP_USER_AGENT=UA)

        response = client.get("/api/tracker/me/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "Token")

    def test_jwt_cookies_do_not_authenticate_tracker_endpoints(self):
        client = APIClient(HTTP_USER_AGENT=UA)
        self.assertEqual(register(client, "carol").status_code, 201)  # signed in, with the JWT cookies

        self.assertEqual(client.get("/api/tracker/me/").status_code, 401)

    def test_an_old_tracker_must_upgrade(self):
        client = APIClient(
            HTTP_AUTHORIZATION=f"Token {self.user.client_token.key}",
            HTTP_USER_AGENT="pokerland-tracker/0.0.1 (macos; arm64)",
        )

        response = client.get("/api/tracker/me/")

        self.assertEqual(response.status_code, 426)
        self.assertEqual(response.data["min_version"], "0.1.0")

    def test_a_missing_user_agent_must_upgrade_too(self):
        client = APIClient(HTTP_AUTHORIZATION=f"Token {self.user.client_token.key}")

        self.assertEqual(client.get("/api/tracker/me/").status_code, 426)

    def test_a_bad_token_is_reported_before_the_version(self):
        client = APIClient(HTTP_AUTHORIZATION="Token nope")

        self.assertEqual(client.get("/api/tracker/me/").status_code, 401)

    def test_config_lists_the_tunables(self):
        response = self.client.get("/api/tracker/config/")

        self.assertEqual(response.data["min_version"], "0.1.0")
        self.assertEqual(response.data["max_chunk_bytes"], 4 * 1024 * 1024)


class StreamTests(TrackerTests):
    def test_registering_a_new_file_starts_at_zero(self):
        response = register_stream(self.client)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, {"stream_id": uuid.UUID(STREAM_ID), "acked_offset": 0})
        self.assertEqual(LogStream.objects.get().path_hint, "Alice/HH20260521 Gertrud VIII.txt")

    def test_registering_again_reports_where_the_tracker_left_off(self):
        register_stream(self.client)
        self.upload(0, HAND)

        response = register_stream(self.client, client_version="0.2.0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["acked_offset"], len(HAND))
        self.assertEqual(LogStream.objects.get().client_version, "0.2.0")

    def test_the_same_id_with_another_fingerprint_is_a_conflict(self):
        register_stream(self.client)

        response = register_stream(self.client, fingerprint="f" * 64)

        self.assertEqual(response.status_code, 409)

    def test_streams_are_per_user(self):
        register_stream(self.client)
        bob = User.objects.create_user("bob")
        client = APIClient(HTTP_AUTHORIZATION=f"Token {bob.client_token.key}", HTTP_USER_AGENT=UA)

        self.assertEqual(register_stream(client).status_code, 201)
        self.assertEqual(LogStream.objects.count(), 2)

    def test_registration_is_validated(self):
        response = register_stream(self.client, fingerprint="not hex")

        self.assertEqual(response.status_code, 400)


class ChunkTests(TrackerTests):
    def setUp(self):
        super().setUp()
        register_stream(self.client)

    def test_consecutive_chunks_are_stored_and_parsed(self):
        first = self.upload(0, HAND)
        second = self.upload(len(HAND), HAND)

        self.assertEqual((first.status_code, first.data), (202, {"acked_offset": len(HAND)}))
        self.assertEqual((second.status_code, second.data), (202, {"acked_offset": 2 * len(HAND)}))
        stream = LogStream.objects.get()
        self.assertEqual(stream.acked_offset, 2 * len(HAND))
        self.assertEqual(stream.parsed_offset, 2 * len(HAND))  # @task runs inline outside Lambda
        self.assertEqual(stream.parser_state["hands_seen"], 2)
        self.assertEqual(list(stream.chunks.values_list("status", flat=True)), ["parsed", "parsed"])
        self.assertIsNotNone(stream.last_chunk_at)

    def test_the_raw_gzip_is_kept(self):
        upload(self.client, 0, HAND)

        chunk = LogChunk.objects.get()
        with open(f"{self.raw_dir.name}/{chunk.storage_key}", "rb") as raw:
            self.assertEqual(gzip.decompress(raw.read()), HAND)

    def test_a_retry_of_a_stored_chunk_is_acknowledged_again(self):
        upload(self.client, 0, HAND)

        response = upload(self.client, 0, HAND)

        self.assertEqual((response.status_code, response.data), (200, {"acked_offset": len(HAND)}))
        self.assertEqual(LogChunk.objects.count(), 1)

    def test_a_gap_tells_the_tracker_the_expected_offset(self):
        upload(self.client, 0, HAND)

        response = upload(self.client, len(HAND) + 10, HAND)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["acked_offset"], len(HAND))

    def test_an_overlap_with_different_bytes_is_a_conflict(self):
        upload(self.client, 0, HAND)

        response = upload(self.client, 0, HAND.replace(b"Gertrud", b"Thernoe"))

        self.assertEqual(response.status_code, 409)

    def test_corrupt_chunks_are_rejected(self):
        bad_hash = upload(self.client, 0, HAND, sha256="0" * 64)
        bad_length = upload(self.client, 0, HAND, end=len(HAND) + 1)
        no_newline = upload(self.client, 0, HAND.rstrip(b"\n"))
        not_gzip = upload(self.client, 0, HAND, body=b"plain")

        self.assertEqual([r.status_code for r in (bad_hash, bad_length, no_newline, not_gzip)], [400, 400, 400, 400])
        self.assertEqual(LogStream.objects.get().acked_offset, 0)

    def test_oversized_chunks_are_refused(self):
        with self.settings(TRACKER={**self._tracker_settings(), "MAX_CHUNK_BYTES": 10}):
            too_big = upload(self.client, 0, HAND)
        bomb = upload(self.client, 0, b"\n" * (100 * 1024 * 1024))

        self.assertEqual(too_big.status_code, 413)
        self.assertEqual(bomb.status_code, 413)

    def test_an_unregistered_stream_is_not_found(self):
        response = upload(self.client, 0, HAND, stream_id=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 404)

    def test_the_wrong_content_type_is_unsupported(self):
        response = self.client.put(
            f"/api/tracker/streams/{STREAM_ID}/chunks/0/",
            HAND,
            content_type="text/plain",
            HTTP_X_CHUNK_END=len(HAND),
            HTTP_X_CHUNK_SHA256=hashlib.sha256(HAND).hexdigest(),
        )

        self.assertEqual(response.status_code, 415)


class DrainTests(TrackerTests):
    def setUp(self):
        super().setUp()
        register_stream(self.client)
        self.stream = LogStream.objects.get()

    def upload_without_parsing(self, start, data):
        with mock.patch("tracker.views.process_stream"):
            upload(self.client, start, data)

    def test_chunks_are_parsed_in_order_with_state_carried_over(self):
        self.upload_without_parsing(0, HAND)
        self.upload_without_parsing(len(HAND), HAND)
        self.upload_without_parsing(2 * len(HAND), HAND)

        tasks.drain(self.stream.pk)

        self.stream.refresh_from_db()
        self.assertEqual(self.stream.parsed_offset, 3 * len(HAND))
        self.assertEqual(
            self.stream.parser_state,
            {"hands_seen": 3, "hands_failed": 0, "bytes_seen": 3 * len(HAND), "partial": ""},
        )
        self.assertEqual(self.stream.parser_version, parsing.PARSER_VERSION)

    def test_parsed_hands_are_saved_for_the_streams_user(self):
        self.upload_without_parsing(0, HAND)

        tasks.drain(self.stream.pk)

        hand = Hand.objects.get()
        self.assertEqual((hand.user, hand.stream, hand.hand_id), (self.user, self.stream, "260883422541"))

    def test_a_hand_split_across_chunks_is_saved_once_it_is_complete(self):
        cut = HAND.index(b"*** SUMMARY ***")
        self.upload(0, HAND[:cut])
        self.assertFalse(Hand.objects.exists())

        self.upload(cut, HAND[cut:])

        self.assertEqual(Hand.objects.count(), 1)

    def test_reparsing_updates_hands_in_place(self):
        self.upload(0, HAND)
        hand = Hand.objects.get()

        tasks.reparse(self.stream.pk)
        tasks.drain(self.stream.pk)

        self.assertEqual(Hand.objects.get().pk, hand.pk)  # replay links stay valid

    def test_a_failed_save_marks_the_chunk_failed(self):
        self.upload_without_parsing(0, HAND)

        with mock.patch("tracker.tasks.store_hands", side_effect=IntegrityError("boom")):
            tasks.drain(self.stream.pk)

        self.assertEqual(list(self.stream.chunks.values_list("status", "error")), [("failed", "IntegrityError: boom")])
        self.assertFalse(Hand.objects.exists())

    def test_a_parser_crash_marks_the_chunk_failed_and_stops(self):
        self.upload_without_parsing(0, HAND)
        self.upload_without_parsing(len(HAND), HAND)

        with mock.patch("tracker.parsing.parse", side_effect=KeyError("boom")):
            tasks.drain(self.stream.pk)

        statuses = list(self.stream.chunks.values_list("status", "error"))
        self.assertEqual(statuses, [("failed", "KeyError: 'boom'"), ("received", "")])
        self.stream.refresh_from_db()
        self.assertEqual(self.stream.parsed_offset, 0)

    def test_reparse_rewinds_and_parses_everything_again(self):
        self.upload(0, HAND)
        self.upload(len(HAND), HAND)

        tasks.reparse(self.stream.pk)
        self.stream.refresh_from_db()
        self.assertEqual((self.stream.parsed_offset, self.stream.parser_state), (0, {}))
        tasks.drain(self.stream.pk)

        self.stream.refresh_from_db()
        self.assertEqual(self.stream.parser_state["hands_seen"], 2)

    def test_the_sweeper_only_retriggers_streams_with_old_waiting_chunks(self):
        self.upload_without_parsing(0, HAND)
        self.assertEqual(tasks.stale_stream_pks(), [])  # just arrived: its own invocation is still coming

        LogChunk.objects.update(received_at=timezone.now() - timedelta(minutes=10))
        with mock.patch("tracker.tasks.process_stream") as process:
            result = tasks.sweep_stale_streams()

        process.assert_called_once_with(self.stream.pk)
        self.assertEqual(result, {"streams": 1})


class StatusTests(TrackerTests):
    def test_the_web_app_sees_what_the_trackers_uploaded(self):
        register_stream(self.client)
        self.upload(0, HAND)
        web = APIClient()
        web.force_authenticate(self.user)

        response = web.get("/api/tracker/status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["file_count"], 1)
        self.assertEqual(response.data["hands_seen"], 1)
        self.assertEqual(response.data["platforms"], ["macos"])
        self.assertEqual(response.data["client_versions"], ["0.1.0"])
        self.assertIsNotNone(response.data["last_upload_at"])

    def test_status_without_uploads_is_empty(self):
        web = APIClient()
        web.force_authenticate(self.user)

        response = web.get("/api/tracker/status/")

        self.assertEqual(
            response.data,
            {"last_upload_at": None, "file_count": 0, "hands_seen": 0, "platforms": [], "client_versions": []},
        )

    def test_status_is_not_for_client_tokens(self):
        self.assertEqual(self.client.get("/api/tracker/status/").status_code, 401)

    def test_status_matches_the_schema(self):
        from pokerlandapi.tests import SchemaTests

        web = APIClient()
        web.force_authenticate(self.user)
        SchemaTests.assertResponseMatchesSchema(self, web.get("/api/tracker/status/"))

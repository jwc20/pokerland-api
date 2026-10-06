# pokerland-api

Django REST API on AWS Lambda (Zappa) behind pokerland-client and the desktop
trackers from [pokerland-trackers](https://github.com/jwc20/pokerland-trackers).

```bash
cp .env.example .env            # fill in DJANGO_SECRET_KEY etc.
uv run python manage.py migrate
uv run python manage.py runserver
uv run python manage.py test
```

Swagger UI: http://localhost:8000/api/docs/ (not served in prod).

## Apps

- `users`: each user has a `ClientToken` the trackers authenticate with
  (`GET /api/users/me/client-token/` shows it to the signed-in user).
- `tracker`: hand-history uploads. The trackers register each PokerStars
  hand-history file as a stream and `PUT` gzipped byte ranges of it;
  `tracker.views.ChunkView` stores the raw chunk (S3, or `var/raw/` locally) and
  queues `tracker.tasks.process_stream`, a Zappa async task that parses chunks
  in order while carrying parser state across them. The web app reads
  `GET /api/tracker/status/`. The wire protocol is documented in
  pokerland-trackers' `protocol/PROTOCOL.md`.

### Tracker operations

- `TRACKER_MIN_CLIENT_VERSION`: trackers below it get 426 and must update.
- `TRACKER_RAW_BUCKET`: private S3 bucket for the raw chunks (required on
  Lambda; Zappa's default execution role can write to S3). Add a lifecycle rule
  to move objects to a colder tier after ~60 days.
- `zappa_settings.json` schedules `tracker.tasks.sweep_stale_streams` every
  five minutes; it re-queues chunks whose async invocation was lost.
- `manage.py tracker_drain [--reparse [--all]] [stream ids]` parses waiting
  chunks synchronously, or re-parses streams from byte zero after a parser
  change. Raise `tracker.parsing.PARSER_VERSION` when the parser's output
  changes.
- `tracker.parsing` is a placeholder that counts hands; the real parser keeps
  its `parse(data, state) -> state` contract.

## Deploying

`uv run python scripts/deploy.py dev|prod` validates `zappa_settings.json` and
`.env.<stage>`, uploads the environment to S3, runs `zappa deploy`/`update` and
migrates. See the script's docstring.

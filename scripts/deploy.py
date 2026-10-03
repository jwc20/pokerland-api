"""Deploy a Zappa stage: validate the config, upload .env.<stage>, deploy or update, migrate.

Usage:
    uv run python scripts/deploy.py dev
    uv run python scripts/deploy.py prod
    uv run python scripts/deploy.py dev --dry-run        # validate only, change nothing in AWS
    uv run python scripts/deploy.py dev --skip-migrate

Each run:
    1. Merges the stage over its `extends` chain the way Zappa does and stops on any
       leftover [placeholder], a missing django_settings or remote_env, or a local
       Python version that differs from `runtime`.
    2. Checks .env.<stage> against .env.example: every variable must have a value,
       except those the stage's environment_variables already set, which must not
       appear in the file.
    3. Uploads .env.<stage> as JSON to the stage's remote_env S3 URL (creating the
       bucket if needed). Zappa loads it into the Lambda environment at cold start.
    4. Runs `zappa deploy` the first time (plus `zappa certify` when the stage has a
       domain), `zappa update` afterwards, then `zappa manage <stage> migrate`.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import boto3
import slugify
from botocore.exceptions import ClientError
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = ROOT / "zappa_settings.json"
ENV_EXAMPLE = ROOT / ".env.example"
PLACEHOLDER = re.compile(r"\[[^\]]+\]")
NOT_DEPLOYABLE = {"base", "local"}


def fail(message):
    sys.exit(f"deploy: {message}")


def resolve_stage(all_settings, stage, seen=()):
    """Shallow-merge a stage over its `extends` chain, as Zappa does."""
    if stage in seen:
        fail(f"circular extends: {' -> '.join((*seen, stage))}")
    if stage not in all_settings:
        fail(f"stage '{stage}' is not in {SETTINGS_FILE.name}")
    settings = dict(all_settings[stage])
    parent = settings.pop("extends", None)
    if parent:
        return {**resolve_stage(all_settings, parent, (*seen, stage)), **settings}
    return settings


def find_placeholders(value, path):
    if isinstance(value, dict):
        hits = []
        for key, item in value.items():
            if PLACEHOLDER.search(key):
                hits.append(f"{path}.{key}")
            hits += find_placeholders(item, f"{path}.{key}")
        return hits
    if isinstance(value, list):
        return [hit for i, item in enumerate(value) for hit in find_placeholders(item, f"{path}[{i}]")]
    if isinstance(value, str) and PLACEHOLDER.search(value):
        return [f"{path} = {value}"]
    return []


def check_settings(stage, settings):
    placeholders = find_placeholders(settings, stage)
    if placeholders:
        fail(f"replace the placeholders in {SETTINGS_FILE.name}:\n  " + "\n  ".join(placeholders))
    if not settings.get("django_settings"):
        fail(f"stage '{stage}' has no django_settings; it would deploy a Lambda with no app")
    if not settings.get("remote_env", "").startswith("s3://"):
        fail(f"stage '{stage}' needs a remote_env S3 URL for its environment variables")
    local_runtime = f"python{sys.version_info.major}.{sys.version_info.minor}"
    if settings.get("runtime") != local_runtime:
        fail(f"runtime is {settings.get('runtime')} but this virtualenv is {local_runtime}")


def load_stage_env(stage, stage_variables):
    env_file = ROOT / f".env.{stage}"
    if not env_file.exists():
        fail(f"{env_file.name} not found; create it from {ENV_EXAMPLE.name}")
    values = dotenv_values(env_file)

    overlap = sorted(set(values) & set(stage_variables))
    if overlap:
        fail(
            f"{env_file.name} sets {', '.join(overlap)}, which {SETTINGS_FILE.name} "
            f"already sets for '{stage}'; remove it from {env_file.name}"
        )
    required = set(dotenv_values(ENV_EXAMPLE)) - set(stage_variables)
    missing = sorted(name for name in required if not values.get(name))
    if missing:
        fail(f"{env_file.name} has no value for: {', '.join(missing)}")
    return {name: value for name, value in values.items() if value is not None}


def upload_env(session, remote_env, values):
    bucket, _, key = remote_env.removeprefix("s3://").partition("/")
    s3 = session.client("s3")
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
            fail(f"cannot access bucket {bucket}: {error}")
        print(f"Creating bucket {bucket}", flush=True)
        if session.region_name == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": session.region_name},
            )
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(values).encode(),
        ContentType="application/json",
    )
    print(f"Uploaded {len(values)} variables to {remote_env}", flush=True)


def is_deployed(session, function_name):
    try:
        session.client("lambda").get_function(FunctionName=function_name)
    except ClientError as error:
        if error.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise
    return True


def run_zappa(*args):
    zappa = shutil.which("zappa")
    if not zappa:
        fail("zappa not found; run this script with `uv run`")
    print(f"\n$ zappa {' '.join(args)}", flush=True)
    result = subprocess.run([zappa, *args], cwd=ROOT)
    if result.returncode != 0:
        fail(f"`zappa {' '.join(args)}` exited with {result.returncode}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", help="stage in zappa_settings.json, e.g. dev or prod")
    parser.add_argument("--dry-run", action="store_true", help="validate only; change nothing in AWS")
    parser.add_argument("--skip-migrate", action="store_true", help="do not run migrate after deploying")
    args = parser.parse_args()
    stage = args.stage

    if stage in NOT_DEPLOYABLE:
        fail(f"'{stage}' is not a deployable stage")
    settings = resolve_stage(json.loads(SETTINGS_FILE.read_text()), stage)
    check_settings(stage, settings)
    env_values = load_stage_env(stage, settings.get("environment_variables", {}))

    if args.dry_run:
        print(f"{stage}: {SETTINGS_FILE.name} and .env.{stage} are valid; nothing was deployed")
        return

    session = boto3.Session(profile_name=settings.get("profile_name"), region_name=settings["aws_region"])
    upload_env(session, settings["remote_env"], env_values)

    function_name = slugify.slugify(f"{settings['project_name']}-{stage}")
    if is_deployed(session, function_name):
        run_zappa("update", stage)
    else:
        run_zappa("deploy", stage)
        if settings.get("domain"):
            run_zappa("certify", stage, "--yes")

    if not args.skip_migrate:
        run_zappa("manage", stage, "migrate")


if __name__ == "__main__":
    main()

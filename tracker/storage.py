"""Where the raw gzipped chunks live: S3 when TRACKER_RAW_BUCKET is set, else a local directory.

Postgres only holds metadata and parsed data. Keeping the originals means the
parser can be improved and every stream re-parsed from byte zero.
"""

from pathlib import Path

from django.conf import settings


class LocalRawStorage:
    def __init__(self, root):
        self.root = Path(root)

    def put(self, key, data):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key):
        return (self.root / key).read_bytes()


class S3RawStorage:
    def __init__(self, bucket):
        import boto3  # a Zappa dependency, so always present on Lambda

        self.bucket = bucket
        self.client = boto3.client("s3")

    def put(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="application/gzip")

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()


def raw_storage():
    bucket = settings.TRACKER["RAW_BUCKET"]
    if bucket:
        return S3RawStorage(bucket)
    return LocalRawStorage(settings.TRACKER["RAW_LOCAL_DIR"])


def chunk_key(stream, start, end):
    return f"raw/{stream.user_id}/{stream.stream_id}/{start:012d}-{end:012d}.gz"

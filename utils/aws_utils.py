from datetime import timedelta
from functools import lru_cache

import boto3
from botocore.signers import CloudFrontSigner
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings
from django.utils import timezone


def upload_to_s3(file_obj, bucket_name, s3_key):
    """
    Upload file(s) to S3.

    Args:
        file_obj: File object to upload (single file or {key: file_obj} dictionary)
        bucket_name: S3 bucket name
        s3_key: Target S3 path/name (or base path for dictionary input)
    Returns:
        str or dict: Uploaded file key or dictionary of uploaded file keys
    """
    if settings.ENV == "local":
        session = boto3.Session(profile_name="pokerland")
    else:
        session = boto3.Session()

    s3_client = session.client("s3")

    # Handle multiple files (dictionary input)
    if isinstance(file_obj, dict):
        results = {}
        for key, file in file_obj.items():
            file_s3_key = f"{s3_key}/{key}" if not s3_key.endswith(key) else s3_key
            try:
                # Reset file pointer and read file content
                file.seek(0)
                file_content = file.read()

                # Use put_object instead of upload_fileobj
                content_type = getattr(file, 'content_type', 'application/octet-stream')
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=file_s3_key,
                    Body=file_content,
                    ContentType=content_type
                )
                results[key] = file_s3_key
            except Exception as e:
                print(f"Error uploading {key}: {str(e)}")
                import traceback
                traceback.print_exc()
        return results
    # Handle single file
    else:
        try:
            # Reset file pointer and read file content
            file_obj.seek(0)
            file_content = file_obj.read()

            # Use put_object instead of upload_fileobj
            content_type = getattr(file_obj, 'content_type', 'application/octet-stream')
            s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=file_content,
                ContentType=content_type
            )
            return s3_key
        except Exception as e:
            print(f"Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

class CloudfrontHandler:

    @classmethod
    @lru_cache(maxsize=1)
    def _load_private_key(cls):
        return serialization.load_pem_private_key(
            settings.AWS_CLOUDFRONT_PRIVATE_KEY.encode("utf-8"),
            password=None,
            backend=default_backend(),
        )

    @classmethod
    def get_signed_url(cls, url, expire_datetime=None):
        aws_cloudfront_public_key_id = "K3K68UZH0TECPW"
        
        def rsa_signer(message):
            private_key = cls._load_private_key()
            return private_key.sign(message, padding.PKCS1v15(), hashes.SHA1())

        if not expire_datetime:
            expire_datetime = timezone.now() + timedelta(days=1)
        cloudfront_signer = CloudFrontSigner(
            aws_cloudfront_public_key_id,
            rsa_signer,
        )
        return cloudfront_signer.generate_presigned_url(
            url, date_less_than=expire_datetime
        )


def send_email(sender, recipient, subject, body_text, body_html=None):
    """
    Send an email via AWS SES.

    Parameters:
    - sender: Sender email address
    - recipient: Recipient email address (single string or list)
    - subject: Email subject
    - body_text: Email body (text)
    - body_html: Email body (HTML, optional)

    Returns:
    - True on success, False on failure
    """
    # Create SES client
    client = boto3.client("ses")

    # Build email payload
    email_message = {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
    }

    # Add HTML body when provided
    if body_html:
        email_message["Body"]["Html"] = {"Data": body_html, "Charset": "UTF-8"}
    client.send_email(
        Source=sender,
        Destination={
            "ToAddresses": [recipient] if isinstance(recipient, str) else recipient
        },
        Message=email_message,
    )

@lru_cache(maxsize=1)
def is_running_on_lambda():
    # Check an environment variable that exists only in Lambda.
    import os
    return "AWS_LAMBDA_FUNCTION_NAME" in os.environ

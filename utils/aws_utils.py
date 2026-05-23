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
    파일을 S3에 업로드합니다.

    Args:
        file_obj: 업로드할 파일 객체 (단일 파일 객체 또는 {key: file_obj} 형태의 딕셔너리)
        bucket_name: S3 버킷 이름
        s3_key: S3에 저장될 파일 경로/이름 (또는 딕셔너리인 경우 기본 경로)
    Returns:
        str 또는 dict: 업로드된 파일의 URL 또는 URLs 딕셔너리
    """
    if settings.ENV == "local":
        session = boto3.Session(profile_name="essentory")
    else:
        session = boto3.Session()

    s3_client = session.client("s3")

    # 여러 파일 처리 (딕셔너리 형태)
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
    # 단일 파일 처리
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
    AWS SES를 사용하여 이메일을 전송하는 함수

    Parameters:
    - sender: 발신자 이메일 주소
    - recipient: 수신자 이메일 주소 (단일 문자열 또는 리스트)
    - subject: 이메일 제목
    - body_text: 이메일 본문 (텍스트)
    - body_html: 이메일 본문 (HTML, 선택사항)

    Returns:
    - 성공 시 True, 실패 시 False
    """
    # SES 클라이언트 생성
    client = boto3.client("ses")

    # 이메일 내용 구성
    email_message = {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
    }

    # HTML 본문이 제공된 경우 추가
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
    # Lambda 환경에만 존재하는 환경 변수 확인
    import os
    return 'AWS_LAMBDA_FUNCTION_NAME' in os.environ
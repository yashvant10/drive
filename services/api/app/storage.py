import os

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException


def private_bucket():
    return os.getenv("DRIVEWELL_DOCUMENT_BUCKET")


def client():
    return boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT_URL"),
                        region_name=os.getenv("AWS_REGION", "ap-south-1"),
                        config=Config(connect_timeout=4, read_timeout=10, retries={"max_attempts": 2}))


def put_document(key, content):
    try:
        client().put_object(Bucket=private_bucket(), Key=key, Body=content,
                            ContentType="application/pdf", ServerSideEncryption="AES256")
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(502, "Private document storage is temporarily unavailable.") from error


def get_document(key):
    try:
        result = client().get_object(Bucket=private_bucket(), Key=key)
        stream = result["Body"]
        try:
            content = stream.read(2_000_001)
        finally:
            stream.close()
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(502, "Private document storage is temporarily unavailable.") from error
    if len(content) > 2_000_000 or not content.startswith(b"%PDF-"):
        raise HTTPException(502, "The stored document could not be validated.")
    return content

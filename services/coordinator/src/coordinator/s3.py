import boto3
import os

def get_s3():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
        region_name="us-east-1",
    )

def delete_object(bucket: str, key: str):
    s3 = get_s3()
    s3.delete_object(Bucket=bucket, Key=key)

import boto3

from infringement.common.settings import get_settings


def s3_client():
    return boto3.client("s3", region_name=get_settings().aws_region)


def sqs_client():
    return boto3.client("sqs", region_name=get_settings().aws_region)

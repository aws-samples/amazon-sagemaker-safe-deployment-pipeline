import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

sm = boto3.client("sagemaker")
s3 = boto3.client("s3")
cd = boto3.client("codedeploy")


def get_bucket_prefix(url):
    try:
        from urllib.parse import urlparse
    except ImportError:
        from urlparse import urlparse
    a = urlparse(url)
    return a.netloc, a.path.lstrip("/") + "/"


def lambda_handler(event, context):
    logger.debug("event %s", json.dumps(event))
    endpoint_name = os.environ["ENDPOINT_NAME"]
    logger.info("post traffic for endpoint: %s", endpoint_name)
    data_capture_uri = os.environ.get("DATA_CAPTURE_URI", "")
    logger.info("data capture uri: %s", data_capture_uri)

    error_message = None
    try:
        if data_capture_uri:
            # List objects under data capture logs director
            bucket, prefix = get_bucket_prefix(data_capture_uri)
            contents = s3.list_objects(Bucket=bucket, Prefix=prefix).get("Contents")
            if contents != None and contents:
                logger.info("Found %d data capture logs", len(contents))
            else:
                error_message = "No data capture logs found"
                logger.error(error_message)
    except ClientError as e:
        error_message = e.response["Error"]["Message"]
        logger.error("Error checking logs %s", error_message)

    try:
        if error_message != None:
            logger.info("put codepipeline failed: %s", error_message)
            response = cd.put_lifecycle_event_hook_execution_status(
                deploymentId=event["DeploymentId"],
                lifecycleEventHookExecutionId=event["LifecycleEventHookExecutionId"],
                status="Failed",
            )
            return {"statusCode": 400, "message": error_message}
        else:
            logger.info("put codepipeline success")
            response = cd.put_lifecycle_event_hook_execution_status(
                deploymentId=event["DeploymentId"],
                lifecycleEventHookExecutionId=event["LifecycleEventHookExecutionId"],
                status="Succeeded",
            )
            return {
                "statusCode": 200,
            }
    except ClientError as e:
        # Error attempting to update the cloud formation
        logger.error("Unexpected codepipeline error")
        logger.error(e)
        return {"statusCode": 500, "message": e.response["Error"]["Message"]}

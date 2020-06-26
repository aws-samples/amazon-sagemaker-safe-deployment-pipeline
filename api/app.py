import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

sm_runtime = boto3.client("sagemaker-runtime")


def lambda_handler(event, context):
    logger.debug("event %s", json.dumps(event))
    endpoint_name = os.environ["ENDPOINT_NAME"]
    logger.info("api for endpoint %s", endpoint_name)

    # Get posted body and content type
    content_type = event["headers"].get("Content-Type", "text/csv")
    custom_attributes = event["headers"].get("X-Amzn-SageMaker-Custom-Attributes", "")
    if content_type.startswith("text/csv"):
        payload = event["body"]
    elif content_type.startswith("application/json"):
        payload = json.loads(event["body"])
    else:
        message = "bad content type: {}".format(content_type)
        logger.error()
        return {"statusCode": 500, "message": message}

    logger.info("content type: %s size: %d", content_type, len(payload))

    try:
        # Invoke the endpoint with full multi-line payload
        response = sm_runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            Body=payload,
            ContentType=content_type,
            CustomAttributes=custom_attributes,
            Accept="application/json",
        )
        # Return predictions as JSON dictionary instead of CSV text
        predictions = response["Body"].read().decode("utf-8")
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": content_type,
                "X-SageMaker-Endpoint": endpoint_name,
            },
            "body": predictions,
        }
    except ClientError as e:
        logger.error(
            "Unexpected sagemaker error: {}".format(e.response["Error"]["Message"])
        )
        logger.error(e)
        return {"statusCode": 500, "message": "Unexpected sagemaker error"}

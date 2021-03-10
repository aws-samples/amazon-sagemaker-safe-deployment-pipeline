import boto3
import logging
import os
import re
import json
from urllib.parse import urlparse

logger = logging.getLogger()
logger.setLevel(logging.INFO)
sm_client = boto3.client("sagemaker")
s3_client = boto3.client("s3")


def get_processing_job(processing_job_name):
    response = sm_client.describe_processing_job(ProcessingJobName=processing_job_name)
    status = response["ProcessingJobStatus"]
    exit_message = response["ExitMessage"]
    s3_result_uri = response["ProcessingOutputConfig"]["Outputs"][0]["S3Output"]["S3Uri"]
    url_parsed = urlparse(s3_result_uri)
    result_bucket, result_path = url_parsed.netloc, url_parsed.path
    return status, exit_message, result_bucket, result_path


def get_s3_results_json(result_bucket, result_path, filename):
    s3_object = s3_client.get_object(
        Bucket=result_bucket, Key=os.path.join(result_path.lstrip("/"), filename),
    )
    return json.loads(s3_object["Body"].read())


def get_baseline_drift(feature):
    if "violations" in feature:
        for violation in feature["violations"]:
            if violation["constraint_check_type"] == "baseline_drift_check":
                desc = violation["description"]
                print(desc)
                matches = re.search("distance: (.+) exceeds threshold: (.+)", desc)
                if matches:
                    match = matches.group(1)
                    threshold = matches.group(2)
                    yield {
                        "feature": violation["feature_name"],
                        "drift": float(match),
                        "threshold": float(threshold),
                    }


# Retrieve transform job name from event and return transform job status.
def lambda_handler(event, context):
    if "ProcessingJobName" in event:
        job_name = event["ProcessingJobName"]
    else:
        raise KeyError("ProcessingJobName key not found in event: {}.".format(json.dumps(event)))
    try:
        # Parse the result uri
        status, exit_message, result_bucket, result_path = get_processing_job(job_name)
        logger.info("Processing job: {} has status:{}.".format(job_name, status))
        drift = None
        if status == "Completed":
            try:
                # Attempt to load the violations
                violations = get_s3_results_json(
                    result_bucket, result_path, "constraint_violations.json"
                )
                status = "CompletedWithViolations"
                logger.info("Has violations")
                drift = list(get_baseline_drift(violations))
            except Exception as e:
                print(e)
                logger.info("No violations")
        return {
            "statusCode": 200,
            "results": {
                "ProcessingJobName": job_name,
                "ProcessingJobStatus": status,
                "ExitMessage": exit_message,
                "BaselineDrift": drift,
            },
        }
    except Exception as e:
        message = "Failed to read processing status!"
        print(e)
        return {"statusCode": 500, "error": message}


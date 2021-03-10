import boto3
import logging
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)
sm_client = boto3.client("sagemaker")


def lambda_handler(event, context):
    if "TrainingJobName" in event:
        job_name = event["TrainingJobName"]
    else:
        raise KeyError("TrainingJobName not found for event: {}.".format(json.dumps(event)))

    # Get the training job
    response = sm_client.describe_training_job(TrainingJobName=job_name)
    status = response["TrainingJobStatus"]
    logger.info("Training job:{} has status:{}.".format(job_name, status))

    # Get the metrics as a dictionary
    for _, metric in enumerate(response["FinalMetricDataList"]):
        metric["Timestamp"] = metric["Timestamp"].timestamp()

    return {
        "statusCode": 200,
        "results": {
            "TrainingJobName": job_name,
            "TrainingJobStatus": status,
            "TrainingMetrics": response["FinalMetricDataList"],
        },
    }

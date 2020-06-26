import json
import logging

import boto3
import botocore
from botocore.exceptions import ClientError

from crhelper import CfnResource

logger = logging.getLogger(__name__)
sm = boto3.client("sagemaker")

# cfnhelper makes it easier to implement a CloudFormation custom resource
helper = CfnResource()

# CFN Handlers


def lambda_handler(event, context):
    helper(event, context)


@helper.create
@helper.update
def create_handler(event, context):
    """
    Called when CloudFormation custom resource sends the delete event
    """
    create_training_job(event)


@helper.delete
def delete_handler(event, context):
    """
    Training Jobs can not be deleted only stopped if running.
    """
    training_job_name = get_training_job_name(event)
    stop_training_job(training_job_name)


@helper.poll_create
@helper.poll_update
def poll_create(event, context):
    """
    Return true if the resource has been created and false otherwise so
    CloudFormation polls again.
    """
    training_job_name = get_training_job_name(event)
    logger.info("Polling for training job: %s", training_job_name)
    return is_training_job_ready(training_job_name)


@helper.poll_delete
def poll_delete(event, context):
    """
    Return true if the resource has been stopped.  
    """
    training_job_name = get_training_job_name(event)
    logger.info("Polling for stopped training job: %s", training_job_name)
    return stop_training_job(training_job_name)


# Helper Functions


def get_training_job_name(event):
    return event["ResourceProperties"]["TrainingJobName"]


def is_training_job_ready(training_job_name):
    is_ready = False
    response = sm.describe_training_job(TrainingJobName=training_job_name)
    status = response["TrainingJobStatus"]

    if status == "Completed":
        logger.info("Training Job (%s) is Completed", training_job_name)

        # Return additional info
        helper.Data["TrainingJobName"] = training_job_name
        helper.Data["Arn"] = response["TrainingJobArn"]
        is_ready = True
    elif status == "InProgress" or status == "Stopping":
        logger.info(
            "Training job (%s) still in progress (%s), waiting and polling again...",
            training_job_name,
            response["SecondaryStatus"],
        )
    else:
        raise Exception(
            "Training job ({}) has unexpected status: {}".format(
                training_job_name, status
            )
        )

    return is_ready


def create_training_job(event):
    training_job_name = get_training_job_name(event)

    request = get_training_request(event)

    logger.info("Creating training job with name: %s", training_job_name)
    logger.debug(json.dumps(request))
    response = sm.create_training_job(**request)

    # Update Output Parameters
    helper.Data["TrainingJobName"] = training_job_name
    helper.Data["Arn"] = response["TrainingJobArn"]
    return helper.Data["Arn"]


# TODO: Test to see what Validation/Resource not found errors are returned for training jobs


def stop_training_job(training_job_name):
    try:
        training_job = sm.describe_training_job(TrainingJobName=training_job_name)
        status = training_job["TrainingJobStatus"]
        if status == "InProgress":
            logger.info("Stopping InProgress training job: %s", training_job_name)
            sm.stop_training_job(TrainingJobName=training_job_name)
            return False
        else:
            logger.info("Training job status: %s, nothing to stop", status)
            return True
    except ClientError as e:
        # NOTE: This doesn't return "ResourceNotFound" code, so need to catch
        if (
            e.response["Error"]["Code"] == "ValidationException"
            and "resource not found" in e.response["Error"]["Message"]
        ):
            logger.info("Resource not found, nothing to stop")
            return True
        else:
            logger.error("Unexpected error while trying to stop training job")
            raise e


def get_training_request(event):
    props = event["ResourceProperties"]

    # Load raw request
    request = json.loads(props["TrainingJobRequest"])

    # Add the KmsKeyId to monitoring outputs and cluster volume if provided
    if props.get("KmsKeyId") is not None:
        request["ResourceConfig"]["VolumeKmsKeyId"] = props["KmsKeyId"]

    # Set the training job name
    request["TrainingJobName"] = props["TrainingJobName"]

    # Add experiment tracking
    request["ExperimentConfig"] = {
        "ExperimentName": props["ExperimentName"],
        "TrialName": props["TrialName"],
        "TrialComponentDisplayName": "Training",
    }

    return request

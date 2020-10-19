import boto3
from botocore.exceptions import ClientError
import logging
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)
sm_client = boto3.client("sagemaker")


def lambda_handler(event, context):
    if "ExperimentName" in event:
        experiment_name = event["ExperimentName"]
    else:
        raise KeyError("ExperimentName key not found in input: {}".format(json.dumps(event)))
    if "TrialName" in event:
        trial_name = event["TrialName"]
    else:
        raise KeyError("TrialName key not found in input: {}".format(json.dumps(event)))
    experiment_created = False
    try:
        response = sm_client.create_experiment(ExperimentName=experiment_name)
        logger.info("Created experiment: {}".format(experiment_name))
        logger.debug(response)
        experiment_created = True
    except ClientError as error:
        if (
            error.response["Error"]["Code"] == "ValidationException"
            and "Experiment names must be unique" in error.response["Error"]["Message"]
        ):
            logger.warn("Attempt to create duplicate experiment: {}".format(experiment_name))
        else:
            raise error
    trial_created = False
    try:
        response = sm_client.create_trial(ExperimentName=experiment_name, TrialName=trial_name)
        logger.info("Created trial: {}".format(trial_name))
        experiment_created = True
    except ClientError as error:
        if (
            error.response["Error"]["Code"] == "ValidationException"
            and "Trial names must be unique" in error.response["Error"]["Message"]
        ):
            logger.warn("Attempt to create duplicate trial: {}".format(trial_name))
        else:
            raise error
    return {
        "statusCode": 200,
        "results": {"ExperimentCreated": experiment_created, "TrialCreated": trial_created,},
    }

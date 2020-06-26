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
def create_handler(event, context):
    """
    Called when CloudFormation custom resource sends the create event
    """
    return create_monitoring_schedule(event)


@helper.update
def update_handler(event, context):
    """
    If this is an update for new schedule then call create_handler
    """
    schedule_name = get_schedule_name(event)
    logger.info("Updating schedule: %s", schedule_name)
    try:
        is_schedule_ready(schedule_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFound":
            return create_handler(event, context)
        else:
            logger.error("Unexpected error while trying to delete endpoint config")
            raise e


@helper.delete
def delete_handler(event, context):
    """
    Called when CloudFormation custom resource sends the delete event
    """
    schedule_name = get_schedule_name(event)
    logger.info("Deleting schedule: %s", schedule_name)
    return delete_monitoring_schedule(schedule_name)


@helper.poll_create
@helper.poll_update
def poll_create(event, context):
    """
    Return true if the resource has been created and false otherwise so
    CloudFormation polls again.
    """
    schedule_name = get_schedule_name(event)
    logger.info("Polling for creation of schedule: %s", schedule_name)
    return is_schedule_ready(schedule_name)


@helper.poll_delete
def poll_delete(event, context):
    """
    Return true if the resource has been deleted.
    """
    schedule_name = get_schedule_name(event)
    logger.info("Polling for deletion of schedule: %s", schedule_name)
    return delete_monitoring_schedule(schedule_name)


# Helper Functions


def get_model_monitor_container_uri(region):
    container_uri_format = (
        "{0}.dkr.ecr.{1}.amazonaws.com/sagemaker-model-monitor-analyzer"
    )

    regions_to_accounts = {
        "eu-north-1": "895015795356",
        "me-south-1": "607024016150",
        "ap-south-1": "126357580389",
        "us-east-2": "680080141114",
        "us-east-2": "777275614652",
        "eu-west-1": "468650794304",
        "eu-central-1": "048819808253",
        "sa-east-1": "539772159869",
        "ap-east-1": "001633400207",
        "us-east-1": "156813124566",
        "ap-northeast-2": "709848358524",
        "eu-west-2": "749857270468",
        "ap-northeast-1": "574779866223",
        "us-west-2": "159807026194",
        "us-west-1": "890145073186",
        "ap-southeast-1": "245545462676",
        "ap-southeast-2": "563025443158",
        "ca-central-1": "536280801234",
    }

    container_uri = container_uri_format.format(regions_to_accounts[region], region)
    return container_uri


def get_schedule_name(event):
    return event["ResourceProperties"]["ScheduleName"]


def create_monitoring_schedule(event):
    schedule_name = get_schedule_name(event)
    monitoring_schedule_config = create_monitoring_schedule_config(event)

    logger.info("Creating monitoring schedule with name: %s", schedule_name)

    try:
        response = sm.create_monitoring_schedule(
            MonitoringScheduleName=schedule_name,
            MonitoringScheduleConfig=monitoring_schedule_config,
        )

        # Updating the monitoring schedule arn
        helper.Data["ScheduleName"] = schedule_name
        helper.Data["Arn"] = response["MonitoringScheduleArn"]
        return helper.Data["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ValidationException":
            logger.error(
                "Unable to create schedule: %s", e.response["Error"]["Message"]
            )
        else:
            logger.error("Unexpected error while trying to delete monitoring schedule")
        raise e


def is_schedule_ready(schedule_name):
    is_ready = False

    schedule = sm.describe_monitoring_schedule(MonitoringScheduleName=schedule_name)
    status = schedule["MonitoringScheduleStatus"]
    if status == "Scheduled":
        logger.info("Monitoring schedule (%s) is ready", schedule_name)
        is_ready = True
    elif status == "Pending":
        logger.info(
            "Monitoring schedule (%s) still creating, waiting and polling again...",
            schedule_name,
        )
    else:
        raise Exception(
            "Monitoring schedule ({}) has unexpected status: {}".format(
                schedule_name, status
            )
        )

    return is_ready


def create_monitoring_schedule_config(event):
    props = event["ResourceProperties"]

    request = {
        "ScheduleConfig": {
            "ScheduleExpression": props.get("ScheduleExpression", "cron(0 * ? * * *)"),
        },
        "MonitoringJobDefinition": {
            "BaselineConfig": {
                "ConstraintsResource": {"S3Uri": props["BaselineConstraintsUri"],},
                "StatisticsResource": {"S3Uri": props["BaselineStatisticsUri"],},
            },
            "MonitoringInputs": [
                {
                    "EndpointInput": {
                        "EndpointName": props["EndpointName"],
                        "LocalPath": props.get(
                            "InputLocalPath", "/opt/ml/processing/endpointdata"
                        ),
                        "S3InputMode": "File",
                        "S3DataDistributionType": "FullyReplicated",
                    }
                }
            ],
            "MonitoringOutputConfig": {
                "MonitoringOutputs": [
                    {
                        "S3Output": {
                            "S3Uri": props["OutputS3URI"],
                            "LocalPath": props.get(
                                "OutputLocalPath", "/opt/ml/processing/localpath"
                            ),
                            "S3UploadMode": "Continuous",
                        }
                    }
                ],
            },
            "MonitoringResources": {
                "ClusterConfig": {
                    "InstanceCount": 1,
                    "InstanceType": props.get("InstanceType", "ml.m5.xlarge"),
                    "VolumeSizeInGB": 30,
                }
            },
            "MonitoringAppSpecification": {
                "ImageUri": props.get(
                    "ImageURI", get_model_monitor_container_uri(helper._region)
                ),
            },
            "StoppingCondition": {
                "MaxRuntimeInSeconds": int(
                    props.get("MaxRuntimeInSeconds", 1800)
                )  # 30 mins
            },
            "Environment": {
                "publish_cloudwatch_metrics": props.get(
                    "PublishCloudwatchMetrics", "Enabled"
                )
            },
            "RoleArn": props["PassRoleArn"],
        },
    }

    # Add the KmsKeyId to monitoring outputs and cluster volume if provided
    if props.get("KmsKeyId") is not None:
        request["MonitoringOutputConfig"]["KmsKeyId"] = props["KmsKeyId"]
        request["MonitoringResources"]["ClusterConfig"]["VolumeKmsKeyId"] = props["KmsKeyId"]

    # Add optional pre/processing scripts

    if props.get("RecordPreprocessorSourceUri"):
        app = request["MonitoringJobDefinition"]["MonitoringAppSpecification"]
        app["RecordPreprocessorSourceUri"] = props["RecordPreprocessorSourceUri"]
    if props.get("PostAnalyticsProcessorSourceUri"):
        app = request["MonitoringJobDefinition"]["MonitoringAppSpecification"]
        app["PostAnalyticsProcessorSourceUri"] = props[
            "PostAnalyticsProcessorSourceUri"
        ]

    return request


def delete_monitoring_schedule(schedule_name):
    try:
        if is_schedule_ready(schedule_name):
            # Check if we have running schedule excutions before deleting schedule
            response = sm.list_monitoring_executions(
                MonitoringScheduleName=schedule_name
            )
            running = [
                m["MonitoringExecutionStatus"]
                for m in response["MonitoringExecutionSummaries"]
                if m["MonitoringExecutionStatus"]
                in ["Pending", "InProgress", "Stopping"]
            ]
            if running:
                logger.info(
                    "You still have %d executions: %s", len(running), ",".join(running)
                )
            else:
                sm.delete_monitoring_schedule(MonitoringScheduleName=schedule_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFound":
            logger.info("Resource not found, nothing to delete")
            # Return true so it stops polling
            return True
        else:
            logger.error("Unexpected error while trying to delete monitoring schedule")
            raise e

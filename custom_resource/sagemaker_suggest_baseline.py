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
    Called when CloudFormation custom resource sends the create event
    """
    return create_processing_job(event)


@helper.delete
def delete_handler(event, context):
    """
    Processing Jobs like Training Jobs can not be deleted only stopped if running.
    """
    processing_job_name = get_processing_job_name(event)
    stop_processing_job(processing_job_name)


@helper.poll_create
@helper.poll_update
def poll_create(event, context):
    """
    Return true if the resource has been created and false otherwise so
    CloudFormation polls again.
    """
    processing_job_name = get_processing_job_name(event)
    logger.info("Polling for creation of processing job: %s", processing_job_name)
    return is_processing_job_ready(processing_job_name)


@helper.poll_delete
def poll_delete(event, context):
    """
    Return true if the resource has been stopped.  
    """
    processing_job_name = get_processing_job_name(event)
    logger.info("Polling for stopped processing job: %s", processing_job_name)
    return stop_processing_job(processing_job_name)


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


def get_processing_job_name(event):
    return event["ResourceProperties"]["ProcessingJobName"]


def is_processing_job_ready(processing_job_name):
    is_ready = False

    processing_job = sm.describe_processing_job(ProcessingJobName=processing_job_name)
    status = processing_job["ProcessingJobStatus"]

    if status == "Stopped" or status == "Completed":
        logger.info("Processing Job (%s) is %s", processing_job_name, status)
        is_ready = True
    elif status == "InProgress" or status == "Stopping":
        logger.info(
            "Processing Job (%s) still in progress, waiting and polling again...",
            processing_job_name,
        )
    else:
        raise Exception(
            "Processing Job ({}) has unexpected status: {}".format(
                processing_job_name, status
            )
        )

    return is_ready


def create_processing_job(event):
    processing_job_name = get_processing_job_name(event)

    request, constraints_uri, statistics_uri = get_processing_request(event)

    logger.info("Creating processing job with name: %s", processing_job_name)
    logger.debug(json.dumps(request))
    response = sm.create_processing_job(**request)

    # Update Output Parameters
    helper.Data["ProcessingJobName"] = processing_job_name
    helper.Data["BaselineConstraintsUri"] = constraints_uri
    helper.Data["BaselineStatisticsUri"] = statistics_uri
    helper.Data["Arn"] = response["ProcessingJobArn"]
    return helper.Data["Arn"]


def stop_processing_job(processing_job_name):
    try:
        processing_job = sm.describe_processing_job(
            ProcessingJobName=processing_job_name
        )
        status = processing_job["ProcessingJobStatus"]
        if status == "InProgress":
            logger.info("Stopping InProgress processing job: %s", processing_job_name)
            sm.stop_processing_job(ProcessingJobName=processing_job_name)
            return False
        else:
            logger.info("Processing job status: %s, nothing to stop", status)
            return True
    except ClientError as e:
        # NOTE: This doesn't return "ResourceNotFound" code, so need to catch
        if (
            e.response["Error"]["Code"] == "ValidationException"
            and "Could not find" in e.response["Error"]["Message"]
        ):
            logger.info("Resource not found, nothing to stop")
            return True
        else:
            logger.error("Unexpected error while trying to stop processing job")
            raise e


class DatasetFormat(object):
    """Represents a Dataset Format that is used when calling a DefaultModelMonitor.
    """

    @staticmethod
    def csv(header=True, output_columns_position="START"):
        """Returns a DatasetFormat JSON string for use with a DefaultModelMonitor.
        Args:
            header (bool): Whether the csv dataset to baseline and monitor has a header.
                Default: True.
            output_columns_position (str): The position of the output columns.
                Must be one of ("START", "END"). Default: "START".
        Returns:
            dict: JSON string containing DatasetFormat to be used by DefaultModelMonitor.
        """
        return {
            "csv": {
                "header": header,
                "output_columns_position": output_columns_position,
            }
        }

    @staticmethod
    def json(lines=True):
        """Returns a DatasetFormat JSON string for use with a DefaultModelMonitor.
        Args:
            lines (bool): Whether the file should be read as a json object per line. Default: True.
        Returns:
            dict: JSON string containing DatasetFormat to be used by DefaultModelMonitor.
        """
        return {"json": {"lines": lines}}

    @staticmethod
    def sagemaker_capture_json():
        """Returns a DatasetFormat SageMaker Capture Json string for use with a DefaultModelMonitor.
        Returns:
            dict: JSON string containing DatasetFormat to be used by DefaultModelMonitor.
        """
        return {
            "sagemaker_capture_json": {
                "captureIndexNames": ["endpointInput", "endpointOutput"]
            }
        }


def get_file_name(url):
    try:
        from urllib.parse import urlparse
    except ImportError:
        from urlparse import urlparse
    a = urlparse(url)
    return os.path.basename(a.path)


def get_processing_request(event, dataset_format=DatasetFormat.csv()):
    props = event["ResourceProperties"]

    request = {
        "ProcessingInputs": [
            {
                "InputName": "baseline_dataset_input",
                "S3Input": {
                    "S3Uri": props["BaselineInputUri"],
                    "LocalPath": "/opt/ml/processing/input/baseline_dataset_input",
                    "S3DataType": "S3Prefix",
                    "S3InputMode": "File",
                    "S3DataDistributionType": "FullyReplicated",
                    "S3CompressionType": "None",
                },
            }
        ],
        "ProcessingOutputConfig": {
            "Outputs": [
                {
                    "OutputName": "monitoring_output",
                    "S3Output": {
                        "S3Uri": props["BaselineResultsUri"],
                        "LocalPath": "/opt/ml/processing/output",
                        "S3UploadMode": props.get("S3UploadMode", "EndOfJob"),
                    },
                }
            ]
        },
        "ProcessingJobName": props["ProcessingJobName"],
        "ProcessingResources": {
            "ClusterConfig": {
                "InstanceCount": 1,
                "InstanceType": props.get("InstanceType", "ml.m5.xlarge"),
                "VolumeSizeInGB": 30,
            }
        },
        "StoppingCondition": {
            "MaxRuntimeInSeconds": int(
                props.get("MaxRuntimeInSeconds", 1800)
            )  # 30 minutes
        },
        "AppSpecification": {
            "ImageUri": props.get(
                "ImageURI", get_model_monitor_container_uri(helper._region)
            ),
        },
        "Environment": {
            "dataset_format": json.dumps(dataset_format),
            "dataset_source": "/opt/ml/processing/input/baseline_dataset_input",
            "output_path": "/opt/ml/processing/output",
            "publish_cloudwatch_metrics": props.get(
                "PublishCloudwatchMetrics", "Disabled"
            ),
        },
        "RoleArn": props["PassRoleArn"],
    }

    # Add the KmsKeyId to monitoring outputs and cluster volume if provided
    if props.get("KmsKeyId") is not None:
        request["ProcessingOutputConfig"]["KmsKeyId"] = props["KmsKeyId"]
        request["ProcessingResources"]["ClusterConfig"]["VolumeKmsKeyId"] = props[
            "KmsKeyId"
        ]

    # Add experiment tracking
    request["ExperimentConfig"] = {
        "ExperimentName": props["ExperimentName"],
        "TrialName": props["TrialName"],
        "TrialComponentDisplayName": "Baseline",
    }

    # Add optional pre/processing scripts

    if props.get("RecordPreprocessorSourceUri"):
        env = request["Environment"]
        fn = get_file_name(props["RecordPreprocessorSourceUri"])
        env["record_preprocessor_script"] = (
            "/opt/ml/processing/code/postprocessing/" + fn
        )
        request["ProcessingInputs"].append(
            {
                "InputName": "pre_processor_script",
                "S3Input": {
                    "S3Uri": props["RecordPreprocessorSourceUri"],
                    "LocalPath": "/opt/ml/processing/code/postprocessing",
                    "S3DataType": "S3Prefix",
                    "S3InputMode": "File",
                    "S3DataDistributionType": "FullyReplicated",
                    "S3CompressionType": "None",
                },
            }
        )

    if props.get("PostAnalyticsProcessorSourceUri"):
        env = request["Environment"]
        fn = get_file_name(props["PostAnalyticsProcessorSourceUri"])
        env["post_analytics_processor_script"] = (
            "/opt/ml/processing/code/postprocessing/" + fn
        )
        request["ProcessingInputs"].append(
            {
                "InputName": "post_processor_script",
                "S3Input": {
                    "S3Uri": props["PostAnalyticsProcessorSourceUri"],
                    "LocalPath": "/opt/ml/processing/code/postprocessing",
                    "S3DataType": "S3Prefix",
                    "S3InputMode": "File",
                    "S3DataDistributionType": "FullyReplicated",
                    "S3CompressionType": "None",
                },
            }
        )

    # If this is an update and we have previous baseline & constraints uri add these as inputs

    data = event.get("CrHelperData")
    if event["RequestType"] == "Update" and data != None:
        # Add baseline constraints
        logger.debug("Update with constraints: %s", data["BaselineConstraintsUri"])
        env = request["Environment"]
        env[
            "baseline_constraints"
        ] = "/opt/ml/processing/baseline/constraints/constraints.json"
        request["ProcessingInputs"].append(
            {
                "InputName": "constraints",
                "S3Input": {
                    "S3Uri": data["BaselineConstraintsUri"],
                    "LocalPath": "/opt/ml/processing/baseline/constraints",
                    "S3DataType": "S3Prefix",
                    "S3InputMode": "File",
                    "S3DataDistributionType": "FullyReplicated",
                    "S3CompressionType": "None",
                },
            }
        )
        # Add baseline statistics
        logger.debug("Update with statistics: %s", data["BaselineStatisticsUri"])
        env["baseline_statistics"] = "/opt/ml/processing/baseline/stats/statistics.json"
        request["ProcessingInputs"].append(
            {
                "InputName": "baseline",
                "S3Input": {
                    "S3Uri": data["BaselineStatisticsUri"],
                    "LocalPath": "/opt/ml/processing/baseline/stats",
                    "S3DataType": "S3Prefix",
                    "S3InputMode": "File",
                    "S3DataDistributionType": "FullyReplicated",
                    "S3CompressionType": "None",
                },
            }
        )

    # Build the constraints and statistics URI from the results URI

    constraints_uri = props["BaselineResultsUri"] + "/constraints.json"
    statistics_uri = props["BaselineResultsUri"] + "/statistics.json"

    return request, constraints_uri, statistics_uri

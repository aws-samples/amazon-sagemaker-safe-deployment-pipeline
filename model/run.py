import argparse
import json
import os
import sys
import time

import boto3
import sagemaker
from sagemaker.workflow.airflow import training_config


def get_training_image(region=None):
    region = region or boto3.Session().region_name
    return sagemaker.image_uris.retrieve(
        region=region, framework="xgboost", version="1.0-1"
    )


def get_training_params(
    model_name,
    job_id,
    role,
    image_uri,
    training_uri,
    validation_uri,
    output_uri,
    hyperparameters,
    kms_key_id,
):
    # Create the estimator
    xgb = sagemaker.estimator.Estimator(
        image_uri,
        role,
        instance_count=1,
        instance_type="ml.m4.xlarge",
        output_path=output_uri,
    )
    # Set the hyperparameters overriding with any defaults
    params = {
        "max_depth": "9",
        "eta": "0.2",
        "gamma": "4",
        "min_child_weight": "300",
        "subsample": "0.8",
        "objective": "reg:linear",
        "early_stopping_rounds": "10",
        "num_round": "100",
    }
    xgb.set_hyperparameters(**{**params, **hyperparameters})

    # Specify the data source
    s3_input_train = sagemaker.inputs.TrainingInput(
        s3_data=training_uri, content_type="csv"
    )
    s3_input_val = sagemaker.inputs.TrainingInput(
        s3_data=validation_uri, content_type="csv"
    )
    data = {"train": s3_input_train, "validation": s3_input_val}

    # Get the training request
    request = training_config(xgb, inputs=data, job_name=job_id)
    return {
        "Parameters": {
            "ModelName": model_name,
            "TrainJobId": job_id,
            "TrainJobRequest": json.dumps(request),
            "KmsKeyId": kms_key_id,
        }
    }


def get_experiment(model_name):
    return {
        "ExperimentName": model_name,
    }


def get_trial(model_name, job_id):
    return {
        "ExperimentName": model_name,
        "TrialName": job_id,
    }


def get_suggest_baseline(model_name, job_id, role, baseline_uri, kms_key_id):
    return {
        "Parameters": {
            "ModelName": model_name,
            "TrainJobId": job_id,
            "MLOpsRoleArn": role,
            "BaselineInputUri": baseline_uri,
            "KmsKeyId": kms_key_id,
        }
    }


def get_dev_params(model_name, job_id, role, image_uri, kms_key_id):
    return {
        "Parameters": {
            "ImageRepoUri": image_uri,
            "ModelName": model_name,
            "TrainJobId": job_id,
            "MLOpsRoleArn": role,
            "VariantName": "dev-{}".format(model_name),
            "KmsKeyId": kms_key_id,
        }
    }


def get_prd_params(model_name, job_id, role, image_uri, kms_key_id):
    dev_params = get_dev_params(model_name, job_id, role, image_uri, kms_key_id)[
        "Parameters"
    ]
    prod_params = {
        "VariantName": "prd-{}".format(model_name),
        "ScheduleMetricName": "feature_baseline_drift_total_amount",
        "ScheduleMetricThreshold": str("0.20"),
    }
    return {"Parameters": dict(dev_params, **prod_params)}


def get_pipeline_id(pipeline_name):
    # Get pipeline execution id
    codepipeline = boto3.client("codepipeline")
    response = codepipeline.get_pipeline_state(name=pipeline_name)
    return response["stageStates"][0]["latestExecution"]["pipelineExecutionId"]


def main(
    pipeline_name,
    model_name,
    role,
    data_bucket,
    data_dir,
    output_dir,
    ecr_dir,
    kms_key_id,
):
    # Get the job id and source revisions
    job_id = get_pipeline_id(pipeline_name)
    print("job id: {}".format(job_id))
    output_uri = "s3://{0}/{1}".format(data_bucket, model_name)

    if ecr_dir:
        # Load the image uri and input data config
        with open(os.path.join(ecr_dir, "imageDetail.json"), "r") as f:
            image_uri = json.load(f)["ImageURI"]
    else:
        # Get the the managed image uri for current region
        image_uri = get_training_image()
    print("image uri: {}".format(image_uri))

    with open(os.path.join(data_dir, "inputData.json"), "r") as f:
        input_data = json.load(f)
        training_uri = input_data["TrainingUri"]
        validation_uri = input_data["ValidationUri"]
        baseline_uri = input_data["BaselineUri"]
        print(
            "training uri: {}\nvalidation uri: {}\n baseline uri: {}".format(
                training_uri, validation_uri, baseline_uri
            )
        )

    hyperparameters = {}
    if os.path.exists(os.path.join(data_dir, "hyperparameters.json")):
        with open(os.path.join(data_dir, "hyperparameters.json"), "r") as f:
            hyperparameters = json.load(f)
            for i in hyperparameters:
                hyperparameters[i] = str(hyperparameters[i])

    # Create output directory
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)

    # Write experiment and trial config
    with open(os.path.join(output_dir, "experiment.json"), "w") as f:
        config = get_experiment(model_name)
        json.dump(config, f)
    with open(os.path.join(output_dir, "trial.json"), "w") as f:
        config = get_trial(model_name, job_id)
        json.dump(config, f)

    # Write the training request
    with open(os.path.join(output_dir, "training-job.json"), "w") as f:
        params = get_training_params(
            model_name,
            job_id,
            role,
            image_uri,
            training_uri,
            validation_uri,
            output_uri,
            hyperparameters,
            kms_key_id,
        )
        json.dump(params, f)

    # Write the baseline params for CFN
    with open(os.path.join(output_dir, "suggest-baseline.json"), "w") as f:
        params = get_suggest_baseline(
            model_name, job_id, role, baseline_uri, kms_key_id
        )
        json.dump(params, f)

    # Write the dev & prod params for CFN
    with open(os.path.join(output_dir, "deploy-model-dev.json"), "w") as f:
        params = get_dev_params(model_name, job_id, role, image_uri, kms_key_id)
        json.dump(params, f)
    with open(os.path.join(output_dir, "template-model-prd.json"), "w") as f:
        params = get_prd_params(model_name, job_id, role, image_uri, kms_key_id)
        json.dump(params, f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load parameters")
    parser.add_argument("--pipeline-name", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--data-bucket", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ecr-dir", required=False)
    parser.add_argument("--kms-key-id", required=True)
    args = vars(parser.parse_args())
    print("args: {}".format(args))
    main(**args)

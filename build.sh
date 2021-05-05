#!/bin/bash
set -euxo pipefail

NOW=$(date +"%x %r %Z")
echo "Time: $NOW"

if [ $# -lt 4 ]; then
    echo "Please provide the solution name as well as the base S3 bucket name and the region to run build script."
    echo "For example: chmod a+x build.sh && ./build.sh S3_BUCKET_NAME STACK_NAME REGION STUDIO_ROLE_NAME"
    echo "STUDIO_ROLE_NAME is just the name not ARN from studio console example: AmazonSageMaker-ExecutionRole-20210112T085906"
    exit 1
fi

PREFIX="mlops" # should match the ProjectPrefix parameter in pipeline.yml and studio.yml additional ARN privileges
BUCKET="$PREFIX-$1"
STACK_NAME="$PREFIX-$2"
REGION=$3
ROLE=$4

aws cloudformation delete-stack --stack-name "$STACK_NAME"

rm -rf build
mkdir build
rsync -av --progress . build --exclude build --exclude "*.git*"
cd build
# binding resources of pipeline.yml and studio.yml together with common PREFIX
sed -i -e "s/PROJECT_PREFIX/$PREFIX/g" assets/*.yml pipeline.yml
sed -i -e "s/S3_BUCKET_NAME/$BUCKET/g" pipeline.yml

python -m pip install black==20.8b1 black-nb -q
black .
black-nb --exclude "/(outputs|\.ipynb_checkpoints)/" notebook/mlops.ipynb # workflow.ipynb fails

zip -r project.zip .

aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
aws s3 cp --region "$REGION" project.zip "s3://$BUCKET/"
aws s3 cp --region "$REGION" pipeline.yml "s3://$BUCKET/"
aws s3 cp --region "$REGION" studio.yml "s3://$BUCKET/"

aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"

aws cloudformation create-stack --stack-name "$STACK_NAME" \
    --template-url "https://$BUCKET.s3.$REGION.amazonaws.com/studio.yml" \
    --capabilities CAPABILITY_IAM \
    --parameters ParameterKey=ProjectPrefix,ParameterValue="$PREFIX" \
    ParameterKey=SageMakerStudioRoleName,ParameterValue="$ROLE" \
    ParameterKey=PipelineBucket,ParameterValue="$BUCKET"

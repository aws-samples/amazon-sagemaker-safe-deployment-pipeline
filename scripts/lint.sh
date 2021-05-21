#!/bin/bash

BASE_DIR="$(pwd)"

python -m pip install black==21.5b1 black-nb==0.5.0 -q
black .
black-nb --exclude "/(outputs|\.ipynb_checkpoints)/" --include "$BASE_DIR"/notebook/mlops.ipynb # workflow.ipynb fails

for nb in "$BASE_DIR"/notebook/*.ipynb; do
    python "$BASE_DIR"/scripts/set_kernelspec.py --notebook "$nb" --display-name "conda_python3" --kernel "conda_python3"
done

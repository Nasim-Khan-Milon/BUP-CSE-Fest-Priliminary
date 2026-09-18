#!/bin/bash

if [ "$1" == "i" ]; then
    pip install -r requirements.txt
elif [ "$1" == "dev" ]; then
    uvicorn main:app --reload
elif [ "$1" == "run" ]; then
    uvicorn app.main:app --host 0.0.0.0 --port 8000
elif [ "$1" == "env" ]; then
    source $(conda info --base)/etc/profile.d/conda.sh
    conda activate ai_starter
fi

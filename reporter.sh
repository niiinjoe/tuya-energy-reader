#!/bin/bash

# --- Configuration ---
# Load environment variables from .env file if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

if [ -z "$TUYA_DEVICE_ID" ]; then
    echo "Error: TUYA_DEVICE_ID must be set."
    echo "Please configure it in your .env file."
    exit 1
fi

VENV_PATH="venv"

# --- Python Venv ---
if [ ! -d "$VENV_PATH" ]; then
    echo "Error: Virtual environment not found at '$VENV_PATH'."
    exit 1
fi
source "$VENV_PATH/bin/activate"

python reporter.py --device-id=$TUYA_DEVICE_ID "$@"

deactivate

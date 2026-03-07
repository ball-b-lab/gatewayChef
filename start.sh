#!/bin/bash

# Ensure we are in the script's directory
cd "$(dirname "$0")"

VENV_DIR="venv"

echo "--- Gateway Provisioner Launcher ---"

# 1. Check/Create Virtual Environment
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv $VENV_DIR
fi

# 2. Activate Virtual Environment
source $VENV_DIR/bin/activate

# 3. Upgrade pip (good practice)
echo "Checking pip..."
pip install --upgrade pip --quiet

# 4. Install Dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# 5. Run Migrations
echo "Running migrations..."
python scripts/migrate.py

# 6. Start Application
echo "Starting App..."
python app.py

#!/bin/bash

# Initialize and run the Lotus Chess Analysis Service

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not found. Please install Python 3.9 or higher."
    exit 1
fi

# Set up virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Setting up virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Failed to create virtual environment. Please make sure venv module is installed."
        exit 1
    fi
    # Flag that we need to install requirements since this is a new environment
    INSTALL_REQUIREMENTS=true
else
    echo "Virtual environment already exists."
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate || source venv/Scripts/activate

# Check if requirements are already installed
if [ "$INSTALL_REQUIREMENTS" = true ] || ! python -c "import fastapi, uvicorn, socketio, redis, celery" &>/dev/null; then
    echo "Installing requirements..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "Failed to install requirements."
        exit 1
    fi
else
    echo "Requirements already installed, skipping installation."
fi

# Set up Stockfish if needed
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS - check for Mac binary
    STOCKFISH_PATH="stockfish/stockfish-macos-arm"
else
    # Linux/Unix - check for Linux binary
    STOCKFISH_PATH="stockfish/stockfish-linux"
fi

if [ -d "stockfish" ] && [ -f "$STOCKFISH_PATH" ] && [ -x "$STOCKFISH_PATH" ]; then
    echo "Stockfish already installed, skipping setup."
else
    echo "Setting up Stockfish..."
    python setup_stockfish.py
    if [ $? -ne 0 ]; then
        echo "Warning: Failed to set up Stockfish automatically."
        echo "Please download Stockfish from https://stockfishchess.org/download/ manually."
    fi
fi

# Start the FastAPI server
cd "$(dirname "$0")"
echo "Starting Lotus Chess Analysis API server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000

# The script will wait until the server is stopped
#!/bin/bash

# Initialize and run the Lotus Chess Analysis Service

# # Check for Python
# if ! command -v python3 &> /dev/null; then
#     echo "Python 3 is required but not found. Please install Python 3.9 or higher."
#     exit 1
# fi

# # Set up virtual environment if it doesn't exist
# if [ ! -d "venv" ]; then
#     echo "Setting up virtual environment..."
#     python3 -m venv venv
#     if [ $? -ne 0 ]; then
#         echo "Failed to create virtual environment. Please make sure venv module is installed."
#         exit 1
#     fi
# fi

# # Activate virtual environment
# echo "Activating virtual environment..."
# source venv/bin/activate || source venv/Scripts/activate

# # Install requirements
# echo "Installing requirements..."
# pip install -r requirements.txt
# if [ $? -ne 0 ]; then
#     echo "Failed to install requirements."
#     exit 1
# fi

# # Set up Stockfish if needed
# echo "Setting up Stockfish..."
# python setup_stockfish.py
# if [ $? -ne 0 ]; then
#     echo "Warning: Failed to set up Stockfish automatically."
#     echo "Please download Stockfish 17 from https://stockfishchess.org/download/ manually."
# fi

# Start the FastAPI server
cd "$(dirname "$0")"
echo "Starting Lotus Chess Analysis API server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000

# The script will wait until the server is stopped

#!/bin/bash
# Script to run the FastAPI chat server

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Set default port if not specified
export PORT=${PORT:-8000}

# Run the server
echo "Starting SDMX Chat Server on port $PORT..."
echo "Open your browser at: http://localhost:$PORT"
python -m uvicorn app:app --host 0.0.0.0 --port $PORT --reload

#!/bin/bash

# Dental Clinic Bot Startup Script

echo "🦷 Starting Dental Clinic Queue Management Bot..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found!"
    echo "Please create .env file from .env.dental.example"
    echo ""
    echo "cp .env.dental.example .env"
    echo ""
    echo "Then edit .env and set your BOT_TOKEN and other settings."
    exit 1
fi

# Check if running in Docker
if [ -f /.dockerenv ]; then
    echo "🐳 Running in Docker container"
else
    echo "💻 Running locally"
    
    # Check if virtual environment exists
    if [ ! -d ".venv" ]; then
        echo "📦 Creating virtual environment..."
        python3 -m venv .venv
    fi
    
    # Activate virtual environment
    source .venv/bin/activate
    
    # Install/update dependencies
    echo "📦 Installing dependencies..."
    pip install -q -r dental_requirements.txt
fi

# Run the application
echo "🚀 Starting application..."
python -m app.main

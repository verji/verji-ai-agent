#!/bin/bash
set -e

echo "Starting Verji AI Agent development environment..."

# Check if .env exists
if [ ! -f .env ]; then
  echo "Creating .env from .env.example..."
  cp .env.example .env
  echo "⚠️  Please edit .env with your actual credentials"
  exit 1
fi

# Start services
docker-compose up --build


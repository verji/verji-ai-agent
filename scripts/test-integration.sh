#!/bin/bash
set -e

echo "Running integration tests..."

# Ensure services are running
docker-compose ps | grep -q "Up" || {
  echo "Services not running. Starting..."
  docker-compose up -d
  sleep 10
}

# Run integration tests
pytest tests/integration/ -v

echo "✓ Integration tests completed"

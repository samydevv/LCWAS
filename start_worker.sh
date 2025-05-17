#!/bin/bash
# Start Redis server in background (if not already running)
if ! pgrep -x "redis-server" > /dev/null; then
  echo "Starting Redis server..."
  redis-server &
else
  echo "Redis server is already running."
fi

# Wait a moment to ensure Redis is up
sleep 2

# Start Celery worker
echo "Starting Celery worker..."
cd "$(dirname "$0")"
celery -A app.tasks worker --loglevel=info

# The script will wait until Celery is stopped

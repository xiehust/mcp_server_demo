#!/bin/bash
export $(grep -v '^#' .env | xargs)

echo "Stopping services..."

# Stop MCP service
if pgrep -f "main.py.*${MCP_SERVICE_PORT}" > /dev/null; then
    echo "Stopping MCP service on port ${MCP_SERVICE_PORT}"
    lsof -t -i:${MCP_SERVICE_PORT} | xargs kill -9
else
    echo "MCP service not running"
fi

# Stop Chatbot service
if pgrep -f "streamlit.*${CHATBOT_SERVICE_PORT}" > /dev/null; then
    echo "Stopping Chatbot service on port ${CHATBOT_SERVICE_PORT}"
    lsof -t -i:${CHATBOT_SERVICE_PORT} | xargs kill -9
else
    echo "Chatbot service not running"
fi

echo "All services stopped"

# Optional: Check if processes are really stopped
sleep 2
if pgrep -f "main.py.*${MCP_SERVICE_PORT}" > /dev/null || pgrep -f "streamlit.*${CHATBOT_SERVICE_PORT}" > /dev/null; then
    echo "Warning: Some processes may still be running"
    ps aux | grep -E "main.py.*${MCP_SERVICE_PORT}|streamlit.*${CHATBOT_SERVICE_PORT}"
fi
#!/bin/bash
export $(grep -v '^#' .env | xargs)

echo "Stopping services..."

echo "Stopping MCP service on port ${MCP_SERVICE_PORT}"
pid=$(lsof -t -i:${MCP_SERVICE_PORT})
kill -9 $pid

# Stop Chatbot service
echo "Stopping Chatbot service on port ${CHATBOT_SERVICE_PORT}"
pid=$(lsof -t -i:${CHATBOT_SERVICE_PORT} -c streamlit)
kill -9 $pid
echo "All services stopped"
#!/bin/bash
export $(grep -v '^#' .env | xargs)
export PYTHONPATH=./src:$PYTHONPATH

source .venv/bin/activate

# Create necessary directories
mkdir -p ./tmp 
mkdir -p ${LOG_DIR}

# Set environment variables
export MCP_BASE_URL=http://${MCP_SERVICE_HOST}:${MCP_SERVICE_PORT}

# Kill existing processes on ports if any
lsof -t -i:${MCP_SERVICE_PORT} | xargs kill -9 2> /dev/null
lsof -t -i:${CHATBOT_SERVICE_PORT} | xargs kill -9 2> /dev/null

# Start MCP service
echo "Starting MCP service..."
nohup python src/main.py --mcp-conf conf/config.json \
    --host ${MCP_SERVICE_HOST} --port ${MCP_SERVICE_PORT} > ${LOG_DIR}/start_mcp.log 2>&1 &

# Start Chatbot service 
echo "Starting Chatbot service..."
nohup streamlit run chatbot.py \
    --server.port ${CHATBOT_SERVICE_PORT} > ${LOG_DIR}/start_chatbot.log 2>&1 &

echo "Services started. Check logs in ${LOG_DIR}"

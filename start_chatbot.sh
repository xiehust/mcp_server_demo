#!/bin/bash
export $(grep -v '^#' .env | xargs)

mkdir -p ${LOG_DIR}

port=${CHATBOT_SERVICE_PORT}
export MCP_BASE_URL=http://${MCP_SERVICE_HOST}:${MCP_SERVICE_PORT}

lsof -t -i:$port -c streamlit| xargs kill -9 2> /dev/null
nohup streamlit run chatbot.py \
    --server.port ${port} > ${LOG_DIR}/start_chatbot.log 2>&1 &

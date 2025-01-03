export $(grep -v '^#' .env | xargs)
export PYTHONPATH=./src:$PYTHONPATH

source .venv/bin/activate

mkdir -p ./tmp
mkdir -p ${LOG_DIR}

host=${MCP_SERVICE_HOST}
port=${MCP_SERVICE_PORT}

lsof -t -i:$port | xargs kill -9 2> /dev/null
nohup python src/main.py --mcp-conf conf/config.json \
    --host ${host} --port ${port} > ${LOG_DIR}/start_mcp.log 2>&1 &

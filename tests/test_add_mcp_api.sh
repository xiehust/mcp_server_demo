git init -q tmp/codebase

curl http://127.0.0.1:7002/v1/add/mcp_server \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "dev_git",
    "command": "uvx",
    "args": ["mcp-server-git", "--repository", "tmp/codebase"]
  }'


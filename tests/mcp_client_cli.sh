mkdir -p ./tmp

#python src/chat_client.py amazon.nova-lite-v1:0 \
#    aws_kb_retrieval ../mcp-servers/aws-kb-retrieval-server/dist/index.js -- \
#    local_fs ../mcp-servers/filesystem/dist/index.js ./tmp -- \
#    db_sqlite uvx:mcp-server-sqlite --db-path ./tmp/test.db

python src/chat_client.py amazon.nova-lite-v1:0 \
    local_fs npx:@modelcontextprotocol/server-filesystem ./tmp -- \
    db_sqlite uvx:mcp-server-sqlite --db-path ./tmp/test.db

curl http://127.0.0.1:7002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 123456" \
  -d '{
    "model": "amazon.nova-lite-v1:0",
    "messages": [
      {
        "role": "user",
        "content": "show all of tables in db"
      }
    ]
  }'


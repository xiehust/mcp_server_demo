# Amazon Nova MCP demo [[中文说明](./README.md)]

> ChatBot is the most common application form in the large model era. However, limited by large models' inability to obtain real-time information and operate external systems, ChatBot application scenarios are relatively limited. Later, with the launch of Function Calling/Tool Use features, large models could interact with external systems, but the drawback was that the large model business logic and Tool development were tightly coupled, unable to leverage the efficiency of Tool-end scaling. In late November 2024, Anthropic launched [MCP](https://www.anthropic.com/news/model-context-protocol), breaking this situation by introducing community power to scale up on the Tool end. Currently, the open-source community and various vendors have developed rich [MCP servers](https://github.com/modelcontextprotocol/servers), making the Tool end flourish. End users can plug and play to integrate them into their ChatBots, greatly extending ChatBot UI capabilities, showing a trend of ChatBots unifying various system UIs.

This project provides ChatBot interaction services based on **Bedrock** large models (Amazon Nova, Anthropic Claude etc) while introducing **MCP**, greatly enhancing and extending ChatBot-form product application scenarios, supporting seamless integration with local file systems, databases, development tools, internet search, and more. If a ChatBot with large models is like a brain, then introducing MCP is like adding arms and legs, truly making the large model move and connect with various existing systems and data.

![](docs/arch.png)

This project is still being continuously explored and improved, and MCP is flourishing in the entire community. Everyone is welcome to follow along!

## Project Features:
- Simultaneously supports Amazon Nova Pro and Claude Sonnet3.5 models
- Fully compatible with Anthropic's official MCP standard, allowing direct use of various community [MCP servers](https://github.com/modelcontextprotocol/servers/tree/main) in the same way
- Decouples MCP capabilities from the client, encapsulates MCP functionality on the server side, provides external API services, and maintains OpenAI-compatible chat API for easy integration with other chat clients
![alt text](./docs/image_api.png)

## 1. Dependencies Installation

Currently, mainstream MCP Servers are developed and run on users' PCs using NodeJS or Python, so these dependencies need to be installed on the user's PC.

### NodeJS

Download and install NodeJS from [here](https://nodejs.org/en). This project has been thoroughly tested with version `v22.12.0`.

### Python

Some MCP Servers are developed in Python, so users must install [Python](https://www.python.org/downloads/). Additionally, this project's code is developed in Python and requires environment and dependency installation.

First, install the Python package management tool uv. Refer to the official [uv guide](https://docs.astral.sh/uv/getting-started/installation/). This project has been thoroughly tested with version `v0.5.11`.

## 2. Environment and Configuration

### Environment Preparation

After downloading and cloning the project, enter the project directory, create a Python virtual environment, and install dependencies:
```bash
uv sync
```

The virtual environment will be created in the `.venv` directory of the project. Activate it:
```
source .venv/bin/activate
```

### Configuration Setup

Project configuration should be written in the `.env` file and include the following items (suggested to copy from `env_dev` and modify):

```
AWS_ACCESS_KEY_ID=<your-access-key>
AWS_SECRET_ACCESS_KEY=<your-secret-key>
AWS_REGION=us-east-1
LOG_DIR=./logs
CHATBOT_SERVICE_PORT=<chatbot-ui-service-port>
MCP_SERVICE_HOST=127.0.0.1
MCP_SERVICE_PORT=<bedrock-mcp-service-port>
API_KEY=<your-new-api-key>
```

Note: This project uses **AWS Bedrock Nova** series models, so you need to register and obtain the above service access keys.

## 3. Running

This project includes two services:

- **Chat Interface Service (Bedrock+MCP)**: Provides Chat API, hosts multiple MCP servers, supports multi-turn conversation history input, includes tool call intermediate results in responses, currently doesn't support streaming responses.  
- The interface service can provide independent APIs to external clients, allowing other chat clients to connect and achieve decoupling between server-side MCP capabilities and client-side functions
- API documentation can be viewed at http://{ip}:7002/docs#/
![alt text](./docs/image_api.png)
- **ChatBot UI Service**: Communicates with the above Chat interface service, provides multi-turn conversation and MCP management Web UI demo service

### Chat Interface Service (Bedrock+MCP)

Edit the configuration file `conf/config.json`, which presets which MCP servers to start. You can edit it to add or modify MCP server parameters.

For MCP server parameter specifications, refer to this example:

```
"db_sqlite": {
    "command": "uvx",
    "args": ["mcp-server-sqlite", "--db-path", "./tmp/test.db"],
    "env": {},
    "description": "DB Sqlite CRUD - MCP Server",
    "status": 1
}
```

Start the service:

```bash
bash start_all.sh
```

After startup, check the log `logs/start_mcp.log` for any errors, then run the test script to check the Chat interface:

```bash
# Script uses Amazon Nova-lite model from Bedrock, can be changed to others
# Use 123456 as API key by default, please change it to your actual api key
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
```

### ChatBot UI Service

After startup, check the log `logs/start_chatbot.log` for any errors, then open the [service address](http://localhost:8502/) in a browser to experience the Bedrock large model ChatBot capabilities enhanced by MCP.

With built-in file system operations, SQLite database, and other MCP Servers, you can try asking these consecutive questions:

```
show all of tables in the db
how many rows in that table
show all of rows in that table
save those rows record into a file, filename is rows.txt
list all of files in the allowed directory
read the content of rows.txt file
```

## 4. Adding MCP Servers

Currently, there are two ways to add MCP Servers:

1. Preset in `conf/config.json`, which will load configured MCP Servers every time the Chat interface service restarts
2. Add MCP Servers through ChatBot UI by submitting MCP Server parameters via form, effective only for the current session and lost after service restart

Here's a demonstration of adding an MCP Server through ChatBot UI, using the Web Search provider [Exa](https://exa.ai/) as an example. The open-source community has an available [MCP Server](https://github.com/exa-labs/exa-mcp-server) for it.

First, go to [Exa](https://exa.ai/) website to register an account and obtain an API Key.

Then click [Add MCP Server], fill in the following parameters in the popup menu and submit:
- Method 1: Directly add MCP json configuration file (same format as Anthropic official)
![](docs/add_mcp_server2.png)  
```json
{
  "mcpServers": {
    "exa": {
      "command": "npx",
      "args": ["-y","exa-mcp-server"],
      "env": {
        "EXA_API_KEY": "your-api-key-here"
      }
    }
  }
}
```
- Method 2: Add by fields
![](docs/add_mcp_server.png)  
The newly added item will appear in the existing MCP Server list, check it to start the MCP Server.

## 5. Enable Deep Research
- Simultaneously enable websearch (refer to the EXA configuration above) and [Sequential Thinking MCP Server](https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking). The Sequential Thinking MCP Server is already preset in the configuration file, and after startup, you can see the server name is "cot".
![alt text](docs/image-serverlist.png)
- Sequential Thinking provides structured thinking processes and reflection through dynamic tool calls, prompting the model to output structured reasoning chains according to the tool's input requirements.
- EXA Search provides both keyword and vector retrieval search for network knowledge, returning detailed content from web pages.
- Test Questions
```
1. use search tool and sequential thinking to make comparison report between different agents frameworks such as autogen, langgraph, aws multi agents orchestrator
2. use sequential thinking and search tool to make me a travel plan to visit shanghai between 3/1/2025 to 3/5/2025. I will departure from Beijing
3. use sequential thinking to research what the key breakthroughs and future impact of deepseek r1
4. use search tool to compare the API performance of Deepseek R1 full version provided by Volcano Engine, Ali Bailian, and Silicon Flow, including inference speed, TTFT, maximum context length, etc. Use sequential thinking tool
```
- Effect Preview
![alt text](docs/image_deepresearch_1.png)
![alt text](docs/image_deepresearch_2.png)

## 6. Stop Services
```bash
bash stop_all.sh
```

[LICENSE](./LICENSE)
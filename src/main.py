import os
import sys
import json
import time
import argparse
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Literal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Security
from pydantic import BaseModel, Field
from fastapi.exceptions import RequestValidationError
from mcp_client import MCPClient
from chat_client import ChatClient

mcp_client = MCPClient()
chat_client = ChatClient()
mcp_server_list = {}
llm_model_list = {}

load_dotenv() # load env vars from .env

API_KEY = os.environ.get("API_KEY")
security = HTTPBearer()

logger = logging.getLogger(__name__)

app = FastAPI()


async def get_api_key(auth: HTTPAuthorizationCredentials = Security(security)):
    if auth.credentials == API_KEY:
        return auth.credentials
    raise HTTPException(status_code=403, detail="Could not validate credentials")

class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    messages: List[Message]
    model: str
    max_tokens: int = 900
    temperature: float = 0.5
    top_p: float = 0.9
    top_k: int = 50
    stream: Optional[bool] = None
    tools: Optional[List[dict]] = None
    options: Optional[dict] = None
    keep_alive: Optional[bool] = None
    mcp_server_ids: Optional[List[str]] = None

class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int]

class AddMCPServerRequest(BaseModel):
    server_id: str = ''
    server_desc: str
    command: Literal["npx", "uvx", "node", "python","docker"] = Field(default='npx')
    args: List[str] = []
    env: Dict[str, str] = Field(default_factory=dict)
    config_json: Dict[str,Any] = Field(default_factory=dict)
    

class AddMCPServerResponse(BaseModel):
    errno: int
    msg: str = "ok"
    data: Dict[str, Any] = Field(default_factory=dict)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.error(f"Validation error: {exc}")
    return JSONResponse(content=AddMCPServerResponse(
                errno=422,
                msg=str(exc.errors())
            ).model_dump())

@app.get("/v1/list/models")
async def list_models(request: Request):
    return JSONResponse(content={"models": [{
        "model_id": mid, 
        "model_name": name} for mid, name in llm_model_list.items()]})

@app.get("/v1/list/mcp_server")
async def list_mcp_server(request: Request):
    return JSONResponse(content={"servers": [{
        "server_id": sid, 
        "server_name": name} for sid, name in mcp_server_list.items()]})

@app.post("/v1/add/mcp_server")
async def add_mcp_server(request: Request,
        data: AddMCPServerRequest,
        background_tasks: BackgroundTasks):
    if data.server_id in mcp_server_list:
        return JSONResponse(content=AddMCPServerResponse(
            errno=-1,
            msg="MCP server id exists!"
        ).model_dump())
    
    server_id=data.server_id
    server_cmd=data.command
    server_script_args=data.args
    server_script_envs=data.env
    server_desc = data.server_desc
    # if config_json is not empty, use it to update config
    if data.config_json:
        config_json = data.config_json
        if not all([isinstance(k, str) for k in config_json.keys()]):
            return JSONResponse(content=AddMCPServerResponse(
                errno=-1,
                msg="env key must be str!"
            ).model_dump())
        if "mcpServers" in config_json:
            config_json = config_json["mcpServers"]
        #直接使用json配置里的id
        logging.info(f'add new mcp server: {config_json}')
        server_id = list(config_json.keys())[0]
        server_cmd = config_json[server_id]["command"]
        server_script_args = config_json[server_id]["args"]
        server_script_envs = config_json[server_id]["env"]
    # connect mcp server
    try:
        await mcp_client.connect_to_server(
            server_id=server_id,
            command=server_cmd,
            server_script_args=server_script_args,
            server_script_envs=server_script_envs
        )
        tool_conf = await mcp_client.get_tool_config(server_ids=[server_id])
        logger.info(f"Connected MCP server {server_id}, tools={tool_conf}")
    except Exception as e:
        tool_conf = {}
        logger.error(f"Connect MCP server {server_id} error: {e}")
        return JSONResponse(content=AddMCPServerResponse(
            errno=-1,
            msg="MCP server connect failed!"
        ).model_dump())

    # add to server list
    mcp_server_list[server_id] = server_desc
    
    return JSONResponse(content=AddMCPServerResponse(
        errno=0,
        msg="The server already been added!",
        data={"tools": tool_conf.get("tools", {}) if tool_conf else {}}
    ).model_dump())

@app.post("/v1/chat/completions")
async def chat_completions(request: Request, 
        data: ChatCompletionRequest, 
        background_tasks: BackgroundTasks,
        #auth: HTTPAuthorizationCredentials = Security(security)
        ):
    #await get_api_key(auth)

    if not data.messages:
        return JSONResponse(content=ChatResponse(
            model=data.model,
            created_at=time.time(),
            message=Message(role="assistant", content=""),
            done=True,
            done_reason="load"
        ).dict())

    messages = [{
        "role": x.role,
        "content": [{"text": x.content}],
    } for x in data.messages]

    # bedrock's first turn cannot be assistant
    if messages and messages[0]['role'] == 'assistant':
        messages = messages[1:]

    logger.info(f"request body: {messages}")

    try:
        tool_use_info = {}
        async for response in chat_client.process_query(
                model_id=data.model,
                max_tokens=data.max_tokens,
                history=messages,
                mcp_client=mcp_client,
                mcp_server_ids=data.mcp_server_ids,
                ):
            logger.info(f"response body: {response}")
            is_tool_use = any([bool(x.get('toolUse')) for x in response['content']])
            is_tool_result = any([bool(x.get('toolResult')) for x in response['content']])
            is_answer = any([bool(x.get('text')) for x in response['content']])

            if is_tool_use:
                for x in response['content']:
                    if 'toolUse' not in x or not x['toolUse'].get('name'):
                        continue
                    tool_id = x['toolUse'].get('toolUseId')
                    if not tool_id:
                        continue
                    if tool_id not in tool_use_info:
                        tool_use_info[tool_id] = {}
                    tool_use_info[tool_id]['name'] = x['toolUse']['name']
                    tool_use_info[tool_id]['arguments'] = x['toolUse']['input']

            if is_tool_result:
                for x in response['content']:
                    if 'toolResult' not in x:
                        continue
                    tool_id = x['toolResult'].get('toolUseId')
                    if not tool_id:
                        continue
                    if tool_id not in tool_use_info:
                        tool_use_info[tool_id] = {}
                    tool_use_info[tool_id]['result'] = x['toolResult']['content'][0]['text']

            if is_tool_use or is_tool_result:
                continue

            #logger.info(tool_use_info)

            chat_response = ChatResponse(
                id=f"chat{time.time_ns()}",
                created=int(time.time()),
                model=data.model,
                choices=[
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response['content'][0]['text'],
                        },
                        "message_extras": {
                            "tool_use": [info for too_id, info in tool_use_info.items()],
                        },
                        "logprobs": None,  
                        "finish_reason": "stop", 
                    }
                ],
                usage={
                    "prompt_tokens": 0, 
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }
            )
            
            return JSONResponse(content=chat_response.dict())
    except Exception as e:
        logger.error(str(e))
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == '__main__':
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7002)
    parser.add_argument('--mcp-conf', default='', help="the mcp servers json config file")
    args = parser.parse_args()
    
    try:
        loop = asyncio.new_event_loop()

        if args.mcp_conf:
            with open(args.mcp_conf, 'r') as f:
                conf = json.load(f)
                for server_id, server_conf in conf.get('mcpServers', {}).items():
                    if server_conf.get('status') == 0:
                        continue
                    loop.run_until_complete(mcp_client.connect_to_server(
                        server_id=server_id,
                        command=server_conf['command'],
                        server_script_args=server_conf['args'],
                        server_script_envs=server_conf.get('env', {})
                    ))
                    mcp_server_list[server_id] = server_conf.get('description', server_id)

                for model_conf in conf.get('models', []):
                    llm_model_list[model_conf['model_id']] = model_conf['model_name']

        config = uvicorn.Config(app, host=args.host, port=args.port, loop=loop)
        server = uvicorn.Server(config)
        loop.run_until_complete(server.serve())
    finally:
        loop.close()
        asyncio.run(mcp_client.cleanup())

"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""
"""
MCP Client maintains Multi-MCP-Servers
"""
import os
import logging
import asyncio
from typing import Optional, Dict
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client, get_default_environment
from mcp.types import Resource, Tool, TextContent, ImageContent, EmbeddedResource

from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
delimiter = "___"

class MCPClient:
    """Manage MCP sessions.

    Support features:
    - MCP multi-server
    - get tool config from server
    - call tool and get result from server
    """

    def __init__(self, access_key_id='', secret_access_key='', region='us-east-1'):
        self.env = {
            'AWS_ACCESS_KEY_ID': access_key_id or os.environ.get('AWS_ACCESS_KEY_ID'),
            'AWS_SECRET_ACCESS_KEY': secret_access_key or os.environ.get('AWS_SECRET_ACCESS_KEY'),
            'AWS_REGION': region or os.environ.get('AWS_REGION'),
        }
        self.sessions: Dict[str, Optional[ClientSession]] = {}
        self.exit_stack = AsyncExitStack()
        self._tool_name_mapping = {}
        self._tool_name_mapping_r = {}

    def _normalize_tool_name(self, tool_name):
        return tool_name.replace('-', '_').replace('/', '_').replace(':', '_')

    def _get_tool_name4llm(self, server_id, tool_name, norm=True, ns_delimiter=delimiter):
        """Convert MCP server tool name to llm tool call"""
        # prepend server prefix namespace to support multi-mcp-server
        tool_key = server_id + ns_delimiter + tool_name
        tool_name4llm = tool_key if not norm else self._normalize_tool_name(tool_key)
        self._tool_name_mapping[tool_key] = tool_name4llm
        self._tool_name_mapping_r[tool_name4llm] = tool_key
        return tool_name4llm

    def _get_tool_name4mcp(self, tool_name4llm, ns_delimiter=delimiter):
        """Convert llm tool call name to MCP server original name"""
        server_id, tool_name = "", ""
        tool_name4mcp = self._tool_name_mapping_r.get(tool_name4llm, "")
        if len(tool_name4mcp.split(ns_delimiter)) == 2:
            server_id, tool_name = tool_name4mcp.split(ns_delimiter)
        return server_id, tool_name

    async def disconnect_to_server(self, server_id: str):
        if server_id in self.sessions:
            del self.sessions[server_id]
            logger.info(f"\nDisconnected to server [{server_id}]")
        else:
            logger.error(f"\nDisconnected not found server [{server_id}]")

    async def connect_to_server(self, server_id: str, 
            server_script_path: str = "", server_script_args: list = [], 
            server_script_envs: Dict = {}, command: str = ""):
        """Connect to an MCP server"""
        if not ((command and server_script_args) or server_script_path):
            raise ValueError("Run server via script or command.")

        if server_id in self.sessions:
            raise ValueError("Server already start a session")

        if server_script_path:
            # run via script
            is_python = server_script_path.endswith('.py')
            is_js = server_script_path.endswith('.js')
            is_uv = server_script_path.startswith('uvx:')
            is_np = server_script_path.startswith('npx:')
            is_docker = server_script_path.startswith('docker:')

            if not (is_python or is_js or is_uv or is_np or is_docker):
                raise ValueError("Server script must be a .py or .js file or package")
            if is_uv or is_np:
                server_script_path = server_script_path[server_script_path.index(':')+1:]

            server_script_args = [server_script_path] + server_script_args
    
            if is_python:
                command = "python"
            elif is_uv:
                command = "uvx"
            elif is_np:
                command = "npx"
                server_script_args = ["-y"] + server_script_args
            elif is_js:
                command = "node"
            elif is_docker:
                command = "docker"
        else:
            # run via command
            if command not in ["npx", "uvx", "node", "python","docker"]:
                raise ValueError("Server command must be in the npx/uvx/node/python/docker")

        env = get_default_environment()
        env['AWS_ACCESS_KEY_ID'] = self.env['AWS_ACCESS_KEY_ID']
        env['AWS_SECRET_ACCESS_KEY'] = self.env['AWS_SECRET_ACCESS_KEY']
        env['AWS_REGION'] = self.env['AWS_REGION']
        env.update(server_script_envs)

        server_params = StdioServerParameters(
            command=command, args=server_script_args, env=env
        )
        logger.info(f"\nAdd server %s %s" % (command, server_script_args))
    
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        _stdio, _write = stdio_transport
        self.sessions[server_id] = await self.exit_stack.enter_async_context(ClientSession(_stdio, _write))
    
        await self.sessions[server_id].initialize()
    
        # List available tools
        response = await self.sessions[server_id].list_tools()
        tools = response.tools
        logger.info(f"\nConnected to server [{server_id}] with tools: " + str([tool.name for tool in tools]))

    async def get_tool_config(self, model_provider='bedrock', server_ids: list = []):
        """Get llm's tool usage config via MCP server"""
        # list tools via mcp server
        responses = [(server_id, await self.sessions[server_id].list_tools()) 
                     for server_id in self.sessions if not server_ids or server_id in server_ids]

        if not responses:
            return None

        # for bedrock tool config
        tool_config = {"tools": []}
        for server_id, response in responses:
            tool_config["tools"].extend([{
                "toolSpec":{
                    # mcp tool's original name to llm tool name (with server id namespace)
                    "name": self._get_tool_name4llm(server_id, tool.name, norm=True),
                    "description": tool.description, 
                    "inputSchema": {"json": tool.inputSchema}
                }
            } for tool in response.tools])

        return tool_config

    async def call_tool(self, tool_name, tool_args, server_id=""):
        """Call tool via MCP server"""
        if not server_id:
            server_id, tool_name = self._get_tool_name4mcp(tool_name)  # llm tool name to mcp

        if not server_id or server_id not in self.sessions:
            raise ValueError("Call tool should with server id")

        result = await self.sessions[server_id].call_tool(tool_name, tool_args)
        return result

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()

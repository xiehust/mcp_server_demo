"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""
import os
import sys
import asyncio
import logging
from typing import Dict

import boto3
from botocore.config import Config

from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env

logger = logging.getLogger(__name__)


class ChatClient:
    """Bedrock simple chat wrapper"""

    def __init__(self, access_key_id='', secret_access_key='', region='us-east-1'):
        self.env = {
            'AWS_ACCESS_KEY_ID': access_key_id or os.environ.get('AWS_ACCESS_KEY_ID'),
            'AWS_SECRET_ACCESS_KEY': secret_access_key or os.environ.get('AWS_SECRET_ACCESS_KEY'),
            'AWS_REGION': region or os.environ.get('AWS_REGION'),
        }

    def _get_bedrock_client(self, runtime=True):
        bedrock_client = boto3.client(
            service_name='bedrock-runtime' if runtime else 'bedrock',
            aws_access_key_id=self.env['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=self.env['AWS_SECRET_ACCESS_KEY'],
            region_name=self.env['AWS_REGION'],
            config=Config(
                retries={
                    "max_attempts": 10,
                    "mode": "standard",
                },
            )
        )

        return bedrock_client
    
    async def process_query(self, query: str = "", 
            model_id="amazon.nova-lite-v1:0", max_tokens=1024, temperature=0.1,max_turns=10,
            history=[], mcp_client=None, mcp_server_ids=[]) -> Dict:
        """Submit user query or history messages, and then get the response answer.

        Note the specified mcp servers' tool maybe used.
        """
        if query:
            history.append({
                    "role": "user",
                    "content": [{"text": query}]
            })
        messages = history

        # get tools from mcp server
        tool_config = None
        if mcp_client is not None:
            tool_config = await mcp_client.get_tool_config(server_ids=mcp_server_ids)

        # logger.info(f"tool_config: {tool_config}")
        bedrock_client = self._get_bedrock_client()

        # invoke bedrock llm with user query
        if tool_config:
            response = bedrock_client.converse(
                modelId=model_id,
                messages=messages,
                toolConfig=tool_config,
                inferenceConfig={"maxTokens":max_tokens,"temperature":temperature,}
            )
        else:
            response = bedrock_client.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig={"maxTokens":max_tokens,"temperature":temperature,}

            )

        # the response may or not request tool use
        output_message = response['output']['message']
        messages.append(output_message)
        stop_reason = response['stopReason']

        if stop_reason == 'end_turn':
            # normal chat finished
            yield output_message
        elif stop_reason == 'tool_use' and mcp_client is not None:
            # return tool request use
            yield output_message
            # multi-loop tool calling
            turn_i = 1
            while stop_reason == 'tool_use' and turn_i <= max_turns:
                logger.info(f"Use tool turn-{turn_i}")
                # tool call has been requested. 
                tool_requests = response['output']['message']['content']

                # 收集所有需要调用的工具请求
                tool_calls = []
                for tool_request in tool_requests:
                    if 'toolUse' in tool_request:
                        tool = tool_request['toolUse']
                        tool_calls.append(tool)
                # 并行执行所有工具调用
                async def execute_tool_call(tool):
                    logger.info("Call tool: %s" % tool)
                    try:
                        tool_name, tool_args = tool['name'], tool['input']
                        result = await mcp_client.call_tool(tool_name, tool_args)
                        result_content = [{"text": "\n".join([x.text for x in result.content if x.type == 'text'])}]
                        return {
                            "toolUseId": tool['toolUseId'],
                            "content": result_content
                        }
                    except Exception as err:
                        err_msg = f"{tool['name']} tool call is failed. error:{err}"
                        return {
                            "toolUseId": tool['toolUseId'],
                            "content": [{"text": err_msg}],
                            "status": 'error'
                        }
                # 使用 asyncio.gather 并行执行所有工具调用
                tool_results = await asyncio.gather(*[execute_tool_call(tool) for tool in tool_calls])
                # 处理所有工具调用的结果
                tool_results_content = []
                for tool_result in tool_results:
                    logger.info("Call tool result: Id: %s" % (tool_result['toolUseId']) )
                    tool_results_content.append({"toolResult": tool_result})
                # save tool call result
                tool_result_message = {
                    "role": "user",
                    "content": tool_results_content
                }
                messages.append(tool_result_message)
                # return tool use results
                yield tool_result_message

                # send the tool results to the model.
                response = bedrock_client.converse(
                    modelId=model_id,
                    messages=messages,
                    toolConfig=tool_config,
                )
                stop_reason = response['stopReason']
                output_message = response['output']['message']
                messages.append(output_message)
                # return user query's answer
                yield output_message
                turn_i += 1
    
    async def chat_loop_cli(self, model_id="amazon.nova-lite-v1:0", mcp_client=None):
        """Run an interactive chat loop"""

        print("\nChat with Bedrock+MCP now!")
        print("Type your queries or 'quit' to exit.")
    
        history = []
        while True:
            try:
                query = input("\nQuery: ").strip()
    
                if query.lower() == 'quit':
                    break
    
                async for response in self.process_query(query, model_id=model_id, 
                                                         history=history, mcp_client=mcp_client):
                    print("\n")
                    print(response)
                    print("\n")
            except Exception as e:
                print(f"\nError: {str(e)}")
    

async def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s: %(message)s")

    if len(sys.argv) < 3:
        print("Usage: python client.py <mcp_server_id> <path_to_server_script> <server_script_args> -- <mcp_server_id> <path_to_server_script> <server_script_args>")
        sys.exit(1)

    model_id = sys.argv[1]
    server_args = [[]]
    for arg in sys.argv[2:]:
        if arg == '--':
            server_args.append([])
        else:
            server_args[-1].append(arg)

    try:
        mcp_client = MCPClient()
        for args in server_args:
            if len(args) < 2:
                continue
            server_id, server_script, server_script_args = args[0], args[1], args[2:]
            await mcp_client.connect_to_server(server_id, server_script, server_script_args)

        chat_client = ChatClient()
        await chat_client.chat_loop_cli(model_id=model_id, mcp_client=mcp_client)
    finally:
        await mcp_client.cleanup()


if __name__ == "__main__":
    from mcp_client import MCPClient
    asyncio.run(main())

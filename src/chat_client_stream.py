"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""
import os
import sys
import asyncio
import logging
from typing import Dict, AsyncGenerator, Optional, List, AsyncIterator
import json
import boto3
from botocore.config import Config
from dotenv import load_dotenv

from chat_client import ChatClient

load_dotenv()  # load environment variables from .env
logger = logging.getLogger(__name__)

class ChatClientStream(ChatClient):
    """Extended ChatClient with streaming support"""

    async def _process_stream_response(self, response) -> AsyncIterator[Dict]:
        """Process the raw response from converse_stream"""
        for event in response['stream']:
            # Handle message start
            if "messageStart" in event:
                yield {"type": "message_start", "data": event["messageStart"]}
                continue

            # Handle content block start
            if "contentBlockStart" in event:
                block_start = event["contentBlockStart"]
                yield {"type": "block_start", "data": block_start}
                continue

            # Handle content block delta
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"]
                yield {"type": "block_delta", "data": delta}
                continue

            # Handle content block stop
            if "contentBlockStop" in event:
                yield {"type": "block_stop", "data": event["contentBlockStop"]}
                continue

            # Handle message stop
            if "messageStop" in event:
                yield {"type": "message_stop", "data": event["messageStop"]}
                continue

            # Handle metadata
            if "metadata" in event:
                yield {"type": "metadata", "data": event["metadata"]}
                continue

    async def process_query_stream(self, query: str = "",
            model_id="amazon.nova-lite-v1:0", max_tokens=1024, max_turns=10,temperature=0.1,
            history=[], mcp_client=None, mcp_server_ids=[]) -> AsyncGenerator[Dict, None]:
        """Submit user query or history messages, and get streaming response.
        
        Similar to process_query but uses converse_stream API for streaming responses.
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

        bedrock_client = self._get_bedrock_client()
        
        # Track the current tool use state
        current_tool_use = None
        current_tooluse_input = ''
        tool_results = []
        text = ''
        stop_reason = ''
        turn_i = 1

        while turn_i <= max_turns and stop_reason != 'end_turn':
            # invoke bedrock llm with user query
            try:
                response = bedrock_client.converse_stream(
                    modelId=model_id,
                    messages=messages,
                    toolConfig=tool_config if tool_config else None,
                    inferenceConfig={"maxTokens":max_tokens,"temperature":temperature,}
                    
                )
                turn_i += 1
                # 收集所有需要调用的工具请求
                tool_calls = []
                async for event in self._process_stream_response(response):
                    logger.info(event)
                    # continue
                    yield event
                    # Handle tool use in content block start
                    if event["type"] == "block_start":
                        block_start = event["data"]
                        if "toolUse" in block_start.get("start", {}):
                            current_tool_use = block_start["start"]["toolUse"]
                            tool_calls.append(current_tool_use)
                            logger.info("Tool use detected: %s", current_tool_use)

                    if event["type"] == "block_delta":
                        delta = event["data"]
                        if "toolUse" in delta.get("delta", {}):
                            #Claude 是stream输出input，而Nova是一次性输出
                            #取出最近添加的tool,追加input参数
                            current_tool_use = tool_calls[-1]
                            if current_tool_use:
                                current_tooluse_input += delta["delta"]["toolUse"]["input"]
                                current_tool_use["input"] = current_tooluse_input 
                        if "text" in delta.get("delta", {}):
                            text += delta["delta"]["text"]

                    # Handle tool use input in content block stop
                    if event["type"] == "block_stop":
                        if current_tooluse_input:
                            #取出最近添加的tool,把input str转成json
                            current_tool_use = tool_calls[-1]
                            if current_tool_use:
                                current_tool_use["input"] = json.loads(current_tooluse_input)
                                current_tooluse_input = ''


                    # Handle message stop and tool use
                    if event["type"] == "message_stop":     
                        stop_reason = event["data"]["stopReason"]
                        
                        # Handle tool use if needed
                        if stop_reason == "tool_use" and tool_calls and mcp_client:
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
                            # output tool results
                            event["data"]["tool_results"] = [item for pair in zip(tool_calls, tool_results) for item in pair]
                            yield event
                            #append assistant message   
                            tool_use_block = [{"toolUse":tool} for tool in tool_calls]
                            assistant_message = {
                                "role": "assistant",
                                "content": [{"text": text}] + tool_use_block
                            }             
                            messages.append(assistant_message)

                            #append tooluse result
                            messages.append(tool_result_message)

                            logger.info("Call new turn : %s" % messages)
                            # Start new stream with tool result
                            response = bedrock_client.converse_stream(
                                modelId=model_id,   
                                messages=messages,
                                toolConfig=tool_config
                            )
                            
                            # Reset tool state
                            current_tool_use = None

                        # normal chat finished
                        elif stop_reason in ['end_turn','max_tokens','stop_sequence']:
                            # yield event
                            continue

            except Exception as e:
                logger.error(f"Stream processing error: {e}")
                yield {"type": "error", "data": {"error": str(e)}}
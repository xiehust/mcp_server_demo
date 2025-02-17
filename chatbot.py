import os
import re
import json
import time
import html
import logging
import requests
import streamlit as st
from dotenv import load_dotenv
load_dotenv() # load env vars from .env
API_KEY = os.environ.get("API_KEY")


logging.basicConfig(level=logging.INFO)
mcp_base_url = os.environ.get('MCP_BASE_URL')
mcp_command_list = ["uvx", "npx", "node", "python","docker"]

def request_list_models():
    url = mcp_base_url.rstrip('/') + '/v1/list/models'
    models = []
    try:
        response = requests.get(url,headers={
                        'Authorization': f'Bearer {API_KEY}'
                    })
        data = response.json()
        models = data.get('models', [])
    except Exception as e:
        logging.error('request list models error: %s' % e)
    return models

def request_list_mcp_servers():
    url = mcp_base_url.rstrip('/') + '/v1/list/mcp_server'
    mcp_servers = []
    try:
        response = requests.get(url,headers={
                        'Authorization': f'Bearer {API_KEY}'
                    })
        data = response.json()
        mcp_servers = data.get('servers', [])
    except Exception as e:
        logging.error('request list mcp servers error: %s' % e)
    return mcp_servers

def request_add_mcp_server( server_id, server_name, command, args=[], env={},config_json={}):
    url = mcp_base_url.rstrip('/') + '/v1/add/mcp_server'
    status = False
    try:
        payload = {
            "server_id": server_id,
            "server_desc": server_name,
            "command": command,
            "args": args,
            "env": env,
            "config_json":config_json
        }
        response = requests.post(url, json=payload,headers={
                        'Authorization': f'Bearer {API_KEY}'
                    })
        data = response.json()
        status = data['errno'] == 0
        msg = data['msg']
    except Exception as e:
        msg = "Add MCP server occurred errors!"
        logging.error('request add mcp servers error: %s' % e)
    return status, msg

def process_stream_response(response):
    """Process streaming response and yield content chunks"""
    for line in response.iter_lines():
        logging.info(f"line:{line}")
        if line:
            line = line.decode('utf-8')
            if line.startswith('data: '):
                data = line[6:]  # Remove 'data: ' prefix
                if data == '[DONE]':
                    break
                try:
                    json_data = json.loads(data)
                    delta = json_data['choices'][0].get('delta', {})
                    if 'role' in delta:
                        continue
                    if 'content' in delta:
                        yield delta['content']
                    
                    message_extras = json_data['choices'][0].get('message_extras', {})
                    if "tool_use" in message_extras:
                        yield f"<tool_use>{message_extras['tool_use']}</tool_use>"

                except json.JSONDecodeError:
                    logging.error(f"Failed to parse JSON: {data}")
                except Exception as e:
                    logging.error(f"Error processing stream: {e}")

def request_chat(messages, model_id, mcp_server_ids, stream=False, max_tokens=1024, temperature=0.1):
    url = mcp_base_url.rstrip('/') + '/v1/chat/completions'
    msg, msg_extras = 'something is wrong!', {}
    try:
        payload = {
            'messages': messages,
            'model': model_id,
            'mcp_server_ids': mcp_server_ids,
            'max_tokens': max_tokens,
            'stream': stream ,
            'temperature':temperature
        }
        logging.info('request payload: %s' % payload)
        if stream:
            # Make streaming request
            response = requests.post(url, 
                                    json=payload,
                                    stream=True,
                                    headers={
                                        'Authorization': f'Bearer {API_KEY}',
                                        'Accept': 'text/event-stream' 
                                    })
            if response.status_code == 200:
                return response, {}
            else:
                msg = 'An error occurred when calling the Converse operation: The system encountered an unexpected error during processing. Try your request again.'
                logging.error('request chat error: %d' % response.status_code)
        else:
            # Make request
            response = requests.post(url, json=payload,headers={
                        'Authorization': f'Bearer {API_KEY}'
                    })
            data = response.json()
            msg = data['choices'][0]['message']['content']
            msg_extras = data['choices'][0]['message_extras']

    except Exception as e:
        msg = 'An error occurred when calling the Converse operation: The system encountered an unexpected error during processing. Try your request again.'
        logging.error('request chat error: %s' % e)
    logging.info('response msg: %s' % msg)
    return msg, msg_extras

# st session state
if not 'model_names' in st.session_state:
    st.session_state.model_names = {}
for x in request_list_models():
    st.session_state.model_names[x['model_name']] = x['model_id']

if not 'mcp_servers' in st.session_state:
    st.session_state.mcp_servers = {}
for x in request_list_mcp_servers():
    st.session_state.mcp_servers[x['server_name']] = x['server_id']

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "How can I help you?"}]

if "enable_stream" not in st.session_state:
    st.session_state.enable_stream = True


# add new mcp UI and handle
def add_new_mcp_server_handle():
    status, msg = True, "The server already been added!"
    server_name = st.session_state.new_mcp_server_name
    server_id = st.session_state.new_mcp_server_id
    server_cmd = st.session_state.new_mcp_server_cmd
    server_args = st.session_state.new_mcp_server_args
    server_env = st.session_state.new_mcp_server_env
    server_config_json = st.session_state.new_mcp_server_json_config
    config_json = {}
    if not server_name:
        status, msg = False, "The server name is empty!"
    elif server_name in st.session_state.mcp_servers:
        status, msg = False, "The server name exists, try another name!"

    # 如果server_config_json配置，则已server_config_json为准
    if server_config_json:
        try:
            config_json = json.loads(server_config_json)
            if not all([isinstance(k, str) for k in config_json.keys()]):
                raise ValueError("env key must be str.")
            if "mcpServers" in config_json:
                config_json = config_json["mcpServers"]
            #直接使用json配置里的id
            logging.info(f'add new mcp server: {config_json}')
            server_id = list(config_json.keys())[0]
            server_cmd = config_json[server_id]["command"]
            server_args = config_json[server_id]["args"]
            server_env = config_json[server_id]["env"]
        except Exception as e:
            status, msg = False, "The config must be a valid JSON."

    if  not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', server_id):
        status, msg = False, "The server id must be a valid variable name!"
    elif server_id in st.session_state.mcp_servers.values():
        status, msg = False, "The server id exists, try another one!"
    elif not server_cmd or server_cmd not in mcp_command_list:
        status, msg = False, "The server command is invalid!"
    if server_env:
        try:
            server_env = json.loads(server_env) if not isinstance(server_env, dict) else server_env
            if not all([isinstance(k, str) for k in server_env.keys()]):
                raise ValueError("env key must be str.")
            if not all([isinstance(v, str) for v in server_env.values()]):
                raise ValueError("env value must be str.")
        except Exception as e:
            server_env = {}
            status, msg = False, "The server env must be a JSON dict[str, str]."
    if isinstance(server_args,str):
        server_args = [x.strip() for x in server_args.split(' ') if x.strip()]

    logging.info(f'add new mcp server: {server_id} :{server_name}')
    
    with st.spinner('Add the server...'):
        status, msg = request_add_mcp_server(server_id, server_name, server_cmd, 
                                             args=server_args, env=server_env,config_json = config_json)
    if status:
        st.session_state.mcp_servers[server_name] = server_id

    st.session_state.new_mcp_server_fd_status = status
    st.session_state.new_mcp_server_fd_msg = msg


@st.dialog('MCP Server 配置')
def add_new_mcp_server():
    with st.form("my_form"):
        st.write("**新增 MCP Server**")

        if 'new_mcp_server_fd_status' in st.session_state:
            if st.session_state.new_mcp_server_fd_status:
                succ1 = st.success(st.session_state.new_mcp_server_fd_msg, icon="✅")
                succ2 = st.success("Please **refresh** the page to display it.", icon="📒")
                time.sleep(3)
                succ1.empty()
                succ2.empty()
                st.session_state.new_mcp_server_fd_msg = ""
                st.session_state.new_mcp_server_id = ""
                st.session_state.new_mcp_server_name = ""
                st.session_state.new_mcp_server_args = ""
                st.session_state.new_mcp_server_env = ""
                st.session_state.new_mcp_server_json_config = ""
            else:
                if st.session_state.new_mcp_server_fd_msg:
                    st.error(st.session_state.new_mcp_server_fd_msg, icon="🚨")

        new_mcp_server_name = st.text_input("Server Name", 
                                            value="", placeholder="Name description of server", key="new_mcp_server_name")
        
        new_mcp_server_config_json = st.text_area("使用JSON配置", 
                                    height = 128,
                                    value="", key="new_mcp_server_json_config",
                                    placeholder="需要提供一个有效的JSON字典")
        with st.expander(label='输入字段配置', expanded=False):
            new_mcp_server_id = st.text_input("Server ID", 
                                            value="", placeholder="server id", key="new_mcp_server_id")

            new_mcp_server_cmd = st.selectbox("运行命令", 
                                            mcp_command_list, key="new_mcp_server_cmd")
            new_mcp_server_args = st.text_area("运行参数", 
                                            value="", key="new_mcp_server_args",
                                            placeholder="mcp-server-git --repository path/to/git/repo")
            new_mcp_server_env = st.text_area("环境变量", 
                                            value="", key="new_mcp_server_env",
                                            placeholder="需要提供一个有效的JSON字典")

        submitted = st.form_submit_button("添加", 
                                          on_click=add_new_mcp_server_handle,
                                          disabled=False)

# UI
with st.sidebar:
    llm_model_name = st.selectbox('Bedrock模型',
                                  list(st.session_state.model_names.keys()))
    max_tokens = st.number_input('上下文长度限制',
                                 min_value=64, max_value=8000, value=4000)
    temperature = st.number_input('temperature',
                                 min_value=0.0, max_value=1.0, value=0.1, step=0.01)
    st.session_state.enable_stream = st.toggle('流式输出', value=True)
    with st.expander(label='已有 MCP Servers', expanded=False):
        for i, server_name in enumerate(st.session_state.mcp_servers):
            st.checkbox(label=server_name, value=True, key=f'mcp_server_{server_name}')
    st.button("添加 MCP Server", 
              on_click=add_new_mcp_server)

st.title("💬 Bedrock Chatbot with MCP")

# Display chat messages
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# Handle user input
if prompt := st.chat_input():
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    model_id = st.session_state.model_names[llm_model_name]
    mcp_server_ids = []
    for server_name in st.session_state.mcp_servers:
        server_key = f'mcp_server_{server_name}'
        if st.session_state.get(server_key):
            mcp_server_ids.append(st.session_state.mcp_servers[server_name])

    # Create a placeholder for the assistant's response
    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""
        response, msg_extras = request_chat(st.session_state.messages, model_id, 
                        mcp_server_ids, stream=st.session_state.enable_stream,
                                         max_tokens=max_tokens,
                                         temperature = temperature)
        # Get streaming response
        if st.session_state.enable_stream:
            thinking_content = ""  # 添加变量存储累积的thinking内容
            thinking_expander = None  # 用于存储thinking的expander对象
            if isinstance(response, requests.Response):
                # Process streaming response
                tool_count = 1
                content_block_idx = 0
                thinking_content = ""
                thinking_expander = None
                for content in process_stream_response(response):
                    logging.info(f"content block idx:{content_block_idx}")
                    content_block_idx += 1
                    full_response += content
                    thk_msg, res_msg, tool_msg = "", "", ""
                    thk_regex = r"<thinking>(.*?)</thinking>"
                    tooluse_regex = r"<tool_use>(.*?)</tool_use>"
                    thk_m = re.search(thk_regex, full_response, re.DOTALL)
                    if thk_m:
                        thk_msg = thk_m.group(1)
                        full_response = re.sub(thk_regex, "", full_response)
                        # 如果有新的thinking内容，追加到现有内容中
                        if thk_msg != thinking_content:
                            thinking_content = thk_msg  # 更新thinking内容
                            # 如果expander不存在则创建，否则更新现有的
                            if thinking_expander is None:
                                thinking_expander = st.expander("Thinking")
                            with thinking_expander:
                                st.write(thinking_content)

                    tool_m = re.search(tooluse_regex, full_response, re.DOTALL)
                    if tool_m:
                        tool_msg = tool_m.group(1)
                        full_response = re.sub(tooluse_regex, "", full_response)
                    if tool_msg:
                        # with st.expander("Tool Used"):
                        with st.container(border=True):
                            tool_blocks = json.loads(tool_msg)
                            for i,tool_block in enumerate(tool_blocks):
                                if i%2 == 0:
                                    with st.expander(f"Tool Call:{tool_count}"):
                                        st.json(tool_block)
                                else:
                                    with st.expander(f"Tool Result:{tool_count}"):
                                        st.json(tool_block)
                                        tool_count += 1

                    # Update response in real-time
                    response_placeholder.markdown(full_response + "▌")
                
                # Update final response without cursor
                response_placeholder.markdown(full_response)
            else:
                # Handle error case
                response_placeholder.markdown(response)
                full_response = response
        else:
            tool_msg = ""
            if True or st.session_state.enable_mcp_result == 'Y':
                if msg_extras.get('tool_use', []):
                    tool_msg = f"```\n{json.dumps(msg_extras.get('tool_use', []), indent=4,ensure_ascii=False)}\n```"
            thk_msg, res_msg = "", ""
            thk_regex = r"<thinking>(.*?)</thinking>"
            thk_m = re.search(thk_regex, response, re.DOTALL)
            if thk_m:
                thk_msg = thk_m.group(1)

            res_msg = re.sub(thk_regex, "", response)
            st.write(res_msg)

            if thk_msg:
                with st.expander("Thinking"):
                    st.write(thk_msg)
            if tool_msg:
                with st.expander("Tool Used"):
                    st.json(tool_msg)

            full_response = response 

    # Add assistant's response to chat history
    st.session_state.messages.append({"role": "assistant", "content": full_response})

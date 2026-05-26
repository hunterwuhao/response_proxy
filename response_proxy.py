#!/usr/bin/env python3
"""
Responses API 到 Chat Completions API 的代理转换服务
"""

import json
import uuid
import time
from flask import Flask, request, Response, jsonify, stream_with_context
import requests

app = Flask(__name__)

# 后端 API 配置
BACKEND_URL = "https://your-api-endpoint/v1"  # 替换为您的 API 地址
API_KEY = "your-api-key-here"  # 替换为您的 API Key
DEFAULT_MODEL = "your-default-model"  # 替换为您默认使用的模型

# 支持的模型列表（这些模型会直接使用，其他的会替换成 DEFAULT_MODEL）
SUPPORTED_MODELS = ["z-ai/glm-5"]


def convert_content_to_text(content):
    """将 Responses API 的 content 转换为纯文本"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "input_text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "output_text":
                    text_parts.append(item.get("text", ""))
                elif "text" in item:
                    text_parts.append(item.get("text", ""))
        return " ".join(text_parts)
    return str(content)


def convert_messages_to_chat_format(messages):
    """将 Responses API 的 messages 转换为 Chat Completions API 格式"""
    result = []

    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]

    if not isinstance(messages, list):
        return [{"role": "user", "content": str(messages)}]

    for msg in messages:
        if isinstance(msg, str):
            result.append({"role": "user", "content": msg})
        elif isinstance(msg, dict):
            role = msg.get("role", "user")
            # 将非标准角色转换为标准角色
            if role == "developer":
                role = "system"
            content = msg.get("content", "")
            if isinstance(content, list):
                content = convert_content_to_text(content)
            elif content is None:
                content = ""
            result.append({"role": role, "content": content})

    return result


def convert_chat_to_response(chat_response, model):
    """将 Chat Completions 响应转换为 Responses API 格式"""
    try:
        response_id = f"resp_{uuid.uuid4().hex[:24]}"
        created = int(time.time())

        choice = chat_response.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")

        response_obj = {
            "id": response_id,
            "object": "response",
            "created_at": created,
            "status": "completed",
            "model": model,
            "output": [
                {
                    "type": "message",
                    "id": f"msg_{uuid.uuid4().hex[:24]}",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": content
                        }
                    ]
                }
            ],
            "usage": {
                "input_tokens": chat_response.get("usage", {}).get("prompt_tokens", 0),
                "output_tokens": chat_response.get("usage", {}).get("completion_tokens", 0),
                "total_tokens": chat_response.get("usage", {}).get("total_tokens", 0)
            }
        }

        return response_obj

    except Exception as e:
        print(f"Error converting response: {e}")
        return None


@app.route('/v1/responses', methods=['POST'])
def proxy_responses():
    """代理 /v1/responses 请求"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": {"message": "Invalid JSON body", "type": "invalid_request"}}), 400

        model = data.get("model", DEFAULT_MODEL)

        # 如果模型不支持，替换成默认模型
        original_model = model
        if model not in SUPPORTED_MODELS:
            print(f"Model '{model}' not supported, replacing with '{DEFAULT_MODEL}'")
            model = DEFAULT_MODEL

        # 处理 input 或 messages 字段
        if "input" in data:
            messages = convert_messages_to_chat_format(data["input"])
        elif "messages" in data:
            messages = convert_messages_to_chat_format(data["messages"])
        else:
            messages = [{"role": "user", "content": ""}]

        chat_request = {
            "model": model,
            "messages": messages,
            "stream": data.get("stream", False)
        }

        # 只复制后端支持的基本参数，不传递 tools 等复杂参数
        for key in ["temperature", "top_p", "max_tokens"]:
            if key in data:
                chat_request[key] = data[key]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }

        is_stream = data.get("stream", False)

        print(f"========== NEW REQUEST ==========")
        print(f"Original request keys: {list(data.keys())}")
        print(f"Model: {model}, Stream: {is_stream}, Messages: {len(messages)}")

        if is_stream:
            return stream_response(chat_request, headers, model)
        else:
            response = requests.post(
                f"{BACKEND_URL}/chat/completions",
                json=chat_request,
                headers=headers,
                timeout=120
            )

            print(f"Backend status: {response.status_code}")

            if response.status_code != 200:
                return jsonify({"error": {"message": response.text, "type": "backend_error"}}), response.status_code

            chat_response = response.json()
            response_obj = convert_chat_to_response(chat_response, model)

            if response_obj is None:
                return jsonify({"error": {"message": "Failed to convert response", "type": "conversion_error"}}), 500

            return jsonify(response_obj)

    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return jsonify({"error": {"message": str(e), "type": "connection_error"}}), 502
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": {"message": str(e), "type": "internal_error"}}), 500


def stream_response(chat_request, headers, model):
    """处理流式响应"""

    def generate():
        print("=== GENERATOR STARTED ===")

        try:
            print("Starting stream to backend...")
            response = requests.post(
                f"{BACKEND_URL}/chat/completions",
                json=chat_request,
                headers=headers,
                stream=True,
                timeout=180
            )

            print(f"Backend stream status: {response.status_code}")
            print(f"Full request: {json.dumps(chat_request, ensure_ascii=False)}")
            print(f"Request sent: {json.dumps(chat_request, indent=2, ensure_ascii=False)[:1000]}")

            if response.status_code != 200:
                error_text = response.text
                print(f"Backend stream error: {error_text}")
                yield f"event: error\ndata: {json.dumps({'error': error_text})}\n\n"
                return

            print(f"Response content-type: {response.headers.get('content-type')}")

            response_id = f"resp_{uuid.uuid4().hex[:24]}"
            message_id = f"msg_{uuid.uuid4().hex[:24]}"
            created = int(time.time())

            output_text = ""

            # 发送响应创建事件
            created_event = {
                "type": "response.created",
                "sequence_number": 0,
                "response": {
                    "id": response_id,
                    "object": "response",
                    "created_at": created,
                    "status": "in_progress",
                    "model": model,
                    "output": []
                }
            }
            yield f"event: response.created\ndata: {json.dumps(created_event)}\n\n"

            # 发送输出项添加事件
            output_added_event = {
                "type": "response.output_item.added",
                "sequence_number": 1,
                "output_index": 0,
                "item": {
                    "type": "message",
                    "id": message_id,
                    "status": "in_progress",
                    "role": "assistant",
                    "content": []
                }
            }
            yield f"event: response.output_item.added\ndata: {json.dumps(output_added_event)}\n\n"

            sequence_num = 2
            chunk_count = 0

            # 使用 iter_content 读取流式响应
            buffer = ""
            print("Starting to read stream content...")

            raw_chunk_count = 0
            for chunk in response.iter_content(chunk_size=1024):
                raw_chunk_count += 1
                if raw_chunk_count <= 5:
                    print(f"Raw chunk {raw_chunk_count}: {chunk[:200] if chunk else 'empty'}...")

                if not chunk:
                    continue

                chunk_str = chunk.decode('utf-8')
                buffer += chunk_str

                # 处理完整的行
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()

                    if not line:
                        continue

                    print(f"Processing line: {line[:100]}...")

                    if line.startswith('data: '):
                        data_str = line[6:]

                        if data_str == '[DONE]':
                            print(f"Stream done. Chunks: {chunk_count}, Text length: {len(output_text)}")
                            break

                        try:
                            chunk_data = json.loads(data_str)
                            choices = chunk_data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")

                                if content:
                                    chunk_count += 1
                                    output_text += content

                                    # 发送增量事件
                                    delta_event = {
                                        "type": "response.output_text.delta",
                                        "sequence_number": sequence_num,
                                        "output_index": 0,
                                        "content_index": 0,
                                        "delta": content
                                    }
                                    yield f"event: response.output_text.delta\ndata: {json.dumps(delta_event)}\n\n"
                                    sequence_num += 1

                        except json.JSONDecodeError:
                            continue

            # 发送完成事件
            text_done_event = {
                "type": "response.output_text.done",
                "sequence_number": sequence_num,
                "output_index": 0,
                "content_index": 0,
                "text": output_text
            }
            yield f"event: response.output_text.done\ndata: {json.dumps(text_done_event)}\n\n"
            sequence_num += 1

            # 发送输出项完成事件
            output_done_event = {
                "type": "response.output_item.done",
                "sequence_number": sequence_num,
                "output_index": 0,
                "item": {
                    "type": "message",
                    "id": message_id,
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": output_text}]
                }
            }
            yield f"event: response.output_item.done\ndata: {json.dumps(output_done_event)}\n\n"
            sequence_num += 1

            # 发送响应完成事件
            completed_event = {
                "type": "response.completed",
                "sequence_number": sequence_num,
                "response": {
                    "id": response_id,
                    "object": "response",
                    "created_at": created,
                    "status": "completed",
                    "model": model,
                    "output": [
                        {
                            "type": "message",
                            "id": message_id,
                            "status": "completed",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": output_text}]
                        }
                    ]
                }
            }
            yield f"event: response.completed\ndata: {json.dumps(completed_event)}\n\n"
            print(f"Sent response.completed. Total text: {len(output_text)} chars")

        except Exception as e:
            print(f"Generate error: {e}")
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    print("Starting Responses API Proxy...")
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Default Model: {DEFAULT_MODEL}")
    print("Listening on http://localhost:8080")
    app.run(host='0.0.0.0', port=8080, debug=True)

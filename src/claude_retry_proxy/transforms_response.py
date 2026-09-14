"""The request/response body transforms for the response endpoint mode."""

import json
import time

from .sinks import log_trace

from .transforms_common import _request_transform_timestamp

__all__ = ["_anthropic_to_response", "_response_to_anthropic"]


def _anthropic_to_response(body_json, request_id=None, mode=None, provider=None,
                           tier=None):
    """Transform an Anthropic Messages request into OpenAI Responses.

    Buffered (stream forced false — response-mode SSE is not implemented):
    the full message history is converted in order into Responses input items —
    user/assistant text as message items, tool_use as function_call, tool_result
    as function_call_output — plus flat function tools and tool_choice. Does not
    mutate body_json.
    """
    out = {}
    if "model" in body_json:
        out["model"] = body_json["model"]
    out["stream"] = False

    cache_stripped = []
    dropped = {"image": 0, "thinking": 0, "redacted_thinking": 0,
               "tool_result": 0, "unknown": 0}
    known_call_ids = set()
    consumed_call_ids = set()

    def _msg_item(role, text):
        ct = "output_text" if role == "assistant" else "input_text"
        return {"type": "message", "role": role,
                "content": [{"type": ct, "text": text}]}

    items = []
    messages = body_json.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            if isinstance(content, str):
                items.append(_msg_item(role, content))
                continue
            if not isinstance(content, list):
                continue
            if role == "assistant":
                text_parts = []
                call_items = []
                for block in content:
                    if not isinstance(block, dict):
                        dropped["unknown"] += 1
                        continue
                    if "cache_control" in block:
                        cache_stripped.append("message")
                    btype = block.get("type")
                    if btype == "thinking":
                        dropped["thinking"] += 1
                        continue
                    if btype == "redacted_thinking":
                        dropped["redacted_thinking"] += 1
                        continue
                    if btype == "tool_use":
                        tool_name = block.get("name")
                        tool_id = block.get("id")
                        input_val = block.get("input")
                        if not isinstance(tool_id, str) or not tool_id:
                            dropped["unknown"] += 1
                            continue
                        if not isinstance(input_val, dict):
                            text_parts.append(
                                "[Tool call failed: arguments for '{}' (call {}) "
                                "could not be serialized as JSON]".format(
                                    tool_name if isinstance(tool_name, str) and tool_name else "<unknown>",
                                    tool_id))
                            log_trace({
                                "timestamp": _request_transform_timestamp(),
                                "event": "tool_args_parse_failure",
                                "request_id": request_id,
                                "mode": mode,
                                "provider": provider,
                                "tier": tier,
                                "tool_name": tool_name,
                                "tool_id": tool_id,
                                "error": "tool_use.input must be a JSON object",
                            })
                            continue
                        try:
                            arguments = json.dumps(input_val, allow_nan=False)
                        except (ValueError, TypeError) as exc:
                            text_parts.append(
                                "[Tool call failed: arguments for '{}' (call {}) "
                                "could not be serialized as JSON]".format(
                                    tool_name if isinstance(tool_name, str) and tool_name else "<unknown>",
                                    tool_id))
                            log_trace({
                                "timestamp": _request_transform_timestamp(),
                                "event": "tool_args_parse_failure",
                                "request_id": request_id,
                                "mode": mode,
                                "provider": provider,
                                "tier": tier,
                                "tool_name": tool_name,
                                "tool_id": tool_id,
                                "error": str(exc),
                            })
                            continue
                        if not isinstance(tool_name, str) or not tool_name:
                            dropped["unknown"] += 1
                            continue
                        known_call_ids.add(tool_id)
                        call_items.append({
                            "type": "function_call",
                            "call_id": tool_id,
                            "name": tool_name,
                            "arguments": arguments,
                        })
                        continue
                    if btype == "text":
                        text = block.get("text")
                        if isinstance(text, str):
                            text_parts.append(text)
                        continue
                    dropped["unknown"] += 1
                if text_parts:
                    items.append(_msg_item("assistant", "\n".join(text_parts)))
                items.extend(call_items)
            elif role == "user":
                text_parts = []
                result_items = []
                for block in content:
                    if not isinstance(block, dict):
                        dropped["unknown"] += 1
                        continue
                    if "cache_control" in block:
                        cache_stripped.append("message")
                    btype = block.get("type")
                    if btype == "tool_result":
                        tid = block.get("tool_use_id")
                        if (not isinstance(tid, str) or not tid
                                or tid not in known_call_ids
                                or tid in consumed_call_ids):
                            dropped["tool_result"] += 1
                            continue
                        consumed_call_ids.add(tid)
                        output = block.get("content")
                        if isinstance(output, list):
                            output = "\n".join(
                                c.get("text") for c in output
                                if isinstance(c, dict) and c.get("type") == "text"
                                and isinstance(c.get("text"), str))
                        if not isinstance(output, str):
                            output = ""
                        result_items.append({
                            "type": "function_call_output",
                            "call_id": tid,
                            "output": output,
                        })
                        continue
                    if btype == "text":
                        text = block.get("text")
                        if isinstance(text, str):
                            text_parts.append(text)
                        continue
                    if btype == "image":
                        dropped["image"] += 1
                        continue
                    dropped["unknown"] += 1
                if text_parts:
                    items.append(_msg_item("user", "\n".join(text_parts)))
                items.extend(result_items)
            else:
                text_parts = []
                for block in content:
                    if not isinstance(block, dict):
                        dropped["unknown"] += 1
                        continue
                    btype = block.get("type")
                    if btype == "thinking":
                        dropped["thinking"] += 1
                        continue
                    if btype == "redacted_thinking":
                        dropped["redacted_thinking"] += 1
                        continue
                    if btype == "tool_use":
                        dropped["unknown"] += 1
                        continue
                    if btype == "tool_result":
                        dropped["tool_result"] += 1
                        continue
                    if btype == "image":
                        dropped["image"] += 1
                        continue
                    if btype == "text":
                        text = block.get("text")
                        if isinstance(text, str):
                            text_parts.append(text)
                        continue
                    dropped["unknown"] += 1
                if text_parts:
                    items.append(_msg_item(role, "\n".join(text_parts)))

    # Coalesce adjacent same-role message items so a dropped turn cannot
    # leave an invalid role sequence.
    coalesced = []
    for it in items:
        if (coalesced and it.get("type") == "message"
                and coalesced[-1].get("type") == "message"
                and coalesced[-1].get("role") == it.get("role")):
            # Derive from the coalesced pair's shared role — the outer `role`
            # variable from the messages loop is stale here.
            ct = "output_text" if it.get("role") == "assistant" else "input_text"
            prev_texts = [c.get("text") for c in (coalesced[-1].get("content") or [])
                          if isinstance(c, dict) and c.get("type") == ct
                          and isinstance(c.get("text"), str)]
            new_texts = [c.get("text") for c in (it.get("content") or [])
                         if isinstance(c, dict) and c.get("type") == ct
                         and isinstance(c.get("text"), str)]
            coalesced[-1]["content"] = [{"type": ct, "text": "\n".join(
                prev_texts + new_texts)}]
            continue
        coalesced.append(it)
    out["input"] = coalesced

    system = body_json.get("system")
    system_text = None
    if isinstance(system, str):
        system_text = system
    elif isinstance(system, list):
        system_text = "\n".join(b.get("text") for b in system
                                if isinstance(b, dict) and isinstance(b.get("text"), str))
    if system_text:
        out["instructions"] = system_text

    # Flat Responses function tools (validated; chat's nested function shape
    # is not used here).
    tools = body_json.get("tools")
    validated_names = []
    tools_out = []
    if isinstance(tools, list):
        dropped_tools = 0
        for tool in tools:
            if not isinstance(tool, dict):
                dropped_tools += 1
                continue
            if "cache_control" in tool:
                cache_stripped.append("tools")
            name = tool.get("name")
            input_schema = tool.get("input_schema")
            if not isinstance(name, str) or not name or not isinstance(input_schema, dict):
                dropped_tools += 1
                continue
            fn = {"type": "function", "name": name, "parameters": input_schema}
            if isinstance(tool.get("description"), str):
                fn["description"] = tool["description"]
            tools_out.append(fn)
            validated_names.append(name)
        if dropped_tools > 0:
            log_trace({
                "timestamp": _request_transform_timestamp(),
                "event": "content_block_dropped",
                "request_id": request_id,
                "dropped_counts": {"unknown": dropped_tools},
                "location": "tool_definition",
                "mode": mode,
                "provider": provider,
                "tier": tier,
            })
    if tools_out:
        out["tools"] = tools_out

    tool_choice = body_json.get("tool_choice")
    if isinstance(tool_choice, dict) and tools_out:
        tc_type = tool_choice.get("type")
        if tc_type == "none":
            out["tool_choice"] = "none"
        elif tc_type == "auto":
            out["tool_choice"] = "auto"
        elif tc_type == "any":
            out["tool_choice"] = "required"
        elif tc_type == "tool":
            name = tool_choice.get("name")
            if isinstance(name, str) and name and name in validated_names:
                out["tool_choice"] = {"type": "function", "name": name}

    if "max_tokens" in body_json:
        out["max_output_tokens"] = body_json["max_tokens"]
    if "temperature" in body_json:
        out["temperature"] = body_json["temperature"]
    if "top_p" in body_json:
        out["top_p"] = body_json["top_p"]

    if cache_stripped:
        log_trace({
            "timestamp": _request_transform_timestamp(),
            "event": "cache_control_stripped",
            "request_id": request_id,
            "locations": cache_stripped,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
    if sum(dropped.values()) > 0:
        log_trace({
            "timestamp": _request_transform_timestamp(),
            "event": "content_block_dropped",
            "request_id": request_id,
            "dropped_counts": dropped,
            "location": "message",
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
    return out


def _response_to_anthropic(resp_body, tier, request_id=None, mode=None, provider=None):
    """Transform an OpenAI Responses JSON response into Anthropic Messages.

    Inspects every output item in order: message/output_text maps to text
    blocks and valid function_call items map to tool_use blocks. Same defensive
    conventions as _chat_to_anthropic: guarded .get() access and an outer
    try/except falling back to the original body.
    """
    try:
        output = resp_body.get("output") or []
        usage = resp_body.get("usage") or {}
        result = {
            "id": resp_body.get("id"),
            "model": tier,
            "type": "message",
            "role": "assistant",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": usage.get("input_tokens") or 0,
                "output_tokens": usage.get("output_tokens") or 0,
            },
        }
        if not output:
            return result

        seen_function_call = False
        emitted_tool_use = False
        for item in output:
            if not isinstance(item, dict):
                continue
            itype = item.get("type")
            if itype == "message":
                for cb in (item.get("content") or []):
                    if not isinstance(cb, dict) or cb.get("type") != "output_text":
                        continue
                    text = cb.get("text")
                    if isinstance(text, str):
                        result["content"].append({"type": "text", "text": text})
            elif itype == "function_call":
                seen_function_call = True
                name = item.get("name")
                call_id = item.get("call_id")
                args = item.get("arguments")
                parsed_args = None
                if isinstance(args, dict):
                    parsed_args = args
                elif isinstance(args, str):
                    try:
                        parsed_args = json.loads(args)
                    except json.JSONDecodeError:
                        parsed_args = None
                    if not isinstance(parsed_args, dict):
                        parsed_args = None
                if parsed_args is None or not isinstance(name, str) or not name \
                        or not isinstance(call_id, str) or not call_id:
                    result["content"].append({
                        "type": "text",
                        "text": "[Tool call failed: arguments for '{}' (call {}) "
                                "could not be parsed as JSON]".format(
                                    name if isinstance(name, str) and name else "<unknown>",
                                    call_id if isinstance(call_id, str) and call_id else "<unknown>"),
                    })
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "tool_args_parse_failure",
                        "request_id": request_id,
                        "mode": mode,
                        "provider": provider,
                        "tier": tier,
                    })
                    continue
                result["content"].append({
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": parsed_args,
                })
                emitted_tool_use = True
            # Other output item types (function_call_output, reasoning, ...) are
            # ignored without crashing.

        if emitted_tool_use:
            result["stop_reason"] = "tool_use"
        elif seen_function_call:
            result["stop_reason"] = None
        else:
            result["stop_reason"] = "end_turn" if resp_body.get("status") == "completed" else None
        return result
    except (json.JSONDecodeError, KeyError, TypeError, IndexError, AttributeError):
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "transform_failure",
            "request_id": request_id,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
        return resp_body

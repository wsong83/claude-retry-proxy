"""The request/response body transforms for the chat endpoint mode."""

import json
import time
import uuid

from .compat import COMPAT_REASONING_FIELDS
from .nesting import check_payload_nesting, nesting_event
from .sinks import log_trace

from .transforms_common import _request_transform_timestamp, _sanitize_schema_patterns

__all__ = ["_anthropic_to_chat", "_transform_anthropic_messages_to_chat",
           "_transform_tool_result_to_chat_tool", "_transform_anthropic_tools_to_chat",
           "_transform_anthropic_tool_choice_to_chat", "_map_chat_finish_reason",
           "_chat_to_anthropic"]


def _anthropic_to_chat(body_json, request_id=None, mode=None, provider=None,
                       tier=None, reasoning_selection="none",
                       reasoning_always=False):
    """Transform an Anthropic Messages request into OpenAI Chat Completions.

    Builds `out` without mutating `body_json`. messages / tools / tool_choice
    are transformed via the _transform_anthropic_*_to_chat helpers; thinking /
    metadata / top_k are Anthropic-specific request config and are dropped.
    `reasoning_selection` is forwarded to the messages transform to choose the
    echo field (see _transform_anthropic_messages_to_chat), and
    `reasoning_always` forces that field onto every assistant message once the
    conversation contains a tool call.
    """
    out = {}
    if "model" in body_json:
        out["model"] = body_json["model"]
    cache_locations = []
    if "messages" in body_json:
        out["messages"] = _transform_anthropic_messages_to_chat(
            body_json.get("messages", []), request_id=request_id, mode=mode,
            provider=provider, tier=tier, cache_stripped_out=cache_locations,
            reasoning_selection=reasoning_selection,
            reasoning_always=reasoning_always)

    system = body_json.get("system")
    system_text = None
    if isinstance(system, str):
        system_text = system
    elif isinstance(system, list):
        parts = [b.get("text") for b in system
                 if isinstance(b, dict) and isinstance(b.get("text"), str)]
        system_text = "\n".join(parts)
    if system_text:
        messages = out.get("messages")
        if not isinstance(messages, list):
            messages = []
        messages.insert(0, {"role": "system", "content": system_text})
        out["messages"] = messages

    if "tools" in body_json and isinstance(body_json.get("tools"), list):
        transformed_tools = _transform_anthropic_tools_to_chat(
            body_json["tools"], request_id=request_id, mode=mode,
            provider=provider, tier=tier, cache_stripped_out=cache_locations)
        out["tools"] = transformed_tools
        if transformed_tools and "tool_choice" in body_json:
            tc = _transform_anthropic_tool_choice_to_chat(
                body_json.get("tool_choice"))
            if tc is not None:
                out["tool_choice"] = tc

    if cache_locations:
        log_trace({
            "timestamp": _request_transform_timestamp(),
            "event": "cache_control_stripped",
            "request_id": request_id,
            "locations": cache_locations,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })

    for field in ("max_tokens", "temperature", "stream", "top_p"):
        if field in body_json:
            out[field] = body_json[field]
    if "stop_sequences" in body_json:
        out["stop"] = body_json["stop_sequences"]
    # OpenAI emits the usage frame as the last data frame of a stream, after
    # finish_reason, and only when asked for it. Non-streaming requests reject
    # stream_options outright, so it is set only when streaming.
    if body_json.get("stream"):
        out["stream_options"] = {"include_usage": True}
    return out


def _transform_anthropic_messages_to_chat(messages, request_id=None, mode=None,
                                          provider=None, tier=None,
                                          cache_stripped_out=None,
                                          reasoning_selection="none",
                                          reasoning_always=False):
    """Convert an Anthropic messages array into OpenAI Chat messages.

Always returns a new list (never mutates the input). One Anthropic
    assistant turn becomes ONE OpenAI assistant message: `content` carries the
    joined text parts (or null when the turn has none), and `tool_calls` rides
    on that same message. A thinking block's text is echoed on that message
    under exactly one field, chosen by `reasoning_selection`:
    "reasoning_content" or "reasoning" emits that field only; anything else
    (the default "none", None, or an unrecognized value) emits no reasoning
    field at all — never both. `reasoning_always` additionally sets the
    selected field on EVERY assistant message once the transformed list
    contains a tool call: the real reasoning text where one exists, "" where
    none does (a redacted-thinking placeholder counts as a placeholder, never
    as real). redacted_thinking blocks with non-empty data are converted to a
    placeholder; a valid `image` block becomes an OpenAI `image_url` part --
    top-level blocks and those nested inside `tool_result` content alike, the
    latter riding the following user message because OpenAI `role:tool`
    messages cannot carry images; an inconvertible image is counted as dropped
    rather than becoming a part; unknown blocks are stripped; tool_use and
    tool_result are converted to OpenAI tool_calls / role:tool messages;
    cache_control is stripped from kept blocks.
    cache_control_stripped is reported to the caller via the optional
    cache_stripped_out list rather than logged here, so _anthropic_to_chat can
    coalesce one event per request.
    """
    if not isinstance(messages, list):
        return []
    dropped = {"thinking": 0, "redacted_thinking": 0, "image": 0,
               "tool_result": 0, "unknown": 0}
    passthrough = {"redacted_thinking": 0}
    cache_stripped = False
    tool_use_ids = set()
    out = []
    # Per-assistant-message reasoning material, keyed by message identity:
    # {id(message): (text or None, is_redacted_placeholder)}. The always-present
    # pass below runs over the built list and needs this to tell a real block
    # from the redacted placeholder and from a message with none at all.
    reasoning_by_msg = {}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "user" and (content is None or content == []):
            out.append({"role": "user", "content": ""})
            continue
        if not isinstance(content, list):
            continue
        if role == "assistant":
            text_parts = []
            tool_calls = []
            reasoning_text = None
            reasoning_is_placeholder = False
            for block in content:
                if not isinstance(block, dict):
                    dropped["unknown"] += 1
                    continue
                if "cache_control" in block:
                    cache_stripped = True
                btype = block.get("type")
                if btype == "thinking":
                    thinking = block.get("thinking")
                    if isinstance(thinking, str) and thinking:
                        reasoning_text = thinking
                        # Real text supersedes an earlier redacted placeholder,
                        # so the flag must describe the value actually kept.
                        reasoning_is_placeholder = False
                    else:
                        dropped["thinking"] += 1
                    continue
                if btype == "redacted_thinking":
                    data = block.get("data")
                    if isinstance(data, str) and data and reasoning_text is None:
                        reasoning_text = "[redacted_thinking: data not available]"
                        reasoning_is_placeholder = True
                        passthrough["redacted_thinking"] += 1
                        log_trace({
                            "timestamp": _request_transform_timestamp(),
                            "event": "redacted_thinking_passthrough",
                            "request_id": request_id,
                            "mode": mode,
                            "provider": provider,
                            "tier": tier,
                            "data_length": len(data) if isinstance(data, str) else -1,
                        })
                    else:
                        dropped["redacted_thinking"] += 1
                    continue
                if btype == "tool_use":
                    tool_name = block.get("name")
                    tool_id = block.get("id")
                    input_val = block.get("input")
                    if not isinstance(input_val, dict):
                        text_parts.append(
                            "[Tool call failed: arguments for '{}' (call {}) "
                            "could not be serialized as JSON]".format(
                                tool_name or "<unknown>", tool_id or "<unknown>"))
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
                                tool_name or "<unknown>", tool_id or "<unknown>"))
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
                    if not isinstance(tool_id, str) or not tool_id:
                        dropped["unknown"] += 1
                        continue
                    tool_use_ids.add(tool_id)
                    if not isinstance(tool_name, str):
                        tool_name = ""
                    tool_calls.append({
                        "id": tool_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": arguments,
                        },
                    })
                    continue
                if btype == "text":
                    text_parts.append(block.get("text"))
                    continue
                dropped["unknown"] += 1
            def _assistant_msg(content):
                m = {"role": "assistant", "content": content}
                if (reasoning_text is not None
                        and reasoning_selection in COMPAT_REASONING_FIELDS):
                    m[reasoning_selection] = reasoning_text
                return m

            # One assistant message per Anthropic assistant turn: the text (null
            # when the turn has none) and the tool_calls share one message, so
            # the reasoning field can ride on the same message the vendor checks.
            if tool_calls:
                m = _assistant_msg("\n".join(
                    t for t in text_parts if isinstance(t, str))
                    if text_parts else None)
                m["tool_calls"] = tool_calls
            elif text_parts:
                m = _assistant_msg("\n".join(
                    t for t in text_parts if isinstance(t, str)))
            else:
                m = _assistant_msg("")
            out.append(m)
            reasoning_by_msg[id(m)] = (reasoning_text, reasoning_is_placeholder)
        elif role == "user":
            tool_messages = []
            text_parts = []
            image_parts = []
            for block in content:
                if not isinstance(block, dict):
                    dropped["unknown"] += 1
                    continue
                if "cache_control" in block:
                    cache_stripped = True
                btype = block.get("type")
                if btype == "tool_result":
                    t = _transform_tool_result_to_chat_tool(block, tool_use_ids)
                    if t is None:
                        dropped["tool_result"] += 1
                    else:
                        tool_messages.append(t)
                    # OpenAI role:tool messages cannot carry images, so
                    # image blocks nested in the tool_result's content ride
                    # the following user message as image_url parts instead
                    # -- the shape OpenAI's function-calling-image pattern
                    # prescribes. Extraction is independent of the
                    # tool_use_id pairing above: a result whose matching
                    # call was never emitted still yields its images.
                    nested = block.get("content")
                    if isinstance(nested, list):
                        for c in nested:
                            if not isinstance(c, dict) or c.get("type") != "image":
                                continue
                            if "cache_control" in c:
                                cache_stripped = True
                            part = _anthropic_image_to_chat_part(c)
                            if part is None:
                                dropped["image"] += 1
                            else:
                                image_parts.append(part)
                    continue
                if btype == "text":
                    text_parts.append(block.get("text"))
                    continue
                if btype == "image":
                    part = _anthropic_image_to_chat_part(block)
                    if part is None:
                        dropped["image"] += 1
                    else:
                        image_parts.append(part)
                    continue
                dropped["unknown"] += 1
            out.extend(tool_messages)
            text = "\n".join(t for t in text_parts if isinstance(t, str))
            if image_parts:
                # OpenAI content parts: the merged text run first, then the
                # image parts in block order. The array shape is used only
                # when at least one valid image survived the conversion; a
                # text-only message keeps the string shape, and a message
                # whose only content was inconvertible emits nothing.
                parts = []
                if text:
                    parts.append({"type": "text", "text": text})
                parts.extend(image_parts)
                out.append({"role": role, "content": parts})
            elif text:
                out.append({"role": role, "content": text})
        else:
            out.append({"role": role, "content": content})
    # Always-present pass, over the fully built list: the predicate is global
    # (does the conversation contain a tool call?), so it cannot live in the
    # per-message loop. Inert with no field name to write (selection "none").
    if reasoning_always and reasoning_selection in COMPAT_REASONING_FIELDS:
        assistant_msgs = [m for m in out if m.get("role") == "assistant"]
        if any(m.get("tool_calls") for m in assistant_msgs):
            real_count = empty_count = placeholder_count = 0
            for m in assistant_msgs:
                text, is_placeholder = reasoning_by_msg.get(id(m), (None, False))
                if isinstance(text, str) and text:
                    m[reasoning_selection] = text
                    if is_placeholder:
                        placeholder_count += 1
                    else:
                        real_count += 1
                else:
                    m[reasoning_selection] = ""
                    empty_count += 1
            if empty_count or placeholder_count:
                log_trace({
                    "timestamp": _request_transform_timestamp(),
                    "event": "reasoning_field_injected",
                    "request_id": request_id,
                    "mode": mode,
                    "provider": provider,
                    "tier": tier,
                    "real": real_count,
                    "empty": empty_count,
                    "placeholder": placeholder_count,
                })
    if cache_stripped and cache_stripped_out is not None:
        cache_stripped_out.append("messages")
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


def _anthropic_image_to_chat_part(block):
    """Convert one Anthropic image content block into an OpenAI image_url part.

    Returns the part dict, or None when the block is inconvertible: `source`
    must be a dict whose `type` is "base64" -- with `media_type` and `data`
    both non-empty strings, emitted as `data:<media_type>;base64,<data>` -- or
    "url", with a non-empty string passed through verbatim. Every other source
    shape -- a missing or non-dict source, an unknown type, the Files-API
    `file` source -- has no chat-completions equivalent and converts to None.
    Callers count None as a dropped block; the data payload is copied verbatim
    (no re-encoding: both APIs use standard base64), and `detail` is omitted
    so the upstream applies its own default.
    """
    source = block.get("source")
    if not isinstance(source, dict):
        return None
    stype = source.get("type")
    if stype == "base64":
        media_type = source.get("media_type")
        data = source.get("data")
        if isinstance(media_type, str) and media_type and isinstance(data, str) and data:
            return {"type": "image_url",
                    "image_url": {"url": "data:{};base64,{}".format(media_type, data)}}
        return None
    if stype == "url":
        url = source.get("url")
        if isinstance(url, str) and url:
            return {"type": "image_url", "image_url": {"url": url}}
        return None
    return None


def _transform_tool_result_to_chat_tool(block, known_ids):
    """Convert one Anthropic tool_result block into an OpenAI role:tool message.

    Returns None if the block's tool_use_id is missing/not a string, or does
    not match a tool_use.id from a preceding assistant message (the block is
    dropped). tool_result.content may be a string or a list of text blocks;
    text is extracted and joined with newlines.
    """
    tid = block.get("tool_use_id")
    if not isinstance(tid, str) or not tid or tid not in known_ids:
        return None
    content = block.get("content")
    if isinstance(content, list):
        parts = [c.get("text") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"
                 and isinstance(c.get("text"), str)]
        content = "\n".join(parts)
    if not isinstance(content, str):
        content = ""
    return {"role": "tool", "tool_call_id": tid, "content": content}


def _transform_anthropic_tools_to_chat(tools, request_id=None, mode=None,
                                       provider=None, tier=None,
                                       cache_stripped_out=None):
    """Convert Anthropic tool definitions to OpenAI Chat function tools.

    Returns a new list; tools:null and non-list inputs become []. Entries
    missing name or input_schema are skipped. cache_control_stripped is
    reported to the caller via the optional cache_stripped_out list rather
    than logged here, so _anthropic_to_chat can coalesce one event per request.
    """
    if not isinstance(tools, list):
        return []
    out = []
    cache_stripped = False
    dropped = 0
    for tool in tools:
        if not isinstance(tool, dict):
            dropped += 1
            continue
        name = tool.get("name")
        input_schema = tool.get("input_schema")
        if not isinstance(name, str) or not name or not isinstance(input_schema, dict):
            dropped += 1
            continue
        fn = {"name": name, "parameters": _sanitize_schema_patterns(input_schema)}
        if isinstance(tool.get("description"), str):
            fn["description"] = tool["description"]
        if "cache_control" in tool:
            cache_stripped = True
        out.append({"type": "function", "function": fn})
    if dropped > 0:
        log_trace({
            "timestamp": _request_transform_timestamp(),
            "event": "content_block_dropped",
            "request_id": request_id,
            "dropped_counts": {"unknown": dropped},
            "location": "tool_definition",
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
    if cache_stripped and cache_stripped_out is not None:
        cache_stripped_out.append("tools")
    return out


def _transform_anthropic_tool_choice_to_chat(tool_choice):
    """Convert an Anthropic tool_choice to OpenAI tool_choice (None to omit)."""
    if not isinstance(tool_choice, dict):
        return None
    tc_type = tool_choice.get("type")
    if tc_type == "none":
        return "none"
    if tc_type == "auto":
        return "auto"
    if tc_type == "any":
        return "required"
    if tc_type == "tool":
        name = tool_choice.get("name")
        if isinstance(name, str) and name:
            return {"type": "function", "function": {"name": name}}
        return None
    return None


def _map_chat_finish_reason(finish_reason):
    """Map an OpenAI finish_reason to an Anthropic stop_reason (null for no map)."""
    mapping = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
    if isinstance(finish_reason, str) and finish_reason in mapping:
        return mapping[finish_reason]
    return None


def _chat_to_anthropic(chat_body, tier, request_id=None, mode=None, provider=None):
    """Transform an OpenAI Chat Completions JSON response into Anthropic Messages.

    All field access is guarded with .get()/truthiness defaults; the whole
    body is wrapped so any shape failure passes through unchanged.
    """
    try:
        _id = chat_body.get("id") or str(uuid.uuid4())
        choices = chat_body.get("choices") or []
        usage = chat_body.get("usage") or {}
        result = {
            "id": "msg_" + _id,
            "model": tier,
            "type": "message",
            "role": "assistant",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": usage.get("prompt_tokens") or 0,
                "output_tokens": usage.get("completion_tokens") or 0,
            },
        }
        if not choices:
            return result

        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content:
            result["content"] = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            result["content"] = [
                {"type": "text", "text": part.get("text")}
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            ]
        else:
            result["content"] = []

        reasoning = message.get("reasoning_content")
        if not (isinstance(reasoning, str) and reasoning):
            reasoning = message.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            result["content"].insert(0, {
                "type": "thinking",
                "thinking": reasoning,
                "signature": "",
            })

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            emitted_tool_use = False
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "tool_args_parse_failure",
                        "request_id": request_id,
                        "mode": mode,
                        "provider": provider,
                        "tier": tier,
                    })
                    result["content"].append({
                        "type": "text",
                        "text": "[Tool call failed: tool call entry is not a dict (call {})]".format(
                            tc.get("id") if isinstance(tc, dict) else "<unknown>"),
                    })
                    continue
                fn = tc.get("function")
                fn = fn if isinstance(fn, dict) else {}
                args = fn.get("arguments")
                if isinstance(args, dict):
                    parsed_args = args
                elif isinstance(args, str):
                    # The arguments ride inside a JSON string, so no outer
                    # body scan can see their depth: bound them here.
                    _nesting = check_payload_nesting(args)
                    if _nesting is not None:
                        log_trace(nesting_event("tool_args", _nesting,
                                                request_id=request_id,
                                                mode=mode,
                                                provider=provider, tier=tier))
                        parsed_args = None
                    else:
                        try:
                            parsed_args = json.loads(args)
                        except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
                            parsed_args = None
                    if not isinstance(parsed_args, dict):
                        parsed_args = None
                else:
                    parsed_args = None
                if parsed_args is None:
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "tool_args_parse_failure",
                        "request_id": request_id,
                        "mode": mode,
                        "provider": provider,
                        "tier": tier,
                    })
                    result["content"].append({
                        "type": "text",
                        "text": "[Tool call failed: arguments for '{}' (call {}) could not be parsed as JSON]".format(
                            fn.get("name") or "<unknown>", tc.get("id") or "<unknown>"),
                    })
                    continue
                result["content"].append({
                    "type": "tool_use",
                    "id": tc.get("id") or str(uuid.uuid4()),
                    "name": fn.get("name") or None,
                    "input": parsed_args,
                })
                emitted_tool_use = True

            if not emitted_tool_use:
                result["stop_reason"] = None
            else:
                result["stop_reason"] = _map_chat_finish_reason(choice.get("finish_reason"))

        if not isinstance(tool_calls, list):
            sr = _map_chat_finish_reason(choice.get("finish_reason"))
            if sr == "tool_use":
                sr = None  # tool_calls null/absent — don't claim tool_use
            result["stop_reason"] = sr
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
        return chat_body

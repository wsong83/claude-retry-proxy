"""Image content-block tests: user-message and tool_result-nested image
conversion to image_url parts, conversion non-mutation, and the
response-direction image filtering."""

import uuid
from _harness import _require_server_func, _trace_events_for_request, fail, pass_, run_cli


def test_anthropic_to_chat_image_blocks_converted():
    """User-message image blocks become image_url parts: base64 payloads as
    `data:<media_type>;base64,<data>` URIs, url sources verbatim; the message's
    content becomes a parts array (merged text part first, images in block
    order) exactly when a valid image survives; text-only messages keep the
    string shape; inconvertible images are dropped and counted; cache_control
    on a converted image is stripped from the emitted part and reported."""
    print("\n--- Test: Anthropic To Chat Image Blocks Converted ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    png = {"type": "image_url",
           "image_url": {"url": "data:image/png;base64,aGVsbG8="}}
    rid = "T-" + uuid.uuid4().hex[:8]
    out = fn([
        {"role": "user", "content": [
            {"type": "text", "text": "caption"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": "aGVsbG8="}},
        ]},
    ], request_id=rid, mode="chat", provider="p", tier="sonnet")
    if out != [{"role": "user", "content": [{"type": "text", "text": "caption"}, png]}]:
        fail("base64 image not converted to a data-URI part, got {!r}".format(out))
        return
    # url source verbatim
    out = fn([
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "url",
                                         "url": "https://example.com/i.png"}},
        ]},
    ], request_id=rid, mode="chat", provider="p", tier="sonnet")
    if out != [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": "https://example.com/i.png"}}]}]:
        fail("url-source image not passed through verbatim, got {!r}".format(out))
        return
    # two images keep block order after the merged text part
    jpg = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,bW9yZQ=="}}
    out = fn([
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": "aGVsbG8="}},
            {"type": "text", "text": "T"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": "bW9yZQ=="}},
        ]},
    ], request_id=rid, mode="chat", provider="p", tier="sonnet")
    if out != [{"role": "user", "content": [
            {"type": "text", "text": "T"}, png, jpg]}]:
        fail("image order not preserved, got {!r}".format(out))
        return
    # text-only messages keep the string shape
    out = fn([{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
             request_id=rid, mode="chat", provider="p", tier="sonnet")
    if out != [{"role": "user", "content": "hi"}]:
        fail("text-only message must keep the string shape, got {!r}".format(out))
        return
    # inconvertible images are dropped and counted, and the message stays a string
    rid2 = "T-" + uuid.uuid4().hex[:8]
    out = fn([
        {"role": "user", "content": [
            {"type": "text", "text": "T"},
            {"type": "image", "source": {"type": "base64", "data": "aGVsbG8="}},
            {"type": "image", "source": {"type": "file", "file_id": "f1"}},
        ]},
    ], request_id=rid2, mode="chat", provider="p", tier="sonnet")
    if out != [{"role": "user", "content": "T"}]:
        fail("inconvertible images must be dropped without changing the shape, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid2) if e.get("event") == "content_block_dropped"]
    counts = (evs[0].get("dropped_counts") or {}) if evs else {}
    if counts.get("image") != 2:
        fail("expected dropped_counts.image == 2 (no media_type + file source), got {!r}".format(counts))
        return
    # cache_control on a converted image: stripped from the part, reported once
    stripped_out = []
    out = fn([
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": "aGVsbG8="},
             "cache_control": {"type": "ephemeral"}},
        ]},
    ], request_id=rid, mode="chat", provider="p", tier="sonnet",
        cache_stripped_out=stripped_out)
    if out != [{"role": "user", "content": [png]}]:
        fail("cache_control must not ride the converted image part, got {!r}".format(out))
        return
    if stripped_out != ["messages"]:
        fail("image cache_control must be reported via cache_stripped_out, got {!r}".format(stripped_out))
        return
    pass_("image blocks: base64 data URI, url verbatim, block order, string shape kept, malformed counted")


def test_anthropic_to_chat_tool_result_images_converted():
    """Image blocks nested in tool_result content ride the following user
    message as image_url parts while the tool text rides the role:tool message
    -- the OpenAI pattern, since role:tool messages cannot carry images.
    Extraction is independent of tool_use_id pairing; malformed nested images
    are counted; an image-only tool_result still yields its images; nested
    cache_control is stripped from the part and reported."""
    print("\n--- Test: Anthropic To Chat Tool Result Images Converted ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    png = {"type": "image_url",
           "image_url": {"url": "data:image/png;base64,aGVsbG8="}}
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                       "data": "aGVsbG8="}}
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1",
             "content": [{"type": "text", "text": "res"}, img]},
            {"type": "text", "text": "Thanks"},
        ]},
    ]
    out = fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "res"},
        {"role": "user", "content": [{"type": "text", "text": "Thanks"}, png]},
    ]
    if out != expected:
        fail("nested image must ride the following user message, got {!r}".format(out))
        return
    # image-only tool_result: tool text "" (existing contract) + image-only user message
    out = fn([
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": [img]},
        ]},
    ], request_id=rid, mode="chat", provider="p", tier="sonnet")
    if out[-1] != {"role": "user", "content": [png]} or out[-2] != {
            "role": "tool", "tool_call_id": "toolu_1", "content": ""}:
        fail("image-only tool_result must yield its images, got {!r}".format(out))
        return
    # dangling tool_result: tool message dropped (existing rule), images still flow
    out = fn([
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_NOPE", "content": [img]},
            {"type": "text", "text": "Thanks"},
        ]},
    ], request_id=rid, mode="chat", provider="p", tier="sonnet")
    if out[-1] != {"role": "user", "content": [{"type": "text", "text": "Thanks"}, png]}:
        fail("dangling tool_result images must still flow, got {!r}".format(out))
        return
    # malformed nested image: counted, no part
    rid2 = "T-" + uuid.uuid4().hex[:8]
    out = fn([
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1",
             "content": [{"type": "image", "source": {"type": "base64", "data": "x"}}]},
        ]},
    ], request_id=rid2, mode="chat", provider="p", tier="sonnet")
    if len(out) != 2 or out[-1] != {"role": "tool", "tool_call_id": "toolu_1", "content": ""}:
        fail("malformed nested image must emit no part, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid2) if e.get("event") == "content_block_dropped"]
    counts = (evs[0].get("dropped_counts") or {}) if evs else {}
    if counts.get("image") != 1:
        fail("expected dropped_counts.image == 1, got {!r}".format(counts))
        return
    # nested cache_control: stripped from the part, reported once per request
    stripped_out = []
    out = fn([
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1",
             "content": [dict(img, cache_control={"type": "ephemeral"})]},
        ]},
    ], request_id=rid, mode="chat", provider="p", tier="sonnet",
        cache_stripped_out=stripped_out)
    if out[-1] != {"role": "user", "content": [png]}:
        fail("nested cache_control must not ride the converted image part, got {!r}".format(out))
        return
    if stripped_out != ["messages"]:
        fail("nested image cache_control must be reported via cache_stripped_out, got {!r}".format(stripped_out))
        return
    pass_("tool_result images: user-message parts, pairing-independent, counted when malformed")


def test_anthropic_to_chat_image_blocks_no_mutation():
    """The image conversion never mutates its input: the parts array and every
    image_url part are fresh structures."""
    print("\n--- Test: Anthropic To Chat Image Blocks No Mutation ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    import copy
    inp = [
        {"role": "user", "content": [
            {"type": "text", "text": "a"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": "aGVsbG8="},
             "cache_control": {"type": "ephemeral"}},
            {"type": "tool_result", "tool_use_id": "x",
             "content": [{"type": "image", "source": {"type": "url",
                                                     "url": "https://e.com/i.png"}}]},
        ]},
    ]
    snapshot = copy.deepcopy(inp)
    fn(inp, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    if inp != snapshot:
        fail("input was mutated: {!r}".format(inp))
        return
    pass_("input untouched; conversion builds fresh structures")


def test_chat_to_anthropic_image_parts_filtered():
    """Deliberate boundary: the response direction is REQUEST-ONLY by operator
    decision 2026-10-22. A provider image part in a buffered chat response stays
    filtered by the text-only branch -- no chat provider emits image parts, and
    the Anthropic Messages response schema has no image block for the client to
    render anyway."""
    print("\n--- Test: Chat To Anthropic Image Parts Filtered ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "c1", "model": "gpt-x",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": [
                             {"type": "text", "text": "kept"},
                             {"type": "image_url",
                              "image_url": {"url": "https://e.com/i.png"}}]},
                         "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out, dict) else None
    if content != [{"type": "text", "text": "kept"}]:
        fail("image parts must stay filtered in the response direction, got {!r}".format(content))
        return
    if any(b.get("type") == "image" for b in (content or [])):
        fail("an image block leaked into the response content")
        return
    pass_("response direction filters provider image parts, as documented")


ALL_TESTS = [
    ("anthropic-to-chat-image-blocks-converted", test_anthropic_to_chat_image_blocks_converted),
    ("anthropic-to-chat-tool-result-images-converted", test_anthropic_to_chat_tool_result_images_converted),
    ("anthropic-to-chat-image-blocks-no-mutation", test_anthropic_to_chat_image_blocks_no_mutation),
    ("chat-to-anthropic-image-parts-filtered", test_chat_to_anthropic_image_parts_filtered),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_transform_images")

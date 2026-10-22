# Plan: Map Anthropic image content blocks to OpenAI image_url parts in chat mode
**Plan ID:** 2026-10-22-chat-mode-image-blocks
**Created:** 2026-10-22

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. Contains per-role action-only directives (no rationale) telling agents what to do next. Agents read the full plan for context. -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [defer-issue-image-content-blocks-chat-mode](./tmp/reports/defer-issue-image-content-blocks-chat-mode.json) | Resolved | 2026-08-29 | 2026-10-22 | coder & tester |

This plan **adopts** the deferral above. One scope narrowing, by operator decision
2026-10-22: the deferral's *expected_behavior* asked for both directions, and the
operator chose **request-direction only**. The rejected reverse direction
(provider `image_url` parts in a buffered chat response → Anthropic image blocks)
is dead at both ends: the chat-completions assistant-message schema has no image
part type (no served chat model emits one), and the Anthropic Messages *response*
schema has no image block either — image blocks are input-only on both APIs, so
Claude Code could not render a converted response image. That reasoning is
recorded in `## Summary` § Out of scope; resolving this row requires no further
work beyond the request direction.

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/transforms_chat.py` — the ONLY file.
No test files, no docs, no other source.

**Round completion — read this before you start.** Run any command that can spawn
a proxy or run a test with an explicit `timeout`, and **write your session report
before you end your turn, whatever the result.** A round that reports nothing is
treated as a failed round even when its code landed.

Both steps are surgical edits inside `_transform_anthropic_messages_to_chat`'s
**user-role** branch plus one module-level helper. The assistant branch, the
other-role passthrough, `_chat_to_anthropic`, and every other function in the
file, the wire, and the retry loop are untouched. Both edits carry their exact
replacement text below; the FINAL branch text after Step 2 is given once at the
end of Step 2 so the coder can check the whole loop shape at once.

### Step 1 — the converter helper and top-level user-message images

**Why this step exists.** Today a user-message `image` block is dropped and
counted (`dropped["image"] += 1`), and the user message's `content` is always a
joined string. After this step, a valid image block becomes an OpenAI
`image_url` part, and a user message that carries at least one **valid** image
emits its content as a **parts array** — the merged text part first, then the
image parts in block order. Text-only messages keep the string shape exactly as
today, so every existing test that sends no image stays green.

**Edit 1 — the helper.** Insert verbatim immediately after
`_transform_anthropic_messages_to_chat`'s `    return out` (the line before
`def _transform_tool_result_to_chat_tool(block, known_ids):`):

```python
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
```

**Edit 2 — the user branch (three spots, all inside `elif role == "user":`).**

(a) Immediately after `            text_parts = []` add:

```python
            image_parts = []
```

(b) Replace the image-drop block

```python
                if btype == "image":
                    dropped["image"] += 1
                    continue
```

with:

```python
                if btype == "image":
                    part = _anthropic_image_to_chat_part(block)
                    if part is None:
                        dropped["image"] += 1
                    else:
                        image_parts.append(part)
                    continue
```

(c) Replace the tail

```python
            out.extend(tool_messages)
            if text_parts:
                text = "\n".join(t for t in text_parts if isinstance(t, str))
                out.append({"role": role, "content": text})
```

with:

```python
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
```

**Edit 3 — the function docstring.** In
`_transform_anthropic_messages_to_chat`'s docstring, replace the clause
"image / unknown blocks are stripped" with:

```
a valid `image` block becomes an OpenAI `image_url` part
(`_anthropic_image_to_chat_part` converts it; an inconvertible one is
counted as dropped rather than becoming a part); unknown blocks are
stripped
```

Contract points this step pins (the Step-1 gate asserts every one):

- **The data: URI is `data:<media_type>;base64,<data>` — concatenation, not
  re-encoding.** The Anthropic payload is already standard base64; the gate
  feeds `"aGVsbG8="` with `media_type` `image/png` and asserts the exact URL
  `data:image/png;base64,aGVsbG8=`. No `base64` module import, no
  decode/encode round-trip — a round-trip would corrupt nothing but waste
  memory on multi-MB images and is not needed.
- **Inconvertible → None, and None → `dropped["image"] += 1`.** The S4–S14
  matrix (missing source, non-dict source, unknown type, the Files-API `file`
  source, base64 without/with-empty/non-string `media_type`/`data`, url with
  empty/non-string `url`) must all return None; a malformed top-level image
  must leave the message's content a **string** (not an array) and be counted
  `1` in the coalesced `content_block_dropped` event's `dropped_counts.image`.
- **Array shape only when a valid image survived.** W2 and W4 pin both
  directions: text-only stays a string; text + malformed image also stays a
  string. W1 and W3 pin the array: text part first, image parts in block
  order.
- **`cache_control` on a converted image is stripped** (the emitted part is a
  freshly built dict — the helper copies nothing else) and still reported via
  the existing per-request `cache_control_stripped` path (`cache_stripped_out
  == ["messages"]`).
- **No input mutation.** W8 pins it; the branch builds fresh dicts.
- **Nothing else moves.** The assistant branch, the `content is None or []`
  early return, the tool_result branch (still its Step-1 form: text-only), and
  the other-role passthrough are byte-identical after this step.

→ coder verify (auto): `grep -n "_anthropic_image_to_chat_part\|image_parts" src/claude_retry_proxy/transforms_chat.py` shows exactly one `def _anthropic_image_to_chat_part(block):`, **one** call site inside the user branch, and the four `image_parts` sites (init, append, `if image_parts:`, `parts.extend(image_parts)`); `grep -n 'dropped\["image"\]' src/claude_retry_proxy/transforms_chat.py` shows the increment only on the part-is-None path; the docstring clause no longer reads "image / unknown blocks are stripped"; `python -c "import claude_retry_proxy.transforms_chat as t; print(t.__file__)"` exits 0 and prints this repo's `src/claude_retry_proxy/transforms_chat.py` (`python3` is an identical 3.14.3 here — either works)
→ coder verify (scripted): `python ./tmp/verification/2026-10-22-chat-mode-image-blocks-step1.py` → **23/23 PASS, exit 0**. It read **5 FAIL / exit 1** against the pre-change tree (S2, S3, W1, W3, W6 — measured by the planner on 2026-10-22; the passes are the continuity checks: the drop-count semantics for a malformed image and the string-shape invariants)
→ tester verify: every pre-existing test in `tests/test_chat_transform.py` passes unchanged (module baseline **51/51**), including `test_anthropic_to_chat_content_block_dropped_trace` — its image fixture has no `media_type`, so it now exercises the malformed-image path and counts exactly as before

### Step 2 — tool_result-nested images

**Why this step exists.** Image blocks nested inside a `tool_result`'s content
list are the path Claude Code actually produces for images (the Read tool
returns them), and they are silently dropped today — the
`_transform_tool_result_to_chat_tool` helper keeps only text parts. OpenAI
`role:tool` messages **cannot carry images** (tool content is a string of
text/structured data), so the prescribed OpenAI pattern — and the shape this
step emits — is: the tool text rides the `role:tool` message, and the images
ride the **following user message** as `image_url` parts.

**Edit — the tool_result branch.** Replace

```python
                if btype == "tool_result":
                    t = _transform_tool_result_to_chat_tool(block, tool_use_ids)
                    if t is None:
                        dropped["tool_result"] += 1
                        continue
                    tool_messages.append(t)
                    continue
```

with:

```python
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
```

**Edit 2 — the docstring clause from Step 1** now covers both sites. Replace
the Step-1 wording

```
a valid `image` block becomes an OpenAI `image_url` part
(`_anthropic_image_to_chat_part` converts it; an inconvertible one is
counted as dropped rather than becoming a part); unknown blocks are
stripped
```

with:

```
a valid `image` block becomes an OpenAI `image_url` part -- top-level
blocks and those nested inside `tool_result` content alike, the latter
riding the following user message because OpenAI `role:tool` messages
cannot carry images; an inconvertible image is counted as dropped rather
than becoming a part; unknown blocks are stripped
```

**The final user-branch shape after both steps** (for a whole-loop check; the
tool_result text conversion helper `_transform_tool_result_to_chat_tool` is
byte-untouched):

```python
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
                parts = []
                if text:
                    parts.append({"type": "text", "text": text})
                parts.extend(image_parts)
                out.append({"role": role, "content": parts})
            elif text:
                out.append({"role": role, "content": text})
```

Contract points this step pins (the Step-2 gate asserts every one):

- **Text stays on the tool message, images move to the following user
  message.** T1: tool_result content `[text "res", image]` plus user text →
  `role:tool` content `"res"`, then a user message whose parts are `[text
  "Thanks", image_url]`.
- **An image-only tool_result still emits its images.** T2: the tool message
  keeps the existing `""` content, and a user message of image-only parts
  follows — the image is never lost just because there is no text.
- **Extraction is independent of `tool_use_id` pairing.** T5: a dangling
  result (id matches no emitted call) drops the tool *message* (existing
  rule, unchanged) but its images still flow onto the user message.
- **Malformed nested images are counted, not parts.** T3/T4.
- **Block order is the walk order.** T6: a nested image then a top-level image
  produce parts in that order after the merged text part.
- **`cache_control` on nested images is stripped and reported.** T7/T8.
- **`_transform_tool_result_to_chat_tool` is untouched** (T9 pins its
  return value for a text-only result).

→ coder verify (auto): `grep -n "_anthropic_image_to_chat_part(" src/claude_retry_proxy/transforms_chat.py` shows exactly **two** call sites; `grep -n "nested = block.get" src/claude_retry_proxy/transforms_chat.py` shows the one nested loop, guarded by `if isinstance(nested, list):`; `grep -n "return {\"role\": \"tool\"" src/claude_retry_proxy/transforms_chat.py` still shows exactly `_transform_tool_result_to_chat_tool`'s unchanged return; the docstring clause names top-level and nested alike; `python -c "import claude_retry_proxy.transforms_chat"` exits 0 with the `src/` path
→ coder verify (scripted): `python ./tmp/verification/2026-10-22-chat-mode-image-blocks-step2.py` → **10/10 PASS, exit 0** (it read **7 FAIL / exit 1** against the pre-change tree — T1, T2, T4, T5, T6, T7, T8 — and the same 7 FAIL against the Step-1-only tree, since Step 1 does not touch the nested path); **and** `python ./tmp/verification/2026-10-22-chat-mode-image-blocks-step1.py` still reads **23/23 PASS, exit 0** — the Step-1 gate is the regression backstop
→ tester verify: the Step-3 `test_anthropic_to_chat_tool_result_images_converted` passes; every pre-existing test passes unchanged

## Guidance for Tester

**Files to modify:** `tests/test_chat_transform.py` only. Do not touch
`src/claude_retry_proxy/transforms_chat.py` (Steps 1 and 2 are the coder's
lane) and do not touch `doc/**`, `README.md` or `CLAUDE.md` (planner-owned).

**Round completion — read this before you start.** Bound every command that can
spawn a proxy or run a test with an explicit `timeout`, run the module and the
full suite in the **foreground**, and **write your session report before you end
your turn.**

### Step 3 — four permanent tests

**Where these go.** `tests/test_chat_transform.py` already carries the
analogue — `_require_server_func("_transform_anthropic_messages_to_chat")`, the
`_trace_events_for_request` helper, and `ALL_TESTS` at the bottom of the file.
Append the four functions before `ALL_TESTS` and register all four at the end
of `ALL_TESTS`. The module baseline is **51 registered tests, 51/51 passing**
(the planner's run; the drop-trace test's image fixture has no `media_type`, so
it becomes a malformed-image check and must keep passing **untouched**).

**Division of labour — read this before writing anything.** The pure conversion
rule (data-URI composition, url verbatim, the None→dropped matrix, part
ordering, tool_result text split) is pinned by the coder's two gates. **Your
lane is everything the gates cannot see**: the drop-count semantics against the
trace (the gates cover them, but only for the request ids they control),
regression surface, and the one deliberate boundary this plan draws — the
response direction stays text-only. Do not re-implement the gates' truth tables
as test cases; if you find a gap in them, add a case and say so in your report.

```python
def test_anthropic_to_chat_image_blocks_converted():
    """User-message image blocks become image_url parts: base64 payloads as
    `data:<media_type>;base64,<data>` URIs, url sources verbatim; the message's
    content becomes a parts array (merged text part first, images in block
    order) exactly when a valid image survives; text-only messages keep the
    string shape; inconvertible images are dropped and counted."""
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
    pass_("image blocks: base64 data URI, url verbatim, block order, string shape kept, malformed counted")


def test_anthropic_to_chat_tool_result_images_converted():
    """Image blocks nested in tool_result content ride the following user
    message as image_url parts while the tool text rides the role:tool message
    -- the OpenAI pattern, since role:tool messages cannot carry images.
    Extraction is independent of tool_use_id pairing; malformed nested images
    are counted; an image-only tool_result still yields its images."""
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
```

**Tests to create:**
- **Permanent:** the four functions above.
- **Temporary:** none.

**Tests to investigate for retirement:**
- **No test obsolescence identified.** Nothing is removed, and the shipped
  image fixture in `test_anthropic_to_chat_content_block_dropped_trace` has no
  `media_type`, so it now pins the malformed-image path — it must keep passing
  **untouched**. Verify, do not edit. Tester may identify additional candidates
  during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being
removed/changed. If obsolete: delete and note in session report. If still valid:
document why in session report (e.g., "tests error handling path still present").

→ tester verify: `tests/test_chat_transform.py` rises **51 → 55** registered
  tests and reads **55/55 exit 0**; the full suite moves **432 → 436 passed** over
  the planner-measured clean-tree baseline, with the failure count **unchanged at
  the recorded baseline of 1** — that one failure (`compat-single-retry-global`,
  `tests/test_compat.py`) is outside the touched module, pre-existing relative to
  this plan, and dispositioned per `## History`; this plan adds no failing test,
  and a new failure is a finding, not a baseline artefact. The report states the
  **measured** before/after counts. The four pre-existing neighbours — `test_anthropic_to_chat_content_block_dropped_trace`,
  `test_anthropic_to_chat_messages_tool_result_to_role_tool`,
  `test_anthropic_to_chat_tool_result_list_content`, and
  `test_chat_to_anthropic_content_array` — pass unchanged.

## Summary

**The problem.** Chat mode strips every image a Claude Code session sends:
top-level user-message `image` blocks are dropped and counted
(`transforms_chat.py`, the user branch), and the path Claude Code actually uses
— image blocks nested in `tool_result` content (the Read tool returning an image
file) — dies silently in `_transform_tool_result_to_chat_tool`, which keeps only
text parts. Since full history is resent every turn, every request of an
image-bearing session carries the blocks. A vision-capable chat provider sees
neither.

**The change — one source file, two edits, no wire, no new trace events.** In
`_transform_anthropic_messages_to_chat`'s user branch, valid image blocks become
OpenAI `image_url` parts via a new pure helper `_anthropic_image_to_chat_part`;
a user message that carried at least one valid image emits its `content` as a
parts array (merged text part first, image parts in block order), and images
nested in `tool_result` content ride the following user message, because OpenAI
`role:tool` messages cannot carry images. Inconvertible images — a missing or
non-dict `source`, an unknown source type, the Files-API `file` source, a
base64 block without `media_type`/`data` — are dropped and counted exactly as
today, reusing the coalesced `content_block_dropped` event.

```
user message content
 ├─ text blocks        → merged string ("\n"-joined, existing)
 ├─ image (valid)      → {"type":"image_url","image_url":{"url":...}}   [NEW]
 │     source.base64   →   "data:<media_type>;base64,<data>"  (payload verbatim,
 │                         no re-encoding; detail omitted → upstream default)
 │     source.url      →   the URL verbatim
 │     source.file /   →   None → dropped["image"] += 1 (existing event)
 │     malformed
 ├─ tool_result        → role:tool message with the text parts (existing)
 │     content images  →   image_url parts on the FOLLOWING user message  [NEW]
 └─ emission           →   content: parts array iff a valid image survived,
                          else the joined string (existing, exact)
```

**Verified against live primary documentation on 2026-10-22** (Firecrawl of the
OpenAI vision guide and the Anthropic vision guide; WebSearch of the OpenAI
function-calling pattern and the Claude Code docs):

| Contract | Source |
|---|---|
| `image_url` part: `{type, image_url: {url, detail?}}`; url is https **or** a `data:image/<mime>;base64,<data>` URI; `detail` optional, defaults `auto` | [OpenAI vision guide](https://developers.openai.com/api/docs/guides/images-vision) |
| Content is a string or an array mixing `text` and `image_url` parts in one **user** message; `image_url` is legal in **no other role**; tool messages "may contain text and/or structured content, but cannot contain images" | [OpenAI chat/create reference](https://platform.openai.com/docs/api-reference/chat/create) |
| The prescribed OpenAI shape for an image a tool produced: tool returns text/JSON in the `role:tool` message, **the image goes in a subsequent user message** as `image_url` | [OpenAI function-calling guide](https://platform.openai.com/docs/guides/function-calling) |
| Anthropic image block: `{type:image, source:{type:base64, media_type, data}}` or `{type:url, url}`, plus a Files-API `{type:file, file_id}` variant with no chat equivalent; images nested in `tool_result.content` are explicitly legal; multiple images per message with interleaved labels recommended | [Anthropic vision guide](https://platform.claude.com/docs/en/build-with-claude/vision) |
| Claude Code sends Read-on-image results as `tool_result` blocks whose content is an image block; chat attachments are top-level image blocks | [Claude Code common workflows](https://code.claude.com/docs/en/common-workflows), [tools reference](https://code.claude.com/docs/en/tools-reference) |

**Design decisions, and why.**

- **D1 — parts array only when a valid image survived.** Text-only messages keep
  today's string `content` byte-for-byte; the array is constructed only around
  converted images. Every existing test that sends no valid image is untouched
  by construction.
- **D2 — merged text part first, images in block order.** The file's idiom is
  already "all text runs join into one string", so intra-message text/image
  interleaving is not emulated; the images themselves keep their relative block
  order (the ordering Anthropic's multi-image guidance cares about). Step 1's
  text-first rule and Step 2's walk-order rule are pinned by the gates.
- **D3 — the data URI is concatenation, never re-encoding.** Both APIs use
  standard base64; the Anthropic payload and `media_type` are concatenated
  verbatim. No new imports, no multi-MB decode/re-encode on the request path.
  `detail` is omitted so the upstream applies its own default (`auto`).
- **D4 — inconvertible = dropped + counted, with the existing event.** The
  helper returns None for every unrepresentable shape (the `file` source
  included), and None increments the existing `dropped["image"]` counter that
  feeds the coalesced `content_block_dropped` event — so `image` in
  `dropped_counts` now means *malformed only*. The shipped drop-trace test's
  fixture has no `media_type` and therefore stays green **unchanged**.
- **D5 — tool_result images ride the following user message.** This is the
  exact shape OpenAI's own function-calling image pattern prescribes, and
  extraction is deliberately independent of `tool_use_id` pairing: a dangling
  result still loses its *message* (existing rule — an unpaired tool message is
  an upstream error) but never its images, which cannot cause that error.
- **D6 — `cache_control` stripped wherever it rides.** Both top-level and
  nested image blocks clear the existing per-block `cache_control` flag path,
  so `cache_control_stripped` stays one coalesced event per request.
- **D7 — the response direction is deliberately unchanged** (operator decision
  2026-10-22): provider image parts in a buffered chat response stay filtered
  by the text-only branch. No served chat model emits image parts, and the
  Anthropic response schema has no image block type — the conversion would
  produce content no client can render.

**Alternatives considered.**

- *Full text/image interleaving in the parts array* — rejected: the file's
  existing merge-then-emit idiom already loses intra-message interleaving
  between text and tool results; D2 captures the useful ordering (images in
  block order) at a fraction of the complexity.
- *A config flag gating image conversion* — rejected: nothing was requested,
  and a flag would fork the transform for no demonstrated need (YAGNI).
- *Convert the response direction too (the deferral's original shape)* —
  rejected by operator decision 2026-10-22 for the reasons in D7; the
  narrowing is recorded on the Issue Log row, not silently.
- *Re-encode base64 through the `base64` module "for safety"* — rejected: both
  sides accept standard base64; a decode/encode round-trip adds CPU on the
  request path without changing a byte.

**Explicitly out of scope.** The response direction (D7); response mode
(`transforms_response.py`) images; `document`/PDF blocks; image blocks in
assistant or system positions (still dropped as `unknown`, as today); streaming
responses (chat deltas carry text/tool-call fragments only, so nothing to
convert); `image_url` on messages the proxy merely passes through
(`_sanitize_body_tools` and the anthropic-mode verbatim forward are untouched).

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

If the plan intentionally contradicts a documented rule (in `CLAUDE.md` or `doc/*`), declare the override here. An empty or absent table means zero tolerance — every documented rule is in force.

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| A non-vision chat provider that previously received the conversation with images silently stripped now receives `image_url` parts | That provider's 400 for traffic that used to work | Inherent to the feature; the proxy cannot know per-provider vision support, and the chat-mode target tier is configured by the operator for a vision-capable backend. The drop counter now means *malformed only*, so `content_block_dropped` no longer reports this class — the trace's `--all` request bodies (existing exposure caveat) are the observability for what was converted. No code mitigation added; the README sentence states what is mapped. |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1:** Add the pure helper `_anthropic_image_to_chat_part(block)` to `src/claude_retry_proxy/transforms_chat.py` (base64 → `data:<media_type>;base64,<data>` part, url → verbatim part, everything else → None) and wire it into `_transform_anthropic_messages_to_chat`'s user branch for top-level image blocks — `image_parts` accumulation, parts-array emission (text part first) only when a valid image survived, None → `dropped["image"] += 1`, and the function docstring's "image / unknown blocks are stripped" clause rewritten; the user branch needs `python` but no new imports
   → coder verify (auto): `grep -n "_anthropic_image_to_chat_part\|image_parts" src/claude_retry_proxy/transforms_chat.py` shows one `def`, one call site, four `image_parts` sites; `dropped["image"]` incremented only on the None path; the docstring clause no longer reads "image / unknown blocks are stripped"; `python -c "import claude_retry_proxy.transforms_chat as t; print(t.__file__)"` exits 0 and prints the repo's `src/` path
   → coder verify (scripted): `python ./tmp/verification/2026-10-22-chat-mode-image-blocks-step1.py` → 23/23 PASS, exit 0. Calibrated RED: 5 FAIL / exit 1 against the pre-change tree (measured 2026-10-22)
   → tester verify: the pre-existing module tests pass unchanged (baseline 51/51), including the drop-trace test whose media_type-less image fixture now pins the malformed path

2. **Step 2:** Wire tool_result-nested image blocks in the same user branch — `_transform_tool_result_to_chat_tool`'s text extraction untouched, plus a nested-content loop that converts each nested image through the Step-1 helper into the following user message's parts (extraction independent of `tool_use_id` pairing; nested `cache_control` strips and reports), and revise the Step-1 docstring clause to cover top-level and nested alike
   → coder verify (auto): exactly two `_anthropic_image_to_chat_part(` call sites; the nested loop present behind `isinstance(nested, list)`; `_transform_tool_result_to_chat_tool`'s `return {"role": "tool", ...}` line unchanged; import exits 0 with the `src/` path
   → coder verify (scripted): `python ./tmp/verification/2026-10-22-chat-mode-image-blocks-step2.py` → 10/10 PASS, exit 0 (calibrated RED: 7 FAIL / exit 1 pre-change); the Step-1 gate re-reads 23/23 PASS, exit 0
   → tester verify: `test_anthropic_to_chat_tool_result_images_converted` passes; all pre-existing tests unchanged

3. **Step 3:** Add four permanent tests to `tests/test_chat_transform.py` — conversion matrix (data URI / url / ordering / string-shape / malformed counting), tool_result-nested conversion (pairing independence, image-only results, malformed counting), no-input-mutation, and the deliberate response-direction filter — registered in `ALL_TESTS` (tester-owned; no coder work)
   → tester verify: `tests/test_chat_transform.py` rises 51 → 55 and reads 55/55 exit 0; the full suite's pass count rises by exactly 4 over the planner-measured baseline with the failure count unchanged; `test_anthropic_to_chat_content_block_dropped_trace`, `test_anthropic_to_chat_messages_tool_result_to_role_tool`, `test_anthropic_to_chat_tool_result_list_content` and `test_chat_to_anthropic_content_array` pass unchanged; the report states the measured before/after counts

4. **Step 4:** Reconcile the documentation with the landed code — `doc/provider-modes.html` (the chat-request table's image row split into converted/dropped, the tool_result row's nested-image clause, a new `#image-content-blocks` paragraph stating the conversion semantics; the chat-response section gains one sentence stating the deliberate request-only filter), `README.md` (replace the "Image content blocks are not mapped…" sentence with the mapped/request-only statement), `CLAUDE.md` (one "Moved out" Gotchas row pointing at the new anchor), and `doc/test-catalog.html` (four per-test rows + the tester's measured counts) (planner-owned; no coder or tester work)
   → Evidence: `grep -n image_url doc/provider-modes.html README.md CLAUDE.md doc/test-catalog.html` shows every surface and the exact sentences; `python scripts/check_doc_anchors.py` exits 0; `python ~/.claude/scripts/doc_structure_check.py` exits 0

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./doc/provider-modes.html`
  - `./README.md`
  - `./CLAUDE.md`
  - `./doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** does not exist in this repo — nothing to update.
- **When:** after the coder and tester finish (the prose must match the landed
  code, and the catalog must carry the tester's *measured* counts).
- **What to sync:**
  - `doc/provider-modes.html` — three edits:
    1. **The chat-request table (~lines 128–137).** Replace the row
       `<tr><td><code>image</code> and unknown blocks</td><td><strong>stripped</strong></td></tr>`
       with two rows: the image row (base64 → `data:` URI `image_url` part, url
       → verbatim, inconvertible incl. the Files-API `file` source → stripped
       and counted) and an unknown-blocks row (stripped). Extend the
       `tool_result` row with the nested clause: images in its content become
       `image_url` parts on the following user message.
    2. **A new paragraph, `id="image-content-blocks"`, after the table** (before
       the `id="pattern-normalization"` paragraph): the parts-array emission rule
       (text part first, images in block order; string shape unchanged for
       text-only), the concatenation-not-re-encoding rule, extraction
       independent of pairing, `cache_control` stripping, and the
       `content_block_dropped` counter's new meaning (inconvertible only).
    3. **The chat-mode response section** (the buffered `_chat_to_anthropic`
       description around line 241): one sentence stating that provider image
       parts in a buffered response are filtered — the conversion is
       request-direction-only by operator decision 2026-10-22, because no chat
       provider emits image parts and the Messages response schema has no image
       block type.
  - `README.md` — the sentence at ~lines 419–420, "Image content blocks are not
    mapped between Anthropic and OpenAI formats.", becomes: "Image content
    blocks are mapped in the Anthropic→Chat request direction: valid `image`
    blocks — top-level and inside `tool_result` content — become `image_url`
    parts (base64 as `data:` URIs, URLs verbatim); inconvertible blocks are
    dropped and counted. The reverse direction is request-only by design: chat
    response bodies keep their text-only filter." Keep it in place; no new
    section.
  - `CLAUDE.md` — one new row in the **"Moved out of this section"** Gotchas
    table: "Chat mode maps `image` blocks — top-level and `tool_result`-nested —
    to `image_url` parts (base64 → `data:` URI, url verbatim, merged text part
    first); inconvertible images (incl. the Files-API `file` source) are dropped
    and counted, and the reverse direction is deliberately request-only" linking
    `doc/provider-modes.html#image-content-blocks`. One row only; delete nothing.
  - `doc/test-catalog.html` — the four new per-test rows in the
    `tests/test_chat_transform.py` section, and the suite/module counts
    **taken from the tester's session report; do not guess them** (the module
    table row and the suite-total chain gain the new totals with the prior
    counts prepended, per the file's existing convention).
- **Deferral bookkeeping.** When Steps 1–3 are complete, the `/update-plan`
  takes the `image-content-blocks-chat-mode` row to `Resolved`; the report
  `./tmp/reports/defer-issue-image-content-blocks-chat-mode.json` is deleted by
  `/update-and-commit` Step 9.6 in the same act that commits the plan — do not
  delete it earlier. The row's scope-narrowing note above is the record of the
  operator's request-only decision.
- **Both doc gates, always, after the final edit:**
  `python scripts/check_doc_anchors.py` and
  `python ~/.claude/scripts/doc_structure_check.py` — record their output in
  the `## Documentation` section.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-22 | Initial plan | Restructured defer-issue-image-content-blocks-chat-mode into a plan after primary-source homework (Firecrawl of both vision guides, WebSearch of the OpenAI function-calling image pattern and the Claude Code docs — facts table in `## Summary`). Operator decisions: tool_result-nested conversion included (the path Claude Code actually uses), response direction **request-only** (recorded on the Issue Log row). Two coder steps + one tester step + one planner doc step; one source file. **Mega-audit not triggered** (4 steps, 1 source file — below both write-time thresholds). Gates written and calibrated RED against the pre-change tree on 2026-10-22: step1 **5 FAIL / exit 1**, step2 **7 FAIL / exit 1**, both exit 0 only after their steps land. **Clean-tree baselines measured by the planner**: module `tests/test_chat_transform.py` **51/51 exit 0**; full suite **432 passed / 1 failed / 433 total** (exit 1) on this machine's Python 3.14.3. The single failure is `compat-single-retry-global` (`tests/test_compat.py`, "expected at least one reasoning_rescue event per served complainer, got 4") — the test rewritten by the just-landed reasoning-field plan (`92b5977`), a five-complainer concurrency pin, **outside this plan's modules**. The 8 frozen py3.14 band failures of defer-issue-suite-json-recursion-profile-py314 **pass** on this interpreter (3.14.3, not the 3.14.7 the deferral was measured on). The failure is pre-existing relative to this plan and is dispositioned, not waved through. **Evidence, corrected after the operator reported a machine halt (~15:00–16:2x, 2026-10-22):** the original three-run record was contaminated (one isolated run was frozen mid-execution, and one passing run was captured in the resume window). Re-measured **post-halt** on Python 3.14.3 with a live proxy up: **3/3 clean isolated runs fail with the identical assertion** ("expected at least one reasoning_rescue event per served complainer, got 4", logs `./tmp/verification/compat-clean-run{1,2,3}.log`), plus the full-suite failure — while the originating reasoning-field plan's two suite runs passed the same code on Python 3.14.7. The pin is interpreter-patch-sensitive, not load-intermittent. Filed 2026-10-22 as [defer-issue-compat-single-retry-global-intermittent](./tmp/reports/defer-issue-compat-single-retry-global-intermittent.json) (standalone deferral, no plan row — this plan does not adopt it; the tester's Step-3 expectation freezes it as the recorded baseline failure count of 1). | — |

| 2026-10-22 | Coder round 1 | **exit 0** (log `./tmp/logs/2026-10-22-chat-mode-image-blocks-coder-2026-10-22.log`, report `./tmp/reports/2026-10-22-chat-mode-image-blocks-coder-2026-10-22.json`): Steps 1–2 complete, `build_result: pass`, no issues filed. Modified `src/claude_retry_proxy/transforms_chat.py` only — matches the plan's single coder file; the report confirms every other function in the file is byte-identical per git diff. Planner re-ran both gates post-round: step1 **23/23 exit 0**, step2 **10/10 exit 0** (outputs `./tmp/verification/post-coder-step{1,2}.out`). Coder notes adopted for Step 4: `_anthropic_image_to_chat_part` is deliberately not in `__all__` (plan never asked; gates reach it via module attribute access), and the doc step must state (a) `dropped_counts.image` now means malformed/inconvertible images only, (b) the parts-array shape appears only when a valid image survives. Post-coder `/update-plan`: nothing resolved, no step/file changes — accumulation unchanged, mega-audit trigger not met; revision non-substantive, so no `## Immediate Actions` section. | — |

| 2026-10-22 | Implementation round (tester) — failed round; retry used (1) | Launched 19:25:12, host halt (~19:55–21:04, operator-confirmed) froze the round mid-suite with no report written; the launcher's wall-clock cap fired on wake (`timeout: killed after 3600s`, exit 3, no `tree not confirmed dead` suffix — tree confirmed dead). Assessed before the retry: prestate delta is exactly `tests/test_chat_transform.py`; the planner re-ran the module post-halt **55/55 exit 0** with all four tests registered in `ALL_TESTS`. | — |

| 2026-10-22 | Implementation round (tester) — round 2 (the retry); exit 0 | Launched 21:12:57 from the `## Immediate Actions` brief, report `./tmp/reports/2026-10-22-chat-mode-image-blocks-tester-2026-10-22.json`. Module **55/55 exit 0**; full suite **436 passed / 1 failed / 437** (+4 over baseline, failures unchanged at 1 — the predicted recorded baseline). All four tests re-verified, reachability measured RED under shadow-package variants for all four (helper neutralised; response-converting variant; mutating variant) — none vacuous. Both coder gates re-read green (23/23, 10/10). Strict verdict FAILURE solely on the out-of-scope pre-existing `compat-single-retry-global`; the tester's two isolated runs of the identical command measured **PASS then FAIL** — the failure is load/interleaving-dependent, refining the deferral's title claim; recorded in the deferral's `updates` array in place (no duplicate report — dedup rule). | — |

| 2026-10-22 | Phase 6 gate — paused by operator decision | Prerequisites checked after Step 4: Issue Log green (sole row Resolved, deferral disposition), coder report `build_result: pass`, tester report exists but `overall_result: FAILURE` — strictly, only on the out-of-scope pre-existing `compat-single-retry-global` (in-scope evidence: module 55/55, suite 432→436 passed with failures unchanged, both coder gates re-read green, all four tests reachability-proven). The SUCCESS-report prerequisite is unmet in the letter and the substitute-evidence clause covers absent reports only. Presented to the operator with two options; the operator chose **fix the pin first**: a standalone test-only plan was written — [2026-10-22-compat-pin-rescue-bijection](./tmp/plans/2026-10-22-compat-pin-rescue-bijection.md), gate calibrated RED 5/5 pre-change — and this plan pauses until that one lands; afterwards this plan's tester round re-runs for a strict SUCCESS and Phase 6 resumes. Step 4 doc work is already complete and stays (see `## Documentation`). | — |

| 2026-10-22 | Implementation round (tester) — round 3 (the Phase-6 re-run); exit 0, **SUCCESS** | Launched 22:31:58 after the pin plan landed; report `./tmp/reports/2026-10-22-chat-mode-image-blocks-tester-2026-10-22-2.json`. Module **55/55 exit 0**; full suite **437 passed / 0 failed / 437 total, exit 0** (recorded baseline 432/1/433; +5 passed, −1 failed — four Step-3 tests plus the pin plan's compat fix). `blocking_failures` empty; the round-2 blocker now passes (4/4 bijection, the direct-serve interleaving the old assertion failed on). Reachability re-measured under three shadow copies — all RED as predicted; both coder gates 23/23 and 10/10; check_doc_anchors resolves 214/214 incl. `#image-content-blocks`. Doc tightening applied on this round's flagged observation: the `#image-content-blocks` sentence now carries the no-string-text clause (planner-owned, applied with the post-round `/update-plan`; doc gates re-run). | — |

| 2026-10-22 | Review (Phase 6) | Verdict **Issues found — non-blocking**: 0 Critical, 0 Warning, 11 Suggestion; ready to commit. Report [2026-10-22-chat-mode-image-blocks-review-2026-10-22.json](./tmp/reports/2026-10-22-chat-mode-image-blocks-review-2026-10-22.json). Reviewer key questions answered clean on all six: type-guards complete, no path mutates input or the tool message; nested images always land on the same message's user-role emission after its tool messages (role is never other than "user", no wrong-message interleaving); ordering, cache_control reporting and the narrowed drop counter all as documented; `_chat_to_anthropic` untouched; all four tests non-vacuous per the shadow evidence; doc prose matched except the items fixed below. Four of the eleven were planner-owned doc/text nits and are **fixed in place** (the reverse-direction wording inversion in README/CLAUDE.md, the `#image-content-blocks` text-shape sentence extended to "no non-empty string", the drift counter to twenty-two, the no-mutation row's function name); doc gates re-passed after the fixes. Seven code/test-scoped improvements are deferred as the slugs below. | `img-rev-media-type-whitespace`; `img-rev-sse-paragraph-placement`; `img-rev-tool-helper-docstring`; `img-rev-dangling-tool-result-assert`; `img-rev-s4-s14-gate-retirement`; `img-rev-no-mutation-fresh-structures`; `img-rev-dedup-convert-block` |

## Plan Metadata

```json
{
  "plan_id": "2026-10-22-chat-mode-image-blocks",
  "steps": [
    "Step 1: Add the pure helper _anthropic_image_to_chat_part to transforms_chat.py and wire top-level user image blocks through it (parts-array emission)",
    "Step 2: Wire tool_result-nested image blocks onto the following user message, extraction independent of tool_use_id pairing",
    "Step 3: Add four permanent tests to tests/test_chat_transform.py (conversion, nested tool_result, no-mutation, response filter)",
    "Step 4: Reconcile doc/provider-modes.html, README.md, CLAUDE.md and doc/test-catalog.html with the landed code"
  ],
  "coder_files": ["src/claude_retry_proxy/transforms_chat.py"],
  "tester_files": ["tests/test_chat_transform.py"],
  "doc_files": ["./doc/provider-modes.html", "./README.md", "./CLAUDE.md", "./doc/test-catalog.html"],
  "verification_scripts": ["./tmp/verification/2026-10-22-chat-mode-image-blocks-step1.py", "./tmp/verification/2026-10-22-chat-mode-image-blocks-step2.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-10-22 |
| steps_changed_since_audit | 0 | 2026-10-22 |
| files_changed_since_audit | 0 | 2026-10-22 |

## Documentation

Step 4 performed by the planner 2026-10-22 after the coder and tester rounds,
prose matched to the landed code and to the tester's measured counts.

- `doc/provider-modes.html` — chat-request table: the `image`/unknown row split
  into an image row (conversion semantics, stripped-and-counted inconvertibles,
  parts-array emission rule, link to the new anchor) and an unknown-blocks row;
  the `tool_result` row extended with the nested-image clause. New paragraph
  `id="image-content-blocks"` after the table (concatenation-not-re-encoding,
  pairing-independence, `cache_control` stripping, the narrowed meaning of
  `dropped_counts.image`). Chat-mode response section: one sentence stating the
  request-only operator decision and the text-only response filter.
- `README.md` — the "not mapped" sentence replaced with the mapped-in-request /
  request-only-reverse statement (~line 419).
- `CLAUDE.md` — one new "Moved out of this section" row pointing at
  `doc/provider-modes.html#image-content-blocks`.
- `doc/test-catalog.html` — four per-test rows; module count 51 → 55 (header
  and summary table); suite chain 433 → 437 with 433 prepended (the tester's
  measured numbers: module 55/55, suite 436+1/437).

Gates (outputs of 2026-10-22):
- `python scripts/check_doc_anchors.py` — **PASS**: 214 anchor references
  resolved, no unresolved anchors, no secret shapes. Exit 0.
- `python ~/.claude/scripts/doc_structure_check.py` — **PASS**: 9 files
  checked, no violations. Exit 0.

## Final Results

**Status: Complete — ready for operator approval and `/update-and-commit`.**

- **Steps 1–2 (coder):** `_anthropic_image_to_chat_part` + top-level and
  tool_result-nested wiring landed in `src/claude_retry_proxy/transforms_chat.py`
  (+83/−6, the only coder file; every other function byte-identical per git diff).
  Coder report `build_result: pass`; gates 23/23 and 10/10 exit 0.
- **Step 3 (tester):** four permanent tests in `tests/test_chat_transform.py`
  (+254/−0, pure additions), registered in `ALL_TESTS`; module 51 → 55; final
  tester report [2026-10-22-chat-mode-image-blocks-tester-2026-10-22-2.json](./tmp/reports/2026-10-22-chat-mode-image-blocks-tester-2026-10-22-2.json)
  reads `overall_result: SUCCESS`: module **55/55**, full suite
  **437 passed / 0 failed / 437 total, exit 0** (baseline 432/1/433; the one
  prior failure was the out-of-scope compat pin, fixed meanwhile by plan
  2026-10-22-compat-pin-rescue-bijection — this plan's round-3 suite exercises
  that revised test green, 4/4 bijection). Reachability proven under three
  shadow variants (all four tests' failing branches fire); the pre-existing
  drop-trace test was not edited and now pins the malformed-image path.
- **Step 4 (planner):** all four doc surfaces reconciled; both doc gates pass
  (anchors 214/214, structure 9 files, secrets clean). See `## Documentation`.
- **Review verdict:** *Issues found — non-blocking* — 0 Critical, 0 Warning,
  11 Suggestion. Report
  [2026-10-22-chat-mode-image-blocks-review-2026-10-22.json](./tmp/reports/2026-10-22-chat-mode-image-blocks-review-2026-10-22.json).
  Four planner-owned doc/text suggestions were fixed in place (History row);
  the other seven are deferred improvements, non-blocking.

**Known caveats (reviewer Suggestions — deferred improvements, non-blocking):**

- `img-rev-media-type-whitespace` — `media_type` is concatenated into the data
  URI without sanitization; a whitespace/control-char value would build an
  upstream-rejected URI. Anthropic emits well-formed types; deferred.
- `img-rev-sse-paragraph-placement` — the request-only sentence sits in the
  SSE-oriented paragraph though it describes buffered responses. Cosmetic;
  deferred.
- `img-rev-tool-helper-docstring` — `_transform_tool_result_to_chat_tool`'s
  docstring does not state that non-text blocks are ignored there. Deferred.
- `img-rev-dangling-tool-result-assert` — the dangling-tool_result test asserts
  only `out[-1]`, so a re-emitted role:tool message would pass. Deferred.
- `img-rev-s4-s14-gate-retirement` — the S4–S14 inconvertible matrix lives only
  in the tmp/ verification gate, which retires at commit. Deferred.
- `img-rev-no-mutation-fresh-structures` — the no-mutation test's "fresh
  structures" claim is unexercised by the assertion. Deferred.
- `img-rev-dedup-convert-block` — convert-or-count is duplicated between the
  nested and top-level paths, and the cache_control membership test now appears
  in three places. Deferred.

**Deferred issues**

- [defer-issue-image-content-blocks-chat-mode](./tmp/reports/defer-issue-image-content-blocks-chat-mode.json)
  — **Resolved by this plan** (Issue Log row above; `Resolved By: coder &
  tester`; scope narrowed to the request direction by operator decision
  2026-10-22, recorded on the row). The report file is deleted by
  `/update-and-commit` Step 9.6 when this plan commits; it must not be deleted
  earlier.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-08-29-fix-chat-mode-request-transform | `image-content-blocks-chat-mode` | This plan mapped Anthropic `image` blocks to OpenAI `image_url` parts in the chat request direction (top-level and tool_result-nested; base64 → `data:` URI, url verbatim, inconvertible dropped and counted) with four permanent tests and doc reconciliation; the reverse direction stays deliberately unmapped per operator decision 2026-10-22. |
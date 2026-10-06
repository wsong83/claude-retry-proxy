"""Shared mechanism for endpoint-mode response transforms: the passthrough-on-failure guard and the shared trace-timestamp helper."""

import json
import time

from .sinks import log_trace

__all__ = ["_transform_and_guard", "_request_transform_timestamp",
           "_strip_regex_identity_escapes", "_sanitize_schema_patterns",
           "_sanitize_body_tools", "_verbatim_copy"]


def _transform_and_guard(raw_body, tier, transform_fn, request_id, mode, provider):
    """Run a response transform on raw JSON bytes with passthrough-on-failure.

    json.loads runs INSIDE the guard: any failure — including RecursionError
    on deeply nested input, which is not a ValueError — logs a
    transform_failure trace event (metadata only — never body content) and
    returns the original raw bytes unchanged. Mirrors the total-parse idiom
    of compat._compat_guarded_parse.
    """
    try:
        parsed = json.loads(raw_body)
    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "transform_failure",
            "request_id": request_id,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
        return raw_body
    try:
        return json.dumps(transform_fn(parsed, tier, request_id=request_id, mode=mode, provider=provider)).encode("utf-8")
    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "transform_failure",
            "request_id": request_id,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
        return raw_body


def _request_transform_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _strip_regex_identity_escapes(pattern):
    r"""Strip ECMA identity escapes from one JSON-Schema `pattern` regex.

    Fixes the strict-backend 400 `^agent\_run\_ is not a "regex"` — Zod's
    startsWith emits a backslash before `_`, an identity escape that is
    definitionally the bare character, so dropping the backslash is a
    semantics-preserving portability normalization on every engine. Pure
    string->string; total in the sense that a trailing backslash (already
    malformed) is copied verbatim rather than reinterpreted.

    Invariant: a backslash is NEVER dropped before an ASCII letter or digit
    (meaningful in every engine: \d \w \s \n \t \x41 A \p{L} ...), nor
    before a metacharacter ^ $ \ . * + ? ( ) [ ] { } | (literal in every
    engine). `\-` is kept inside a character class (literal hyphen) and
    dropped outside it. A `]` in the first-member slot — immediately after
    `[` or `[^` — is a literal class member, not the terminator (ECMA),
    so `[]\-a]` is left unchanged rather than truncated to `[]-a]`.

    Reference (input -> output): `^agent\_run\_` -> `^agent_run_`;
    `foo\-bar` -> `foo-bar`; `[a\-z]` unchanged; `[a\-z]\-x` -> `[a\-z]-x`;
    `[]\-a]` and `[^]\-a]` unchanged; `\d{1,3}\.\d+`, `\s\w\n\t\x41A\p{L}\Qx\E\0`
    and the metachar string `\.\^\[\]\{\}\\\*\+\?\$\|` unchanged;
    `a\/b\:c\@d\!\#e` -> `a/b:c@d!#e`; `\ ` -> ` `; `ab\` and the empty
    string unchanged.
    """
    out = []
    in_class = False
    class_slot = False  # next char is the class's first-member slot (a ^ may
    # still precede it right after `[`; a `]` there is a literal member)
    just_entered = False
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\":
            class_slot = False  # the escaped char fills the first-member slot
            just_entered = False
            if i + 1 >= n:
                out.append(ch)  # trailing escape: already malformed, copy as-is
                break
            nxt = pattern[i + 1]
            keep = (("0" <= nxt <= "9") or ("A" <= nxt <= "Z")
                    or ("a" <= nxt <= "z")
                    or nxt in "^$\\.*+?()[]{}|"
                    or (nxt == "-" and in_class))
            if keep:
                out.append(ch)
                out.append(nxt)
            else:
                out.append(nxt)  # identity escape: the backslash is redundant
            i += 2
            continue
        if ch == "[" and not in_class:
            in_class = True
            class_slot = True
            just_entered = True
        elif just_entered and ch == "^":
            just_entered = False  # negation prefix: the member slot is ahead
        elif ch == "]" and in_class:
            if class_slot:
                class_slot = False  # leading ] is a literal member, not the end
                just_entered = False
            else:
                in_class = False
        else:
            class_slot = False
            just_entered = False
        out.append(ch)
        i += 1
    return "".join(out)


def _verbatim_copy(value):
    """Deep-copy a value-keyword subtree without interpreting it as a schema.

    Keeps the fresh-structure-at-every-level contract for the subtrees
    _sanitize_schema_patterns skips: content identical, new objects.
    """
    if isinstance(value, dict):
        return {k: _verbatim_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_verbatim_copy(v) for v in value]
    return value


def _sanitize_schema_patterns(node):
    """Return a position-aware copy of a tool input_schema with regexes sanitized.

    Walks a JSON-Schema document by NODE ROLE, so only regex-typed
    locations are rewritten and asserted data is never touched:

    - schema nodes (this function's normal path): a `pattern` string value
      and the keys of a `patternProperties` object are rewritten by
      _strip_regex_identity_escapes. Colliding `patternProperties` keys —
      two source keys differing only by identity escapes — merge as
      ``{"allOf": [existing, new]}`` instead of silently dropping one: the
      equivalent patterns all apply to a matching property.
    - value keywords `const`, `enum`, `default`, `examples` hold asserted
      DATA, not subschemas: copied verbatim (via _verbatim_copy), never
      recursed, so a `pattern`-keyed string inside them is not rewritten.
    - name->schema maps `properties`, `$defs`, `definitions`,
      `dependentSchemas`: their keys are names, never read as keywords and
      never sanitized, and each value is walked as a schema — which is what
      keeps a property legitimately named `const` or `default` sanitized.
    - every other value is walked as a schema (`items`, `prefixItems`,
      `allOf`/`anyOf`/`oneOf`, `not`, `if`/`then`/`else`, `contains`,
      `propertyNames`, `additionalProperties`, ...).

    Never mutates `node`: every dict/list level it touches is rebuilt
    fresh (scalar leaves may be shared). Total — a non-string `pattern`
    value, a non-string `patternProperties` key, non-dict/list nodes, and
    a malformed name-map value all pass through or recurse without
    assumption; nothing raises.
    """
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "pattern" and isinstance(value, str):
                out[key] = _strip_regex_identity_escapes(value)
            elif key == "patternProperties" and isinstance(value, dict):
                rebuilt = {}
                for pk, pv in value.items():
                    out_key = (_strip_regex_identity_escapes(pk)
                               if isinstance(pk, str) else pk)
                    sub = _sanitize_schema_patterns(pv)
                    if out_key in rebuilt:
                        # two source keys stripped to the same output key:
                        # merge so no schema entry is dropped
                        rebuilt[out_key] = {"allOf": [rebuilt[out_key], sub]}
                    else:
                        rebuilt[out_key] = sub
                out[key] = rebuilt
            elif key in ("const", "enum", "default", "examples"):
                out[key] = _verbatim_copy(value)  # asserted data, not a schema
            elif key in ("properties", "$defs", "definitions",
                         "dependentSchemas") and isinstance(value, dict):
                # name->schema map: names are never keywords/regexes
                out[key] = {name: _sanitize_schema_patterns(sub)
                            for name, sub in value.items()}
            else:
                out[key] = _sanitize_schema_patterns(value)
        return out
    if isinstance(node, list):
        return [_sanitize_schema_patterns(x) for x in node]
    return node


def _sanitize_body_tools(body_json):
    """Return the body unchanged or a shallow copy with tool schemas sanitized.

    For the common no-tools case (a non-dict body, or `tools` absent or not
    a list) the identical input object is returned; otherwise a shallow copy
    of `body_json` whose `tools` list is rebuilt. The anthropic-mode forward
    passes the parsed body through verbatim, so a tool `input_schema`
    carrying an ECMA identity escape (e.g. Zod's `^agent\\_run\\_`) would
    reach a strict backend unnormalized and 400. This replaces every dict
    `tools[i]["input_schema"]` with the output of `_sanitize_schema_patterns`,
    which is itself a full copy — the input is never mutated.

    Total: a non-dict body, a missing or non-list `tools`, a non-dict tool
    entry, and a non-dict `input_schema` all pass through unchanged (the
    latter two still land in the copied `tools` list as-is).
    """
    if not isinstance(body_json, dict):
        return body_json
    tools = body_json.get("tools")
    if not isinstance(tools, list):
        return body_json
    out = dict(body_json)
    new_tools = []
    for tool in tools:
        if isinstance(tool, dict) and isinstance(tool.get("input_schema"), dict):
            new_tool = dict(tool)
            new_tool["input_schema"] = _sanitize_schema_patterns(
                tool["input_schema"])
            new_tools.append(new_tool)
        else:
            new_tools.append(tool)
    out["tools"] = new_tools
    return out

"""Pattern-sanitization tests for the shared transform sanitizers:
_strip_regex_identity_escapes, _sanitize_schema_patterns, and
_sanitize_body_tools — their tables, walks, non-mutation, value
positions, and collision merges — plus the chat-mode end-to-end
confirmation."""

import uuid
from _harness import _require_server_func, fail, pass_, run_cli
from claude_retry_proxy.transforms_common import _sanitize_body_tools, _sanitize_schema_patterns, _strip_regex_identity_escapes


def test_strip_regex_identity_escapes_table():
    """_strip_regex_identity_escapes implements the plan's reference table exactly.

    Plan 2026-10-06-re2-portable-tool-schema-patterns, Step 1: the sanitizer
    rewrites one JSON-Schema `pattern` regex by dropping ECMA identity
    escapes (backslash before a non-metacharacter symbol), while preserving
    every meaningful escape (ASCII letter/digit-introduced) and the
    metacharacter escapes. The class tracker keeps `\\-` inside a character
    class and drops it outside. One row per table entry so a regression in
    any single rule fails loudly.
    """
    print("\n--- Test: Strip Regex Identity Escapes Table ---")
    # backslash built at runtime so this file never carries a \ + u escape
    # sequence that a tool layer might mangle on write
    _bs = chr(92)
    unicode_escape = _bs + "u0041"
    # (raw input, expected output, why) -- the plan's reference table.
    table = [
        (r"^agent\_run\_", r"^agent_run_", "the reported bug"),
        (r"foo\-bar", "foo-bar", "- outside class is identity"),
        (r"[a\-z]", r"[a\-z]", "- inside class is a literal-hyphen escape (kept)"),
        (r"[a\-z]\-x", r"[a\-z]-x", "mixed: in-class kept, out-of-class dropped"),
        (r"\d{1,3}\.\d+", r"\d{1,3}\.\d+", "\\d (letter), \\. (metachar) meaningful"),
        (r"\.\^\[\]\{\}\\\*\+\?\$\|", r"\.\^\[\]\{\}\\\*\+\?\$\|",
         "all metacharacter escapes unchanged"),
        (r"\s\w\n\t\x41" + unicode_escape + r"\p{L}\Qx\E\0",
         r"\s\w\n\t\x41" + unicode_escape + r"\p{L}\Qx\E\0",
         "every escape is letter/digit-introduced"),
        (r"a\/b\:c\@d\!\#e", "a/b:c@d!#e", "/ and punctuation are identity"),
        (r"\ ", " ", "whitespace is identity"),
        ("ab\\", "ab\\", "trailing escape copied verbatim"),
        ("", "", "empty passthrough"),
    ]
    for raw, expected, why in table:
        out = _strip_regex_identity_escapes(raw)
        if out != expected:
            fail("row {!r} -> {!r}, expected {!r} ({})".format(raw, out, expected, why))
            return
    pass_("all 11 reference-table rows transformed correctly")


def test_sanitize_schema_patterns_walk():
    """_sanitize_schema_patterns rewrites pattern/patternProperties at every depth.

    Nested schema: `pattern` under properties, items, anyOf[0] and a nested
    $defs entry; a patternProperties object whose string keys carry escapes
    and whose values recurse to their own pattern; totality -- a non-string
    `pattern` value, a non-string patternProperties key, non-dict/list nodes
    (scalars, lists of scalars) all pass through unchanged.
    """
    print("\n--- Test: Sanitize Schema Patterns Walk ---")
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "pattern": r"^agent\_run\_"},
            "arr": {"type": "array", "items": {"type": "string", "pattern": r"foo\-bar"}},
        },
        "anyOf": [
            {"type": "string", "pattern": r"a\/b"},
            {"type": "number"},
        ],
        "patternProperties": {
            r"^k\-e\_\d": {"type": "string", "pattern": r"nested\/p"},
            7: {"pattern": r"kept\-p"},
        },
        "not": {"pattern": 42},          # non-string pattern -> untouched
        "$defs": {"sub": {"pattern": r"deep\-x"}},
        "scalar": "plain",               # non-dict node -> untouched
        "list": ["a", 7, None],          # list of scalars -> untouched
    }
    out = _sanitize_schema_patterns(schema)
    checks = [
        (out["properties"]["name"]["pattern"], "^agent_run_", "properties depth"),
        (out["properties"]["arr"]["items"]["pattern"], "foo-bar", "items depth"),
        (out["anyOf"][0]["pattern"], "a/b", "anyOf depth"),
        (out["$defs"]["sub"]["pattern"], "deep-x", "$defs depth"),
        (list(out["patternProperties"].keys())[0], r"^k-e_\d",
         "patternProperties key stripped (identity escapes dropped, \\d kept)"),
        (out["patternProperties"][r"^k-e_\d"]["pattern"], "nested/p",
         "patternProperties value recursed"),
        (out["patternProperties"][7]["pattern"], "kept-p",
         "non-string key preserved, its value still recursed"),
        (out["not"]["pattern"], 42, "non-string pattern passes through"),
        (out["scalar"], "plain", "scalar node passes through"),
        (out["list"], ["a", 7, None], "scalar list passes through"),
    ]
    for got, expected, label in checks:
        if got != expected:
            fail("{}: got {!r}, expected {!r}".format(label, got, expected))
            return
    pass_("walk sanitizes both regex-typed locations at every depth; totality holds")


def test_sanitize_schema_patterns_no_mutation():
    """_sanitize_schema_patterns never mutates its argument; returns a new structure."""
    print("\n--- Test: Sanitize Schema Patterns No Mutation ---")
    import copy
    schema = {
        "type": "object",
        "properties": {"n": {"type": "string", "pattern": r"^agent\_run\_"}},
        "patternProperties": {r"p\-": {"pattern": r"q\/"}},
        "anyOf": [{"pattern": r"a\-b"}],
    }
    snapshot = copy.deepcopy(schema)
    out = _sanitize_schema_patterns(schema)
    if schema != snapshot:
        fail("input schema was mutated: {!r}".format(schema))
        return
    if out is schema:
        fail("returned object is the input itself (must be a copy)")
        return
    if out["properties"] is schema["properties"]:
        fail("nested dict shared with input (shallow copy), not rebuilt")
        return
    if out["properties"]["n"]["pattern"] != "^agent_run_":
        fail("expected sanitized copy, got {!r}".format(out["properties"]["n"]["pattern"]))
        return
    pass_("input unchanged; fresh structure returned with sanitized patterns")


def test_sanitize_schema_patterns_value_positions():
    """Step 4a: value keywords verbatim, name->schema map values sanitized.

    Plan 2026-10-06-re2-portable-tool-schema-patterns, Step 4 (review finding
    2): `const`/`enum`/`default`/`examples` hold asserted DATA, so a
    `pattern`-keyed string inside them must survive byte-for-byte at any
    depth, while a property legitimately *named* `default` (or `const`,
    `enum`) is a name->schema map entry whose subschema IS walked — both
    directions of the position split. `$defs`/`definitions`/`dependentSchemas`
    behave the same way: keys are names, values are schemas.
    """
    print("\n--- Test: Sanitize Schema Patterns Value Positions ---")
    import copy
    schema = {
        # asserted data: byte-for-byte, at any depth
        "const": {"pattern": r"^agent\_run\_",
                  "nested": {"pattern": r"foo\-bar"}},
        "enum": [{"pattern": r"a\/b"}, r"str\-x"],
        "default": {"pattern": r"def\-ault"},
        "examples": [{"pattern": r"exa\-mple"}],
        # name->schema maps: names never rewritten, values are schemas
        "properties": {
            "default": {"type": "string", "pattern": r"^agent\_run\_"},
            "const": {"type": "string", "pattern": r"foo\-bar"},
            "enum": {"type": "string", "pattern": r"keep\-d"},
        },
        "$defs": {"default": {"pattern": r"defs\-p"}},
        "definitions": {"examples": {"pattern": r"defn\-p"}},
        "dependentSchemas": {"const": {"pattern": r"dep\-p"}},
        # a `default` inside an ordinary subschema is still asserted data
        "items": {"type": "string", "default": {"pattern": r"item\-d"}},
    }
    snapshot = copy.deepcopy(schema)
    out = _sanitize_schema_patterns(schema)
    checks = [
        (out["const"]["pattern"], r"^agent\_run\_", "const value verbatim"),
        (out["const"]["nested"]["pattern"], r"foo\-bar",
         "nested-under-const value verbatim"),
        (out["enum"][0]["pattern"], r"a\/b", "dict enum entry verbatim"),
        (out["enum"][1], r"str\-x", "scalar enum entry verbatim"),
        (out["default"]["pattern"], r"def\-ault", "default value verbatim"),
        (out["examples"][0]["pattern"], r"exa\-mple", "examples value verbatim"),
        (out["items"]["default"]["pattern"], r"item\-d",
         "default inside an ordinary subschema verbatim"),
        (out["properties"]["default"]["pattern"], "^agent_run_",
         "property named default sanitized"),
        (out["properties"]["const"]["pattern"], "foo-bar",
         "property named const sanitized"),
        (out["properties"]["enum"]["pattern"], "keep-d",
         "property named enum sanitized"),
        (out["$defs"]["default"]["pattern"], "defs-p",
         "$defs name kept, its value sanitized"),
        (out["definitions"]["examples"]["pattern"], "defn-p",
         "definitions name kept, its value sanitized"),
        (out["dependentSchemas"]["const"]["pattern"], "dep-p",
         "dependentSchemas name kept, its value sanitized"),
    ]
    for got, expected, label in checks:
        if got != expected:
            fail("{}: got {!r}, expected {!r}".format(label, got, expected))
            return
    if set(out["properties"]) != {"default", "const", "enum"}:
        fail("property names rewritten: {!r}".format(list(out["properties"])))
        return
    if out["const"] is schema["const"]:
        fail("value-keyword subtree shared with input (not a fresh copy)")
        return
    if schema != snapshot:
        fail("input schema was mutated: {!r}".format(schema))
        return
    pass_("value keywords verbatim; name-map keys kept, their schemas sanitized")


def test_sanitize_schema_patterns_collision_merge():
    """Step 4b: colliding patternProperties keys merge as allOf; none dropped.

    Plan 2026-10-06-re2-portable-tool-schema-patterns, Step 4 (review finding
    3): source keys differing only by identity escapes strip to the same
    output key. The merge keeps BOTH subschemas under `{"allOf": [...]}`,
    chained for repeated collisions, while a key that does not collide
    survives untouched beside it and a non-string key still passes through
    with its value recursed.
    """
    print("\n--- Test: Sanitize Schema Patterns Collision Merge ---")
    import copy
    schema = {
        "patternProperties": {
            # three distinct sources, one output key: ^a-b-c
            r"^a\-b\-c": {"type": "string", "pattern": r"p\-1"},
            r"^a-b\-c": {"type": "string", "pattern": r"p\-2"},
            r"^a-b-c": {"type": "string", "pattern": r"p\-3"},
            # non-colliding key: must be preserved as-is
            r"^k\-e\_\d": {"type": "string", "pattern": r"keep\-p"},
            # non-string key: left alone, value still recursed
            7: {"pattern": r"non\-string"},
        },
    }
    snapshot = copy.deepcopy(schema)
    out = _sanitize_schema_patterns(schema)
    pp = out["patternProperties"]
    if schema != snapshot:
        fail("input schema was mutated: {!r}".format(schema))
        return
    if len(pp) != 3:
        fail("expected 3 output keys (3 sources collide to one), got {}: "
             "{!r}".format(len(pp), list(pp)))
        return
    if r"^a-b-c" not in pp:
        fail("collided output key missing: {!r}".format(list(pp)))
        return
    expect_merged = {"allOf": [
        {"allOf": [{"type": "string", "pattern": "p-1"},
                   {"type": "string", "pattern": "p-2"}]},
        {"type": "string", "pattern": "p-3"},
    ]}
    if pp[r"^a-b-c"] != expect_merged:
        fail("collision merge wrong: got {!r}, expected {!r}".format(
            pp[r"^a-b-c"], expect_merged))
        return
    if pp[r"^k-e_\d"] != {"type": "string", "pattern": "keep-p"}:
        fail("non-colliding key altered: {!r}".format(pp.get(r"^k-e_\d")))
        return
    if pp.get(7) != {"pattern": "non-string"}:
        fail("non-string key/value handling altered: {!r}".format(pp.get(7)))
        return
    pass_("collisions merge as chained allOf (no entry dropped); "
          "non-colliding and non-string keys preserved")


def test_anthropic_to_chat_tools_pattern_sanitized():
    """Chat mode: input_schema.pattern identity escapes stripped before forwarding.

    Integration for Step 2's chat call site: a tool whose input_schema
    carries Zod's `^agent\\_run\\_` pattern reaches the backend as
    `^agent_run_` in function.parameters, and the input tools list is
    unmutated (the transforms' declared no-mutation contract).
    """
    print("\n--- Test: Anthropic To Chat Tools Pattern Sanitized ---")
    fn = _require_server_func("_transform_anthropic_tools_to_chat")
    if fn is None:
        return
    import copy
    tools = [
        {"name": "mcp__exa__agent_run",
         "input_schema": {"type": "object",
                          "properties": {"query": {"type": "string",
                                                  "pattern": r"^agent\_run\_"}},
                          "patternProperties": {r"^k\-": {"type": "string"}}}},
    ]
    snapshot = copy.deepcopy(tools)
    out = fn(tools, request_id="T-" + uuid.uuid4().hex[:8], mode="chat",
             provider="p", tier="sonnet")
    params = out[0]["function"]["parameters"]
    if params["properties"]["query"]["pattern"] != "^agent_run_":
        fail("parameters.pattern not sanitized, got {!r}".format(
            params["properties"]["query"]["pattern"]))
        return
    if list(params["patternProperties"].keys())[0] != "^k-":
        fail("patternProperties key not sanitized, got {!r}".format(
            list(params["patternProperties"].keys())))
        return
    if tools != snapshot:
        fail("input tools list was mutated: {!r}".format(tools))
        return
    pass_("chat parameters sanitized (pattern + patternProperties key); input unmutated")


def test_sanitize_body_tools_sanitized_copy():
    """_sanitize_body_tools returns a sanitized copy; input never mutated.

    Plan 2026-10-06-re2-portable-tool-schema-patterns, Step 3: the
    anthropic-mode verbatim forward calls this helper, so every dict
    `tools[i]["input_schema"]` must arrive sanitized (pattern value and
    patternProperties key), other tool/body fields must be preserved
    verbatim, and the returned body must be a fresh object — the parsed
    client body is never mutated in place.
    """
    print("\n--- Test: Sanitize Body Tools Sanitized Copy ---")
    import copy
    body = {
        "model": "sonnet",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "mcp__exa__agent_run",
                   "description": "run a research agent",
                   "input_schema": {"type": "object",
                                    "properties": {"query": {"type": "string",
                                                             "pattern": r"^agent\_run\_"}},
                                    "patternProperties": {r"^k\-": {"type": "string"}}}},
                  {"name": "plain", "input_schema": {"type": "object",
                                                     "properties": {}}}],
    }
    snapshot = copy.deepcopy(body)
    out = _sanitize_body_tools(body)
    if out is body:
        fail("returned body is the input itself (must be a copy)")
        return
    if body != snapshot:
        fail("input body was mutated: {!r}".format(body))
        return
    if out["tools"][0] is body["tools"][0]:
        fail("tool entry shared with input (shallow), not rebuilt")
        return
    schema = out["tools"][0]["input_schema"]
    if schema["properties"]["query"]["pattern"] != "^agent_run_":
        fail("input_schema.pattern not sanitized, got {!r}".format(
            schema["properties"]["query"]["pattern"]))
        return
    if list(schema["patternProperties"].keys())[0] != "^k-":
        fail("patternProperties key not sanitized, got {!r}".format(
            list(schema["patternProperties"].keys())))
        return
    if out["tools"][0]["description"] != "run a research agent":
        fail("tool description lost: {!r}".format(out["tools"][0].get("description")))
        return
    if out["tools"][1] != {"name": "plain",
                           "input_schema": {"type": "object", "properties": {}}}:
        fail("pattern-free tool altered: {!r}".format(out["tools"][1]))
        return
    if out.get("model") != "sonnet" or out.get("messages") != body["messages"]:
        fail("non-tool body fields altered: {!r}".format(out))
        return
    pass_("body copied with sanitized tool schemas; other fields and input preserved")


def test_sanitize_body_tools_totality():
    """_sanitize_body_tools is total: malformed bodies pass through unchanged.

    Step 3's helper must never raise on the request path: a non-dict body,
    a missing or non-list `tools`, a non-dict tool entry, and a non-dict
    `input_schema` all pass through (the parsed client body may be any
    valid JSON), and none of them mutate their input.
    """
    print("\n--- Test: Sanitize Body Tools Totality ---")
    import copy
    cases = [
        ("non-dict body (list)", [1, 2, 3]),
        ("non-dict body (str)", "not a body"),
        ("absent tools", {"model": "sonnet", "messages": []}),
        ("non-list tools", {"model": "sonnet", "tools": "oops"}),
        ("null tools", {"model": "sonnet", "tools": None}),
        ("non-dict tool entries", {"tools": ["garbage", 42, None]}),
        ("tool without input_schema", {"tools": [{"name": "bare"}]}),
        ("non-dict input_schema", {"tools": [{"name": "t", "input_schema": "notdict"}]}),
    ]
    for label, body in cases:
        snapshot = copy.deepcopy(body)
        out = _sanitize_body_tools(body)
        if body != snapshot:
            fail("{}: input was mutated: {!r}".format(label, body))
            return
        if out != body:
            fail("{}: expected passthrough, got {!r}".format(label, out))
            return
    pass_("all 8 malformed-body cases pass through unchanged, input untouched")


ALL_TESTS = [
    ("strip-regex-identity-escapes-table", test_strip_regex_identity_escapes_table),
    ("sanitize-schema-patterns-walk", test_sanitize_schema_patterns_walk),
    ("sanitize-schema-patterns-no-mutation", test_sanitize_schema_patterns_no_mutation),
    ("sanitize-schema-patterns-value-positions", test_sanitize_schema_patterns_value_positions),
    ("sanitize-schema-patterns-collision-merge", test_sanitize_schema_patterns_collision_merge),
    ("anthropic-to-chat-tools-pattern-sanitized", test_anthropic_to_chat_tools_pattern_sanitized),
    ("sanitize-body-tools-sanitized-copy", test_sanitize_body_tools_sanitized_copy),
    ("sanitize-body-tools-totality", test_sanitize_body_tools_totality),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_transform_patterns")

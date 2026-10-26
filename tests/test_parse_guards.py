"""Parse-guard totality invariant (plan 2026-10-25-guard-totality-and-blank-admin).

WHY THIS EXISTS. `json.loads` — and its `json.load(fp)` twin, which is literally
`loads(fp.read())` — fails in more than one way, and the ways are NOT related by
inheritance:

    json.JSONDecodeError   syntax         (a ValueError subclass)
    UnicodeDecodeError     invalid bytes  (a ValueError SIBLING, not a subclass)
    RecursionError         deep nesting   (a RuntimeError, not a ValueError)

A guard naming only `json.JSONDecodeError` therefore lets the other two escape.
That is not hypothetical: `test_tier_routing.py::test_deep_nested_body_invalid_json`
records the same defect being found and fixed once on the client-body path, and
further sites were left narrow afterwards. Naming exception classes one at a time
is what produced both rounds, so the durable rule is TOTALITY — every parse sits
in a `try` with a total handler — checked here by `try`-ENCLOSURE, never by
grepping for an `except` line.

SCOPE. Every `json.loads(...)` / `json.load(...)` call in the package, plus every
bare `loads(...)` / `load(...)` name call (a `from json import loads` can hide a
site from an attribute-only scan).

KNOWN LIMIT. `import json as j; j.loads(...)` is invisible to this matcher: the
attribute scan pins the receiver name to `json`. The bare-name rule catches the
`from json import loads` form, which is the shape that actually hides a site
today; an aliased module import would need a per-module import analysis this
gate deliberately does not do. Stated here rather than claimed away.

PYTHON 3.8. `pyproject.toml` declares `requires-python = ">=3.8"`, so the gate
must not use `ast.unparse` (3.9+); exception names are read straight off the
nodes. `test_parse_guard_gate_python38_portable` pins that on this module's own
source.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import ast
import os

from _harness import (
    fail,
    pass_,
    run_cli,
)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src", "claude_retry_proxy")


# A handler is total when it catches every Exception. `except Exception`,
# `except BaseException` and a bare `except:` qualify; a tuple qualifies only if
# one of its members is total.
TOTAL_NAMES = {"Exception", "BaseException"}

# Parse entry points that carry the same failure class.
PARSE_CALLS = {"loads", "load"}


def _exc_name(node):
    """Readable name for an exception expression without `ast.unparse` (3.9+)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return "<call>"
    return "<expr>"


def _handler_is_total(handler):
    """True when this `except` clause catches every Exception."""
    if handler.type is None:            # bare `except:`
        return True
    node = handler.type
    if isinstance(node, ast.Tuple):
        names = [_exc_name(e) for e in node.elts]
    else:
        names = [_exc_name(node)]
    return any(n in TOTAL_NAMES for n in names)


def _handler_names(handler):
    """The exception names this handler actually names (for the FAIL message)."""
    if handler.type is None:
        return ["<bare>"]
    node = handler.type
    if isinstance(node, ast.Tuple):
        return sorted({_exc_name(e) for e in node.elts})
    return [_exc_name(node)]


def _parents(tree):
    """Map id(child) -> list of ancestor nodes, outermost first."""
    out = {}
    stack = [(tree, [])]
    while stack:
        node, chain = stack.pop()
        for child in ast.iter_child_nodes(node):
            out[id(child)] = chain + [node]
            stack.append((child, chain + [node]))
    return out


def _parse_sites(tree):
    """Every `json.loads(...)` / `json.load(...)` call, and bare alias calls.

    Returns (json_attr_calls, bare_alias_calls). The bare list catches
    `from json import loads` / `from json import load`, which an attribute-only
    matcher cannot see.
    """
    attr_calls, bare_calls = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (isinstance(fn, ast.Attribute) and fn.attr in PARSE_CALLS
                and isinstance(fn.value, ast.Name) and fn.value.id == "json"):
            attr_calls.append(node)
        elif isinstance(fn, ast.Name) and fn.id in PARSE_CALLS:
            bare_calls.append(node)
    return attr_calls, bare_calls


def _enclosing_function(parents, node):
    for anc in reversed(parents.get(id(node), [])):
        if isinstance(anc, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return anc.name
    return "<module>"


# A nested scope is a BOUNDARY: a `try` catches exceptions raised while its
# body executes, not exceptions raised later when a function / class / lambda
# it merely DEFINED is invoked. `class` is the conservative member of the set
# (its body runs at definition time), kept for uniformity — the plan fixes the
# four kinds together and a class-body parse is not a shape this package uses.
#
# A GENERATOR EXPRESSION is a boundary for the same reason, and is not a
# counter-example to the comprehensions left out below: `gen = (json.loads(s)
# for s in xs)` performs no call at binding time — the call runs when the
# generator is CONSUMED, outside the try. A list / set / dict comprehension is
# eagerly evaluated in the try body, so those stay out of this tuple.
SCOPE_BOUNDARIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                    ast.Lambda, ast.GeneratorExp)


def _guard_for(parents, node):
    """The innermost `try` whose BODY encloses `node`, or None.

    Membership is tested on the `body` clause specifically, matched through the
    direct child of the Try on the ancestor path. A parse call sitting in a
    handler, `else` or `finally` clause is NOT guarded by that try — it can
    raise there just as freely — so it keeps walking outward. A looser "is any
    enclosing node a Try" test would call such a site guarded and hide it.

    A `try` also stops enclosing at a SCOPE BOUNDARY. `try: def f(): json.loads(s)`
    reports the parse as guarded if only the direct child is inspected, but the
    call runs when `f` is INVOKED — outside the try — and the same holds for an
    `async def`, a `class` body, a `lambda` and a generator expression (which
    defers the call until it is consumed). The whole path between the try and
    the call is checked rather than only the direct child for two reasons: a
    lambda is never a try body's direct child statement (it always sits inside
    an expression statement), so a direct-child rule could not reach it at all;
    and a `def` one `if` deeper than the try body would slip through the same
    way. All of those shapes are pinned in `_SCANNER_CASES`.
    """
    chain = parents.get(id(node), [])
    for i in range(len(chain) - 1, -1, -1):
        anc = chain[i]
        if not isinstance(anc, ast.Try):
            continue
        child = chain[i + 1] if i + 1 < len(chain) else None
        if any(isinstance(n, SCOPE_BOUNDARIES) for n in chain[i + 1:]):
            continue
        for stmt in anc.body:
            if child is stmt:
                return anc
    return None


def _scan_source(path, src):
    """Scan one module's source.

    Returns (lines, sites, site_failures, fatal) where `lines` is a list of
    (ok, message) pairs to print, `sites` counts the parse sites examined,
    `site_failures` counts those that failed, and `fatal` lists file-level
    problems (unreadable / unparseable source) that are failures without being
    sites.
    """
    lines, fatal = [], []
    sites = 0
    site_failures = 0

    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        fatal.append("{}: cannot parse ({})".format(path, exc))
        lines.append((False, fatal[-1]))
        return lines, sites, site_failures, fatal

    parents = _parents(tree)
    attr_calls, bare_calls = _parse_sites(tree)

    for call in bare_calls:
        sites += 1
        site_failures += 1
        lines.append((False, (
            "{}:{} in {} -> bare alias call `{}(...)` (a `from json import {}` "
            "can hide a site from an attribute-only scan); use `json.{}(...)`"
        ).format(path, call.lineno, _enclosing_function(parents, call),
                 call.func.id, call.func.id, call.func.id)))

    for call in attr_calls:
        sites += 1
        where = "{}:{} in {}".format(path, call.lineno,
                                     _enclosing_function(parents, call))
        guard = _guard_for(parents, call)
        if guard is None:
            site_failures += 1
            lines.append((False, "{} -> no enclosing try at all".format(where)))
            continue
        if any(_handler_is_total(h) for h in guard.handlers):
            lines.append((True, "{} -> total guard".format(where)))
        else:
            named = []
            for h in guard.handlers:
                named.extend(_handler_names(h))
            site_failures += 1
            lines.append((False, "{} -> narrow guard {}".format(
                where, sorted(set(named)))))

    return lines, sites, site_failures, fatal


def _scan_dir(src_dir):
    """Aggregate `_scan_source` over every `*.py` under `src_dir`."""
    lines, fatal = [], []
    sites = 0
    site_failures = 0

    if not os.path.isdir(src_dir):
        fatal.append("source directory not found: {}".format(src_dir))
        return lines, sites, site_failures, fatal

    files = sorted(f for f in os.listdir(src_dir) if f.endswith(".py"))
    if not files:
        fatal.append("no python modules under {}".format(src_dir))
        return lines, sites, site_failures, fatal

    for name in files:
        path = os.path.join(src_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
        except OSError as exc:
            fatal.append("{}: cannot read ({})".format(path, exc))
            lines.append((False, fatal[-1]))
            continue
        sub_lines, sub_sites, sub_failures, sub_fatal = _scan_source(path, src)
        lines.extend(sub_lines)
        sites += sub_sites
        site_failures += sub_failures
        fatal.extend(sub_fatal)

    return lines, sites, site_failures, fatal


def test_parse_guards_totality():
    """Every JSON parse site in the package sits in a `try` with a TOTAL
    handler, and the scan is not vacuous.

    The rule the plan adopted: `except Exception` (or BaseException, or a bare
    `except:`) at every `json.loads` / `json.load` call, because RecursionError
    is a RuntimeError and UnicodeDecodeError is a sibling of JSONDecodeError
    rather than a subclass. The site count is asserted non-zero so a path
    change, an import failure or a parse error cannot turn this into a green
    no-op; the observed count is printed either way.

    WHAT THIS PINS, AND WHAT IT DOES NOT: guard SHAPE. It does not check that a
    `try` body holds the parse and nothing else unrelated — a widened try that
    swallowed unrelated logic would still pass here, which is why the plan's
    per-site body review stays a code-review obligation. It also does not
    subsume the behavioural client-body path: `test_deep_nested_body_invalid_json`
    drives a real proxy and still covers that end to end.
    """
    print("\n--- Test: Parse Guards Are Total ---")
    lines, sites, site_failures, fatal = _scan_dir(SRC_DIR)

    for ok, msg in lines:
        if ok:
            pass_(msg)
        else:
            fail(msg)

    if fatal:
        fail("{} file-level scan problem(s); see the FAIL line(s) above".format(
            len(fatal)))
        return

    if sites == 0:
        fail("the scan found 0 parse sites under {} — a path change, an import "
             "failure or a parse error would otherwise pass this test "
             "vacuously".format(SRC_DIR))
        return

    if site_failures:
        fail("{} of {} parse sites do not have a total guard".format(
            site_failures, sites))
    else:
        pass_("{} of {} parse sites have a total guard".format(sites, sites))


# (label, source, expected_sites, expected_site_failures) — each row pins one
# accept/reject branch of the scanner. Synthetic sources rather than the live
# tree: a branch with no live representative (a bare-alias site, say) would
# otherwise never be exercised, so deleting it would leave this suite green.
_SCANNER_CASES = [
    ("total guard (except Exception)",
     "try:\n    v = json.loads(s)\nexcept Exception:\n    v = None\n",
     1, 0),
    ("bare except is total",
     "try:\n    v = json.loads(s)\nexcept:\n    v = None\n",
     1, 0),
    ("BaseException is total",
     "try:\n    v = json.loads(s)\nexcept BaseException:\n    v = None\n",
     1, 0),
    ("a tuple naming Exception is total",
     "try:\n    v = json.loads(s)\nexcept (ValueError, Exception):\n    v = None\n",
     1, 0),
    ("json.load(fp) is a site too",
     "try:\n    with open(p) as f:\n        v = json.load(f)\nexcept Exception:\n"
     "    v = None\n",
     1, 0),
    ("narrow guard (JSONDecodeError only) fails",
     "try:\n    v = json.loads(s)\nexcept json.JSONDecodeError:\n    v = None\n",
     1, 1),
    ("a narrow tuple fails",
     "try:\n    v = json.loads(s)\nexcept (ValueError, TypeError):\n    v = None\n",
     1, 1),
    ("no try at all fails",
     "v = json.loads(s)\n",
     1, 1),
    ("a parse in an except handler is not guarded by that try",
     "try:\n    pass\nexcept Exception:\n    v = json.loads(s)\n",
     1, 1),
    ("a parse in an else clause is not guarded by that try",
     "try:\n    pass\nexcept Exception:\n    pass\nelse:\n    v = json.loads(s)\n",
     1, 1),
    ("a parse in a finally clause is not guarded by that try",
     "try:\n    pass\nexcept Exception:\n    pass\nfinally:\n    v = json.loads(s)\n",
     1, 1),
    # Scope boundaries: a nested scope DEFINED inside a try body is not
    # protected by it. The call raises when the scope is invoked later, which is
    # outside the try — so the walker must keep going outward, not accept the
    # try as enclosing.
    ("a parse inside a def defined in a try body is not guarded by it",
     "try:\n    def f():\n        return json.loads(s)\nexcept Exception:\n"
     "    pass\n",
     1, 1),
    ("a parse inside an async def defined in a try body is not guarded by it",
     "try:\n    async def f():\n        return json.loads(s)\nexcept "
     "Exception:\n    pass\n",
     1, 1),
    ("a parse inside a class defined in a try body is not guarded by it",
     "try:\n    class C:\n        v = json.loads(s)\nexcept Exception:\n"
     "    pass\n",
     1, 1),
    # The lambda row is also what pins the rule to the whole try-to-call path:
    # a lambda is never a try body's direct child statement (it sits inside an
    # expression statement), so a direct-child-only rule would report this
    # GUARDED and this row would fail. Same for a def behind an `if`, covered
    # below by the shared branch.
    ("a parse inside a lambda defined in a try body is not guarded by it",
     "try:\n    f = lambda: json.loads(s)\nexcept Exception:\n    pass\n",
     1, 1),
    ("a parse inside a def nested under an if in a try body is not guarded",
     "try:\n    if True:\n        def f():\n            return json.loads(s)\n"
     "except Exception:\n    pass\n",
     1, 1),
    # A generator expression is LAZY: binding it performs no call, so the parse
    # raises when the generator is consumed — later, outside the try. A list
    # comprehension, by contrast, IS eager and stays guarded (it is deliberately
    # absent from SCOPE_BOUNDARIES), which is why this row is a real distinction
    # rather than pedantry.
    ("a parse inside a generator expression is not guarded by it",
     "try:\n    gen = (json.loads(s) for s in xs)\nexcept Exception:\n    pass\n",
     1, 1),
    ("an inner try's total guard still wins for its own body",
     "try:\n    try:\n        v = json.loads(s)\n    except Exception:\n"
     "        v = None\nexcept Exception:\n    pass\n",
     1, 0),
    ("a bare `loads(...)` name call is flagged even inside a total try",
     "from json import loads\ntry:\n    v = loads(s)\nexcept Exception:\n"
     "    v = None\n",
     1, 1),
    ("a bare `load(...)` name call is flagged",
     "from json import load\ntry:\n    v = load(f)\nexcept Exception:\n"
     "    v = None\n",
     1, 1),
    ("a non-json attribute call is not a site",
     "try:\n    v = yaml.loads(s)\nexcept Exception:\n    v = None\n",
     0, 0),
    # Documented limit, pinned so the docstring and the matcher cannot drift:
    # `import json as j; j.loads(...)` is invisible to this scan.
    ("an aliased module receiver is invisible (documented limit)",
     "import json as j\ntry:\n    v = j.loads(s)\nexcept Exception:\n    v = None\n",
     0, 0),
]


def test_parse_guard_scanner_semantics():
    """Each accept/reject branch of the scanner, on synthetic sources.

    Without these, the branches with no live representative — the bare-alias
    flag, the no-enclosing-try rejection, the narrow-guard rejection, the
    handler/else/finally non-enclosure rule, the scope-boundary rule (a parse
    inside a `def`/`async def`/`class`/`lambda` merely DEFINED in a try body is
    not guarded by it, and neither is one inside a generator expression, whose
    call is deferred until the generator is consumed) — would be exercised only
    by the live tree happening to contain an example. A deleted branch would
    then ship a scanner that silently accepts what it was written to refuse, and
    `test_parse_guards_totality` would still pass on a clean tree.
    """
    print("\n--- Test: Parse-Guard Scanner Semantics ---")
    for label, src, want_sites, want_failures in _SCANNER_CASES:
        lines, sites, site_failures, fatal = _scan_source("<synthetic>", src)
        if fatal:
            fail("{}: unexpected parse failure: {}".format(label, fatal))
            continue
        if sites == want_sites and site_failures == want_failures:
            pass_("{}: {} site(s), {} failing".format(label, sites,
                                                      site_failures))
        else:
            fail("{}: expected {} site(s) / {} failing, got {} / {} ({})".format(
                label, want_sites, want_failures, sites, site_failures,
                "; ".join(msg for _ok, msg in lines)))


def test_parse_guard_gate_python38_portable():
    """This gate runs on Python 3.8, so it must not call `ast.unparse` (3.9+).

    A gate that raises AttributeError on a supported interpreter emits no
    verdict at all — the failure mode is a silent skip, not a red line. Read
    off this module's own source so a future edit that reaches for the
    convenience cannot land quietly.
    """
    print("\n--- Test: Parse-Guard Gate Is Python 3.8 Portable ---")
    try:
        with open(os.path.abspath(__file__), encoding="utf-8") as fh:
            src = fh.read()
    except OSError as exc:
        fail("cannot read this module's own source: {}".format(exc))
        return
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Attribute) and node.attr == "unparse":
            offenders.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id == "unparse":
            offenders.append(node.lineno)
    if offenders:
        fail("this module references `unparse` at line(s) {} — `ast.unparse` "
             "is Python 3.9+, and pyproject declares requires-python >= "
             "3.8".format(sorted(set(offenders))))
    else:
        pass_("no `unparse` reference in this module (3.8-compatible)")


ALL_TESTS = [
    ("parse-guards-totality", test_parse_guards_totality),
    ("parse-guard-scanner-semantics", test_parse_guard_scanner_semantics),
    ("parse-guard-gate-python38-portable",
     test_parse_guard_gate_python38_portable),
]

if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_parse_guards")

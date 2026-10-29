"""Access rules live only in atrium/policy.py. Never weaken or skip.

No module outside policy.py may select or fetch Channel, Message, Pull or
MemoryEntry rows itself, so every read goes through the wall.
"""

import ast
from pathlib import Path

GUARDED = {"Channel", "Message", "Pull", "MemoryEntry"}
ROOT = Path(__file__).resolve().parents[2] / "atrium"
ALLOWED = {ROOT / "policy.py", ROOT / "seed.py"}


def offenders():
    for path in ROOT.rglob("*.py"):
        if path in ALLOWED:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if name in ("select", "get", "query") and node.args:
                first = node.args[0]
                target = first.id if isinstance(first, ast.Name) else first.attr if isinstance(first, ast.Attribute) else ""
                if target in GUARDED:
                    yield f"{path.relative_to(ROOT.parent)}:{node.lineno} {name}({target})"


def test_only_policy_reads_guarded_tables():
    found = list(offenders())
    assert not found, "read these through atrium.policy instead:\n" + "\n".join(found)

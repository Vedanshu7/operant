"""One-off codemod: convert Google docstrings to the amp/reST style.

Two transforms per docstring, matching the ``nctquery`` house style the amp
linter enforces:

- the summary's first word is made imperative (``Returns`` -> ``Return``),
  using the exact word pairs pydocstyle suggests;
- Google sections (``Args:``/``Returns:``/``Raises:``/``Yields:``/
  ``Attributes:``) become reST field lists (``:param:``/``:return:``/
  ``:raises:``/``:yield:``/``:ivar:``).

Run: ``uv run python scripts/amp_docstrings.py <file.py> ...``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import libcst as cst

_IMPERATIVE = {
    "Returns": "Return", "Builds": "Build", "Reports": "Report",
    "Records": "Record", "Loads": "Load", "Registers": "Register",
    "Lists": "List", "Runs": "Run", "Writes": "Write",
    "Resolves": "Resolve", "Stops": "Stop", "Renders": "Render",
    "Appends": "Append", "Starts": "Start", "Applies": "Apply",
    "Validates": "Validate", "Adds": "Add", "Serialises": "Serialise",
    "Finds": "Find", "Ends": "End", "Checks": "Check", "Stores": "Store",
    "Removes": "Remove", "Performs": "Perform", "Opens": "Open",
    "Moves": "Move", "Creates": "Create", "Prints": "Print",
    "Matches": "Match", "Executes": "Execute", "Captures": "Capture",
    "Yields": "Yield", "Walks": "Walk", "Tries": "Try", "Sets": "Set",
    "Serves": "Serve", "Requests": "Request", "Replaces": "Replace",
    "Reads": "Read", "Polls": "Poll", "Parses": "Parse", "Emits": "Emit",
    "Wires": "Wire", "Wraps": "Wrap", "Returns": "Return",
    "Chooses": "Choose", "Collects": "Collect", "Composes": "Compose",
    "Computes": "Compute", "Confirms": "Confirm", "Converts": "Convert",
    "Delivers": "Deliver", "Denies": "Deny", "Derives": "Derive",
    "Describes": "Describe", "Detects": "Detect", "Drives": "Drive",
    "Enters": "Enter", "Enumerates": "Enumerate", "Evaluates": "Evaluate",
    "Extracts": "Extract", "Fans": "Fan", "Fills": "Fill",
    "Fetches": "Fetch", "Formats": "Format", "Gates": "Gate",
    "Generates": "Generate", "Gives": "Give", "Groups": "Group",
    "Handles": "Handle", "Hands": "Hand", "Holds": "Hold",
    "Includes": "Include", "Indexes": "Index", "Injects": "Inject",
    "Inserts": "Insert", "Installs": "Install", "Invokes": "Invoke",
    "Keeps": "Keep", "Launches": "Launch", "Leaves": "Leave",
    "Maps": "Map", "Marks": "Mark", "Merges": "Merge", "Mirrors": "Mirror",
    "Moves": "Move", "Normalises": "Normalise", "Notes": "Note",
    "Overrides": "Override", "Owns": "Own", "Pauses": "Pause",
    "Picks": "Pick", "Plans": "Plan", "Prepares": "Prepare",
    "Produces": "Produce", "Pulls": "Pull", "Pushes": "Push",
    "Queues": "Queue", "Raises": "Raise", "Recovers": "Recover",
    "Rejects": "Reject", "Releases": "Release", "Renames": "Rename",
    "Renders": "Render", "Requires": "Require", "Resets": "Reset",
    "Resumes": "Resume", "Returns": "Return", "Reuses": "Reuse",
    "Routes": "Route", "Saves": "Save", "Scans": "Scan", "Seeds": "Seed",
    "Selects": "Select", "Sends": "Send", "Separates": "Separate",
    "Shows": "Show", "Skips": "Skip", "Splits": "Split", "Streams": "Stream",
    "Takes": "Take", "Tears": "Tear", "Tells": "Tell", "Tracks": "Track",
    "Transfers": "Transfer", "Turns": "Turn", "Updates": "Update",
    "Uses": "Use", "Verifies": "Verify", "Waits": "Wait", "Wakes": "Wake",
    "Watches": "Watch", "Wipes": "Wipe", "Carries": "Carry",
    "Clears": "Clear", "Closes": "Close", "Compiles": "Compile",
    "Counts": "Count", "Declares": "Declare", "Defers": "Defer",
    "Draws": "Draw", "Dumps": "Dump", "Echoes": "Echo", "Exports": "Export",
    "Flags": "Flag", "Flushes": "Flush", "Forces": "Force",
    "Guards": "Guard", "Imports": "Import", "Joins": "Join",
    "Locates": "Locate", "Logs": "Log", "Looks": "Look", "Names": "Name",
    "Offers": "Offer", "Parts": "Part", "Passes": "Pass", "Pins": "Pin",
    "Points": "Point", "Prepends": "Prepend", "Presents": "Present",
    "Rebuilds": "Rebuild", "Refuses": "Refuse", "Represents": "Represent",
    "Restores": "Restore", "Retries": "Retry", "Rolls": "Roll",
    "Rounds": "Round", "Scrolls": "Scroll", "Settles": "Settle",
    "Signs": "Sign", "Sorts": "Sort", "Spawns": "Spawn", "Steps": "Step",
    "Strips": "Strip", "Submits": "Submit", "Swaps": "Swap",
    "Toggles": "Toggle", "Traverses": "Traverse", "Trims": "Trim",
    "Unpacks": "Unpack", "Unregisters": "Unregister", "Wraps": "Wrap",
    "Configures": "Configure", "Copies": "Copy", "Drops": "Drop",
    "Expands": "Expand", "Filters": "Filter", "Fires": "Fire",
    "Persists": "Persist",
}

_SECTION = re.compile(
    r"^(?P<indent>\s*)(?P<name>Args|Arguments|Returns|Return|Yields|"
    r"Yield|Raises|Attributes|Parameters):\s*$"
)
_FIELD = re.compile(r"^(?P<indent>\s+)(?P<name>[\w*]+):\s?(?P<desc>.*)$")


def _fix_summary(lines: list[str]) -> None:
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        first, _, rest = line.strip().partition(" ")
        if first in _IMPERATIVE:
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = f"{indent}{_IMPERATIVE[first]} {rest}".rstrip()
        return


def _convert_sections(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        match = _SECTION.match(lines[i])
        if match is None:
            out.append(lines[i])
            i += 1
            continue
        name = match.group("name")
        body_indent = len(match.group("indent"))
        i += 1
        block: list[str] = []
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= body_indent:
                break
            block.append(nxt)
            i += 1
        out.extend(_render(name, block, match.group("indent")))
    return out


def _render(name: str, block: list[str], indent: str) -> list[str]:
    if name in ("Args", "Arguments", "Parameters", "Attributes"):
        tag = "ivar" if name == "Attributes" else "param"
        return _fields(block, indent, tag)
    if name in ("Returns", "Return"):
        return _scalar(block, indent, "return")
    if name in ("Yields", "Yield"):
        return _scalar(block, indent, "yield")
    if name == "Raises":
        return _raises(block, indent)
    return [indent + name + ":", *block]


def _fields(block: list[str], indent: str, tag: str) -> list[str]:
    out: list[str] = []
    for line in block:
        field = _FIELD.match(line)
        if field is not None:
            out.append(
                f"{indent}:{tag} {field.group('name')}: "
                f"{field.group('desc')}".rstrip()
            )
        elif line.strip():
            out.append(f"{indent}    {line.strip()}")
    return out


def _scalar(block: list[str], indent: str, tag: str) -> list[str]:
    text = " ".join(line.strip() for line in block if line.strip())
    return [f"{indent}:{tag}: {text}".rstrip()] if text else [f"{indent}:{tag}:"]


def _raises(block: list[str], indent: str) -> list[str]:
    out: list[str] = []
    for line in block:
        field = _FIELD.match(line)
        if field is not None:
            out.append(
                f"{indent}:raises {field.group('name')}: "
                f"{field.group('desc')}".rstrip()
            )
        elif line.strip() and out:
            out[-1] = f"{out[-1]} {line.strip()}"
    return out


def _transform(text: str) -> str:
    lines = text.split("\n")
    _fix_summary(lines)
    return "\n".join(_convert_sections(lines))


def _docstring_id(body: object) -> int | None:
    stmts = getattr(body, "body", body)
    if not stmts:
        return None
    first = stmts[0]
    if (
        isinstance(first, cst.SimpleStatementLine)
        and first.body
        and isinstance(first.body[0], cst.Expr)
        and isinstance(first.body[0].value, cst.SimpleString)
    ):
        return id(first.body[0].value)
    return None


class _Finder(cst.CSTVisitor):
    """Collect the node ids of module/class/function docstrings only."""

    def __init__(self) -> None:
        self.ids: set[int] = set()

    def visit_Module(self, node: cst.Module) -> None:
        self._add(node.body)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self._add(node.body)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._add(node.body)

    def _add(self, body: object) -> None:
        found = _docstring_id(body)
        if found is not None:
            self.ids.add(found)


class _Docstrings(cst.CSTTransformer):
    def __init__(self, ids: set[int]) -> None:
        self._ids = ids

    def leave_SimpleString(
        self, original: cst.SimpleString, updated: cst.SimpleString
    ) -> cst.SimpleString:
        if id(original) not in self._ids or not updated.quote.startswith(
            '"""'
        ):
            return updated
        raw = updated.raw_value
        new = _transform(raw)
        # Keep the closing-quote structure: re-attach whatever trailing
        # newline/indent the original had before ``"""``.
        trailing = raw[len(raw.rstrip("\n \t")) :]
        new = new.rstrip("\n \t") + trailing
        if new == raw:
            return updated
        return updated.with_changes(
            value=f"{updated.prefix}{updated.quote}{new}{updated.quote}"
        )


def main() -> None:
    for path_str in sys.argv[1:]:
        path = Path(path_str)
        module = cst.parse_module(path.read_text(encoding="utf-8"))
        finder = _Finder()
        module.visit(finder)
        new = module.visit(_Docstrings(finder.ids))
        path.write_text(new.code, encoding="utf-8")
        print(f"  docstrings: {path}")


if __name__ == "__main__":
    main()

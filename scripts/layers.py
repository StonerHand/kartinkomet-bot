"""The layer diagram in docs/ARCHITECTURE.md, drawn from the code's real imports.

    python scripts/layers.py           # rewrite the block between the markers
    python scripts/layers.py --check   # exit 1 when the block is stale (tests/structure runs this)

The order of sections comes from .importlinter, the single source of truth; the arrows and the table
come from every `import bot...` in bot/, including imports inside functions. The diagram drops an
arrow a longer path already implies; the table lists every section each section imports.
"""

import ast
import configparser
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "ARCHITECTURE.md"
BEGIN = "<!-- layers:begin: scripts/layers.py writes this block from .importlinter and the imports -->"
END = "<!-- layers:end -->"


def layer_rows() -> list[list[str]]:
    """Sections from top to bottom; siblings that must not import each other share a row."""
    config = configparser.ConfigParser()
    config.read(ROOT / ".importlinter")
    lines = config["importlinter:contract:layers"]["layers"].split("\n")
    return [[name.strip() for name in line.split("|")] for line in lines if line.strip()]


def section(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "bot" else None


def module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports() -> Counter[tuple[str, str]]:
    """(section, section it imports) → how many import statements say so."""
    counts: Counter[tuple[str, str]] = Counter()
    for path in sorted((ROOT / "bot").rglob("*.py")):
        source = section(module_name(path))
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                targets = [node.module]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            else:
                continue
            for target in {section(name) for name in targets} - {None, source}:
                if source is not None:
                    counts[(source, target)] += 1
    return counts


def implied(edges: set[tuple[str, str]], start: str, goal: str) -> bool:
    """Does a longer path start → … → goal exist besides the direct arrow?"""
    below = defaultdict(set)
    for upper, lower in edges:
        below[upper].add(lower)
    stack = [step for step in below[start] if step != goal]
    seen = set(stack)
    while stack:
        current = stack.pop()
        if current == goal:
            return True
        for step in below[current] - seen:
            seen.add(step)
            stack.append(step)
    return False


def render() -> str:
    rows = layer_rows()
    order = {name: (index, place) for index, row in enumerate(rows) for place, name in enumerate(row)}
    counts = imports()
    edges = set(counts)
    arrows = sorted((edge for edge in edges if not implied(edges, *edge)), key=lambda e: (order[e[0]], order[e[1]], e))
    node = {name: name.replace("__main__", "main") for name in order}
    lines = [BEGIN, "", "```mermaid", "flowchart TB"]
    for index, row in enumerate(rows):
        if len(row) == 1:
            lines.append(f'    {node[row[0]]}["{label(row[0])}"]')
            continue
        lines.append(f'    subgraph row{index}[" "]')
        lines.append("        direction LR")
        lines.extend(f'        {node[name]}["{label(name)}"]' for name in row)
        lines.append("    end")
    lines.extend(f"    {node[upper]} --> {node[lower]}" for upper, lower in arrows)
    lines += ["```", "", "| Раздел | Опирается на (сколько импортов) |", "|---|---|"]
    for name in sorted(order, key=order.get):
        uses = sorted((lower for upper, lower in edges if upper == name), key=order.get)
        listed = ", ".join(f"`{lower}` ({counts[(name, lower)]})" for lower in uses) or "—"
        lines.append(f"| `{label(name)}` | {listed} |")
    return "\n".join([*lines, "", END])


def label(name: str) -> str:
    return "bot/__main__.py" if name == "__main__" else name


def current_block(text: str) -> str:
    start, end = text.index(BEGIN), text.index(END) + len(END)
    return text[start:end]


def main(check: bool) -> int:
    text = DOC.read_text()
    fresh = render()
    if current_block(text) == fresh:
        return 0
    if check:
        print(f"{DOC.relative_to(ROOT)}: the layer diagram is stale, run python scripts/layers.py")
        return 1
    DOC.write_text(text.replace(current_block(text), fresh))
    print(f"updated {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv[1:]))

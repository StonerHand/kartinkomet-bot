"""Every message the bot sends in the test suite, as plain text, for a design review.

    python scripts/dump_screens.py screens.txt
    python scripts/dump_screens.py screens.html   # Telegram-like bubbles at phone width

Runs the whole suite against the fake Telegram, keeps one sample of each message structure
(numbers, names and phrase lines collapsed) and writes them out with tags stripped, so all
screens can be read side by side the way a phone shows them.
"""

import importlib
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
importlib.import_module("tests")  # lean aiogram loading, as in the suite

from tests import harness, layout  # noqa: E402
from tests.ui import test_screens  # noqa: E402

NAMES = r"(user|Михаил|Захар|train|stoner_hand|fata11st|kcifekzhue|uploader)\S*"
seen: dict[str, str] = {}


def plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def remember(text: str, where: str) -> None:
    lines = re.sub(r"\d+", "#", text).split("\n")
    shape = [lines[0]] + [
        line if layout.EMOJI.match(plain(line)) else ("~" if line.strip() else "") for line in lines[1:]
    ]
    seen.setdefault(re.sub(NAMES, "N", "\n".join(shape)), f"[{where}]\n{text}")


def main(output: str) -> None:
    check_outgoing = harness.BotHarness.check_outgoing
    layout_problems = layout.layout_problems

    def check(self) -> None:
        for request in self.session.requests:
            text = getattr(request, "text", None) or getattr(request, "caption", None)
            if isinstance(text, str) and self.session.kind(request) in harness.CHECKED_METHODS:
                remember(text, f"{type(self).__name__}.{self._testMethodName} {self.session.kind(request)}")
        check_outgoing(self)

    def problems(text: str) -> list[str]:
        remember(text, "direct render")
        return layout_problems(text)

    harness.BotHarness.check_outgoing = check
    layout.layout_problems = test_screens.layout_problems = harness.layout_problems = problems
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    with open("/dev/null", "w") as quiet:
        unittest.TextTestRunner(verbosity=0, stream=quiet).run(suite)
    with open(output, "w") as out:
        if output.endswith(".html"):
            out.write(bubbles([seen[key] for key in sorted(seen)]))
        else:
            for key in sorted(seen):
                out.write(plain(seen[key]) + "\n\n" + "─" * 40 + "\n\n")
    print(f"{len(seen)} distinct messages → {output}")


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>kartinkomet screens</title>
<style>
body {{ margin: 0; padding: 16px; background: #0e1621; font: 17px/1.3 -apple-system, "SF Pro Text", Roboto, sans-serif;
       display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }}
.card {{ width: 320px; }}
.where {{ color: #6c7883; font-size: 11px; margin: 0 0 4px 4px; word-break: break-all; }}
.bubble {{ background: #182533; color: #f5f5f5; border-radius: 14px; padding: 8px 12px 10px; white-space: pre-wrap;
          overflow-wrap: anywhere; }}
.bubble b {{ font-weight: 600; }}
.bubble code {{ font-family: ui-monospace, Menlo, monospace; font-size: 14px; }}
.bubble blockquote {{ margin: 4px 0; padding: 2px 8px; border-left: 3px solid #6ab3f3; background: #1f3346;
                     border-radius: 4px; white-space: pre-wrap; }}
</style></head><body>{cards}</body></html>"""


def bubbles(samples: list[str]) -> str:
    """Every sample as a phone-width chat bubble: the bot's HTML is what Telegram renders."""
    cards = []
    for sample in samples:
        where, _, text = sample.partition("\n")
        text = text.replace("<blockquote expandable>", "<blockquote>")
        cards.append(f'<div class="card"><div class="where">{where}</div><div class="bubble">{text}</div></div>')
    return PAGE.format(cards="".join(cards))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "screens.txt")

"""Every message the bot sends in the test suite, as plain text, for a design review.

    python scripts/dump_screens.py screens.txt

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

from tests import test_bot, test_screens, test_texts  # noqa: E402

NAMES = r"(user|Михаил|Захар|train|stoner_hand|fata11st|kcifekzhue|uploader)\S*"
seen: dict[str, str] = {}


def plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def remember(text: str, where: str) -> None:
    lines = re.sub(r"\d+", "#", text).split("\n")
    shape = [lines[0]] + [
        line if test_texts.EMOJI.match(plain(line)) else ("~" if line.strip() else "") for line in lines[1:]
    ]
    seen.setdefault(re.sub(NAMES, "N", "\n".join(shape)), f"[{where}]\n{text}")


def main(output: str) -> None:
    check_outgoing = test_bot.BotHarness.check_outgoing
    layout_problems = test_texts.layout_problems

    def check(self) -> None:
        for request in self.session.requests:
            text = getattr(request, "text", None) or getattr(request, "caption", None)
            if isinstance(text, str) and self.session.kind(request) in test_bot.CHECKED_METHODS:
                remember(text, f"{type(self).__name__}.{self._testMethodName} {self.session.kind(request)}")
        check_outgoing(self)

    def problems(text: str) -> list[str]:
        remember(text, "direct render")
        return layout_problems(text)

    test_bot.BotHarness.check_outgoing = check
    test_texts.layout_problems = test_screens.layout_problems = test_bot.layout_problems = problems
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    with open("/dev/null", "w") as quiet:
        unittest.TextTestRunner(verbosity=0, stream=quiet).run(suite)
    with open(output, "w") as out:
        for key in sorted(seen):
            out.write(plain(seen[key]) + "\n\n" + "─" * 40 + "\n\n")
    print(f"{len(seen)} distinct messages → {output}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "screens.txt")

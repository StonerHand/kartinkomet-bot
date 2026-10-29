"""The design system as checks: every message the bot sends goes through layout_problems() and
assert_html() (see bot/tg/ui/views/layout.card for the rules in words)."""

import re
from html.parser import HTMLParser

from bot.tg.ui.views.layout import PHONE_LINE, fits


class HtmlBalance(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        self.stack.append(tag)

    def handle_endtag(self, tag) -> None:
        assert self.stack and self.stack.pop() == tag, f"unbalanced </{tag}>"


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B06\u2194-\u21FF\u2300-\u23FF\u25AA\u25AB\u25B6\u25C0\u25FB-\u25FE]")
MARK = re.compile(r"^(\d+\.|\d\ufe0f?\u20e3)")  # «1.» in a list, a keycap like 7️⃣
NOT_COUNTED = set("\U0001F3FB\U0001F3FC🟥🟦🟩🟨")  # skin tones and vote bars
TITLE = re.compile(r"^(\S+ )?<b>")  # "🎁 <b>Title</b>…": the head of an item
CAPTION = re.compile(r"^<i>[^<]*</i>$")  # an italic phrase under the lines above it


def marked(raw: str) -> bool:
    """A line opens with its emoji or a list mark (1., ▫️, 7️⃣, a vote square), or is a bar."""
    plain = re.sub(r"<[^>]+>", "", raw)
    return bool(EMOJI.match(plain) or MARK.match(plain) or raw.startswith("<code>"))


def layout_problems(text: str) -> list[str]:
    """The message layout rules (see bot/tg/views/layout.py), as checks:

    - one emoji per line, and at its start;
    - a message opens with its mechanic's emoji (a pic's caption: with its italic line);
    - every block opens with an emoji or a list mark; a list (several marked lines) has no
      unmarked lines in it, a single item may have description lines under it;
    - rules and explanations sit in a quote box (<blockquote>), where text may wrap freely;
    - outside boxes a line too long for one phone line must not merge with its neighbours: it
      stands in a block of its own, or it is the last line of a block: the description under its
      item's title ("🎁 <b>Title</b>" first, no other item in the block) or the italic caption
      under short lines.
    The header and its flavour line are one unit: only its last line may wrap."""
    raw_lines = text.split("\n")
    lines = [re.sub(r"<[^>]+>", "", line).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
             for line in raw_lines]
    problems = []
    for line in lines:
        emoji = [char for char in EMOJI.findall(line) if char not in NOT_COUNTED]
        if len(emoji) > 1:
            problems.append(f"several emoji: {line}")
        elif emoji and not EMOJI.match(line.lstrip("▫️✅ ")) and not EMOJI.match(line):
            problems.append(f"emoji inside a line: {line}")
    paragraphs: list[list[int]] = [[]]
    quoted = False
    for index, line in enumerate(lines):
        if raw_lines[index].startswith("<blockquote"):
            quoted = True
        if quoted:  # Telegram draws a quote as a box of its own: it is no paragraph's line
            if paragraphs[-1]:
                paragraphs.append([])
            quoted = "</blockquote>" not in raw_lines[index]
        elif line.strip():
            paragraphs[-1].append(index)
        elif paragraphs[-1]:
            paragraphs.append([])
    first = raw_lines[0]
    if not (marked(first) or CAPTION.match(first) or first.startswith("<blockquote")):
        problems.append(f"message without its emoji: {lines[0]}")  # a pic's caption is italic instead
    for index in paragraphs[0][:-1]:
        if not fits(raw_lines[index]):  # bold capitals are wide: a header wraps sooner than text
            problems.append(f"header wraps: {lines[index]}")
    for number, paragraph in enumerate(paragraphs):
        if number == 0 or not paragraph:
            continue  # the header block
        marks = [marked(raw_lines[index]) for index in paragraph]
        if not marks[0]:
            problems.append(f"block without its emoji: {lines[paragraph[0]]}")
        elif sum(marks) > 1 and not all(marks):
            problems.append(f"unmarked line in a list: {lines[paragraph[marks.index(False)]]}")
        if len(paragraph) < 2:
            continue  # a line standing alone
        first = paragraph[0]
        titled = bool(TITLE.match(raw_lines[first])) and len(lines[first]) <= PHONE_LINE and not any(
            EMOJI.match(lines[index]) for index in paragraph[1:]
        )
        last = paragraph[-1]
        caption = CAPTION.match(raw_lines[last]) and all(len(lines[index]) <= PHONE_LINE for index in paragraph[:-1])
        for index in paragraph:
            # Under a title only the last line may wrap: wrapped lines in the middle run together.
            if len(lines[index]) > PHONE_LINE and not ((titled or caption) and index == last):
                problems.append(f"long line glued to a neighbour: {lines[index]}")
    return problems


def assert_html(text: str) -> None:
    parser = HtmlBalance()
    parser.feed(text)
    assert not parser.stack, f"unclosed {parser.stack}"
    assert len(text) <= 4096

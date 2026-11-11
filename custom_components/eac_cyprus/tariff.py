"""Extract a tariff identifier, never personal report content or inferred prices."""

import re
from html.parser import HTMLParser


class _ReportText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignore += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.ignore:
            self.ignore -= 1

    def handle_data(self, data):
        if not self.ignore and data.strip():
            self.parts.append(data.strip())


def parse_tariff_code(html: str) -> str | None:
    parser = _ReportText()
    parser.feed(html)
    for index, part in enumerate(parser.parts):
        match = re.fullmatch(
            r"\s*(?:TARR?IF(?:F)?(?:\s*/\s*RATE)?|ΔΙΑΤΙΜΗΣΗ|ΔΙΑΤΙΜΗΣΗ\s*/\s*ΤΙΜΟΛΟΓΙΟ)\s*:\s*(.*)",
            part,
            re.I,
        )
        if not match:
            continue
        value = match[1].strip() or (
            parser.parts[index + 1].strip() if index + 1 < len(parser.parts) else ""
        )
        # Accept future identifiers as well as existing codes, but no labels,
        # addresses, markup or executable content from a changed report format.
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,31}", value):
            return value
    return None

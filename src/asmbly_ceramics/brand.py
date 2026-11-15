"""The Asmbly brand and ceramics colours: the one source the pages and the emails share.

The values are the facilities repository's kiln drop-off viewer's (`common/brand.py` and
its `page.html`), copied, not imported. `web/static/app.css` repeats them in its
`:root`, since a static file can't import, and `tests/web/test_style.py` checks it
matches. The email layout (`mail/templates/_layout.html`) takes them from here through
the composer. It lives beside `web/` and `mail/`, not in either, so the mailer never
imports the web layer (`tests/mail/test_compose.py` checks it).

Derived colours, per sRGB channel, rounded: `shade(p) = p * colour + (1 - p) * midnight-black`
and `tint(p) = p * colour + (1 - p) * asmbly-white` (the test recomputes each).
"""

from types import MappingProxyType

ASMBLY_PURPLE = "#292D6A"
ASMBLY_WHITE = "#F2F4EF"
MIDNIGHT_BLACK = "#171d1a"
CERAMICS = "#b34a9a"
LASERS = "#D33E43"

COLOURS = MappingProxyType(
    {
        "asmbly-purple": ASMBLY_PURPLE,
        "asmbly-white": ASMBLY_WHITE,
        "midnight-black": MIDNIGHT_BLACK,
        "ceramics": CERAMICS,
        "lasers": LASERS,
        "ceramics-shade": "#944180",
        "ceramics-shade-60": "#753867",
        "ceramics-40": "#d9b0cd",
        "ceramics-20": "#e5d2de",
        "ceramics-10": "#ece3e6",
        "lasers-shade": "#ad373b",
        "lasers-20": "#ecd0cd",
        "asmbly-purple-20": "#caccd4",
        "asmbly-purple-40": "#a2a4ba",
        "asmbly-purple-5": "#e8eae8",
        "midnight-black-70": "#595e5a",
    }
)
"""Each colour token's name (as `--<name>` in `app.css`) and its value."""

# How each derived colour is made: (base, "shade" or "tint", p).
DERIVED = MappingProxyType(
    {
        "ceramics-shade": ("ceramics", "shade", 0.8),
        "ceramics-shade-60": ("ceramics", "shade", 0.6),
        "ceramics-40": ("ceramics", "tint", 0.4),
        "ceramics-20": ("ceramics", "tint", 0.2),
        "ceramics-10": ("ceramics", "tint", 0.1),
        "lasers-shade": ("lasers", "shade", 0.8),
        "lasers-20": ("lasers", "tint", 0.2),
        "asmbly-purple-20": ("asmbly-purple", "tint", 0.2),
        "asmbly-purple-40": ("asmbly-purple", "tint", 0.4),
        "asmbly-purple-5": ("asmbly-purple", "tint", 0.05),
        "midnight-black-70": ("midnight-black", "tint", 0.7),
    }
)

EMAIL_COLOURS = MappingProxyType(
    {
        "page": ASMBLY_WHITE,
        "text": MIDNIGHT_BLACK,
        "band": ASMBLY_PURPLE,
        "on_band": ASMBLY_WHITE,
        "accent": CERAMICS,
        "id": COLOURS["ceramics-shade"],
        "on_accent": "#ffffff",
        "card": "#ffffff",
        "line": COLOURS["asmbly-purple-20"],
    }
)
"""What the email layout paints with: inline styles, since an email can't use CSS
variables."""

"""`app.css`: tokens only in `:root`, the brand's values, tap targets, and contrast."""

import re
from pathlib import Path

import pytest

import asmbly_ceramics.web
from asmbly_ceramics.brand import COLOURS, DERIVED

WEB = Path(asmbly_ceramics.web.__file__).parent
CSS = re.sub(r"/\*.*?\*/", "", (WEB / "static" / "app.css").read_text(), flags=re.DOTALL)
ROOT_MATCH = re.search(r":root\s*\{(.*?)\}", CSS, flags=re.DOTALL)
assert ROOT_MATCH is not None
ROOT = ROOT_MATCH.group(1)
REST = CSS[ROOT_MATCH.end() :]
TOKENS: dict[str, str] = dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", ROOT))
LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|(?<![\w-])\d*\.?\d+(px|rem|em|%|vh|vw|pt)\b")


def colour(name: str) -> str:
    """A token's colour, following `var(--other)` references."""
    value = TOKENS[name].strip()
    while value.startswith("var(--"):
        value = TOKENS[value[len("var(--") : -1]].strip()
    return value


def rgb(hex_colour: str) -> tuple[int, int, int]:
    value = hex_colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_colours_and_sizes_are_only_tokens() -> None:
    declarations = re.findall(r"([a-z-]+)\s*:\s*([^;{}]+);", REST)
    assert len(declarations) > 50
    problems = [f"{name}: {value}" for name, value in declarations if LITERAL.search(value)]
    assert problems == []


def test_the_colours_are_brand_py_s() -> None:
    for name, value in COLOURS.items():
        assert TOKENS[name].lower() == value.lower(), name


@pytest.mark.parametrize("name", sorted(DERIVED))
def test_derived_colours_follow_the_formula(name: str) -> None:
    base, how, share = DERIVED[name]
    other = COLOURS["midnight-black"] if how == "shade" else COLOURS["asmbly-white"]
    expected = [share * a + (1 - share) * b for a, b in zip(rgb(COLOURS[base]), rgb(other), strict=True)]
    actual = rgb(COLOURS[name])
    assert all(abs(e - a) <= 2 for e, a in zip(expected, actual, strict=True)), name


def test_buttons_and_inputs_are_at_least_44px() -> None:
    assert TOKENS["tap-target"].strip() == "2.75rem"
    rules = dict(re.findall(r"([^{}]+)\{([^{}]*)\}", REST))
    for selector in ("button, .button", 'input[type="file"]', ".choice", ".segmented label"):
        body = next(body for sel, body in rules.items() if sel.strip() == selector)
        assert "min-height: var(--tap-target)" in body, selector
    text_inputs = next(body for sel, body in rules.items() if sel.strip().startswith('input[type="text"]'))
    assert "min-height: var(--tap-target)" in text_inputs
    assert "font-size: var(--font-size-body)" in text_inputs  # 16px: iOS doesn't zoom
    assert TOKENS["font-size-body"].strip() == "1rem"


def test_cancel_links_are_at_least_44px() -> None:
    rules = dict(re.findall(r"([^{}]+)\{([^{}]*)\}", REST))
    body = next(body for sel, body in rules.items() if sel.strip() == ".cancel")
    assert "min-height: var(--tap-target)" in body
    for template in ("drop_off.html", "reject_preview.html"):
        page = (WEB / "templates" / "console" / template).read_text()
        assert '<a class="cancel" href="/console/drop-offs/{{ drop_off.id }}">Cancel</a>' in page, template


def test_summaries_and_action_links_are_at_least_44px() -> None:
    """The load page's "Change kiln, firing or date" and the weeks' links are tapped at
    the kiln, as the buttons are."""
    rules = dict(re.findall(r"([^{}]+)\{([^{}]*)\}", REST))
    for selector in ("summary", ".actions a"):
        body = next(body for sel, body in rules.items() if sel.strip() == selector)
        assert "min-height: var(--tap-target)" in body, selector
    load = (WEB / "templates" / "console" / "load.html").read_text()
    assert "<summary>Change kiln, firing or date</summary>" in load
    counts = (WEB / "templates" / "console" / "counts.html").read_text()
    assert '<nav class="actions" aria-label="Weeks">' in counts


@pytest.mark.parametrize(
    ("foreground", "background", "minimum"),
    [
        ("text", "page-bg", 7.0),  # readable in sunlight
        ("text", "error-bg", 4.5),
        ("text", "notice-bg", 4.5),
        ("text", "field-bg", 4.5),
        ("accent-strong", "page-bg", 4.5),  # the ID, links
        ("on-accent", "accent-strong", 4.5),  # buttons
        ("on-accent", "accent-hover", 4.5),
        ("on-accent", "danger", 4.5),  # "Delete L-4"
        ("on-band", "band-bg", 4.5),  # the logo band
        ("on-accent", "accent", 3.0),  # large h1 and the icon only
        ("error-edge", "page-bg", 3.0),
        ("error-edge", "error-bg", 3.0),
        ("focus", "page-bg", 3.0),
        ("line", "page-bg", 3.0),  # input edges
        ("text", "canvas", 7.0),  # the console's canvas
        ("muted", "canvas", 4.5),  # the console's secondary text
        ("muted", "surface", 4.5),
        ("accent-strong", "canvas", 4.5),  # links on the canvas
        ("tag-text", "tag-bg", 4.5),
        ("line", "canvas", 3.0),
        ("control-edge", "surface", 3.0),  # quiet buttons, chips, the weeks
        ("control-edge", "canvas", 3.0),
        ("accent-strong", "row-hover", 4.5),  # links on a hovered row
        ("muted", "row-hover", 4.5),
    ],
)
def test_text_colour_pairs_meet_wcag_aa(foreground: str, background: str, minimum: float) -> None:
    assert contrast(colour(foreground), colour(background)) >= minimum


def test_no_template_has_inline_style_or_script() -> None:
    for path in (WEB / "templates").rglob("*"):
        if path.is_file():
            text = path.read_text().lower()
            assert "style=" not in text, path
            assert "<style" not in text, path
            assert not re.search(r"<script(?![^>]*\bsrc=)", text), path


def _public_classes() -> set[str]:
    """Every class the public form's pages and script use."""
    names: set[str] = set()
    sources = [
        *(WEB / "templates").glob("*.html"),
        *(WEB / "templates" / "partials" / name for name in ("field.html", "logo.svg", "ceramics-icon.svg")),
        WEB / "static" / "upload.js",
    ]
    for path in sources:
        text = re.sub(r"\{[%{#].*?[%}#]\}", " ", path.read_text())
        for value in re.findall(r'class="([^"]*)"', text):
            names |= set(value.split())
        for value in re.findall(r"class(?:Name\s*=|List\.add\()\s*[\"']([^\"']+)", text):
            names |= set(value.split())
    return names


def test_console_rules_do_not_reach_the_public_form() -> None:
    """A rule in the console's section starts at .console, .page-console, or a class
    only the console uses, so the public form looks as it did."""
    public = _public_classes()
    assert {"photos", "photo-item", "field", "notice"} <= public
    section = REST[REST.index(".console {") :]
    problems = []
    for selectors, _ in re.findall(r"([^{}]+)\{([^{}]*)\}", section):
        for selector in selectors.split(","):
            first = re.search(r"\.([a-z][a-z0-9-]*)", selector)
            if first is not None and first.group(1) in public:
                problems.append(selector.strip())
    assert problems == []


def test_rows_that_open_something_are_one_link_with_a_chevron() -> None:
    """A table row that opens a drop-off or a load is one stretched link (.row-link) and
    ends in a chevron cell (.row-go); no row carries a bare underlined "Open" link."""
    rules = dict(re.findall(r"([^{}]+)\{([^{}]*)\}", REST))
    stretched = next(body for sel, body in rules.items() if sel.strip() == ".list .row-link::after")
    assert "position: absolute" in stretched
    assert "inset: var(--none)" in stretched
    lifted = next(body for sel, body in rules.items() if ":is(form, button, input, select)" in sel)
    assert "z-index" in lifted  # a row's own buttons stay clickable above the link
    pages = {
        "loads.html": 2,
        "waiting.html": 1,
        "load.html": 1,
        "counts.html": 1,
        "emails.html": 1,
        "firing_log.html": 1,
    }
    for name, tables in pages.items():
        page = (WEB / "templates" / "console" / name).read_text()
        assert page.count('class="row-link') == tables, name
        assert page.count('<td class="row-go"></td>') == tables, name
        assert ">Open</a>" not in page, name


def test_a_hidden_file_input_stays_hidden() -> None:
    """`input[type="file"]` sets `display: block`, which would beat the `hidden` attribute
    and show the camera input as a second, unlabeled picker."""
    rules = dict(re.findall(r"([^{}]+)\{([^{}]*)\}", REST))
    body = next(body for sel, body in rules.items() if sel.strip() == 'input[type="file"][hidden]')
    assert "display: none" in body
    assert REST.index('input[type="file"][hidden]') > REST.index('input[type="file"] {')


def test_a_disabled_quiet_button_is_readable() -> None:
    """`button:disabled` paints the accent-hover background; the quiet button must set its
    own, or its accent text sits on it at about 1.3:1."""
    rules = dict(re.findall(r"([^{}]+)\{([^{}]*)\}", REST))
    body = next(body for sel, body in rules.items() if sel.strip() == ".button-quiet:disabled")
    assert "background: var(--surface)" in body
    assert "color: var(--muted)" in body


def test_the_hidden_take_a_photo_button_stays_hidden() -> None:
    """`button, .button` sets `display: inline-flex`; the button stays hidden until the
    script shows it only because the global `[hidden]` rule comes after it."""
    assert REST.index("button, .button {") < REST.index("\n[hidden] { display: none; }")

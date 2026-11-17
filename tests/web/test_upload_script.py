"""The drop-off form's upload script, run in Node against a small DOM stub (decision 0009).

`tests/web/js/upload.test.mjs` tests what the photo list does; this file renders the real
form on the in-memory fakes, hands its photo field's limits and sentences to those tests
and runs them with Node's own test runner. Node 20 or later must be on the PATH: without
it these tests fail, never skip, so the script is never left untested by accident.
"""

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import asmbly_ceramics.web
from asmbly_ceramics.adapters.memory.images import NOT_IMAGE
from tests.repo.files import REPO
from tests.web.conftest import PHOTO, Site

NODE_MIN = 20  # the floor decision 0009 states; seen to work on Node 22 only
NODE_TESTS = 14  # the tests in upload.test.mjs; each must run and pass
JS = Path(__file__).parent / "js"
SCRIPT = Path(asmbly_ceramics.web.__file__).parent / "static" / "upload.js"
TEMPLATE = Path(asmbly_ceramics.web.__file__).parent / "templates" / "form.html"
# On the page only after a refused submit; the script checks it for null before use.
OPTIONAL_IDS = {"error-summary"}
ADVICE = (
    "Node 20 or later is needed on the PATH to run the upload script's tests "
    "(decision 0009, README Prerequisites); this test never skips."
)


def node_env(**extra: str) -> dict[str, str]:
    """The minimal environment Node runs with, for the version probe and the tests alike."""
    return {"PATH": os.environ.get("PATH", ""), **extra}


def find_node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.fail(ADVICE)
    found = subprocess.run(  # noqa: S603 (a fixed command)
        [node, "--version"], check=True, capture_output=True, text=True, timeout=30, env=node_env()
    ).stdout.strip()
    version = re.fullmatch(r"v(\d+)\.\d+\.\d+", found)
    if version is None or int(version.group(1)) < NODE_MIN:
        pytest.fail(f"{ADVICE} Found {found or 'no version'} at {node}.")
    return node


def photo_field(page: str) -> dict[str, str]:
    """The `data-*` attributes of the element with `id="photos-field"`, unescaped."""
    tag = re.search(r'<[a-z]+\b[^>]*\bid="photos-field"[^>]*>', page)
    assert tag, "the form has no photo field"
    attributes = re.findall(r'\b(data-[\w-]+)="([^"]*)"', tag.group(0))
    return {name: html.unescape(value) for name, value in attributes}


def pieces_limits(page: str) -> dict[str, str]:
    """The `min` and `max` of the pieces input, as the form renders them."""
    tag = re.search(r'<input\b[^>]*\bid="pieces"[^>]*>', page)
    assert tag, "the form has no pieces input"
    found = dict(re.findall(r'\b(min|max)="(\d+)"', tag.group(0)))
    assert set(found) == {"min", "max"}, tag.group(0)
    return found


def kept_slot(site: Site) -> dict[str, str]:
    """The classes of a kept photo's markup, from a refused submit that keeps one upload."""
    good, bad = site.world.uploaded(PHOTO, NOT_IMAGE)
    page = site.submit(site.details(slot=[good, bad], name="")).text
    item = re.search(r'<li class="([^"]*)" data-slot="[^"]*">(.*?)</li>', page, re.DOTALL)
    assert item, "a refused submit shows no kept photo"
    label = re.search(r'<span class="([^"]*)">A photo you already added</span>', item.group(2))
    remove = re.search(r'<button type="button" class="([^"]*)">Remove</button>', item.group(2))
    assert label, item.group(0)
    assert remove, item.group(0)
    return {"item": item.group(1), "label": label.group(1), "remove": remove.group(1)}


def script_ids() -> list[str]:
    return sorted(set(re.findall(r'getElementById\("([^"]+)"\)', SCRIPT.read_text())))


def test_every_element_the_script_reads_is_on_the_form(site: Site) -> None:
    page = site.client.get("/").text
    ids = script_ids()
    assert len(ids) >= 10, ids
    missing = [i for i in ids if i not in OPTIONAL_IDS and f'id="{i}"' not in page]
    assert not missing
    for optional in OPTIONAL_IDS:
        assert f'id="{optional}"' in TEMPLATE.read_text()
        guarded = rf'var (\w+) = document\.getElementById\("{optional}"\);\s*if \(\1\)'
        assert re.search(guarded, SCRIPT.read_text()), f"upload.js uses {optional} without checking for null"


def test_a_kept_photo_has_the_classes_the_script_selects_on(site: Site) -> None:
    kept = kept_slot(site)
    assert set(kept["item"].split()) >= {"photo-item", "photo-kept"}, kept
    assert "photo-label" in kept["label"].split(), kept
    assert "remove" in kept["remove"].split(), kept
    script = SCRIPT.read_text()
    for selector in (".photo-item", ".photo-kept .remove", ".photo-label", ".remove", '"photo-kept"'):
        assert selector in script, f"upload.js no longer selects {selector}; update this test and dom.mjs"


def test_the_upload_script_behaves_as_the_form_needs(site: Site, tmp_path: Path) -> None:
    node = find_node()
    fixture = tmp_path / "form.json"
    page = site.client.get("/").text
    ids = [i for i in script_ids() if i not in OPTIONAL_IDS]
    form = {"field": photo_field(page), "ids": ids, "pieces": pieces_limits(page), "kept": kept_slot(site)}
    fixture.write_text(json.dumps(form))
    ran = subprocess.run(  # noqa: S603 (a fixed command)
        [node, "--test", "--test-reporter=tap", str(JS / "upload.test.mjs")],
        cwd=REPO,
        env=node_env(UPLOAD_FORM=str(fixture), UPLOAD_SCRIPT=str(SCRIPT)),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = ran.stdout + ran.stderr
    assert ran.returncode == 0, output
    # Node counts skipped and todo tests in "# tests", so every test must also pass: a
    # `test.skip` or a test file that defines nothing can't pass.
    counts = dict(re.findall(r"^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", ran.stdout, re.MULTILINE))
    expected = {"tests": NODE_TESTS, "pass": NODE_TESTS, "fail": 0, "cancelled": 0, "skipped": 0, "todo": 0}
    assert {name: int(count) for name, count in counts.items()} == expected, output


def test_a_missing_node_fails_and_says_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(pytest.fail.Exception, match=r"Node 20 or later.*decision 0009"):
        find_node()


def test_an_old_node_fails_and_names_its_version(monkeypatch: pytest.MonkeyPatch) -> None:
    def old_node(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == ["/made-up/bin/node", "--version"]
        assert kwargs["env"] == {"PATH": os.environ.get("PATH", "")}, "probed with the tests' environment"
        return subprocess.CompletedProcess(command, 0, stdout="v18.19.0\n", stderr="")

    monkeypatch.setattr(shutil, "which", lambda name: "/made-up/bin/node")
    monkeypatch.setattr(subprocess, "run", old_node)
    with pytest.raises(pytest.fail.Exception, match=r"Node 20 or later.*v18\.19\.0"):
        find_node()


def test_an_unreadable_node_version_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def odd_node(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="not a version\n", stderr="")

    monkeypatch.setattr(shutil, "which", lambda name: "/made-up/bin/node")
    monkeypatch.setattr(subprocess, "run", odd_node)
    with pytest.raises(pytest.fail.Exception, match=r"Node 20 or later.*not a version"):
        find_node()

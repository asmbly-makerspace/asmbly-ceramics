"""The console's own health check and stylesheet: the API sends `/console` paths to the
console's function only, so neither depends on the form's function, which can be taken
offline (reserved concurrency 0, `docs/runbooks/operations.md`)."""

from tests.web.conftest import VERSION, Site
from tests.web.console.conftest import Console


def test_the_console_answers_its_own_health_check_without_a_session(console: Console) -> None:
    answer = console.get("/console/health")
    assert answer.status_code == 200
    assert answer.json() == {"status": "ok", "version": VERSION}


def test_the_console_serves_its_own_stylesheet_cached(console: Console) -> None:
    answer = console.get("/console/static/app.css")
    assert answer.status_code == 200
    assert answer.headers["cache-control"] == "public, max-age=3600"
    assert answer.headers["x-content-type-options"] == "nosniff"
    missing = console.get("/console/static/nothing.css")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"


def test_console_pages_link_the_console_s_stylesheet_and_form_pages_the_form_s(
    console: Console, site: Site
) -> None:
    signed_out = console.get("/console/signed-out")
    assert f'href="/console/static/app.css?v={VERSION}"' in signed_out.text
    console.sign_in()
    waiting = console.get("/console")
    assert f'href="/console/static/app.css?v={VERSION}"' in waiting.text
    not_found = console.get("/console/no-such-page")
    assert f'href="/console/static/app.css?v={VERSION}"' in not_found.text
    form = site.client.get("/")
    assert f'href="/static/app.css?v={VERSION}"' in form.text


def test_the_form_s_app_has_no_console_paths(site: Site) -> None:
    assert site.client.get("/console/health").status_code == 404
    assert site.client.get("/console/static/app.css").status_code == 404

"""`create_from_environment`, the deployed app's factory: the role, the logging and the deadline."""

import logging

import pytest
from starlette.testclient import TestClient

from asmbly_ceramics import composition
from asmbly_ceramics.settings import Settings, SettingsError
from asmbly_ceramics.web.app import RequestDeadline, WebServices, WebSettings, create_from_environment
from tests.test_settings import ENVIRONMENT
from tests.use_cases.conftest import World
from tests.web.conftest import services, settings


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("APP_ROLE", "form")

    def build(given: Settings | None = None) -> tuple[WebServices, WebSettings]:
        assert given == Settings.from_environment(ENVIRONMENT)
        return services(world), settings()

    monkeypatch.setattr(composition, "build_form_services", build)


def test_the_form_role_builds_the_form_under_a_deadline(deployed: None) -> None:
    root = logging.getLogger()
    saved = list(root.handlers), root.level
    try:
        app = create_from_environment()
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved[0]:
            root.addHandler(handler)
        root.setLevel(saved[1])
    outermost: object = app.user_middleware[0].cls
    assert outermost is RequestDeadline  # every request runs under it
    with TestClient(app, base_url="https://testserver") as client:
        health = client.get("/health")
    assert health.json() == {"status": "ok", "version": "test-1"}


@pytest.mark.parametrize("role", ["", "console", "FORM"])
def test_any_other_role_fails_at_start(deployed: None, monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    monkeypatch.setenv("APP_ROLE", role)
    with pytest.raises(SettingsError, match="APP_ROLE"):
        create_from_environment()

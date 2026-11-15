"""`Settings.from_environment`: every variable read, and a missing one named without its value."""

import pytest

from asmbly_ceramics.settings import Settings, SettingsError

ENVIRONMENT = {
    "APP_ENV": "stage",
    "APP_VERSION": "abc1234",
    "TABLE_NAME": "asmbly-ceramics-stage-records",
    "PHOTO_BUCKET": "asmbly-ceramics-stage-photos-0a1b2c3d",
    "SITE_URL": "https://ceramics-stage.asmbly.org",
    "INITIAL_SENDING_ADDRESS": "ceramics" + "@" + "asmbly.org",
    "AWS_REGION": "us-east-2",
    "LOG_LEVEL": "info",
}


def test_settings_read_every_variable() -> None:
    settings = Settings.from_environment(ENVIRONMENT)
    assert settings == Settings(
        app_env="stage",
        version="abc1234",
        table_name="asmbly-ceramics-stage-records",
        photo_bucket="asmbly-ceramics-stage-photos-0a1b2c3d",
        site_url="https://ceramics-stage.asmbly.org",
        initial_sending_address=ENVIRONMENT["INITIAL_SENDING_ADDRESS"],
        region="us-east-2",
        log_level="INFO",
    )
    assert (
        settings.photo_upload_origin
        == "https://asmbly-ceramics-stage-photos-0a1b2c3d.s3.us-east-2.amazonaws.com"
    )


def test_settings_default_to_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    assert Settings.from_environment().table_name == "asmbly-ceramics-stage-records"


@pytest.mark.parametrize("name", sorted(ENVIRONMENT))
def test_a_missing_variable_is_named_without_its_value(name: str) -> None:
    for environ in ({k: v for k, v in ENVIRONMENT.items() if k != name}, {**ENVIRONMENT, name: "  "}):
        with pytest.raises(SettingsError) as raised:
            Settings.from_environment(environ)
        assert name in str(raised.value)
        assert ENVIRONMENT[name] not in str(raised.value)


def test_the_site_url_must_be_https() -> None:
    with pytest.raises(SettingsError, match="SITE_URL"):
        Settings.from_environment({**ENVIRONMENT, "SITE_URL": "http://ceramics-stage.asmbly.org"})


@pytest.mark.parametrize(("name", "value"), [("APP_ENV", "dev"), ("LOG_LEVEL", "LOUD")])
def test_a_value_of_the_wrong_shape_is_refused(name: str, value: str) -> None:
    with pytest.raises(SettingsError, match=name) as raised:
        Settings.from_environment({**ENVIRONMENT, name: value})
    assert value not in str(raised.value)

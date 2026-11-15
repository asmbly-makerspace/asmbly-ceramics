"""What a deployed function knows about its environment, read once from the variables
`infra/app.yaml` sets (standard library only).

A missing or empty variable is a deploy mistake, so it fails the function at start with
`SettingsError` naming the variable, never its value.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

ENVIRONMENTS = ("stage", "prod")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class SettingsError(Exception):
    """A variable is missing or has the wrong shape; the message names it, never its value."""


@dataclass(frozen=True)
class Settings:
    app_env: Literal["stage", "prod"]
    version: str
    table_name: str
    photo_bucket: str
    site_url: str  # "https://ceramics.asmbly.org"
    initial_sending_address: str  # checked by `CurrentStudio` (an asmbly.org address)
    region: str  # AWS_REGION, set by Lambda
    log_level: str

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> Settings:
        environ = os.environ if environ is None else environ

        def read(name: str) -> str:
            value = environ.get(name, "").strip()
            if not value:
                raise SettingsError(f"{name} is not set")
            return value

        app_env = read("APP_ENV")
        if app_env not in ENVIRONMENTS:
            raise SettingsError("APP_ENV is neither stage nor prod")
        site_url = read("SITE_URL")
        if not site_url.startswith("https://"):
            raise SettingsError("SITE_URL must start with https://")
        log_level = read("LOG_LEVEL").upper()
        if log_level not in LOG_LEVELS:
            raise SettingsError("LOG_LEVEL is not a log level")
        return cls(
            app_env=cast("Literal['stage', 'prod']", app_env),
            version=read("APP_VERSION"),
            table_name=read("TABLE_NAME"),
            photo_bucket=read("PHOTO_BUCKET"),
            site_url=site_url,
            initial_sending_address=read("INITIAL_SENDING_ADDRESS"),
            region=read("AWS_REGION"),
            log_level=log_level,
        )

    @property
    def photo_upload_origin(self) -> str:
        """The host `S3PhotoStore` presigns its POSTs to (virtual-hosted, regional), which
        the form's CSP allows in `connect-src`."""
        return f"https://{self.photo_bucket}.s3.{self.region}.amazonaws.com"

"""Every template parameter for one config environment, as `sam deploy --parameter-overrides`
takes them, so a parameter left out of the command never keeps a stale value.

    python3 scripts/sam_parameters.py stage AppVersion=abc1234 WebAdapterLayerArn=arn:...

The values come from, in order (a later one wins): the template's defaults, the config
environment's `parameter_overrides` in `samconfig.toml`, then the arguments. A key the
template doesn't have, a parameter left without a value, or a value with a space or a
quote is refused. Standard library only: the deploy runs it before installing anything.
"""

import re
import shlex
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infra" / "app.yaml"
SAMCONFIG = ROOT / "samconfig.toml"
_PARAMETER = re.compile(r"^  ([A-Za-z0-9]+):\s*$")
_DEFAULT = re.compile(r"^    Default:\s*(.*?)\s*$")
_VALUE = re.compile(r"[^\s'\"]+")


class ParameterError(Exception):
    pass


def template_parameters(text: str) -> dict[str, str | None]:
    """The `Parameters` section's names and their defaults (None when there is none)."""
    parameters: dict[str, str | None] = {}
    inside = False
    current: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            inside = line.rstrip() == "Parameters:"
            current = None
            continue
        if not inside:
            continue
        if match := _PARAMETER.match(line):
            current = match.group(1)
            parameters[current] = None
        elif current is not None and (default := _DEFAULT.match(line)):
            parameters[current] = default.group(1).strip("'\"")
    return parameters


def pairs(texts: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for text in texts:
        key, sep, value = text.partition("=")
        if not sep or not key:
            raise ParameterError(f"not Key=Value: {key or text[:20]}")
        if not _VALUE.fullmatch(value):
            raise ParameterError(f"{key}'s value is empty or holds a space or a quote")
        values[key] = value
    return values


def parameters_for(config_env: str, arguments: list[str], template: str, samconfig: str) -> list[str]:
    defaults = template_parameters(template)
    config = tomllib.loads(samconfig)
    try:
        overrides = config[config_env]["deploy"]["parameters"]["parameter_overrides"]
    except KeyError:
        raise ParameterError(
            f"samconfig.toml has no {config_env}.deploy.parameters.parameter_overrides"
        ) from None
    values: dict[str, str | None] = dict(defaults)
    for given in (pairs(shlex.split(overrides)), pairs(arguments)):
        unknown = sorted(set(given) - set(defaults))
        if unknown:
            raise ParameterError("the template has no parameter " + ", ".join(unknown))
        values.update(given)
    missing = sorted(name for name, value in values.items() if value is None)
    if missing:
        raise ParameterError("no value for " + ", ".join(missing))
    return [f"{name}={value}" for name, value in values.items()]


def main(argv: list[str]) -> int:
    if len(argv) < 1:
        print("usage: sam_parameters.py <config-env> [Key=Value ...]", file=sys.stderr)
        return 2
    try:
        result = parameters_for(argv[0], argv[1:], TEMPLATE.read_text(), SAMCONFIG.read_text())
    except ParameterError as error:
        print(f"sam_parameters: {error}", file=sys.stderr)
        return 1
    print(" ".join(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

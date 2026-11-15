"""Read a CloudFormation template so tests can walk it.

CloudFormation's YAML has short tags (`!Ref`, `!Sub`, `!GetAtt`, ...) that
`yaml.safe_load` refuses. This loader reads each one into its long form
(`{"Ref": ...}`, `{"Fn::Sub": ...}`), the form AWS documents for JSON templates.
"""

from pathlib import Path
from typing import Any

import yaml

# Short tag -> long form. `!GetAtt A.B` is the one with its own string syntax.
SHORT_TAGS = {
    "Ref": "Ref",
    "Condition": "Condition",
    **{
        name: f"Fn::{name}"
        for name in (
            "Sub",
            "GetAtt",
            "Join",
            "If",
            "Equals",
            "Not",
            "And",
            "Or",
            "Select",
            "Split",
            "ImportValue",
            "FindInMap",
            "Base64",
            "GetAZs",
            "Cidr",
        )
    },
}


class CloudFormationLoader(yaml.SafeLoader):
    """A SafeLoader that also reads CloudFormation's short tags."""


def _construct(long_form: str) -> Any:
    def construct(loader: yaml.SafeLoader, node: yaml.Node) -> dict[str, Any]:
        value: Any
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
            if long_form == "Fn::GetAtt":
                value = value.split(".", 1)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node, deep=True)
        else:
            value = loader.construct_mapping(node, deep=True)  # type: ignore[arg-type]
        return {long_form: value}

    return construct


for _short, _long in SHORT_TAGS.items():
    CloudFormationLoader.add_constructor(f"!{_short}", _construct(_long))


def load_template(path: Path) -> dict[str, Any]:
    """The template at `path` as plain data, short tags in their long forms."""
    loaded = yaml.load(path.read_text(), Loader=CloudFormationLoader)  # noqa: S506 (a SafeLoader subclass)
    assert isinstance(loaded, dict), f"{path} is not a template"
    return loaded

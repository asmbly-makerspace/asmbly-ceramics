"""`scripts/sam_parameters.py`: every parameter printed, the command's values winning."""

import pytest
from scripts.sam_parameters import ParameterError, parameters_for, template_parameters

from scripts import sam_parameters

TEMPLATE = """\
AWSTemplateFormatVersion: '2010-09-09'
Parameters:
  # a comment
  ProjectSlug:
    Type: String
    Default: asmbly-ceramics
  AppEnv:
    Type: String
  AppVersion:
    Type: String
  EmailDomain:
    Type: String
    Default: 'asmbly.org'
Resources:
  Thing:
    Type: AWS::SNS::Topic
    Properties:
      Default: not-a-parameter
"""
SAMCONFIG = """\
version = 0.1
[stage.deploy.parameters]
parameter_overrides = "AppEnv=stage AppVersion=old0000"
"""


def test_the_template_s_parameters_and_defaults_are_read() -> None:
    assert template_parameters(TEMPLATE) == {
        "ProjectSlug": "asmbly-ceramics",
        "AppEnv": None,
        "AppVersion": None,
        "EmailDomain": "asmbly.org",
    }


def test_every_parameter_is_printed() -> None:
    assert parameters_for("stage", [], TEMPLATE, SAMCONFIG) == [
        "ProjectSlug=asmbly-ceramics",
        "AppEnv=stage",
        "AppVersion=old0000",
        "EmailDomain=asmbly.org",
    ]


def test_a_value_from_the_command_wins_over_samconfig() -> None:
    printed = parameters_for("stage", ["AppVersion=abc1234"], TEMPLATE, SAMCONFIG)
    assert "AppVersion=abc1234" in printed
    assert "AppVersion=old0000" not in printed


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ParameterError, match="no parameter Stale"):
        parameters_for("stage", ["Stale=1"], TEMPLATE, SAMCONFIG)


@pytest.mark.parametrize(
    ("argument", "message"),
    [("AppVersion=", "empty"), ("AppVersion=a b", "space"), ("AppVersion='x'", "quote"), ("=x", "Key=Value")],
)
def test_a_bad_pair_is_refused(argument: str, message: str) -> None:
    with pytest.raises(ParameterError, match=message):
        parameters_for("stage", [argument], TEMPLATE, SAMCONFIG)


def test_a_parameter_without_a_value_is_refused() -> None:
    samconfig = SAMCONFIG.replace(" AppVersion=old0000", "")
    with pytest.raises(ParameterError, match="no value for AppVersion"):
        parameters_for("stage", [], TEMPLATE, samconfig)


def test_an_unknown_config_environment_is_refused() -> None:
    with pytest.raises(ParameterError, match="no prod"):
        parameters_for("prod", [], TEMPLATE, SAMCONFIG)


def test_the_repository_s_samconfig_names_every_parameter_but_the_two_the_deploy_adds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for env in ("stage", "prod"):
        assert sam_parameters.main([env, "AppVersion=abc1234", "WebAdapterLayerArn=arn:x"]) == 0
        printed = capsys.readouterr().out.split()
        assert f"AppEnv={env}" in printed
        assert f"AlertEmail=/asmbly-ceramics/{env}/alert-email" in printed
        assert f"InitialSendingAddress=/asmbly-ceramics/{env}/initial-sending-address" in printed
        assert sam_parameters.main([env]) == 1  # AppVersion and the layer come from the deploy
        assert "no value for AppVersion, WebAdapterLayerArn" in capsys.readouterr().err


def test_main_needs_a_config_environment(capsys: pytest.CaptureFixture[str]) -> None:
    assert sam_parameters.main([]) == 2

"""The bootstrap stack's security properties (infra/bootstrap.yaml).

The bootstrap is deployed by hand, once, and everything the app's deploys may do comes
from it: who can assume the deploy roles, what CloudFormation may create and change,
and the most a function can ever do. These tests pin those properties so that a later
edit can't widen them unnoticed. They read the file only; none calls AWS.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest

from tests.repo.cloudformation import load_template
from tests.repo.files import REPO

TEMPLATE = load_template(REPO / "infra" / "bootstrap.yaml")
RESOURCES: dict[str, Any] = TEMPLATE["Resources"]
SLUG = "${ProjectSlug}"
TAGS = {
    "Project": {"Ref": "ProjectSlug"},
    "Component": "Bootstrap",
    "Environment": {"Ref": "EnvironmentTag"},
    "Owner": "it-volunteers",
    "ManagedBy": "cloudformation",
}
DEPLOY_ROLES = {"GitHubDeployRoleStage": "stage", "GitHubDeployRoleProd": "prod"}
BOUNDARIES = {"FunctionBoundaryStage": "stage", "FunctionBoundaryProd": "prod"}
TAG_CREATE_KEYS = ("Component", "Environment", "Owner", "ManagedBy")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def sub(value: Any) -> str:
    """The text of a `!Sub` (or a plain string), for matching on names."""
    if isinstance(value, dict) and "Fn::Sub" in value:
        text = value["Fn::Sub"]
        return text if isinstance(text, str) else text[0]
    return value if isinstance(value, str) else json.dumps(value)


def statements(resource: str) -> list[dict[str, Any]]:
    """Every statement of a role's inline policies, or of a managed policy."""
    properties = RESOURCES[resource]["Properties"]
    if "PolicyDocument" in properties:
        return list(properties["PolicyDocument"]["Statement"])
    attached = [reference["Ref"] for reference in properties.get("ManagedPolicyArns", [])]
    return [
        statement for policy in properties["Policies"] for statement in policy["PolicyDocument"]["Statement"]
    ] + [statement for name in attached for statement in statements(name)]


def by_sid(resource: str) -> dict[str, dict[str, Any]]:
    return {statement["Sid"]: statement for statement in statements(resource)}


def allows(resource: str) -> Iterator[dict[str, Any]]:
    return (statement for statement in statements(resource) if statement["Effect"] == "Allow")


def actions(statement: dict[str, Any]) -> list[str]:
    return [str(action) for action in as_list(statement.get("Action", []))]


def resources(statement: dict[str, Any]) -> list[str]:
    return [sub(resource) for resource in as_list(statement.get("Resource", []))]


EXEC_POLICIES = ("CreateAndTagPolicy", "ChangeOwnPolicy", "RolesAndNamesPolicy", "ApisAndNamesPolicy")
EXEC = by_sid("CloudFormationExecutionRole")

# The execution role's statements that may allow without a tag condition, each for the
# reason its comment in the template gives (the prep revisions in the phase document).
UNTAGGED_EXCEPTIONS = {
    "SamTransform",  # the transform is AWS's, with no tags
    "ReadArtifacts",  # the bootstrap's own bucket, read only
    "PhotoBucketsByName",  # S3 checks aws:ResourceTag only on a bucket with ABAC on
    "SchedulesByName",  # schedules in the default group take no tags
    "SubscriptionsByName",  # SNS subscriptions take no tags
    "WebAdapterLayer",  # AWS's layer, read only
    "PassFunctionRoles",  # fenced by the app path and the services it may pass to
    "ResolveStackParameters",  # Strings read as stack parameters; another project tags some
    "DescribeWithoutAResource",  # reads that take no resource
    "ApiAccessLogDelivery",  # API Gateway's access-log delivery: no resource, no tag
    "ApisById",  # HTTP API routes, integrations and mappings take no tags (decision 0005)
    "ReadAndDeleteByName",  # before a create (no tag yet) and in a rollback (0005)
    "ReadAndDeleteRolesByName",  # the same, for the app's function roles (0005)
}
# Where "*" may be a resource, and why.
STAR_ALLOWED = {
    ("CloudFormationExecutionRole", "DescribeWithoutAResource"),
    ("CloudFormationExecutionRole", "ApiAccessLogDelivery"),
    ("CloudFormationExecutionRole", "CreateEventSourceMappings"),
    ("GitHubDeployRoleStage", "TemplateChecksWithoutAResource"),
    ("GitHubDeployRoleProd", "TemplateChecksWithoutAResource"),
    ("FunctionBoundaryStage", "DecryptOwnSecretsThroughSsm"),
    ("FunctionBoundaryProd", "DecryptOwnSecretsThroughSsm"),
}


def test_every_name_starts_with_the_project_slug() -> None:
    parameter = TEMPLATE["Parameters"]["ProjectSlug"]
    assert parameter["Default"] == "asmbly-ceramics"
    assert parameter["AllowedPattern"] == "^asmbly-ceramics$"
    names = [
        properties[key]
        for resource in RESOURCES.values()
        for properties in [resource.get("Properties", {})]
        for key in ("RoleName", "ManagedPolicyName", "BucketName", "PolicyName")
        if key in properties
    ]
    names += [r["Properties"]["Name"] for r in RESOURCES.values() if r["Type"] == "AWS::ApiGatewayV2::Api"]
    assert len(names) == 13
    for name in names:
        assert sub(name).startswith(f"{SLUG}-"), name
    for output in TEMPLATE["Outputs"].values():
        if "Export" in output:
            assert sub(output["Export"]["Name"]).startswith(f"{SLUG}-")


def test_roles_and_boundary_live_under_the_bootstrap_path() -> None:
    iam = [
        name
        for name, resource in RESOURCES.items()
        if resource["Type"] in {"AWS::IAM::Role", "AWS::IAM::ManagedPolicy"}
    ]
    assert set(iam) == {
        *DEPLOY_ROLES,
        "CloudFormationExecutionRole",
        *BOUNDARIES,
        *EXEC_POLICIES,
    }
    for name in iam:
        assert sub(RESOURCES[name]["Properties"]["Path"]) == f"/{SLUG}-bootstrap/", name


@pytest.mark.parametrize(("role", "environment"), DEPLOY_ROLES.items())
def test_each_deploy_role_trusts_only_its_own_environment_of_this_repository(
    role: str, environment: str
) -> None:
    (trust,) = RESOURCES[role]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert trust["Effect"] == "Allow"
    assert trust["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert sub(trust["Principal"]["Federated"]).endswith(":oidc-provider/token.actions.githubusercontent.com")
    assert set(trust["Condition"]) == {"StringEquals"}, "a StringLike would let other subjects match"
    condition = trust["Condition"]["StringEquals"]
    assert condition["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    # Only a job in this environment: a pull request's job runs in none.
    assert (
        sub(condition["token.actions.githubusercontent.com:sub"])
        == f"${{GitHubSubjectPrefix}}:environment:{environment}"
    )
    pattern = TEMPLATE["Parameters"]["GitHubSubjectPrefix"]["AllowedPattern"]
    assert pattern == "^repo:asmbly-makerspace@[0-9]+/asmbly-ceramics@[0-9]+$"


@pytest.mark.parametrize(("role", "environment"), DEPLOY_ROLES.items())
def test_each_deploy_role_can_only_hand_its_own_stack_to_cloudformation(role: str, environment: str) -> None:
    reached = {resource for statement in allows(role) for resource in resources(statement)}
    assert reached == {
        f"arn:${{AWS::Partition}}:cloudformation:${{AWS::Region}}:${{AWS::AccountId}}:stack/{SLUG}-{environment}/*",
        "arn:${AWS::Partition}:cloudformation:${AWS::Region}:aws:transform/Serverless-2016-10-31",
        "*",
        json.dumps({"Fn::GetAtt": ["CloudFormationExecutionRole", "Arn"]}),
        json.dumps({"Fn::GetAtt": ["ArtifactsBucket", "Arn"]}),
        "${ArtifactsBucket.Arn}/*",
    }
    sids = by_sid(role)
    tagged = sids["TaggedChangeSets"]
    assert actions(tagged) == ["cloudformation:CreateChangeSet", "cloudformation:TagResource"]
    assert resources(tagged) == [
        f"arn:${{AWS::Partition}}:cloudformation:${{AWS::Region}}:${{AWS::AccountId}}:stack/{SLUG}-{environment}/*"
    ]
    assert tagged["Condition"] == {
        "StringEquals": {"aws:RequestTag/Project": {"Ref": "ProjectSlug"}},
        "Null": {f"aws:RequestTag/{key}": "false" for key in TAG_CREATE_KEYS},
    }
    for statement in allows(role):
        if "cloudformation:CreateChangeSet" in actions(statement) and statement["Sid"] != "SamTransform":
            assert statement["Sid"] == "TaggedChangeSets"
    # No import change set: importing would tag an existing resource of another
    # project (an untagged event-source mapping or API) with this Project (decision 0003).
    assert sids["NoResourceImport"] == {
        "Sid": "NoResourceImport",
        "Effect": "Deny",
        "Action": "cloudformation:CreateChangeSet",
        "Resource": "*",
        "Condition": {"Null": {"cloudformation:ImportResourceTypes": "false"}},
    }
    assert actions(sids["TheAppStack"]) == [
        "cloudformation:DescribeChangeSet",
        "cloudformation:ExecuteChangeSet",
        "cloudformation:DeleteChangeSet",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:GetTemplate",
        "cloudformation:GetTemplateSummary",
        "cloudformation:ListStackResources",
    ]
    assert actions(sids["SamTransform"]) == ["cloudformation:CreateChangeSet"]
    assert actions(sids["Artifacts"]) == [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket",
        "s3:GetBucketLocation",
    ]
    assert actions(sids["TemplateChecksWithoutAResource"]) == [
        "cloudformation:ValidateTemplate",
        "cloudformation:GetTemplateSummary",
    ]
    passing = sids["HandStacksToTheExecutionRole"]
    assert actions(passing) == ["iam:PassRole"]
    assert passing["Condition"] == {"StringEquals": {"iam:PassedToService": "cloudformation.amazonaws.com"}}
    never = sids["NeverTheBootstrap"]
    assert never["Effect"] == "Deny"
    assert resources(never) == [
        "arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/${AWS::StackName}/*"
    ]
    for statement in allows(role):
        assert all(not action.startswith("iam:") or action == "iam:PassRole" for action in actions(statement))


def test_the_execution_role_is_trusted_only_by_cloudformation_in_this_account() -> None:
    (trust,) = RESOURCES["CloudFormationExecutionRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert trust["Principal"] == {"Service": "cloudformation.amazonaws.com"}
    assert trust["Condition"] == {"StringEquals": {"aws:SourceAccount": {"Ref": "AWS::AccountId"}}}


ROLE_SIDS = {
    sid: (boundary, environment)
    for boundary, environment in BOUNDARIES.items()
    for sid in (f"Create{environment.title()}FunctionRoles", f"Grant{environment.title()}InsideItsBoundary")
}


def test_the_execution_role_creates_roles_only_inside_their_environments_boundary() -> None:
    app_roles = f"arn:${{AWS::Partition}}:iam::${{AWS::AccountId}}:role/{SLUG}-app/{SLUG}-*"
    for sid, (boundary, environment) in ROLE_SIDS.items():
        statement = EXEC[sid]
        # A stage-named role only with the stage boundary, a prod-named one only with prod's.
        assert resources(statement) == [
            f"arn:${{AWS::Partition}}:iam::${{AWS::AccountId}}:role/{SLUG}-app/{SLUG}-{environment}-*"
        ], sid
        assert statement["Condition"]["StringEquals"]["iam:PermissionsBoundary"] == {"Ref": boundary}, sid
        assert statement["Condition"]["StringEquals"][
            "aws:RequestTag/Project" if "Create" in sid else "aws:ResourceTag/Project"
        ] == {"Ref": "ProjectSlug"}
    for environment in BOUNDARIES.values():
        assert actions(EXEC[f"Create{environment.title()}FunctionRoles"]) == ["iam:CreateRole"]
    granting = {
        "iam:CreateRole",
        "iam:PutRolePolicy",
        "iam:AttachRolePolicy",
        "iam:PutRolePermissionsBoundary",
    }
    for sid, statement in EXEC.items():
        if statement["Effect"] == "Allow" and granting & set(actions(statement)):
            assert sid in ROLE_SIDS, sid
    # Every other IAM right is on the app's roles, or nothing.
    for sid, statement in EXEC.items():
        if statement["Effect"] == "Allow" and any(action.startswith("iam:") for action in actions(statement)):
            for resource in resources(statement):
                assert resource.startswith(app_roles[:-1]) or (
                    sid == "TagOnCreate" and not resource.startswith("arn:${AWS::Partition}:iam:")
                ), (sid, resource)
    assert EXEC["NoBoundaryRemoval"] == {
        "Sid": "NoBoundaryRemoval",
        "Effect": "Deny",
        "Action": "iam:DeleteRolePermissionsBoundary",
        "Resource": "*",
    }
    assert EXEC["PassFunctionRoles"]["Condition"] == {
        "StringEquals": {"iam:PassedToService": ["lambda.amazonaws.com", "scheduler.amazonaws.com"]}
    }


def test_every_create_statement_requires_the_project_request_tag() -> None:
    for sid in (
        "CreateTagged",
        "CreateEventSourceMappings",
        "CreateStageFunctionRoles",
        "CreateProdFunctionRoles",
    ):
        condition = EXEC[sid]["Condition"]
        assert condition["StringEquals"]["aws:RequestTag/Project"] == {"Ref": "ProjectSlug"}
        assert condition["Null"] == {f"aws:RequestTag/{key}": "false" for key in TAG_CREATE_KEYS}
    assert EXEC["TagOnCreate"]["Condition"] == {
        "StringEquals": {"aws:RequestTag/Project": {"Ref": "ProjectSlug"}}
    }
    # A log delivery (API Gateway's access logs) is created on no resource, so it
    # can't carry a tag: the one create outside these statements.
    creating = re.compile(r":(Create(?!ChangeSet|LogDelivery)|PutMetricAlarm)")
    for sid, statement in EXEC.items():
        if statement["Effect"] == "Allow" and any(creating.search(action) for action in actions(statement)):
            assert sid in {
                "CreateTagged",
                "CreateEventSourceMappings",
                "CreateStageFunctionRoles",
                "CreateProdFunctionRoles",
                "ChangeOwn",  # PutMetricAlarm also updates an alarm
                "SchedulesByName",  # schedules take no tags
            }, sid
    # The app creates no API: the two are the bootstrap's (decision 0005).
    assert not [r for r in resources(EXEC["CreateTagged"]) if ":apigateway:" in r]


def test_every_change_statement_requires_the_project_resource_tag() -> None:
    for sid, statement in EXEC.items():
        if statement["Effect"] != "Allow" or sid in UNTAGGED_EXCEPTIONS:
            continue
        conditions = statement["Condition"]
        tagged = conditions.get("StringEquals", {})
        assert tagged.get("aws:ResourceTag/Project") == {"Ref": "ProjectSlug"} or tagged.get(
            "aws:RequestTag/Project"
        ) == {"Ref": "ProjectSlug"}, sid


def test_no_untag_right_so_a_resource_cannot_drop_its_project_tag() -> None:
    for name in (*DEPLOY_ROLES, "CloudFormationExecutionRole", *BOUNDARIES):
        for statement in allows(name):
            assert not any("untag" in action.lower() for action in actions(statement)), name


def test_untagged_exceptions_reach_only_project_names_or_read_only_resources() -> None:
    expected = {
        "PhotoBucketsByName": [f"arn:${{AWS::Partition}}:s3:::{SLUG}-*-photos-*"],
        "SchedulesByName": [
            f"arn:${{AWS::Partition}}:scheduler:${{AWS::Region}}:${{AWS::AccountId}}:schedule/default/{SLUG}-*"
        ],
        "SubscriptionsByName": [f"arn:${{AWS::Partition}}:sns:${{AWS::Region}}:${{AWS::AccountId}}:{SLUG}-*"],
        "WebAdapterLayer": [
            "arn:${AWS::Partition}:lambda:${AWS::Region}:${WebAdapterPublisherAccount}:layer:LambdaAdapterLayerArm64:*"
        ],
    }
    for sid, reached in expected.items():
        assert resources(EXEC[sid]) == reached, sid
    assert actions(EXEC["WebAdapterLayer"]) == ["lambda:GetLayerVersion"]
    # The layer's publisher is a parameter set by hand: never "*", never a GitHub variable.
    assert TEMPLATE["Parameters"]["WebAdapterPublisherAccount"]["AllowedPattern"] == "^[0-9]{12}$"
    assert "Default" not in TEMPLATE["Parameters"]["WebAdapterPublisherAccount"]
    mappings = EXEC["CreateEventSourceMappings"]
    assert actions(mappings) == ["lambda:CreateEventSourceMapping"]
    assert sub(mappings["Condition"]["ArnLike"]["lambda:FunctionArn"]) == (
        f"arn:${{AWS::Partition}}:lambda:${{AWS::Region}}:${{AWS::AccountId}}:function:{SLUG}-*"
    )
    assert all(
        action.startswith(("s3:Get", "s3:Put", "s3:List", "s3:Delete"))
        for action in actions(EXEC["PhotoBucketsByName"])
    )
    photo_rights = re.compile(r"^s3:(Get|Put|Delete)Object(Version|Acl|Tagging)?$")
    assert not any(photo_rights.match(action) for action in actions(EXEC["PhotoBucketsByName"])), (
        "no photo rights"
    )
    assert actions(EXEC["ResolveStackParameters"]) == ["ssm:GetParameters"]
    assert resources(EXEC["ResolveStackParameters"]) == [
        "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter/config/cognito/staff/*",
        f"arn:${{AWS::Partition}}:ssm:${{AWS::Region}}:${{AWS::AccountId}}:parameter/{SLUG}/*/alert-email",
        f"arn:${{AWS::Partition}}:ssm:${{AWS::Region}}:${{AWS::AccountId}}:parameter/{SLUG}/*/initial-sending-address",
    ]
    assert actions(EXEC["ReadArtifacts"]) == ["s3:GetObject", "s3:GetObjectVersion"]


def test_other_projects_tags_and_the_bootstrap_are_denied() -> None:
    others = EXEC["HandsOffOtherProjects"]
    assert others["Effect"] == "Deny"
    assert others["Action"] == "*"
    # Any Project value but this one: no list that a new project could be missing from.
    assert others["Condition"] == {
        "Null": {"aws:ResourceTag/Project": "false"},
        "StringNotEquals": {"aws:ResourceTag/Project": {"Ref": "ProjectSlug"}},
    }
    # The one exception: the staff sign-in's Strings, which the role may only read.
    assert sub(others["NotResource"]) == (
        "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter/config/cognito/staff/*"
    )
    staff = "parameter/config/cognito/staff/"
    for sid, statement in EXEC.items():
        if statement["Effect"] == "Allow" and any(staff in resource for resource in resources(statement)):
            assert sid == "ResolveStackParameters"
    bootstrap = EXEC["HandsOffTheBootstrap"]
    assert bootstrap["Effect"] == "Deny"
    assert bootstrap["Action"] == "*"
    assert resources(bootstrap) == [
        "arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/${AWS::StackName}/*",
        f"arn:${{AWS::Partition}}:iam::${{AWS::AccountId}}:role/{SLUG}-bootstrap/*",
        f"arn:${{AWS::Partition}}:iam::${{AWS::AccountId}}:policy/{SLUG}-bootstrap/*",
        "arn:${AWS::Partition}:apigateway:${AWS::Region}::/domainnames/${ProdDomainName}",
        "arn:${AWS::Partition}:apigateway:${AWS::Region}::/domainnames/${StageDomainName}",
    ]
    artifacts = EXEC["ArtifactsAreReadOnly"]
    assert artifacts["Effect"] == "Deny"
    assert artifacts["NotAction"] == ["s3:GetObject", "s3:GetObjectVersion"]


def test_no_sign_in_email_or_dns_rights_for_the_execution_role() -> None:
    assert EXEC["NoSignInRights"]["Effect"] == "Deny"
    assert set(actions(EXEC["NoSignInRights"])) == {"cognito-idp:*", "cognito-identity:*"}
    assert EXEC["NoEmailOrDnsRights"]["Effect"] == "Deny"
    assert set(actions(EXEC["NoEmailOrDnsRights"])) == {"ses:*", "route53:*", "acm:*"}
    for statement in allows("CloudFormationExecutionRole"):
        for action in actions(statement):
            assert not action.startswith(("cognito", "ses:", "route53", "acm:")), action
    # API Gateway: only the two addresses' API mappings, never a domain name itself.
    for resource in (r for s in allows("CloudFormationExecutionRole") for r in resources(s)):
        if "/domainnames/" in resource:
            assert re.search(r"/domainnames/\$\{(Prod|Stage)DomainName\}/apimappings(/\*)?$", resource), (
                resource
            )


def test_resource_star_only_where_documented() -> None:
    for name in (*DEPLOY_ROLES, "CloudFormationExecutionRole", *BOUNDARIES):
        for statement in statements(name):
            if "*" in resources(statement) and statement["Effect"] == "Allow":
                assert (name, statement["Sid"]) in STAR_ALLOWED, (name, statement["Sid"])
    assert actions(EXEC["DescribeWithoutAResource"]) == [
        "logs:DescribeLogGroups",
        "logs:DescribeMetricFilters",
        "logs:DescribeResourcePolicies",
        "logs:DescribeIndexPolicies",
        "logs:GetLogDelivery",
        "logs:ListLogDeliveries",
        "cloudwatch:DescribeAlarms",
    ]
    assert actions(EXEC["ApiAccessLogDelivery"]) == [
        "logs:CreateLogDelivery",
        "logs:UpdateLogDelivery",
        "logs:DeleteLogDelivery",
    ]


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_the_boundary_sends_only_from_the_email_domain(boundary: str) -> None:
    sids = by_sid(boundary)
    send = sids["SendFromAsmblyAddresses"]
    assert actions(send) == ["ses:SendEmail"]
    assert resources(send) == [
        "arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/${EmailIdentityDomain}",
        "arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/*@${EmailIdentityDomain}",
    ]
    assert send["Condition"] == {"StringLike": {"ses:FromAddress": {"Fn::Sub": "*@${EmailIdentityDomain}"}}}
    assert TEMPLATE["Parameters"]["EmailIdentityDomain"]["Default"] == "asmbly.org"
    others = [a for s in statements(boundary) if s is not send for a in actions(s) if a.startswith("ses:")]
    assert not others


@pytest.mark.parametrize(("boundary", "environment"), BOUNDARIES.items())
def test_each_boundary_reaches_only_its_own_environments_resources(boundary: str, environment: str) -> None:
    sids = by_sid(boundary)
    assert (
        sub(RESOURCES[boundary]["Properties"]["ManagedPolicyName"])
        == f"{SLUG}-{environment}-function-boundary"
    )
    assert set(sids) == {
        "WriteOwnLogs",
        "OwnTables",
        "OwnPhotos",
        "ListOwnPhotos",
        "OwnSecrets",
        "DecryptOwnSecretsThroughSsm",
        "SendFromAsmblyAddresses",
        "RunOwnFunctions",
        "OwnDeadLetterQueues",
    }
    other = "prod" if environment == "stage" else "stage"
    for sid, statement in sids.items():
        assert statement["Effect"] == "Allow"
        if sid in {"DecryptOwnSecretsThroughSsm", "SendFromAsmblyAddresses"}:
            continue
        for resource in resources(statement):
            # Its own environment's names only: a stage function never reaches prod's.
            assert f"{SLUG}-{environment}-" in resource or f"{SLUG}/{environment}/" in resource, (
                sid,
                resource,
            )
            assert other not in resource, (sid, resource)
        assert not any(action.startswith(("iam:", "cognito", "sts:")) for action in actions(statement))
    assert {sid: actions(statement) for sid, statement in sids.items()} == {
        "WriteOwnLogs": ["logs:CreateLogStream", "logs:PutLogEvents"],
        # No dynamodb:ListStreams: it takes no resource, so a table ARN never grants it.
        "OwnTables": [
            "dynamodb:GetItem",
            "dynamodb:Query",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:DescribeStream",
            "dynamodb:GetRecords",
            "dynamodb:GetShardIterator",
        ],
        "OwnPhotos": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        "ListOwnPhotos": ["s3:ListBucket"],
        "OwnSecrets": ["ssm:GetParameter"],
        "DecryptOwnSecretsThroughSsm": ["kms:Decrypt"],
        "SendFromAsmblyAddresses": ["ses:SendEmail"],
        "RunOwnFunctions": ["lambda:InvokeFunction"],
        "OwnDeadLetterQueues": ["sqs:SendMessage"],
    }
    decrypt = sids["DecryptOwnSecretsThroughSsm"]
    assert actions(decrypt) == ["kms:Decrypt"]
    assert decrypt["Condition"] == {
        "StringEquals": {"kms:ViaService": {"Fn::Sub": "ssm.${AWS::Region}.amazonaws.com"}}
    }


def test_no_wildcard_action_is_ever_allowed() -> None:
    for name in (*DEPLOY_ROLES, "CloudFormationExecutionRole", *BOUNDARIES):
        for statement in allows(name):
            assert "NotAction" not in statement, (name, statement["Sid"])
            assert not any("*" in action for action in actions(statement)), (name, statement["Sid"])


def test_the_artifacts_bucket_is_private_encrypted_and_retained() -> None:
    bucket = RESOURCES["ArtifactsBucket"]
    assert bucket["DeletionPolicy"] == "Retain"
    assert bucket["UpdateReplacePolicy"] == "Retain"
    properties = bucket["Properties"]
    # A random suffix, never the account ID: the name is a GitHub variable.
    assert sub(properties["BucketName"]) == f"{SLUG}-artifacts-${{ArtifactsBucketSuffix}}"
    assert TEMPLATE["Parameters"]["ArtifactsBucketSuffix"]["AllowedPattern"] == "^[a-z0-9]{8}$"
    assert properties["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }
    assert properties["OwnershipControls"] == {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
    (encryption,) = properties["BucketEncryption"]["ServerSideEncryptionConfiguration"]
    assert encryption["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"
    rules = {rule["Id"]: rule for rule in properties["LifecycleConfiguration"]["Rules"]}
    assert rules["expire-artifacts"]["ExpirationInDays"] == 90
    assert rules["abort-multipart"]["AbortIncompleteMultipartUpload"] == {"DaysAfterInitiation": 1}
    (tls,) = RESOURCES["ArtifactsBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]
    assert tls["Effect"] == "Deny"
    assert tls["Action"] == "s3:*"
    assert tls["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
    assert set(resources(tls)) == {
        json.dumps({"Fn::GetAtt": ["ArtifactsBucket", "Arn"]}),
        "${ArtifactsBucket.Arn}/*",
    }


@pytest.mark.parametrize("environment", ["Prod", "Stage"])
def test_each_address_has_a_dns_validated_certificate_a_regional_domain_and_aliases(environment: str) -> None:
    certificate = RESOURCES[f"{environment}Certificate"]
    properties = certificate["Properties"]
    domain = {"Ref": f"{environment}DomainName"}
    assert properties["DomainName"] == domain
    assert properties["ValidationMethod"] == "DNS"
    assert properties["DomainValidationOptions"] == [
        {"DomainName": domain, "HostedZoneId": {"Ref": "ParentHostedZoneId"}}
    ]
    (configuration,) = RESOURCES[f"{environment}Domain"]["Properties"]["DomainNameConfigurations"]
    assert configuration == {
        "CertificateArn": {"Ref": f"{environment}Certificate"},
        "EndpointType": "REGIONAL",
        "SecurityPolicy": "TLS_1_2",
        "IpAddressType": "dualstack",
    }
    for suffix, record_type in (("", "A"), ("Ipv6", "AAAA")):
        record = RESOURCES[f"{environment}DnsRecord{suffix}"]["Properties"]
        assert record["Type"] == record_type
        assert record["Name"] == domain
        assert record["HostedZoneId"] == {"Ref": "ParentHostedZoneId"}
        assert record["AliasTarget"]["DNSName"] == {
            "Fn::GetAtt": [f"{environment}Domain", "RegionalDomainName"]
        }
    defaults = {"Prod": "ceramics.asmbly.org", "Stage": "ceramics-stage.asmbly.org"}
    assert TEMPLATE["Parameters"][f"{environment}DomainName"]["Default"] == defaults[environment]


def test_the_template_creates_only_the_resources_the_runbook_expects() -> None:
    # Runbook step 4 checks the change set against this count: 22, or 23 with the
    # provider (the two HTTP APIs and their policy came with decision 0005).
    assert len(RESOURCES) == 23
    assert RESOURCES["GitHubOidcProvider"]["Condition"] == "CreateOidcProvider"


def test_every_resource_that_takes_tags_has_the_five() -> None:
    untaggable = {
        "AWS::IAM::ManagedPolicy",
        "AWS::S3::BucketPolicy",
        "AWS::Route53::RecordSet",
        "AWS::Logs::ResourcePolicy",
    }
    for name, resource in RESOURCES.items():
        if resource["Type"] in untaggable:
            assert "Tags" not in resource["Properties"], name
            continue
        tags = resource["Properties"]["Tags"]
        found = tags if isinstance(tags, dict) else {tag["Key"]: tag["Value"] for tag in tags}
        assert found == TAGS, name


def test_the_outputs_and_exports_phase_7_reads() -> None:
    outputs = TEMPLATE["Outputs"]
    assert set(outputs) == {
        "StageDeployRoleArn",
        "ProdDeployRoleArn",
        "ExecutionRoleArn",
        "ArtifactsBucketName",
        "StageFunctionBoundaryArn",
        "ProdFunctionBoundaryArn",
        "ProdDomainNameOut",
        "StageDomainNameOut",
        "ProdApiId",
        "StageApiId",
    }
    exports = {name: sub(output["Export"]["Name"]) for name, output in outputs.items() if "Export" in output}
    assert exports == {
        "StageFunctionBoundaryArn": f"{SLUG}-stage-function-boundary-arn",
        "ProdFunctionBoundaryArn": f"{SLUG}-prod-function-boundary-arn",
        "ProdDomainNameOut": f"{SLUG}-prod-domain-name",
        "StageDomainNameOut": f"{SLUG}-stage-domain-name",
        "ProdApiId": f"{SLUG}-prod-api-id",
        "StageApiId": f"{SLUG}-stage-api-id",
    }


def test_no_account_id_or_address_in_the_template() -> None:
    text = (REPO / "infra" / "bootstrap.yaml").read_text()
    assert not re.search(r"(?<!\d)\d{12}(?!\d)", text), "an account ID"
    assert not re.search(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d+:", text), (
        "an ARN built by hand with an account"
    )
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text), "an email address"
    assert "${AWS::AccountId}" in text


def test_only_the_deploy_workflow_may_get_credentials() -> None:
    # The deploy roles trust only the stage and prod environments, which only
    # deploy.yml's jobs name (tests/repo/test_workflows.py pins those jobs).
    for workflow in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        if workflow.name == "deploy.yml":
            assert workflow.read_text().count("configure-aws-credentials@") == 2
        else:
            assert "configure-aws-credentials" not in workflow.read_text(), workflow.name


# What a policy document looks like once CloudFormation has filled it in, near enough
# to measure: the longest values each reference can take (a 12-digit account).
ACCOUNT = "9" * 12
BOOTSTRAP_PATH = "asmbly-ceramics-bootstrap/"
EXEC_NAME = "asmbly-ceramics-cfn-exec"
POLICIES = f"arn:aws:iam::{ACCOUNT}:policy/{BOOTSTRAP_PATH}"
FILLED = {
    "AWS::Partition": "aws-us-gov",
    "AWS::Region": "us-gov-east-1",
    "AWS::AccountId": ACCOUNT,
    "AWS::StackName": "asmbly-ceramics-bootstrap",
    "ProjectSlug": "asmbly-ceramics",
    "GitHubSubjectPrefix": "repo:asmbly-makerspace@99999999999/asmbly-ceramics@99999999999",
    "ProdDomainName": "ceramics.asmbly.org",
    "StageDomainName": "ceramics-stage.asmbly.org",
    "EmailIdentityDomain": "asmbly.org",
    "ArtifactsBucket.Arn": "arn:aws:s3:::asmbly-ceramics-artifacts-99999999",
    "FunctionBoundaryStage": f"{POLICIES}asmbly-ceramics-stage-function-boundary",
    "FunctionBoundaryProd": f"{POLICIES}asmbly-ceramics-prod-function-boundary",
    "WebAdapterPublisherAccount": "8" * 12,
    "CloudFormationExecutionRole.Arn": f"arn:aws:iam::{ACCOUNT}:role/{BOOTSTRAP_PATH}{EXEC_NAME}",
    "StageApi": "a1b2c3d4e5",
    "ProdApi": "f6g7h8i9j0",
}


def filled(value: Any) -> Any:
    if isinstance(value, dict):
        if "Fn::Sub" in value:
            return re.sub(r"\$\{([^}]+)\}", lambda m: FILLED[m.group(1)], value["Fn::Sub"])
        if "Ref" in value:
            return FILLED[value["Ref"]]
        if "Fn::GetAtt" in value:
            return FILLED[".".join(value["Fn::GetAtt"])]
        return {key: filled(item) for key, item in value.items()}
    if isinstance(value, list):
        return [filled(item) for item in value]
    return value


def size(document: Any) -> int:
    # IAM counts a policy's characters without whitespace.
    return len(re.sub(r"\s", "", json.dumps(filled(document), separators=(",", ":"))))


def test_every_policy_fits_iams_size_limits() -> None:
    for name, resource in RESOURCES.items():
        properties = resource["Properties"]
        if resource["Type"] == "AWS::IAM::Role":
            inline = sum(size(policy["PolicyDocument"]) for policy in properties.get("Policies", []))
            assert inline <= 10_240, (name, inline)
            assert len(properties.get("ManagedPolicyArns", [])) <= 10, name
        if resource["Type"] == "AWS::IAM::ManagedPolicy":
            assert size(properties["PolicyDocument"]) <= 6_144, (name, size(properties["PolicyDocument"]))


# The execution role's Allow resources that carry no project name, each because the
# resource's ID is generated or AWS's: everything else must name the project.
GENERATED_OR_AWS = {
    "arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:event-source-mapping:*",
    "arn:${AWS::Partition}:lambda:${AWS::Region}:${WebAdapterPublisherAccount}:layer:LambdaAdapterLayerArm64:*",
    "arn:${AWS::Partition}:cloudformation:${AWS::Region}:aws:transform/Serverless-2016-10-31",
    "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter/config/cognito/staff/*",
    "*",
}


def test_the_execution_role_reaches_only_project_names() -> None:
    for statement in allows("CloudFormationExecutionRole"):
        for resource in resources(statement):
            assert (
                f"{SLUG}-" in resource
                or f"{SLUG}/" in resource
                or "ArtifactsBucket" in resource
                or "${ProdDomainName}/apimappings" in resource
                or "${StageDomainName}/apimappings" in resource
                or "${StageApi}" in resource
                or "${ProdApi}" in resource
                or resource in GENERATED_OR_AWS
            ), (statement["Sid"], resource)


TEMPLATE_BYTES_LIMIT = 1_000_000  # CloudFormation's limit for a template uploaded to S3


def test_the_template_fits_cloudformations_s3_size_limit() -> None:
    # Over the 51,200-byte inline limit since decision 0005: an update uploads it to the
    # artifacts bucket (--s3-bucket, the runbook's "Later changes to the bootstrap
    # stack"). A rebuild from nothing uploads it to a bucket made by hand first.
    assert len((REPO / "infra" / "bootstrap.yaml").read_bytes()) < TEMPLATE_BYTES_LIMIT


def test_no_api_gateway_tagging_and_mapping_tags_only_with_the_five() -> None:
    # API IDs are generated: a tagging right on any API would let the role give another
    # project's untagged API this Project tag, and then change it. Only the stages of
    # the bootstrap's two APIs may be tagged, and only with this Project (0005).
    for statement in allows("CloudFormationExecutionRole"):
        for resource in resources(statement):
            assert "/tags/" not in resource, statement["Sid"]
        if "apigateway:TagResource" in actions(statement):
            assert statement["Sid"] == "StageTagsById", statement["Sid"]
    stage_tags = EXEC["StageTagsById"]
    assert actions(stage_tags) == ["apigateway:TagResource"]
    apis = "arn:${AWS::Partition}:apigateway:${AWS::Region}::/apis/"
    assert resources(stage_tags) == [
        f"{apis}${{{api}}}/stages{rest}" for api in ("StageApi", "ProdApi") for rest in ("", "/*")
    ]
    assert stage_tags["Condition"] == {"StringEquals": {"aws:RequestTag/Project": {"Ref": "ProjectSlug"}}}
    tagging = EXEC["TagOnCreate"]
    assert not any(action.startswith("apigateway:") for action in actions(tagging))
    assert not any("event-source-mapping" in resource for resource in resources(tagging))
    # Lambda authorizes a mapping's tags in CreateEventSourceMapping as
    # lambda:TagResource. No key limits it to the create call: the fence is that only
    # CloudFormation assumes the role and the deploy roles may not import.
    mapping_tags = EXEC["TagEventSourceMappingsOnCreate"]
    assert actions(mapping_tags) == ["lambda:TagResource"]
    assert resources(mapping_tags) == [
        "arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:event-source-mapping:*"
    ]
    assert mapping_tags["Condition"] == {
        "StringEquals": {"aws:RequestTag/Project": {"Ref": "ProjectSlug"}},
        "Null": {f"aws:RequestTag/{key}": "false" for key in TAG_CREATE_KEYS},
    }
    for role in DEPLOY_ROLES:
        assert by_sid(role)["NoResourceImport"]["Effect"] == "Deny"
    # API Gateway: only the bootstrap's two APIs and their sub-resources, by ID, and
    # the two addresses' mappings; the APIs themselves are only read.
    apis = "arn:${AWS::Partition}:apigateway:${AWS::Region}::/apis/"
    for statement in allows("CloudFormationExecutionRole"):
        for resource in resources(statement):
            if resource.startswith(apis) and statement["Sid"] != "StageTagsById":
                assert statement["Sid"] == "ApisById", statement["Sid"]
                assert re.fullmatch(r"\$\{(Stage|Prod)Api\}(/\*)?", resource[len(apis) :]), resource
    read_only = EXEC["TheApisAreReadOnly"]
    assert (read_only["Effect"], read_only["NotAction"]) == ("Deny", "apigateway:GET")
    assert resources(read_only) == [apis + "${StageApi}", apis + "${ProdApi}"]


def test_by_name_reads_and_deletes_only() -> None:
    verbs = re.compile(r":(Get|List|Describe|Delete|Detach)")
    for sid in ("ReadAndDeleteByName", "ReadAndDeleteRolesByName"):
        assert all(verbs.search(action) for action in actions(EXEC[sid])), sid
        assert "Condition" not in EXEC[sid]
    roles = f"arn:${{AWS::Partition}}:iam::${{AWS::AccountId}}:role/{SLUG}-app/{SLUG}-*"
    assert resources(EXEC["ReadAndDeleteRolesByName"]) == [roles]


def test_event_source_mappings_only_when_tagged_and_feeding_this_projects_functions() -> None:
    functions = f"arn:${{AWS::Partition}}:lambda:${{AWS::Region}}:${{AWS::AccountId}}:function:{SLUG}-*"
    mappings = "arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:event-source-mapping:*"
    own = EXEC["OwnEventSourceMappings"]
    assert actions(own) == [
        "lambda:GetEventSourceMapping",
        "lambda:UpdateEventSourceMapping",
        "lambda:DeleteEventSourceMapping",
    ]
    assert resources(own) == [mappings]
    assert sub(own["Condition"]["ArnLike"]["lambda:FunctionArn"]) == functions
    assert own["Condition"]["StringEquals"] == {"aws:ResourceTag/Project": {"Ref": "ProjectSlug"}}
    tags = EXEC["OwnEventSourceMappingTags"]
    assert actions(tags) == ["lambda:ListTags"]
    for sid, statement in EXEC.items():
        if statement["Effect"] == "Allow" and mappings in resources(statement):
            assert sid in {
                "OwnEventSourceMappings",
                "OwnEventSourceMappingTags",
                "TagEventSourceMappingsOnCreate",
            }, sid


def test_only_api_gateway_may_be_given_invoke_permission() -> None:
    permission = EXEC["InvokePermissionsForApiGatewayOnly"]
    assert actions(permission) == ["lambda:AddPermission", "lambda:RemovePermission"]
    assert permission["Condition"] == {
        "StringEquals": {
            "lambda:Principal": "apigateway.amazonaws.com",
            "aws:ResourceTag/Project": {"Ref": "ProjectSlug"},
        }
    }
    for sid, statement in EXEC.items():
        if statement["Effect"] == "Allow" and set(actions(statement)) & {
            "lambda:AddPermission",
            "lambda:RemovePermission",
        }:
            assert sid == "InvokePermissionsForApiGatewayOnly", sid


def test_bucket_tagging_is_by_name_and_no_account_log_policy() -> None:
    assert "s3:PutBucketTagging" in actions(EXEC["PhotoBucketsByName"])
    assert "s3:PutBucketTagging" not in actions(EXEC["TagOnCreate"])
    # No condition key sees a public access block's settings: the role never removes
    # one (DeletePublicAccessBlock is authorized as s3:PutBucketPublicAccessBlock,
    # which phase 7's template test pins on), and it has no account-level S3 right.
    for statement in allows("CloudFormationExecutionRole"):
        assert not any(action.startswith(("s3:PutAccount", "s3control:")) for action in actions(statement))
        assert "logs:PutResourcePolicy" not in actions(statement), statement["Sid"]
        assert "logs:DeleteResourcePolicy" not in actions(statement), statement["Sid"]
    deny = EXEC["NoAccountLogPolicies"]
    assert deny["Effect"] == "Deny"
    assert actions(deny) == ["logs:PutResourcePolicy", "logs:DeleteResourcePolicy"]
    assert deny["Resource"] == "*"


def test_the_log_delivery_policy_is_this_projects_own_and_the_role_writes_none() -> None:
    # HTTP API access logs need a policy letting log delivery write the group. The
    # bootstrap owns it, under its own name, so the execution role needs no
    # logs:PutResourcePolicy, which no resource or key could fence (decision 0003).
    policy = RESOURCES["LogDeliveryPolicy"]
    assert policy["Type"] == "AWS::Logs::ResourcePolicy"
    properties = policy["Properties"]
    assert set(properties) == {"PolicyName", "PolicyDocument"}  # account scope, by its name
    assert sub(properties["PolicyName"]) == f"{SLUG}-log-delivery"
    document = json.loads(sub(properties["PolicyDocument"]))
    [statement] = document["Statement"]
    assert statement["Effect"] == "Allow"
    assert statement["Principal"] == {"Service": "delivery.logs.amazonaws.com"}
    assert statement["Action"] == ["logs:CreateLogStream", "logs:PutLogEvents"]
    assert statement["Resource"] == [
        f"arn:${{AWS::Partition}}:logs:${{AWS::Region}}:${{AWS::AccountId}}:log-group:/aws/apigateway/{SLUG}-*:log-stream:*"
    ]
    assert statement["Condition"] == {
        "StringEquals": {"aws:SourceAccount": "${AWS::AccountId}"},
        "ArnLike": {"aws:SourceArn": "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:*"},
    }
    assert EXEC["NoAccountLogPolicies"]["Effect"] == "Deny"


def test_the_environment_tag_is_prod_unless_claude_md_is_amended() -> None:
    parameter = TEMPLATE["Parameters"]["EnvironmentTag"]
    assert parameter["Default"] == "prod"
    assert parameter["AllowedValues"] == ["prod", "shared"]

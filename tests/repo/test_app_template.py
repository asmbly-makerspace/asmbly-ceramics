"""`infra/app.yaml`, pinned where no IAM condition can see it.

The bootstrap's execution role changes the photo bucket by name and creates function
roles whose trust policies and statements no condition key sees (decision 0003), so
these tests are the fence: the bucket stays private, the roles trust only Lambda (or
phase 9's scheduler), each function's role holds only what its use cases call, and the
names, retention and alarms are what the plan says.
"""

import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest

from asmbly_ceramics.adapters.aws import keys
from asmbly_ceramics.adapters.aws.ids import DROP_OFF_COUNTER
from asmbly_ceramics.adapters.aws.photos import KEPT_PREFIX, UPLOADS_PREFIX
from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus, claim, new_email
from asmbly_ceramics.domain.ids import DropOffId, LoadId
from asmbly_ceramics.use_cases.emails import EMAIL_FAILED
from tests.repo.cloudformation import load_template
from tests.repo.files import REPO
from tests.use_cases.conftest import World
from tests.use_cases.conftest import world as world  # the fakes, for the apps' routes

PATH = REPO / "infra" / "app.yaml"
TEXT = PATH.read_text()
TEMPLATE = load_template(PATH)
RESOURCES: dict[str, Any] = TEMPLATE["Resources"]
GLOBALS: dict[str, Any] = TEMPLATE["Globals"]["Function"]
FUNCTIONS = {name: r for name, r in RESOURCES.items() if r["Type"] == "AWS::Serverless::Function"}
ALARMS = {name: r for name, r in RESOURCES.items() if r["Type"] == "AWS::CloudWatch::Alarm"}
TAGS = {"Project", "Component", "Environment", "Owner", "ManagedBy"}

# What the template names, taken from the code that writes it, so a rename in the code
# fails here instead of silently stopping an IAM grant, the mailer's stream or an alarm.
_ID = DropOffId.parse("AC-1")


def _partition_prefix(made: dict[str, Any], variable: str) -> str:
    """`DROPOFF#AC-1` with `AC-1` as the variable part -> `DROPOFF#*`."""
    pk: str = made["PK"]["S"]
    assert pk.endswith(variable), pk
    return pk.removesuffix(variable) + "*"


DROP_OFFS = _partition_prefix(keys.drop_off_key(_ID), str(_ID))
EMAILS = _partition_prefix(keys.email_key(_ID, EmailKind.RECEIVED), str(_ID))
SUBMISSIONS = _partition_prefix(keys.submission_key("x"), "x")
RATES = _partition_prefix(keys.rate_key("x"), "x")
STUDIO = keys.studio_key()["PK"]["S"]
DROP_OFF_COUNTER_PK = keys.counter_key(DROP_OFF_COUNTER)["PK"]["S"]
UPLOADS = f"{UPLOADS_PREFIX}*"
KEPT = f"{KEPT_PREFIX}*"


def sub(value: Any) -> str:
    """The text of a `!Sub` (or a plain string)."""
    if isinstance(value, dict) and "Fn::Sub" in value:
        text = value["Fn::Sub"]
        assert isinstance(text, str)
        return text
    assert isinstance(value, str), value
    return value


def statements(function: str) -> dict[str, dict[str, Any]]:
    [policy] = FUNCTIONS[function]["Properties"]["Policies"]
    return {statement["Sid"]: statement for statement in policy["Statement"]}


def actions(statement: dict[str, Any]) -> list[str]:
    action = statement["Action"]
    return [action] if isinstance(action, str) else list(action)


def resources(statement: dict[str, Any]) -> list[Any]:
    resource = statement["Resource"]
    return resource if isinstance(resource, list) else [resource]


def leading_keys(statement: dict[str, Any]) -> list[str]:
    keys: list[str] = statement["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"]
    return keys


def granted(function: str, action: str) -> list[dict[str, Any]]:
    return [s for s in statements(function).values() if s["Effect"] == "Allow" and action in actions(s)]


TABLE = {"Fn::GetAtt": ["RecordsTable", "Arn"]}
BUCKET = {"Fn::GetAtt": ["PhotoBucket", "Arn"]}


# Names, tags, retention ---------------------------------------------------------------


def test_every_name_starts_with_the_project_slug() -> None:
    named = {
        "FunctionName": "${ProjectSlug}-${AppEnv}-",
        "TableName": "${ProjectSlug}-${AppEnv}-",
        "BucketName": "${ProjectSlug}-${AppEnv}-",
        "QueueName": "${ProjectSlug}-${AppEnv}-",
        "TopicName": "${ProjectSlug}-${AppEnv}-",
        "AlarmName": "${ProjectSlug}-${AppEnv}-",
        "Name": "${ProjectSlug}-${AppEnv}",
    }
    seen = 0
    for name, resource in RESOURCES.items():
        for key, prefix in named.items():
            value = resource.get("Properties", {}).get(key)
            if value is not None and not (isinstance(value, dict) and "Ref" in value):  # a Ref names our own
                assert sub(resource["Properties"][key]).startswith(prefix), name
                seen += 1
        if resource["Type"] == "AWS::Logs::LogGroup":
            assert re.match(
                r"^/aws/(lambda|apigateway)/\$\{ProjectSlug\}-\$\{AppEnv\}",
                sub(resource["Properties"]["LogGroupName"]),
            )
            assert resource["Properties"]["RetentionInDays"] == {"Fn::If": ["IsProd", 90, 14]}
    assert seen >= 11
    assert TEMPLATE["Parameters"]["ProjectSlug"]["AllowedPattern"] == "^asmbly-ceramics$"


def test_tags_are_sent_in_each_create_request() -> None:
    assert GLOBALS["PropagateTags"] is True
    assert set(GLOBALS["Tags"]) == TAGS  # copied to each function's role and mapping
    assert set(RESOURCES["HttpApiStage"]["Properties"]["Tags"]) == TAGS
    for name, alarm in ALARMS.items():
        assert {tag["Key"] for tag in alarm["Properties"]["Tags"]} == TAGS, name
    samconfig = (REPO / "samconfig.toml").read_text()
    for env in ("stage", "prod"):
        assert (
            f'tags = "Project=asmbly-ceramics Component=App Environment={env} '
            'Owner=it-volunteers ManagedBy=sam"' in samconfig
        )


def test_the_table_and_the_bucket_are_kept_and_the_table_is_recoverable() -> None:
    for name in ("RecordsTable", "PhotoBucket"):
        assert RESOURCES[name]["DeletionPolicy"] == "Retain", name
        assert RESOURCES[name]["UpdateReplacePolicy"] == "Retain", name
    table = RESOURCES["RecordsTable"]["Properties"]
    assert sub(table["TableName"]) == "${ProjectSlug}-${AppEnv}-records"
    assert table["BillingMode"] == "PAY_PER_REQUEST"
    assert table["KeySchema"] == [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ]
    assert {d["AttributeName"]: d["AttributeType"] for d in table["AttributeDefinitions"]} == dict.fromkeys(
        ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"), "S"
    )
    assert [(i["IndexName"], i["Projection"]) for i in table["GlobalSecondaryIndexes"]] == [
        ("GSI1", {"ProjectionType": "ALL"}),
        ("GSI2", {"ProjectionType": "ALL"}),
    ]
    assert table["PointInTimeRecoverySpecification"] == {
        "PointInTimeRecoveryEnabled": True,
        "RecoveryPeriodInDays": 7,
    }
    assert table["DeletionProtectionEnabled"] is True
    assert table["TimeToLiveSpecification"] == {"AttributeName": "ttl", "Enabled": True}
    assert table["StreamSpecification"] == {"StreamViewType": "NEW_IMAGE"}


# The photo bucket ------------------------------------------------------------------------


def test_the_bucket_is_named_without_the_account_id_and_never_versioned() -> None:
    bucket = RESOURCES["PhotoBucket"]["Properties"]
    assert sub(bucket["BucketName"]) == "${ProjectSlug}-${AppEnv}-photos-${PhotoBucketSuffix}"
    assert "AccountId" not in str(bucket["BucketName"])
    # delete_drop_off deletes without version IDs: versions would outlive the close (#7).
    assert "VersioningConfiguration" not in bucket
    assert TEMPLATE["Parameters"]["PhotoBucketSuffix"]["AllowedPattern"] == "^[a-z0-9]{8}$"


def test_the_bucket_blocks_all_public_access_and_allows_only_posts_from_the_site() -> None:
    bucket = RESOURCES["PhotoBucket"]["Properties"]
    assert bucket["PublicAccessBlockConfiguration"] == dict.fromkeys(
        ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"), True
    )
    assert bucket["OwnershipControls"] == {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
    assert bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"] == [
        {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
    ]
    rules = {rule["Id"]: rule for rule in bucket["LifecycleConfiguration"]["Rules"]}
    assert rules["expire-uploads"] == {
        "Id": "expire-uploads",
        "Status": "Enabled",
        "Prefix": UPLOADS_PREFIX,
        "ExpirationInDays": 1,
    }
    [cors] = bucket["CorsConfiguration"]["CorsRules"]
    assert cors["AllowedMethods"] == ["POST"]
    assert [sub(origin) for origin in cors["AllowedOrigins"]] == ["https://${SiteHost}"]


def test_the_bucket_policy_only_denies_requests_without_tls() -> None:
    policy = RESOURCES["PhotoBucketPolicy"]["Properties"]
    assert policy["Bucket"] == {"Ref": "PhotoBucket"}
    [statement] = policy["PolicyDocument"]["Statement"]
    assert statement["Effect"] == "Deny"
    assert statement["Principal"] == "*"
    assert statement["Action"] == "s3:*"
    assert statement["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
    assert "Allow" not in str(policy)


# The HTTP API --------------------------------------------------------------------------


def test_the_api_is_plain_cloudformation_with_no_body_and_no_sam_events() -> None:
    assert not [r for r in RESOURCES.values() if r["Type"] == "AWS::Serverless::HttpApi"]
    for name, function in FUNCTIONS.items():
        for event in function["Properties"].get("Events", {}).values():
            assert event["Type"] not in ("HttpApi", "Api"), name
    # The API itself is the bootstrap's (decision 0005); this stack adds to it by its ID.
    assert not [r for r in RESOURCES.values() if r["Type"] == "AWS::ApiGatewayV2::Api"]
    api_id = {"Fn::ImportValue": {"Fn::Sub": "${ProjectSlug}-${AppEnv}-api-id"}}
    for name, resource in RESOURCES.items():
        if resource["Type"].startswith("AWS::ApiGatewayV2::"):
            assert resource["Properties"]["ApiId"] == api_id, name
    assert not [r for r in RESOURCES.values() if r["Type"] == "AWS::Logs::ResourcePolicy"]
    mapping = RESOURCES["HttpApiMapping"]["Properties"]
    assert mapping["DomainName"] == {"Fn::ImportValue": {"Fn::Sub": "${ProjectSlug}-${AppEnv}-domain-name"}}


def test_every_invoke_permission_is_for_api_gateway_on_this_api_only() -> None:
    permissions = [r for r in RESOURCES.values() if r["Type"] == "AWS::Lambda::Permission"]
    assert permissions
    for permission in permissions:
        properties = permission["Properties"]
        assert properties["Principal"] == "apigateway.amazonaws.com"
        assert properties["Action"] == "lambda:InvokeFunction"
        assert properties["SourceArn"] == {
            "Fn::Sub": [
                "arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${ApiId}/*",
                {"ApiId": {"Fn::ImportValue": {"Fn::Sub": "${ProjectSlug}-${AppEnv}-api-id"}}},
            ]
        }


def test_access_logs_hold_no_address_agent_or_query() -> None:
    stage = RESOURCES["HttpApiStage"]["Properties"]
    log_format = stage["AccessLogSettings"]["Format"]
    for field in ("requestId", "routeKey", "status", "responseLength", "integrationLatency"):
        assert f"$context.{field}" in log_format
    for leak in ("sourceIp", "userAgent", "identity", "path", "querystring", "authorizer"):
        assert leak not in log_format
    assert stage["DefaultRouteSettings"] == {"ThrottlingBurstLimit": 20, "ThrottlingRateLimit": 5}


# The roles -------------------------------------------------------------------------------


def test_every_function_has_its_environment_s_boundary_a_path_and_its_own_log_group() -> None:
    assert GLOBALS["PermissionsBoundary"] == {
        "Fn::ImportValue": {"Fn::Sub": "${ProjectSlug}-${AppEnv}-function-boundary-arn"}
    }
    assert GLOBALS["RolePath"] == "/asmbly-ceramics-app/"
    assert set(FUNCTIONS) == {"FormFunction", "MailerFunction", "ConsoleFunction", "CloseFunction"}
    for name, function in FUNCTIONS.items():
        properties = function["Properties"]
        for override in ("PermissionsBoundary", "RolePath", "Role", "AssumeRolePolicyDocument"):
            assert override not in properties, f"{name} overrides {override}"
        group = properties["LoggingConfig"]["LogGroup"]["Ref"]
        assert RESOURCES[group]["Type"] == "AWS::Logs::LogGroup"


def test_every_role_trusts_only_lambda_or_the_scheduler() -> None:
    # SAM makes each function's role trusting lambda.amazonaws.com; a role written here
    # (phase 9's scheduler role) may trust only the scheduler.
    for name, resource in RESOURCES.items():
        if resource["Type"] == "AWS::IAM::Role":
            for statement in resource["Properties"]["AssumeRolePolicyDocument"]["Statement"]:
                assert statement["Principal"] in (
                    {"Service": "lambda.amazonaws.com"},
                    {"Service": "scheduler.amazonaws.com"},
                ), name


def test_no_statement_is_broad() -> None:
    for function in FUNCTIONS:
        for sid, statement in statements(function).items():
            assert statement["Effect"] == "Allow", sid
            assert "*" not in resources(statement), f"{function}.{sid}"
            for action in actions(statement):
                assert not action.endswith(":*"), f"{function}.{sid}"
                assert not action.startswith(("iam:", "sts:", "kms:")), f"{function}.{sid}"
                assert action != "dynamodb:TransactWriteItems", (
                    "not an IAM action: items are authorized one by one"
                )


def test_the_form_can_t_read_kept_photos_drop_offs_or_the_console_s_key() -> None:
    form = statements("FormFunction")
    for statement in form.values():
        for action in actions(statement):
            assert action not in (
                "dynamodb:Scan",
                "dynamodb:Query",
                "dynamodb:DeleteItem",
                "dynamodb:ConditionCheckItem",
            )
            assert not action.startswith(("ses:", "sqs:", "sns:"))
    for statement in granted("FormFunction", "s3:GetObject"):
        assert [sub(r) for r in resources(statement)] == ["${PhotoBucket.Arn}/" + UPLOADS]
    [listing] = granted("FormFunction", "s3:ListBucket")
    assert listing["Condition"] == {"StringLike": {"s3:prefix": UPLOADS}}
    for statement in granted("FormFunction", "dynamodb:GetItem"):
        assert set(leading_keys(statement)) <= {STUDIO, SUBMISSIONS, RATES}
    keys = [sub(r) for r in resources(form["ReadOwnKeys"])]
    assert [key.rsplit("/", 1)[1] for key in keys] == ["hash-key", "form-key"]
    assert all("${ProjectSlug}/${AppEnv}/" in key for key in keys)
    assert "session-key" not in str(form)


def test_the_form_writes_only_new_drop_offs_ids_rates_and_its_cleanup() -> None:
    puts = granted("FormFunction", "dynamodb:PutItem")
    assert sorted(k for s in puts for k in leading_keys(s)) == sorted(
        [DROP_OFFS, EMAILS, SUBMISSIONS, STUDIO, RATES]
    )
    for statement in puts + granted("MailerFunction", "dynamodb:PutItem"):
        # A put never returns the item it replaces (or met in a failed condition).
        assert statement["Condition"]["StringEqualsIfExists"] == {"dynamodb:ReturnValues": "NONE"}
    # Drop-offs, emails, submissions and the studio only through the commit's transaction.
    for statement in [
        statements("FormFunction")["CreateDropOffs"],
        statements("MailerFunction")["MarkEmails"],
    ]:
        assert statement["Condition"]["ForAnyValue:StringEquals"] == {
            "dynamodb:EnclosingOperation": ["TransactWriteItems"]
        }
    [update] = granted("FormFunction", "dynamodb:UpdateItem")
    assert leading_keys(update) == [DROP_OFF_COUNTER_PK]
    kept = statements("FormFunction")["KeepPhotos"]
    assert sorted(actions(kept)) == ["s3:DeleteObject", "s3:PutObject"]  # decision 0004
    assert sub(kept["Resource"]) == "${PhotoBucket.Arn}/" + KEPT


def test_the_mailer_reads_what_an_email_needs_and_writes_only_emails() -> None:
    mailer = statements("MailerFunction")
    [get] = granted("MailerFunction", "dynamodb:GetItem")
    assert sorted(leading_keys(get)) == sorted([DROP_OFFS, EMAILS, STUDIO])
    [put] = granted("MailerFunction", "dynamodb:PutItem")
    assert leading_keys(put) == [EMAILS]
    assert not granted("MailerFunction", "dynamodb:UpdateItem")
    assert not granted("MailerFunction", "s3:PutObject")
    assert not granted("MailerFunction", "s3:DeleteObject")
    assert not granted("MailerFunction", "ssm:GetParameter")
    [listing] = granted("MailerFunction", "s3:ListBucket")
    assert listing["Condition"] == {"StringLike": {"s3:prefix": KEPT}}
    [read] = granted("MailerFunction", "s3:GetObject")
    assert sub(read["Resource"]) == "${PhotoBucket.Arn}/" + KEPT
    stream = mailer["ReadTheStream"]
    assert stream["Resource"] == {"Fn::GetAtt": ["RecordsTable", "StreamArn"]}
    assert mailer["DeadLetters"]["Resource"] == {"Fn::GetAtt": ["MailerDeadLetterQueue", "Arn"]}


def test_every_table_statement_is_on_the_table_and_scoped_by_its_keys() -> None:
    for function in FUNCTIONS:
        for sid, statement in statements(function).items():
            table_actions = {
                a
                for a in actions(statement)
                if a in ("dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem")
            }
            if table_actions:
                assert statement["Resource"] == TABLE, f"{function}.{sid}"
                assert leading_keys(statement), f"{function}.{sid}"


def test_ses_send_is_limited_to_the_asmbly_org_identity_and_from_address() -> None:
    # The mailer sends the outbox; the console sends only the test email (#6).
    assert not granted("FormFunction", "ses:SendEmail")
    assert not granted("CloseFunction", "ses:SendEmail")
    for function in ("MailerFunction", "ConsoleFunction"):
        [send] = granted(function, "ses:SendEmail")
        assert actions(send) == ["ses:SendEmail"], function
        assert [sub(r) for r in resources(send)] == [
            "arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/${EmailDomain}",
            "arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/*@${EmailDomain}",
        ], function
        assert send["Condition"] == {"StringLike": {"ses:FromAddress": {"Fn::Sub": "*@${EmailDomain}"}}}
    assert TEMPLATE["Parameters"]["EmailDomain"]["AllowedValues"] == ["asmbly.org"]


# The mailer's stream and the alarms ---------------------------------------------------------


def test_the_mailer_takes_only_pending_emails_with_bounded_retries() -> None:
    properties = FUNCTIONS["MailerFunction"]["Properties"]
    outbox = properties["Events"]["Outbox"]
    assert outbox["Type"] == "DynamoDB"
    stream = outbox["Properties"]
    assert stream["Stream"] == {"Fn::GetAtt": ["RecordsTable", "StreamArn"]}
    [pattern] = stream["FilterCriteria"]["Filters"]
    assert json.loads(pattern["Pattern"]) == {
        "dynamodb": {"NewImage": {"type": {"S": [keys.EMAIL]}, "status": {"S": [EmailStatus.PENDING]}}}
    }
    assert stream["StartingPosition"] == "TRIM_HORIZON"
    assert stream["BatchSize"] == 1
    assert stream["MaximumRetryAttempts"] == 3
    assert stream["FunctionResponseTypes"] == ["ReportBatchItemFailures"]
    assert stream["DestinationConfig"] == {
        "OnFailure": {"Type": "SQS", "Destination": {"Fn::GetAtt": ["MailerDeadLetterQueue", "Arn"]}}
    }
    assert properties["Handler"] == "asmbly_ceramics.entry.mailer.handler"
    assert properties["Timeout"] >= 10 * 18 + 30  # ten reads at their worst, then one send


def _matches(pattern: Any, event: Any) -> bool:
    """An event filter of exact values, as Lambda applies it: every key the pattern
    names is in the event, and each leaf list holds the event's value."""
    if isinstance(pattern, list):
        return event in pattern
    return isinstance(event, dict) and all(
        name in event and _matches(value, event[name]) for name, value in pattern.items()
    )


def test_a_new_email_item_is_what_the_mailer_s_stream_filter_lets_through() -> None:
    [pattern] = FUNCTIONS["MailerFunction"]["Properties"]["Events"]["Outbox"]["Properties"]["FilterCriteria"][
        "Filters"
    ]
    filter_ = json.loads(pattern["Pattern"])
    at = datetime(2026, 1, 5, 12, tzinfo=UTC)
    for kind in (EmailKind.RECEIVED, EmailKind.READY):
        email = new_email(_ID, kind, at)
        item = keys.to_item(email, keys.item_key(email), 1)
        assert _matches(filter_, {"dynamodb": {"NewImage": item}}), kind
        sending = claim(email, at)
        claimed = keys.to_item(sending, keys.item_key(sending), 2)
        assert not _matches(filter_, {"dynamodb": {"NewImage": claimed}}), kind
    drop_off_key = keys.drop_off_key(_ID)
    assert not _matches(filter_, {"dynamodb": {"NewImage": {**drop_off_key, "type": {"S": keys.DROP_OFF}}}})


def test_every_alarm_notifies_this_project_s_topic_and_ignores_missing_data() -> None:
    assert set(ALARMS) == {
        "EmailFailuresAlarm",
        "LoggedErrorsAlarm",
        "MailerDeadLettersAlarm",
        "FunctionErrorsAlarm",
        "Api5xxAlarm",
        "CloseErrorsAlarm",
        "CloseDeadLettersAlarm",
    }
    for name, alarm in ALARMS.items():
        properties = alarm["Properties"]
        assert properties["AlarmActions"] == [{"Ref": "AlarmTopic"}], name
        assert properties["OKActions"] == [{"Ref": "AlarmTopic"}], name
        assert properties["TreatMissingData"] == "notBreaching", name
    topic = RESOURCES["AlarmTopic"]["Properties"]
    assert "KmsMasterKeyId" not in topic
    assert RESOURCES["AlarmEmailSubscription"]["Properties"]["Endpoint"] == {"Ref": "AlertEmail"}
    assert not [
        r for r in RESOURCES.values() if r["Type"] in ("AWS::SNS::TopicPolicy", "AWS::SQS::QueuePolicy")
    ]


def test_every_alarm_has_a_row_in_the_operations_runbook() -> None:
    runbook = (REPO / "docs" / "runbooks" / "operations.md").read_text()
    section = runbook.split("## When an alarm fires\n", 1)[1].split("\n## ", 1)[0]
    rows = set(re.findall(r"^\| `([a-z0-9-]+)` \|", section, flags=re.MULTILINE))
    names = set()
    for alarm in ALARMS.values():
        name = sub(alarm["Properties"]["AlarmName"])
        assert name.startswith("${ProjectSlug}-${AppEnv}-"), name
        names.add(name.removeprefix("${ProjectSlug}-${AppEnv}-"))
    assert rows == names


def test_the_function_errors_alarm_counts_a_function_that_wasn_t_invoked_as_zero() -> None:
    [total] = [m for m in ALARMS["FunctionErrorsAlarm"]["Properties"]["Metrics"] if m.get("ReturnData")]
    assert total["Expression"] == "FILL(form, 0) + FILL(mailer, 0) + FILL(console, 0)"


def test_the_template_sets_exactly_the_variables_the_app_reads() -> None:
    settings = (REPO / "src" / "asmbly_ceramics" / "settings.py").read_text()
    read = set(re.findall(r'read\("([A-Z_]+)"\)', settings))
    app = (REPO / "src" / "asmbly_ceramics" / "web" / "app.py").read_text()
    read |= set(re.findall(r'os\.environ\.get\("([A-Z_]+)"', app))
    form = FUNCTIONS["FormFunction"]["Properties"]["Environment"]["Variables"]
    console = FUNCTIONS["ConsoleFunction"]["Properties"]["Environment"]["Variables"]
    staff = {"STAFF_ISSUER", "STAFF_SIGN_IN_URL", "STAFF_CLIENT_ID"}
    set_by_template = set(GLOBALS["Environment"]["Variables"]) | {"APP_ROLE"} | staff
    lambda_sets = {"AWS_REGION"}
    assert read == set_by_template | lambda_sets
    web = {"APP_ROLE", "AWS_LAMBDA_EXEC_WRAPPER", "PORT", "AWS_LWA_READINESS_CHECK_PATH"}
    assert set(form) == web
    assert set(console) == web | staff
    assert (form["APP_ROLE"], console["APP_ROLE"]) == ("form", "console")


def test_the_dead_letters_alarm_counts_each_new_dead_letter() -> None:
    properties = ALARMS["MailerDeadLettersAlarm"]["Properties"]
    assert (properties["MetricName"], properties["Statistic"], properties["Threshold"]) == (
        "NumberOfMessagesSent",
        "Sum",
        1,
    )


def test_the_email_failures_alarm_counts_the_email_failed_event() -> None:
    email = RESOURCES["EmailFailuresFilter"]["Properties"]
    assert email["LogGroupName"] == {"Ref": "MailerLogGroup"}
    assert email["FilterPattern"] == f'{{ $.event = "{EMAIL_FAILED}" }}'
    assert (
        email["MetricTransformations"][0]["MetricName"]
        == ALARMS["EmailFailuresAlarm"]["Properties"]["MetricName"]
    )
    for name in ("FormLoggedErrorsFilter", "MailerLoggedErrorsFilter", "ConsoleLoggedErrorsFilter"):
        assert (
            RESOURCES[name]["Properties"]["FilterPattern"]
            == f'{{ ($.level = "ERROR") && ($.event != "{EMAIL_FAILED}") }}'
        )
    dimensions = [
        metric["MetricStat"]["Metric"]["Dimensions"]
        for metric in ALARMS["FunctionErrorsAlarm"]["Properties"]["Metrics"]
        if "MetricStat" in metric
    ]
    assert dimensions == [
        [{"Name": "FunctionName", "Value": {"Ref": "FormFunction"}}],
        [{"Name": "FunctionName", "Value": {"Ref": "MailerFunction"}}],
        [{"Name": "FunctionName", "Value": {"Ref": "ConsoleFunction"}}],
    ]
    assert RESOURCES["ConsoleLoggedErrorsFilter"]["Properties"]["LogGroupName"] == {"Ref": "ConsoleLogGroup"}


# What the file may not hold --------------------------------------------------------------


def test_no_account_id_address_or_exported_output() -> None:
    assert not re.search(r"(?<![\w.])\d{12}(?![\w.])", TEXT), "an account ID"
    assert not re.search(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d+:", TEXT), (
        "an ARN built by hand with an account"
    )
    addresses = re.findall(r"[^\s'\"]*@[^\s'\"]*", TEXT)
    assert {address.rsplit("/", 1)[-1] for address in addresses} == {"*@${EmailDomain}"}, addresses
    for name, output in TEMPLATE["Outputs"].items():
        assert "Export" not in output, name
        assert "Arn" not in str(output["Value"]), name


@pytest.mark.parametrize("name", ["AlertEmail", "InitialSendingAddress"])
def test_the_addresses_are_ssm_parameters_resolved_by_cloudformation(name: str) -> None:
    assert TEMPLATE["Parameters"][name]["Type"] == "AWS::SSM::Parameter::Value<String>"
    samconfig = (REPO / "samconfig.toml").read_text()
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    for env in ("stage", "prod"):
        assert f"{name}=/asmbly-ceramics/{env}/{kebab}" in samconfig


# The console (phase 8) -------------------------------------------------------------------------

LOADS = _partition_prefix(keys.load_key(LoadId(1)), "L-1")
LOAD_COUNTER_PK = keys.counter_key("load")["PK"]["S"]


def test_the_console_reads_only_kept_photos_and_its_session_key() -> None:
    console = statements("ConsoleFunction")
    [read] = granted("ConsoleFunction", "s3:GetObject")
    assert sub(read["Resource"]) == "${PhotoBucket.Arn}/" + KEPT
    [listing] = granted("ConsoleFunction", "s3:ListBucket")
    assert listing["Condition"] == {"StringLike": {"s3:prefix": KEPT}}
    assert not granted("ConsoleFunction", "s3:PutObject")
    assert not granted("ConsoleFunction", "s3:DeleteObject")
    [key] = granted("ConsoleFunction", "ssm:GetParameter")
    assert [sub(r) for r in resources(key)] == [
        "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter/${ProjectSlug}/${AppEnv}/session-key"
    ]
    assert "hash-key" not in str(console)
    assert "form-key" not in str(console)
    [get] = granted("ConsoleFunction", "dynamodb:GetItem")
    assert sorted(leading_keys(get)) == sorted([DROP_OFFS, EMAILS, LOADS, STUDIO])
    table_query, index_query = granted("ConsoleFunction", "dynamodb:Query")
    assert table_query["Resource"] == TABLE
    # A drop-off's emails and the settings history: never SUBMISSION#, RATE# or COUNTER#.
    assert leading_keys(table_query) == [EMAILS, STUDIO]
    assert sub(index_query["Resource"]) == "${RecordsTable.Arn}/index/*"


def test_the_console_sends_only_the_test_email_and_nothing_else() -> None:
    for statement in statements("ConsoleFunction").values():
        for action in actions(statement):
            assert not action.startswith(("sqs:", "sns:", "lambda:", "iam:")), action
            assert not action.startswith("ses:") or action == "ses:SendEmail", action


def test_the_console_writes_with_put_item_only_and_updates_only_the_load_counter() -> None:
    every = [
        a for s in statements("ConsoleFunction").values() for a in actions(s) if a.startswith("dynamodb:")
    ]
    assert sorted(set(every)) == [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Query",
        "dynamodb:UpdateItem",
    ]
    for forbidden in ("dynamodb:ConditionCheckItem", "dynamodb:DeleteItem", "dynamodb:Scan"):
        assert forbidden not in every
    [update] = granted("ConsoleFunction", "dynamodb:UpdateItem")
    assert update["Resource"] == TABLE
    assert leading_keys(update) == [LOAD_COUNTER_PK]  # never the form's drop-off counter
    [put] = granted("ConsoleFunction", "dynamodb:PutItem")
    assert sorted(leading_keys(put)) == sorted([DROP_OFFS, EMAILS, LOADS, STUDIO])
    assert put["Condition"]["ForAnyValue:StringEquals"] == {
        "dynamodb:EnclosingOperation": ["TransactWriteItems"]
    }
    assert put["Condition"]["StringEqualsIfExists"] == {"dynamodb:ReturnValues": "NONE"}


def test_the_console_routes_go_to_the_console_function_only() -> None:
    routes = {
        r["Properties"]["RouteKey"]: r for r in RESOURCES.values() if r["Type"] == "AWS::ApiGatewayV2::Route"
    }
    photos = "GET /console/drop-offs/{id}/photos/{proxy+}"
    assert set(routes) == {"$default", "ANY /console", "ANY /console/{proxy+}", photos}
    for key in ("ANY /console", "ANY /console/{proxy+}", photos):
        assert sub(routes[key]["Properties"]["Target"]) == "integrations/${ConsoleIntegration}"
    assert sub(routes["$default"]["Properties"]["Target"]) == "integrations/${FormIntegration}"
    integration = RESOURCES["ConsoleIntegration"]["Properties"]
    assert integration["IntegrationUri"] == {"Fn::GetAtt": ["ConsoleFunction", "Arn"]}
    assert (integration["IntegrationType"], integration["PayloadFormatVersion"]) == ("AWS_PROXY", "2.0")
    assert RESOURCES["ConsoleInvokePermission"]["Properties"]["FunctionName"] == {"Ref": "ConsoleFunction"}
    properties = FUNCTIONS["ConsoleFunction"]["Properties"]
    assert properties["Handler"] == "asmbly_ceramics/entry/run.sh"
    assert properties["ReservedConcurrentExecutions"] == 25
    assert properties["Timeout"] == 29
    stage = RESOURCES["HttpApiStage"]
    assert set(stage["DependsOn"]) == {"ConsoleRoute", "ConsoleProxyRoute", "ConsolePhotosRoute"}
    assert stage["Properties"]["RouteSettings"] == {
        "ANY /console/{proxy+}": {"ThrottlingBurstLimit": 40, "ThrottlingRateLimit": 10},
        photos: {"ThrottlingBurstLimit": 100, "ThrottlingRateLimit": 30},
    }


def test_every_console_path_reaches_the_console_function_and_no_form_path_does(world: World) -> None:
    """The console's pages, its health check and its stylesheet all go to its function, so
    it keeps working while the form's function is offline (reserved concurrency 0)."""
    from starlette.routing import Mount, Route

    from asmbly_ceramics.web.app import create_app
    from tests.web.conftest import services, settings
    from tests.web.console.conftest import console_services, console_settings

    def paths(app: Any) -> set[str]:
        return {r.path for r in app.routes if isinstance(r, (Route, Mount))}

    console = paths(create_app(None, console_settings(world), console_services(world)))
    form = paths(create_app(services(world), settings()))
    assert {"/console/health", "/console/static"} <= console
    for path in console - {"/health", "/static"}:
        assert path == "/console" or path.startswith("/console/"), path
    for path in form:
        assert not path.startswith("/console"), path


def test_the_staff_sign_in_values_come_from_parameter_store() -> None:
    expected = {
        "StaffIssuer": "/config/cognito/staff/issuer",
        "StaffSignInUrl": "/config/cognito/staff/sign-in-url",
        "StaffClientId": "/config/cognito/staff/ceramics-staff-app-client-id",
    }
    variables = FUNCTIONS["ConsoleFunction"]["Properties"]["Environment"]["Variables"]
    for name, default in expected.items():
        parameter = TEMPLATE["Parameters"][name]
        assert (parameter["Type"], parameter["Default"]) == ("AWS::SSM::Parameter::Value<String>", default)
    assert variables["STAFF_ISSUER"] == {"Ref": "StaffIssuer"}
    assert variables["STAFF_SIGN_IN_URL"] == {"Ref": "StaffSignInUrl"}
    assert variables["STAFF_CLIENT_ID"] == {"Ref": "StaffClientId"}
    # One pool serves stage and prod: no environment overrides them.
    assert "Staff" not in (REPO / "samconfig.toml").read_text()


# The daily close (#7) ---------------------------------------------------------------------


def test_the_close_schedule_runs_daily_in_austin_time_with_a_dead_letter_queue() -> None:
    schedule = RESOURCES["CloseSchedule"]["Properties"]
    assert schedule["ScheduleExpression"] == "cron(17 3 * * ? *)"
    assert schedule["ScheduleExpressionTimezone"] == "America/Chicago"
    assert schedule["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert schedule["State"] == "ENABLED"
    target = schedule["Target"]
    assert target["Arn"] == {"Fn::GetAtt": ["CloseFunction", "Arn"]}
    assert target["RoleArn"] == {"Fn::GetAtt": ["CloseSchedulerRole", "Arn"]}
    assert target["Input"] == "{}"
    retry = target["RetryPolicy"]
    assert 0 <= retry["MaximumRetryAttempts"] <= 185
    assert 60 <= retry["MaximumEventAgeInSeconds"] <= 3600  # a retry stays inside the night
    assert target["DeadLetterConfig"] == {"Arn": {"Fn::GetAtt": ["CloseDeadLetterQueue", "Arn"]}}
    queue = RESOURCES["CloseDeadLetterQueue"]["Properties"]
    assert queue["SqsManagedSseEnabled"] is True


def test_the_close_function_has_a_dead_letter_queue_for_failed_runs() -> None:
    # The scheduler invokes Lambda asynchronously: a run that raises is retried by Lambda
    # and then lands here, not in the schedule's own dead-letter config.
    close = FUNCTIONS["CloseFunction"]["Properties"]
    assert close["Handler"] == "asmbly_ceramics.entry.close.handler"
    assert close["DeadLetterQueue"] == {
        "Type": "SQS",
        "TargetArn": {"Fn::GetAtt": ["CloseDeadLetterQueue", "Arn"]},
    }
    assert close["ReservedConcurrentExecutions"] == 1
    assert "Events" not in close  # only the schedule runs it; no API route reaches it
    errors = ALARMS["CloseErrorsAlarm"]["Properties"]
    assert errors["Dimensions"] == [{"Name": "FunctionName", "Value": {"Ref": "CloseFunction"}}]
    dead = ALARMS["CloseDeadLettersAlarm"]["Properties"]
    assert (dead["MetricName"], dead["Statistic"], dead["Threshold"]) == ("NumberOfMessagesSent", "Sum", 1)
    assert dead["Dimensions"] == [
        {"Name": "QueueName", "Value": {"Fn::GetAtt": ["CloseDeadLetterQueue", "QueueName"]}}
    ]


def test_the_scheduler_role_invokes_only_the_close_function() -> None:
    role = RESOURCES["CloseSchedulerRole"]["Properties"]
    assert "RoleName" not in role  # CAPABILITY_IAM: the stack names it, under the prefix
    assert role["Path"] == "/asmbly-ceramics-app/"
    assert role["PermissionsBoundary"] == GLOBALS["PermissionsBoundary"]
    assert {tag["Key"] for tag in role["Tags"]} == TAGS
    [trust] = role["AssumeRolePolicyDocument"]["Statement"]
    assert trust["Principal"] == {"Service": "scheduler.amazonaws.com"}
    condition = trust["Condition"]["StringEquals"]
    assert condition["aws:SourceAccount"] == {"Ref": "AWS::AccountId"}
    # A schedule group, as AWS requires: a schedule's own ARN would refuse every invoke.
    assert sub(condition["aws:SourceArn"]) == (
        "arn:${AWS::Partition}:scheduler:${AWS::Region}:${AWS::AccountId}:schedule-group/default"
    )
    [policy] = role["Policies"]
    granted_here = {
        statement["Action"]: statement["Resource"] for statement in policy["PolicyDocument"]["Statement"]
    }
    assert granted_here == {
        "lambda:InvokeFunction": {"Fn::GetAtt": ["CloseFunction", "Arn"]},
        "sqs:SendMessage": {"Fn::GetAtt": ["CloseDeadLetterQueue", "Arn"]},
    }


def test_the_close_role_deletes_only_kept_photos_and_cannot_read_them() -> None:
    [delete] = granted("CloseFunction", "s3:DeleteObject")
    assert sub(delete["Resource"]) == "${PhotoBucket.Arn}/" + KEPT
    for action in ("s3:GetObject", "s3:PutObject", "s3:ListBucket", "ssm:GetParameter", "ses:SendEmail"):
        assert not granted("CloseFunction", action), action


def test_the_close_role_writes_with_put_item_only() -> None:
    every = {a for s in statements("CloseFunction").values() for a in actions(s) if a.startswith("dynamodb:")}
    assert every == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"}
    [get] = granted("CloseFunction", "dynamodb:GetItem")
    assert sorted(leading_keys(get)) == sorted([DROP_OFFS, EMAILS, STUDIO])
    [put] = granted("CloseFunction", "dynamodb:PutItem")
    assert leading_keys(put) == [DROP_OFFS]
    assert put["Condition"]["ForAnyValue:StringEquals"] == {
        "dynamodb:EnclosingOperation": ["TransactWriteItems"]
    }
    assert put["Condition"]["StringEqualsIfExists"] == {"dynamodb:ReturnValues": "NONE"}
    [dead] = granted("CloseFunction", "sqs:SendMessage")
    assert dead["Resource"] == {"Fn::GetAtt": ["CloseDeadLetterQueue", "Arn"]}


def test_the_close_role_queries_only_gsi1_s_fired_and_rejected_partitions() -> None:
    """Never the waiting drop-offs' details, nor the emails' GSI2: the partitions are
    the ones `drop_offs_in` asks for, from the code's own key function."""
    [query] = granted("CloseFunction", "dynamodb:Query")
    assert sub(query["Resource"]) == "${RecordsTable.Arn}/index/" + keys.GSI1
    partitions = sorted(keys.drop_off_partition(s) for s in (DropOffState.FIRED, DropOffState.REJECTED))
    assert query["Condition"] == {
        "ForAllValues:StringEquals": {"dynamodb:LeadingKeys": partitions},
        "Null": {"dynamodb:LeadingKeys": "false"},
    }

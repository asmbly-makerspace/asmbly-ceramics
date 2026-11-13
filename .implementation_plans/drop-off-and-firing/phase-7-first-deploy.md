---
phase_id: 7
title: "First deploy: stage and prod"
epic: 1
implements: [2, 4]
depends_on: [4, 5, 6]
domain: [infra, ci]
estimated_size: L
---

# Phase 7: First deploy: stage and prod

> **Status:** [ ] Pending

## Required reading

- [CLAUDE.md](../../CLAUDE.md): names, tags, private photos, email, "a pull request
  from a fork is untrusted code", and what is never logged.
- [The plan's README](README.md) and
  [decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md).
- [Phase 4](phase-4-aws-adapters.md): the table's keys and indexes, the adapters' AWS
  calls and the rights each needs. [Phase 5](phase-5-aws-bootstrap.md): the bootstrap's
  exports, the execution role's rights and the boundary. [Phase 6](phase-6-drop-off-form.md):
  `create_app`, the routes, the S3 CORS rule.
- [Phase 3](phase-3-load-and-studio-use-cases.md): `SendPendingEmail` and the
  `email_failed` log line the alarm counts.
- The closest example: AsmblyMCPs' `infra/server.yaml` (a function behind an HTTP API
  through the Lambda Web Adapter, its log groups, alarms and metric filters),
  `samconfig.toml`, `scripts/sam_parameters.py`, `scripts/smoke.sh` and
  `.github/workflows/deploy.yml` ("Deploy only the tip of main"). Copy their patterns,
  not their names.
- AWS (all under `https://docs.aws.amazon.com`):
  - "Lambda quotas" (`/lambda/latest/dg/gettingstarted-limits.html`): 6 MB each way.
  - "Quotas for configuring and running an HTTP API"
    (`/apigateway/latest/developerguide/http-api-quotas.html`): 30 s, 10 MB.
  - "Throttle requests to your HTTP APIs" (`/apigateway/latest/developerguide/http-api-throttling.html`).
  - "Using event filtering with a DynamoDB event source"
    (`/lambda/latest/dg/with-ddb-filtering.html`): filters only on the `dynamodb` key,
    so the mailer filters on `NewImage.status`, not on `eventName`.
  - "Retain discarded records for a DynamoDB event source"
    (`/lambda/latest/dg/services-dynamodb-errors.html`) and "Configuring partial batch
    response" (`/lambda/latest/dg/services-ddb-batchfailurereporting.html`).
  - "Point-in-time backups for DynamoDB" (`/amazondynamodb/latest/developerguide/Point-in-time-recovery.html`).
  - "Blocking public access to your Amazon S3 storage", "Configuring default
    encryption", "Controlling ownership of objects", "Examples of Amazon S3 bucket
    policies" (`aws:SecureTransport`), "Lifecycle configuration elements" (S3 user
    guide).
  - "Actions, resources, and condition keys for Amazon Simple Email Service v2"
    (`/service-authorization/latest/reference/list_sesv2.html`): `ses:FromAddress`;
    "Identity and access management in Amazon SES" (`/ses/latest/dg/control-user-access.html`).
  - "Using IAM policy conditions for fine-grained access control" (DynamoDB developer
    guide): `dynamodb:LeadingKeys`. **To confirm in `/prep`**: that `LeadingKeys` is
    evaluated for each item of a `TransactWriteItems` call. If the page doesn't say so,
    the form's role keeps the action scoped to the table and the condition is noted as
    unverified in the template's comment.
  - "Specification: Embedded metric format" and "PutMetricAlarm"
    (`TreatMissingData`), CloudWatch user guide and API reference.
  - "HttpApi" and "AWS::Serverless::HttpApi" (SAM developer guide), "DeletionPolicy
    attribute" and "UpdateReplacePolicy attribute" (CloudFormation template reference),
    "sam deploy" (tags propagate to resources that support them).

## Goal

A merge to `main` deploys `asmbly-ceramics-stage`, smoke-tests it, then deploys
`asmbly-ceramics-prod` and smoke-tests it. Each stack holds the records table, the
private photo bucket, the form function behind an HTTP API at the environment's
address, and the mailer that sends the outbox's emails, with alarms that notify the
maintainers when sending fails. Someone can drop off on stage from a phone and get the
"We received your drop-off" email with their photos. The prod form is live but its
address isn't published until phase 10.

## Files to create

| Path | What |
| --- | --- |
| `infra/app.yaml` | The SAM template for one environment (below) |
| `samconfig.toml` | `[stage]` and `[prod]` config environments |
| `src/asmbly_ceramics/settings.py` | `Settings`, read once from environment variables (stdlib only) |
| `src/asmbly_ceramics/composition.py` | Builds the AWS adapters and the use cases from `Settings` |
| `src/asmbly_ceramics/logs.py` | JSON logging for every function, with the fixed field names |
| `src/asmbly_ceramics/entry/__init__.py` | Package marker |
| `src/asmbly_ceramics/entry/run.sh` | Starts the web app under uvicorn for the Lambda Web Adapter |
| `src/asmbly_ceramics/entry/mailer.py` | The mailer's Lambda handler |
| `src/requirements.txt` | `uv export --frozen --no-dev --no-emit-project`, for `sam build`; never edited by hand |
| `scripts/sam_parameters.py` | Every template parameter for one config environment, so `sam deploy` never keeps a stale value |
| `scripts/smoke.py` | The smoke test, with no AWS credentials |
| `.github/workflows/deploy.yml` | Deploy on merge: stage, smoke, prod, smoke |
| `tests/test_settings.py`, `tests/test_composition.py`, `tests/test_logs.py`, `tests/entry/test_mailer.py` | The app's wiring |
| `tests/repo/test_app_template.py` | Pins the template (below) |
| `tests/repo/test_deploy_workflow.py` | Pins the deploy workflow |
| `tests/scripts/test_smoke.py`, `tests/scripts/test_sam_parameters.py` | The scripts, against a local stub server and a sample config |

## Files to modify

| Path | What changes |
| --- | --- |
| `src/asmbly_ceramics/web/app.py` | `create_from_environment() -> Starlette`: reads `APP_ROLE` (`form` today; any other value fails at start) and returns `create_app(*composition.build_form_services())`. Phase 8 adds the `console` role |
| `.github/workflows/pr-checks.yml` | Top-level `env: SAM_CLI_VERSION`; job `python` gains "Requirements match the lock" (`uv export … \| diff - src/requirements.txt`); phase 5's `infra` job (named `Templates`, already running `cfn-lint` and already in `PR check`'s `needs`) gains `aws-actions/setup-sam` at `$SAM_CLI_VERSION`, `sam validate --lint -t infra/app.yaml` and `sam build -t infra/app.yaml`; no credentials |
| `tests/repo/test_workflows.py` | Exactly `deploy.yml`'s jobs `stage` and `prod` may have an `environment`, `permissions: {id-token: write, contents: read}` and `configure-aws-credentials`; `deploy.yml` runs only on `push` to `main` and `workflow_dispatch`; every other workflow and job keeps today's rules |
| `tests/repo/test_checks.py` | The SAM CLI version appears only in `pr-checks.yml`'s and `deploy.yml`'s top-level `env`, and they agree |
| `CLAUDE.md` | "Done means verified" gains `uv export --frozen --no-dev --no-emit-project -o src/requirements.txt` (after a dependency change) and `sam validate --lint -t infra/app.yaml && sam build -t infra/app.yaml` (after a template change); "Commits and pull requests" replaces "Today a merge deploys nothing" with what a merge deploys and the smoke test to watch |
| `README.md` | "How changes reach production": merge → stage → smoke → prod → smoke, and where to watch it; "Status" says the form is deployed |
| `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md` | The new checks, where `tests/repo/test_checks.py` requires them |
| `docs/README.md` | Runbooks: the deploy's rollback (a revert pull request), in `docs/runbooks/operations.md`, created here |
| `pyproject.toml` | `[tool.coverage.run] omit` nothing new; `mypy` `files` gains `scripts` (`tests/repo/test_checks.py` requires every Python folder) |

## Implementation details

### infra: `infra/app.yaml`

`Transform: AWS::Serverless-2016-10-31`. Every name comes from `ProjectSlug` and
`AppEnv`; nothing in the file is an account ID, an address or a secret.

**Parameters**

| Name | Type and default | Set from |
| --- | --- | --- |
| `ProjectSlug` | String, `asmbly-ceramics`, `AllowedPattern ^asmbly-ceramics$` | default |
| `AppEnv` | String, `AllowedValues [stage, prod]` | samconfig |
| `AppVersion` | String | the workflow (the commit's short SHA) |
| `SiteHost` | String | samconfig: `ceramics-stage.asmbly.org` or `ceramics.asmbly.org` |
| `EmailDomain` | String, `asmbly.org` | default |
| `WebAdapterLayerArn` | String, `AllowedPattern ^arn:aws:lambda:us-east-2:[0-9]+:layer:LambdaAdapterLayerArm64:[0-9]+$` | the GitHub variable `WEB_ADAPTER_LAYER_ARN` (AWS's published ARN for the arm64 layer, version 27 or later; it holds AWS's account number, which the repository's test refuses in a file) |
| `AlertEmail` | `AWS::SSM::Parameter::Value<String>` | samconfig: the parameter's name, `/asmbly-ceramics/<env>/alert-email` (a String the maintainer sets by hand) |
| `InitialSendingAddress` | `AWS::SSM::Parameter::Value<String>` | samconfig: the parameter's name, `/asmbly-ceramics/<env>/initial-sending-address` (a String the maintainer sets by hand; the domain refuses an address outside `asmbly.org`) |

The two addresses are not in GitHub and not in the deploy command: `sam deploy` and the
change set print the parameters' names, never their values, so the public Actions logs
hold neither. CloudFormation resolves them with the execution role's
`ssm:GetParameters` on `parameter/asmbly-ceramics/*` (phase 5).

The staff sign-in values (`StaffIssuer`, `StaffSignInUrl`, `StaffClientId`) are added
by phase 8, which uses them.

**Conditions**: `IsProd` (`AppEnv` = prod).

**Globals.Function**: `Runtime: python3.14`, `Architectures: [arm64]`,
`CodeUri: ../src/`, `PermissionsBoundary: !ImportValue asmbly-ceramics-function-boundary-arn`,
`Tracing: PassThrough`, `LoggingConfig: {LogFormat: JSON}` is not used (the app logs its
own JSON), `Environment.Variables` (all functions):

| Variable | Value |
| --- | --- |
| `APP_ENV` | `!Ref AppEnv` |
| `APP_VERSION` | `!Ref AppVersion` |
| `TABLE_NAME` | `!Ref RecordsTable` |
| `PHOTO_BUCKET` | `!Ref PhotoBucket` |
| `SITE_URL` | `!Sub https://${SiteHost}` |
| `INITIAL_SENDING_ADDRESS` | `!Ref InitialSendingAddress` |
| `LOG_LEVEL` | `INFO` |

Each function adds only the keys it reads: `FormFunction` sets `HASH_KEY_PARAMETER`
(`!Sub /${ProjectSlug}/${AppEnv}/hash-key`) and `FORM_KEY_PARAMETER`
(`!Sub /${ProjectSlug}/${AppEnv}/form-key`); phase 8's `ConsoleFunction` sets
`SESSION_KEY_PARAMETER`; the mailer reads no key.

Tags come from the stack (`sam deploy --tags`, below); `PropagateTags: true` on every
SAM resource that has it, so the generated roles and the API carry them too.

**Resources**

`RecordsTable` (`AWS::DynamoDB::Table`, `DeletionPolicy: Retain`,
`UpdateReplacePolicy: Retain`):

```yaml
TableName: !Sub ${ProjectSlug}-${AppEnv}-records
BillingMode: PAY_PER_REQUEST
AttributeDefinitions: # PK, SK, GSI1PK, GSI1SK, GSI2PK, GSI2SK: S (phase 4's keys)
KeySchema: [{AttributeName: PK, KeyType: HASH}, {AttributeName: SK, KeyType: RANGE}]
GlobalSecondaryIndexes: # GSI1 and GSI2 exactly as phase 4 defines them, Projection ALL
TimeToLiveSpecification: {AttributeName: ttl, Enabled: true}
StreamSpecification: {StreamViewType: NEW_IMAGE}
PointInTimeRecoverySpecification: {PointInTimeRecoveryEnabled: true, RecoveryPeriodInDays: 7}
DeletionProtectionEnabled: true
```

Changing `TableName`, `KeySchema` or a key attribute's type replaces the table
(CloudFormation's `AWS::DynamoDB::Table` reference: "Update requires: Replacement");
`tests/repo/test_app_template.py` pins them, and the retain policies keep the data if
it ever happens. Adding a GSI or changing PITR updates in place.

`PhotoBucket` (`AWS::S3::Bucket`, Retain on delete and replace):

```yaml
BucketName: !Sub ${ProjectSlug}-${AppEnv}-photos-${AWS::AccountId}
PublicAccessBlockConfiguration: {BlockPublicAcls: true, BlockPublicPolicy: true,
                                 IgnorePublicAcls: true, RestrictPublicBuckets: true}
OwnershipControls: {Rules: [{ObjectOwnership: BucketOwnerEnforced}]}
BucketEncryption: {ServerSideEncryptionConfiguration: [{ServerSideEncryptionByDefault: {SSEAlgorithm: AES256}}]}
LifecycleConfiguration:
  Rules:
    - {Id: expire-uploads, Status: Enabled, Prefix: uploads/, ExpirationInDays: 1}
    - {Id: abort-multipart, Status: Enabled, AbortIncompleteMultipartUpload: {DaysAfterInitiation: 1}}
CorsConfiguration:
  CorsRules: [{AllowedOrigins: [!Sub "https://${SiteHost}"], AllowedMethods: [POST],
               AllowedHeaders: ["*"], MaxAge: 3000}]
```

Bucket names are global across all AWS accounts; the account number, added by
CloudFormation at deploy time, keeps the name unique without writing it in the file.
The name still starts with `asmbly-ceramics-`. Changing `BucketName` replaces the
bucket (Retain keeps the old one).

`PhotoBucketPolicy`: one statement, `Deny` `s3:*` to `*` on the bucket and its objects
when `aws:SecureTransport` is `false`. No `Allow`: access comes only from the functions'
roles.

`HttpApi` (`AWS::Serverless::HttpApi`): `DisableExecuteApiEndpoint: true`;
`DefaultRouteSettings: {ThrottlingBurstLimit: 20, ThrottlingRateLimit: 5}`;
`AccessLogSettings` to `HttpApiLogGroup` with fields `requestId`, `routeKey`, `status`,
`responseLength`, `integrationLatency`, and no source address, user agent or query string;
`PropagateTags: true`.

`HttpApiMapping` (`AWS::ApiGatewayV2::ApiMapping`): `DomainName: {'Fn::ImportValue': !Sub '${ProjectSlug}-${AppEnv}-domain-name'}`
(phase 5's export; the long form, because CloudFormation refuses `!ImportValue` around a short-form `!Sub`), `ApiId: !Ref HttpApi`,
`Stage: !Ref HttpApi.Stage`.

`FormFunction` (`AWS::Serverless::Function`):

```yaml
FunctionName: !Sub ${ProjectSlug}-${AppEnv}-form
Handler: asmbly_ceramics/entry/run.sh
MemorySize: 2048            # Pillow decodes up to six 10 MB photos on submit
Timeout: 29
ReservedConcurrentExecutions: 5
Layers: [!Ref WebAdapterLayerArn]
Environment:
  Variables: {APP_ROLE: form, AWS_LAMBDA_EXEC_WRAPPER: /opt/bootstrap, PORT: "8080",
              AWS_LWA_READINESS_CHECK_PATH: /health}
Events:
  Default: {Type: HttpApi, Properties: {ApiId: !Ref HttpApi, Path: $default, Method: ANY,
                                        PayloadFormatVersion: "2.0"}}
LoggingConfig: {LogGroup: !Ref FormLogGroup}
Policies: [the statements below]
```

`MailerFunction`:

```yaml
FunctionName: !Sub ${ProjectSlug}-${AppEnv}-mailer
Handler: asmbly_ceramics.entry.mailer.handler
MemorySize: 512
Timeout: 60
ReservedConcurrentExecutions: 2      # SES rate stays far below the account's limit
Events:
  Outbox:
    Type: DynamoDB
    Properties:
      Stream: !GetAtt RecordsTable.StreamArn
      StartingPosition: LATEST
      BatchSize: 1
      MaximumRetryAttempts: 3
      BisectBatchOnFunctionError: true
      FunctionResponseTypes: [ReportBatchItemFailures]
      FilterCriteria:
        Filters: [{Pattern: '{"dynamodb": {"NewImage": {"type": {"S": ["email"]}, "status": {"S": ["pending"]}}}}'}]
      DestinationConfig: {OnFailure: {Type: SQS, Destination: !GetAtt MailerDeadLetterQueue.Arn}}
LoggingConfig: {LogGroup: !Ref MailerLogGroup}
```

The attribute names `type` and `status` are phase 4's outbox item attributes; if phase
4 names them otherwise, this filter follows phase 4.

`MailerDeadLetterQueue` (`AWS::SQS::Queue`): `QueueName: ${ProjectSlug}-${AppEnv}-mailer-dlq`,
`SqsManagedSseEnabled: true`, `MessageRetentionPeriod: 1209600`. Its messages hold the
stream record's metadata (the shard and sequence numbers), not the item.

Log groups (`AWS::Logs::LogGroup`): `FormLogGroup` (`/aws/lambda/${ProjectSlug}-${AppEnv}-form`),
`MailerLogGroup`, `HttpApiLogGroup` (`/aws/apigateway/${ProjectSlug}-${AppEnv}`);
`RetentionInDays: !If [IsProd, 90, 14]`.

`AlarmTopic` (`AWS::SNS::Topic`, `TopicName: ${ProjectSlug}-${AppEnv}-alarms`; no KMS
key, since CloudWatch can't publish to a topic encrypted with the AWS managed key, as
AsmblyMCPs found), and `AlarmEmailSubscription` (`Protocol: email`, `Endpoint: !Ref AlertEmail`).

Metric filters and alarms, each with `AlarmActions` and `OKActions` on `AlarmTopic`,
`TreatMissingData: notBreaching`, names `${ProjectSlug}-${AppEnv}-<name>`:

| Alarm | Metric | Fires when |
| --- | --- | --- |
| `EmailFailuresAlarm` (`email-failures`) | metric filter on `MailerLogGroup` and `FormLogGroup`, pattern `{ $.event = "email_failed" }`, metric `EmailFailures` in namespace `asmbly-ceramics/<env>` | ≥ 1 in 5 minutes |
| `LoggedErrorsAlarm` (`logged-errors`) | metric filter `{ $.level = "ERROR" }` on each function's log group | ≥ 1 in 5 minutes |
| `MailerDeadLettersAlarm` (`mailer-dead-letters`) | `AWS/SQS` `ApproximateNumberOfMessagesVisible` on the queue | > 0 |
| `FunctionErrorsAlarm` (`function-errors`) | `AWS/Lambda` `Errors`, each function | ≥ 1 in 5 minutes |
| `Api5xxAlarm` (`api-5xx`) | `AWS/ApiGateway` `5xx` for the API | ≥ 3 in 5 minutes |

**The roles** (SAM `Policies`, each statement naming its resources; the boundary from
phase 5 caps them):

Form function:

```yaml
- Sid: ReadStudioAndSubmissions        # never a drop-off: the ID page reads the submission's summary
  Effect: Allow
  Action: [dynamodb:GetItem, dynamodb:Query]
  Resource: !GetAtt RecordsTable.Arn
  Condition:
    ForAllValues:StringLike: {dynamodb:LeadingKeys: ["STUDIO", "STUDIO#*", "SUBMISSION#*"]}
- Sid: CreateDropOffs                  # new items only, through the submit transaction
  Effect: Allow
  Action: [dynamodb:PutItem, dynamodb:ConditionCheckItem]
  Resource: !GetAtt RecordsTable.Arn
  Condition:
    ForAllValues:StringLike:
      dynamodb:LeadingKeys: ["DROPOFF#*", "EMAIL#*", "SUBMISSION#*", "STUDIO", "STUDIO#*"]
- Sid: CountIds
  Effect: Allow
  Action: dynamodb:UpdateItem
  Resource: !GetAtt RecordsTable.Arn
  Condition:
    ForAllValues:StringLike: {dynamodb:LeadingKeys: ["COUNTER#*"]}
- Sid: CountRates                      # a rolling window: read the hits, put them back (phase 4)
  Effect: Allow
  Action: [dynamodb:GetItem, dynamodb:PutItem]
  Resource: !GetAtt RecordsTable.Arn
  Condition:
    ForAllValues:StringLike: {dynamodb:LeadingKeys: ["RATE#*"]}
- Sid: TransactOnTheTable                # TransactWriteItems is authorised per item action above
  Effect: Allow
  Action: dynamodb:TransactWriteItems   # if the IAM reference lists it as an action; see Required reading
  Resource: !GetAtt RecordsTable.Arn
- Sid: Uploads                         # GetObject also covers discard_uploads' marker check (HeadObject)
  Effect: Allow
  Action: [s3:PutObject, s3:GetObject, s3:DeleteObject]
  Resource: !Sub ${PhotoBucket.Arn}/uploads/*
- Sid: KeepPhotos
  Effect: Allow
  Action: s3:PutObject
  Resource: !Sub ${PhotoBucket.Arn}/dropoffs/*
- Sid: ReadOwnKeys
  Effect: Allow
  Action: ssm:GetParameter
  Resource:
    - !Sub arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/${ProjectSlug}/${AppEnv}/hash-key
    - !Sub arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/${ProjectSlug}/${AppEnv}/form-key
```

The form never gets `s3:GetObject` on `dropoffs/*`, any read of a `DROPOFF#`, `EMAIL#`
or `LOAD#` item, `UpdateItem` on them, `dynamodb:Scan`, a `Query` outside the studio and
its own submissions, the console's `session-key`, or any SES right. IAM can't require
`attribute_not_exists` on a `PutItem`, so a form function whose code was taken over
could still overwrite a drop-off item with a `Put`; that is accepted in decision 0002
(the mailer re-reads each drop-off by key, so only an overwritten one could be
affected). `STUDIO` writes are for phase 3's
first-use seeding of the studio from `INITIAL_SENDING_ADDRESS` (a conditional put that
does nothing once it exists). Decrypting the SecureStrings uses the AWS managed key for
SSM, which the boundary allows through `kms:ViaService` (phase 5).

Mailer function:

```yaml
- Sid: ReadWhatAnEmailNeeds
  Effect: Allow
  Action: dynamodb:GetItem
  Resource: !GetAtt RecordsTable.Arn
  Condition:
    ForAllValues:StringLike: {dynamodb:LeadingKeys: ["EMAIL#*", "DROPOFF#*", "LOAD#*", "STUDIO", "STUDIO#*"]}
- Sid: MarkEmails                      # claim, sent, failed: the only writes the mailer makes
  Effect: Allow
  Action: dynamodb:UpdateItem
  Resource: !GetAtt RecordsTable.Arn
  Condition:
    ForAllValues:StringLike: {dynamodb:LeadingKeys: ["EMAIL#*"]}
- Sid: ReadTheStream
  Effect: Allow
  Action: [dynamodb:DescribeStream, dynamodb:GetRecords, dynamodb:GetShardIterator, dynamodb:ListStreams]
  Resource: !GetAtt RecordsTable.StreamArn
- Sid: ReadKeptPhotos
  Effect: Allow
  Action: s3:GetObject
  Resource: !Sub ${PhotoBucket.Arn}/dropoffs/*
- Sid: SendFromAsmblyOrg
  Effect: Allow
  Action: ses:SendEmail
  Resource: !Sub arn:aws:ses:${AWS::Region}:${AWS::AccountId}:identity/${EmailDomain}
  Condition:
    StringLike: {ses:FromAddress: !Sub "*@${EmailDomain}"}
- Sid: DeadLetters
  Effect: Allow
  Action: sqs:SendMessage
  Resource: !GetAtt MailerDeadLetterQueue.Arn
```

`ses:Recipients` can't be limited: the mailer emails the person who dropped off. The
use case sends only to the drop-off's own address (phase 3), which is what holds that
rule.

**Outputs**: `ApiUrl` (`!Sub https://${SiteHost}`, also exported for nothing: outputs
only), `SiteUrl`, `PhotoBucketName`, `TableName`, `AlarmTopicArn`. No export: nothing
else imports this stack.

### infra: `samconfig.toml`

```toml
version = 0.1

[stage.deploy.parameters]
stack_name = "asmbly-ceramics-stage"
region = "us-east-2"
capabilities = "CAPABILITY_IAM"
confirm_changeset = false
fail_on_empty_changeset = false
tags = "Project=asmbly-ceramics Component=App Environment=stage Owner=it-volunteers ManagedBy=sam"
parameter_overrides = "AppEnv=stage SiteHost=ceramics-stage.asmbly.org"

[prod.deploy.parameters]
stack_name = "asmbly-ceramics-prod"
# … the same, with Environment=prod, AppEnv=prod, SiteHost=ceramics.asmbly.org
```

`[default.build.parameters]` sets `template = "infra/app.yaml"`, `cached = true`,
`parallel = true`. The `Component` value is `App` for the app stack and `Bootstrap` for
phase 5's; if the Asmbly AWS Tagging Guide names other values, they win (open question
in the README).

### app: settings, composition, logging, entry points

`settings.py` (stdlib only, read once per container):

```python
@dataclass(frozen=True)
class Settings:
    app_env: Literal["stage", "prod"]
    version: str
    table_name: str
    photo_bucket: str
    site_url: str
    hash_key_parameter: str | None  # form only
    form_key_parameter: str | None  # form only
    session_key_parameter: str | None  # console only (phase 8)
    initial_sending_address: str
    region: str  # AWS_REGION, set by Lambda
    log_level: str

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] = os.environ) -> "Settings": ...
```

A missing or empty variable raises `SettingsError` naming the variable (never its
value); `site_url` must start with `https://`.

`composition.py`:

```python
def build_form_services(settings: Settings | None = None) -> tuple[WebServices, WebSettings]: ...
def build_mailer(settings: Settings | None = None) -> SendPendingEmail: ...
```

Each creates its boto3 clients once (module-level cache), builds phase 4's adapters
(`DynamoDbRecords`, `DynamoDbIdNumbers`, `DynamoDbRateLimiter`, `S3PhotoStore`,
`PillowPhotoInspector`, `SesMailer`, `SsmSecrets`, `SystemClock`) and phase 2's and 3's
use cases. `WebSettings.photo_upload_origin` is
`https://<bucket>.s3.<region>.amazonaws.com`; `WebSettings.cookie_key` is
`Secrets.get(SecretName.FORM_KEY)`. The form function reads `hash-key` and `form-key`
only. Phase 8 adds `build_console_services` and
phase 9 `build_closer`.

`logs.py`: `configure_logging(level)` installs one handler on the root logger with a
JSON formatter; fields, a contract with the metric filters above: `level`, `message`,
`event`, `drop_off_id`, `load_id`, `user`, `kind`, `outcome`, `reason`, `error_code`, `count`, `fields`, `list`, `item`, `version` (phase 2's `LOG_FIELDS`, plus `version`). Extra
keys passed in `extra=` are kept only if they are in that list; anything else is
dropped. `botocore`, `boto3` and `urllib3` loggers are floored at `INFO` (their debug
output can hold request bodies). A test asserts the field list.

`entry/run.sh`:

```sh
#!/bin/sh
exec python -m uvicorn asmbly_ceramics.web.app:create_from_environment --factory \
  --host 0.0.0.0 --port "$PORT" --no-access-log
```

Executable in git (`chmod +x`, checked by a test). uvicorn's access log is off (it
would log paths and addresses); the app logs its own lines. It runs without
`--proxy-headers`: the client's address is read only by phase 6's
`security.client_address`, from the last `X-Forwarded-For` value, so a caller can't
choose the address the rate limit counts.

`entry/mailer.py`:

```python
def handler(event: dict[str, Any], context: object) -> dict[str, list[dict[str, str]]]:
    """For each stream record, send its email; report the ones that failed to retry."""
```

For each record: read `PK`/`SK` from `dynamodb.Keys` (never the image's personal
fields), call `SendPendingEmail(EmailKey(...))`; a `SendFailed` is the use case's
business (it marks the email `failed` and logs `email_failed`) and is not a retry; any
other exception adds `{"itemIdentifier": record["dynamodb"]["SequenceNumber"]}` to
`batchItemFailures` and logs `mailer_crashed` with the exception's class only.

### ci: `.github/workflows/deploy.yml`

```yaml
name: Deploy
on:
  push: {branches: [main]}
  workflow_dispatch:
permissions:
  contents: read
env:
  SAM_CLI_VERSION: '<the version pr-checks.yml uses>'
defaults: {run: {shell: bash}}
jobs:
  stage:
    name: Deploy stage
    runs-on: ubuntu-24.04
    timeout-minutes: 25
    environment: {name: stage, url: https://ceramics-stage.asmbly.org}
    permissions: {id-token: write, contents: read}
    concurrency: {group: deploy-stage, cancel-in-progress: false}
    steps: [the steps below, CONFIG_ENV=stage]
  prod:
    name: Deploy prod
    needs: stage
    # … the same with environment prod, url https://ceramics.asmbly.org, CONFIG_ENV=prod
```

Steps of each job:

1. **Deploy only the tip of main**: `gh api repos/${{ github.repository }}/git/ref/heads/main
   --jq .object.sha` must equal `GITHUB_SHA`, else stop with "A newer commit is on main;
   it deploys itself." (the same text in both jobs; a test checks).
2. `actions/checkout@v7`, `actions/setup-python@v7` (`python-version-file: .python-version`),
   `aws-actions/setup-sam@v3` (`version: ${{ env.SAM_CLI_VERSION }}`, `use-installer: true`).
3. `aws-actions/configure-aws-credentials@v6` with `role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}`,
   `aws-region: ${{ vars.AWS_REGION }}`, `mask-aws-account-id: true`; then, before any
   step that prints, `echo "::add-mask::$(aws sts get-caller-identity --query Account
   --output text)"`, so the account ID (in role ARNs and the bucket's name) is masked in
   the public Actions log.
4. `sam build --config-env "$CONFIG_ENV"`.
5. `sam deploy --config-env "$CONFIG_ENV" --no-progressbar --role-arn "$EXECUTION_ROLE"
   --s3-bucket "$ARTIFACTS_BUCKET" --parameter-overrides "$(python3 scripts/sam_parameters.py
   "$CONFIG_ENV" "AppVersion=${GITHUB_SHA::7}" "WebAdapterLayerArn=$WEB_ADAPTER_LAYER_ARN")"`,
   with those values from `vars.*` in `env:`. The addresses are SSM-typed parameters
   named in samconfig, so no address is in the command or its output.
6. **Smoke test**: `python3 scripts/smoke.py "https://<site host>" "${GITHUB_SHA::7}"`,
   no credentials needed (the step runs after the deploy; the job's credentials expire
   in an hour and the script doesn't use them).
7. Write only the site URL, the version and the smoke result to `GITHUB_STEP_SUMMARY`:
   no stack output, role ARN or bucket name (they hold the account ID), and no address.

`id-token: write` is the only right beyond `contents: read`, on these two jobs only.

### ci: `scripts/smoke.py`

Standard library only (`urllib.request`), exit 1 on the first failure, printing which
check failed and the status, never a body. Checks:

1. `GET /health` answers 200 with `status: ok` and the expected `version` (retries 10
   times, 6 s apart, for the new version to be live).
2. `GET /` answers 200 with `Content-Security-Policy` starting `default-src 'none'`,
   `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`.
3. `GET /console` answers 404 (phase 8 changes this to a 302 to the staff sign-in).
4. `POST /drop-off/uploads` with `Origin: https://example.org` answers 403.
5. With a device cookie and a submission token from step 2's page and the site's
   `Origin`, `POST /drop-off/uploads` for one slot answers 200; posting 10 MB + 1 byte
   to that slot answers a 4xx from S3 (`EntityTooLarge` is expected; whichever 4xx code
   comes back is printed, which settles the open question), and the object doesn't
   exist afterwards.
6. `GET https://<bucket>.s3.us-east-2.amazonaws.com/dropoffs/AC-1/1.jpg` (and an
   `uploads/` key) without credentials answers 403.

The smoke test never submits a drop-off and never sends an email. Its upload slot uses
the rate limit once per deploy.

### ci: `scripts/sam_parameters.py`

As AsmblyMCPs': reads `samconfig.toml`'s `parameter_overrides` for the config
environment and the template's parameter defaults, adds the arguments given, and prints
`Key=Value` pairs for every parameter, so a parameter dropped from the command never
keeps its old value. Refuses an unknown key.

### tests/repo/test_app_template.py

Loads `infra/app.yaml` with a loader that understands CloudFormation's short tags, and
checks:

- every `FunctionName`, `TableName`, `BucketName`, `QueueName`, `TopicName`, alarm name
  and log group name starts with `${ProjectSlug}-` or `/aws/…/${ProjectSlug}-`;
- `RecordsTable` and `PhotoBucket` have `DeletionPolicy` and `UpdateReplacePolicy`
  `Retain`; the table has PITR with 7 days, deletion protection, TTL on `ttl`, and a
  `NEW_IMAGE` stream;
- the bucket's four public-access settings are true, ownership is `BucketOwnerEnforced`,
  encryption is set, the policy denies non-TLS, the lifecycle expires `uploads/` after 1
  day, CORS allows only `POST` from the site;
- no statement in any role has `Resource: "*"`, `s3:*` with an `Allow`, or `iam:*`;
- the form's role has no `s3:GetObject` on `dropoffs/*`, no `dynamodb:Scan`, no `ses:*`;
- the only `ses:SendEmail` is the mailer's, on the `asmbly.org` identity, with
  `ses:FromAddress` limited to that domain;
- the mailer's event filter matches `status = pending` and the outbox type, with retries
  bounded and an on-failure queue;
- every alarm has `AlarmActions` on `AlarmTopic` and `TreatMissingData: notBreaching`;
  `EmailFailuresAlarm` counts the `email_failed` event;
- the template holds no 12-digit number and no address with an `@` other than the
  `*@${EmailDomain}` pattern;
- every function has `PermissionsBoundary` from the bootstrap export and a log group with
  retention.

And `tests/repo/test_deploy_workflow.py`: the two jobs, `prod` needs `stage`, both have
the tip-of-main step with identical text, the smoke step, `cancel-in-progress: false`,
and use only `vars.*` (no `secrets.*`).

## Tests

- `tests/test_settings.py`: `test_settings_read_every_variable`,
  `test_a_missing_variable_is_named_without_its_value`,
  `test_the_site_url_must_be_https`.
- `tests/test_composition.py`: `test_form_services_build_on_stubbed_clients` (botocore
  `Stubber` clients, no network), `test_the_mailer_builds`.
- `tests/test_logs.py`: `test_lines_are_json_with_the_fixed_fields`,
  `test_unknown_extra_fields_are_dropped`, `test_library_loggers_are_floored_at_info`.
- `tests/entry/test_mailer.py`: `test_each_record_sends_its_email` (the fake use case
  gets the keys), `test_a_crash_reports_the_record_for_retry`,
  `test_a_send_failure_is_not_retried_by_lambda`,
  `test_the_handler_never_reads_personal_fields_from_the_image`.
- `tests/scripts/test_smoke.py`: against a local `http.server` stub that answers each
  check right, then wrong one at a time: each wrong answer fails the script with that
  check's name.
- `tests/scripts/test_sam_parameters.py`: every parameter is printed; an unknown key is
  refused; a value from the command wins over samconfig.
- `tests/repo/test_app_template.py`, `tests/repo/test_deploy_workflow.py`,
  `tests/repo/test_workflows.py`, `tests/repo/test_checks.py`: as above.
- `tests/test_entry_script.py`: `run.sh` is executable and starts uvicorn with the
  factory and no access log.

## Acceptance criteria

1. A merge to `main` deploys `asmbly-ceramics-stage`, runs the smoke test against
   `https://ceramics-stage.asmbly.org`, then deploys `asmbly-ceramics-prod` and runs it
   against `https://ceramics.asmbly.org`; a failed step stops what follows.
2. A photo's storage address alone gets 403 (smoke check 6) (#2).
3. A POST of 10 MB + 1 byte to an upload slot is refused by S3 and leaves no object
   (smoke check 5) (#2).
4. A drop-off made on stage stores its record, its photos under `dropoffs/AC-n/`, and its
   `received` email, which the mailer sends with the photos inline from the sending
   address (#2).
5. An email that fails to send is marked `failed`, logs `email_failed` with the drop-off's
   ID and the SES error code, and within 5 minutes `asmbly-ceramics-<env>-email-failures`
   goes to ALARM and the maintainers' address gets the notification (#4).
6. Every resource the stacks create has a name starting `asmbly-ceramics-` and the tags
   `Project=asmbly-ceramics`, `Component`, `Environment`, `Owner=it-volunteers`,
   `ManagedBy=sam` (`aws resourcegroupstaggingapi get-resources` read-only check).
7. The form's role can't read kept photos, read, update or list any `DROPOFF#`,
   `EMAIL#` or `LOAD#` item, scan the table, or read `session-key`; the mailer's role
   writes only `EMAIL#` items (`UpdateItem`, no `PutItem`); only the mailer can send
   email, only from `asmbly.org` (`test_app_template.py` pins each). The mailer can't
   seed the studio's starting values, and needn't: an email exists only after a
   submit, which reads (and so seeds) the studio first; `build_mailer` passes
   `CurrentStudio` a read-only flag that raises if the studio is missing.
8. No pull request job has AWS credentials or an environment; only `deploy.yml`'s two
   jobs do, and only on `main`.
9. `uv run pytest --cov`, `uvx cfn-lint`, `sam validate --lint` and `sam build` pass in
   `PR check`.
10. No address and no account ID appears in a deploy run's log or step summary: the
   addresses are SSM-typed parameters named in samconfig, and the account ID is masked
   (`test_deploy_workflow.py` checks the masking step comes before `sam deploy`).

## Verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
uv export --frozen --no-dev --no-emit-project -o src/requirements.txt && git diff --exit-code src/requirements.txt
uvx cfn-lint==1.57.1 infra/*.yaml
sam validate --lint -t infra/app.yaml && sam build -t infra/app.yaml
```

After the merge, watch **Deploy** to the end (both smoke tests). Then, read only:

```bash
export AWS_PROFILE=asmbly AWS_REGION=us-east-2
aws cloudformation describe-stacks --stack-name asmbly-ceramics-stage --query 'Stacks[0].[StackStatus,Outputs]'
aws s3api get-public-access-block --bucket <PhotoBucketName from the outputs>
aws dynamodb describe-continuous-backups --table-name asmbly-ceramics-stage-records
aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=asmbly-ceramics --query 'ResourceTagMappingList[].ResourceARN'
```

On a phone: phase 6's verification on `https://ceramics-stage.asmbly.org/` (made-up
details, a mailbox you own, two photos). Expect the ID page and, within a minute, the
email with both photos; save an emailed photo and check it has no location (any EXIF
viewer: no GPS fields). Never look at the stored item's details with the CLI.

The email-failure alarm, on stage only: make one drop-off with made-up details, then in
the stage bucket delete its `dropoffs/AC-n/1.jpg` (the maintainer, by hand: a change,
so asked for in the conversation, on stage only) and use the console's "Try sending
again" once phase 8 exists, or before it, re-mark the email `pending` with
`aws dynamodb update-item` on its key (again by hand, stage only). The mailer can't
read the photo, marks the email `failed` with code `photo_missing`, logs
`email_failed`, and the alarm fires within 5 minutes; check the maintainers' mailbox,
then let it return to OK. A bounce from SES's mailbox simulator is not a send failure
and doesn't test this alarm.

## Rollout

| Step | Done by | Check | Undo |
| --- | --- | --- | --- |
| The pull request merges | The maintainer, on his word for it | **Deploy** runs | none needed |
| Stage deploys | the workflow | the change set is all `Add` on the first run (the run's log); the smoke test passes | revert the pull request; the next run removes what it added, except the retained table and bucket |
| Prod deploys | the workflow, after stage's smoke test | the smoke test against prod passes | as for stage |
| A real drop-off on stage | the maintainer, with made-up details | the ID, the email with photos, no location in them | none: the drop-off closes like any other (phase 9) or stays waiting on stage |
| The alarm | the maintainer, on stage | the notification arrives | the alarm returns to OK by itself |

Removing an environment entirely is a step for the maintainer by hand: delete the
stack, then, only if the data is truly not wanted, the retained table (turn deletion
protection off first) and the bucket. Nothing in the workflow deletes data.

The prod form is live from this phase but its address isn't published (phase 10 does
that), and no QR code points to it. Nobody is told yet.

## Admin actions

- Before merging: the sending right agreed in AsmblyMCPs (README, Dependencies). The
  same-account IAM statement above is enough for SES to accept the sends; the agreement
  is that the identity's owner knows and accepts another sender and its bounces.
- Before merging: for each environment, the SecureString parameters
  `/asmbly-ceramics/<env>/hash-key`, `/asmbly-ceramics/<env>/form-key` and
  `/asmbly-ceramics/<env>/session-key`, 32 random bytes each, and the String parameters
  `/asmbly-ceramics/<env>/alert-email` (the maintainers' address) and
  `/asmbly-ceramics/<env>/initial-sending-address` (the studio's sending address at
  `asmbly.org`, used until staff change it in the console), all set by the maintainer by
  hand (phase 5's runbook; values never shown or committed).
- Before merging: in both GitHub environments, the variables `AWS_REGION`,
  `AWS_DEPLOY_ROLE_ARN`, `AWS_CFN_EXECUTION_ROLE_ARN`, `SAM_ARTIFACTS_BUCKET` (from
  phase 5's outputs) and `WEB_ADAPTER_LAYER_ARN` (AWS's published arm64 layer ARN for
  us-east-2). No address is a GitHub variable.
- After the first deploy: confirm the SNS subscription from the email AWS sends to
  `/asmbly-ceramics/<env>/alert-email` for each environment.

## Hand-off

Filled in when the phase is done. Phases 8 and 9 rely on:

- **Template logical IDs**: `RecordsTable`, `PhotoBucket`, `PhotoBucketPolicy`, `HttpApi`,
  `HttpApiMapping`, `FormFunction`, `MailerFunction`, `MailerDeadLetterQueue`,
  `FormLogGroup`, `MailerLogGroup`, `HttpApiLogGroup`, `AlarmTopic`,
  `AlarmEmailSubscription`, `EmailFailuresAlarm`, `LoggedErrorsAlarm`,
  `MailerDeadLettersAlarm`, `FunctionErrorsAlarm`, `Api5xxAlarm`. Phase 8 adds
  `ConsoleFunction` with `HttpApi` events on `ANY /console` and `ANY /console/{proxy+}`
  (more specific than `$default`), and the parameters `StaffIssuer`, `StaffSignInUrl`,
  `StaffClientId`; phase 9 adds `CloseFunction`, `CloseSchedule`, `CloseDeadLetterQueue`.
- **Environment variables**: `APP_ENV`, `APP_VERSION`, `TABLE_NAME`, `PHOTO_BUCKET`,
  `SITE_URL`, `INITIAL_SENDING_ADDRESS`, `HASH_KEY_PARAMETER` and `FORM_KEY_PARAMETER`
  (form only; phase 8 adds `SESSION_KEY_PARAMETER` on the console only),
  `LOG_LEVEL`, and on web functions `AWS_LAMBDA_EXEC_WRAPPER`, `PORT`,
  `AWS_LWA_READINESS_CHECK_PATH`, `APP_ROLE` (`form`). Phase 8 adds `STAFF_ISSUER`, `STAFF_SIGN_IN_URL`,
  `STAFF_CLIENT_ID`.
- **Log fields**: `level`, `message`, `event`, `drop_off_id`, `load_id`, `user`, `error_code`,
  `outcome`, `fields`, `version`; the `email_failed` event feeds `EmailFailuresAlarm`.
- **Composition**: `Settings.from_environment()`, `build_form_services()`,
  `build_mailer()`; `web.app.create_from_environment()`; `entry/run.sh`.
- **The smoke test**: `scripts/smoke.py <site> <version>`; check 3 is phase 8's to change.
- **Names**: stacks `asmbly-ceramics-stage` and `asmbly-ceramics-prod`; table
  `asmbly-ceramics-<env>-records`; bucket `asmbly-ceramics-<env>-photos-<account>`;
  alarm topic `asmbly-ceramics-<env>-alarms`.
- The S3 answer to a too-large POST, as the first smoke run printed it, and the phone
  tests' results (iOS version, JPEG or not).

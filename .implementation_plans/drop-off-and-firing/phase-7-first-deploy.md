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

> **Status:** [~] In progress

## Prep revisions (15 November 2026)

`/prep` checked this document against the code (a drift check and an adversarial audit,
both run as subagents). Where this section and the text below disagree, this section
wins; the build follows it.

- **No `TransactOnTheTable` statements.** `dynamodb:TransactWriteItems` is not an IAM
  action: AWS's "Using IAM with DynamoDB transactions"
  (`/amazondynamodb/latest/developerguide/transaction-apis-iam.html`) authorizes each
  item of a transaction as its own `PutItem`/`UpdateItem`/`DeleteItem`/`ConditionCheckItem`
  (with `dynamodb:EnclosingOperation`), so `dynamodb:LeadingKeys` is evaluated per item.
  The roles' `PutItem` statements are what a commit needs. The "To confirm in `/prep`"
  note under Required reading is settled this way; the first stage submit proves it.
- **The mailer's SES statement names both identities** the bootstrap's boundary names:
  `identity/${EmailDomain}` and `identity/*@${EmailDomain}` (SES authorizes against the
  most specific identity covering the From address), with `ses:FromAddress` `*@${EmailDomain}`.
  Every ARN uses `${AWS::Partition}`.
- **The whole-request bound is a deadline** (phase 6's hand-off: the use cases run
  synchronously on the event loop, so an `asyncio` timeout can't stop them, and per-call
  configs can't sum some forty calls under 29 s). `asmbly_ceramics/deadline.py` (stdlib
  only) holds the request's deadline in a `ContextVar`, `REQUEST_BUDGET_SECONDS = 14` for the work and
  `CLEANUP_BUDGET_SECONDS = 22` for cleanups;
  `web.app.RequestDeadline` (ASGI middleware, added by `create_from_environment`) sets it
  for each HTTP request; `adapters/aws/deadline.py` registers a botocore `before-send`
  hook on every client `adapters.aws.clients` builds, which raises `DeadlinePassed` (a
  `BotoCoreError`) before any attempt once the deadline has passed. The adapters already
  turn a `BotoCoreError` into their port's `Unavailable`, so the page answers phase 6's
  503 and logs `drop_off_unavailable` with `error_code=DeadlinePassed`. One attempt then
  takes at most 2 s to connect and 4 s per read, so a request ends near 26 s (28 s after review). Outside a
  request (the mailer) the hook does nothing.
- **Clients are built in `adapters/aws/clients.py`** (`dynamodb_client`, `s3_client`,
  `ssm_client`, `ses_client`): `tests/domain/test_imports.py` lets only `adapters/` import
  boto3, so `composition.py` imports these, never boto3. The mailer's config is
  `adapters.aws.mailer.STREAM_SES_CLIENT_CONFIG` (`SES_CLIENT_CONFIG` merged with a 30 s
  read). `composition.build_form_services(settings, clients)` and `build_mailer(settings,
  clients)` take stubbed clients in tests.
- **`build_mailer` passes `CurrentStudio(..., seed=False)`**, which raises
  `StudioNotSeeded` when the studio is missing (the flag phase 2a built).
- **Alarms.** A metric filter belongs to one log group: only the mailer logs
  `email_failed`, so `EmailFailuresFilter` is on `MailerLogGroup` only. `LoggedErrors`
  has one filter per function's group, pattern `{ ($.level = "ERROR") && ($.event != "email_failed") }`,
  so one failed email sets off one alarm. `FunctionErrorsAlarm` sums each function's
  `AWS/Lambda` `Errors` with metric math (an `Errors` alarm without `FunctionName` is
  account-wide). Alarms carry the five tags explicitly (the execution role creates them
  only with the tags in the request).
- **The mailer.** `Timeout: 300` (up to ten reads at a worst 18 s each, then a 30 s send;
  a timeout would leave the email `sending` with nothing logged) and
  `StartingPosition: TRIM_HORIZON` (a replaced mapping doesn't skip pending emails; the
  claim skips whatever is no longer pending).
- **Outputs**: `SiteUrl`, `PhotoBucketName`, `TableName` only. `sam deploy` prints the
  outputs in the public log, so none is an ARN (it holds the account ID).
- **Smoke check 5** checks that S3 refuses the oversized POST (a 4xx, its code printed),
  not that the object is absent afterwards: without credentials a GET answers 403 either
  way. A refused POST stores nothing.
- **`run.sh`** sets `PYTHONPATH` to `$LAMBDA_TASK_ROOT` (the Web Adapter's Python
  examples do the same) and starts uvicorn on `0.0.0.0:$PORT` with `--no-access-log`.
  `logs.configure_logging(level, version)` replaces Lambda's root handler and uvicorn's
  own handlers, so every line is JSON; a line holds a message's template, never its
  arguments, and an exception only by its class name.
- **CI details**: the `Templates` job gains `actions/setup-python` (`.python-version`)
  for `sam build`; the tip-of-main step reads `gh api` with `GH_TOKEN: ${{ github.token }}`
  and, when a newer commit is on main, prints the notice and ends the job with exit 0 and
  every later step skipped (an output `tip`); `SAM_CLI_VERSION` is `1.172.1`.
- **Merge order**: phases 7, 8 and 9 are built on one branch and merge in one pull
  request, so stage and prod never take drop-offs without the console's reject and the
  daily close (#7). Phase 8 sets the console's routes their own throttling (the stage's
  default 5 per second, burst 20, is shared by every route).
- **Account check, read only (done in `/prep`)**: `aws lambda get-account-settings`
  shows 1,000 concurrent executions with 976 unreserved, so the 7 reserved per
  environment here (and phases 8 and 9's) leave well over 100.
- **Files added to the tables below**: `src/asmbly_ceramics/deadline.py`,
  `src/asmbly_ceramics/adapters/aws/deadline.py`, `docs/decisions/0004-the-form-role-and-the-photo-bucket-name.md`
  (status proposed: the four points in Admin actions), `docs/runbooks/operations.md`
  (the rollback, taking the form offline, removing an environment), `tests/entry/__init__.py`,
  `tests/scripts/__init__.py`, `tests/scripts/test_compose_check.py`,
  `tests/test_entry_script.py`, `tests/test_deadline.py`; modified:
  `src/asmbly_ceramics/adapters/aws/clients.py`, `src/asmbly_ceramics/adapters/aws/mailer.py`,
  `tests/repo/test_bootstrap.py` (its "no workflow gets credentials" test now names
  `deploy.yml`'s two jobs).
- **The undo.** Reverting this phase's pull request also removes `deploy.yml`, so no
  Deploy run follows a revert of the first deploy, and the stacks stay. The rollback
  for a later change is a revert pull request (its Deploy runs); taking the form
  offline at once, or removing an environment, are maintainer steps in
  `docs/runbooks/operations.md` (the form function's reserved concurrency set to 0, by
  hand, as a step he asks for). The retained table and bucket keep personal details
  until they are deleted; the runbook says so.
- **The size note**: the repository's plan rules say a phase is about 800 lines at most;
  the maintainer accepts phases up to about 5,000, so this phase isn't split.

## Required reading

- [CLAUDE.md](../../CLAUDE.md): names, tags, private photos, email, "a pull request
  from a fork is untrusted code", and what is never logged.
- [The plan's README](README.md) and
  [decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md).
- [Phase 4](phase-4-aws-adapters.md): the table's keys and indexes, the adapters' AWS
  calls and the rights each needs. [Phase 5](phase-5-aws-bootstrap.md): the bootstrap's
  exports, the execution role's rights and the two boundaries (its Hand-off, and
  [decision 0003](../../docs/decisions/0003-one-function-boundary-per-environment.md)). [Phase 6](phase-6-drop-off-form.md):
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
  - "AWS::ApiGatewayV2::Api", "::Integration", "::Route", "::Stage" and
    "AWS::Lambda::Permission" (CloudFormation template reference), "DeletionPolicy
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
| `scripts/compose_check.py` | The built artefact's smoke check: composes every email from `.aws-sam/build/`, no AWS |
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
| `PhotoBucketSuffix` | String, `AllowedPattern ^[a-z0-9]{8}$` | samconfig: 8 random lowercase hex characters per environment, made once when this phase is built (`python -c "import secrets; print(secrets.token_hex(4))"`); it keeps the bucket's global name unique without the account ID, and changing it replaces the bucket |
| `WebAdapterLayerArn` | String, `AllowedPattern ^arn:aws:lambda:us-east-2:[0-9]+:layer:LambdaAdapterLayerArm64:[0-9]+$` | the GitHub variable `WEB_ADAPTER_LAYER_ARN` (the arm64 layer's published ARN, version 27 or later; it holds its publisher's account number, which the repository's test refuses in a file). The execution role reads the layer only from the publisher account the maintainer set in the bootstrap (`WebAdapterPublisherAccount`), so a wrong variable fails the deploy |
| `AlertEmail` | `AWS::SSM::Parameter::Value<String>` | samconfig: the parameter's name, `/asmbly-ceramics/<env>/alert-email` (a String the maintainer sets by hand) |
| `InitialSendingAddress` | `AWS::SSM::Parameter::Value<String>` | samconfig: the parameter's name, `/asmbly-ceramics/<env>/initial-sending-address` (a String the maintainer sets by hand; the domain refuses an address outside `asmbly.org`) |

The two addresses are not in GitHub and not in the deploy command: samconfig and the
deploy command hold only the parameters' names. CloudFormation resolves them with the
execution role's `ssm:GetParameters` on `parameter/asmbly-ceramics/*/alert-email` and
`parameter/asmbly-ceramics/*/initial-sending-address` only (phase 5; never the keys).
`describe-stacks` and `describe-change-set` show the **resolved values**, so the deploy
workflow never runs either for an app stack, and nothing it runs prints a change set's
parameters (the Actions logs are public; runbook step 7).

The staff sign-in values (`StaffIssuer`, `StaffSignInUrl`, `StaffClientId`) are added
by phase 8, which uses them.

**Conditions**: `IsProd` (`AppEnv` = prod).

**Globals.Function**: `Runtime: python3.14`, `Architectures: [arm64]`,
`CodeUri: ../src/`, `PermissionsBoundary: {'Fn::ImportValue': !Sub '${ProjectSlug}-${AppEnv}-function-boundary-arn'}`
(its own environment's boundary, phase 5 and decision 0003; the long form, as for the
API mapping below), `RolePath: /asmbly-ceramics-app/`,
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

No variable names a key's parameter: phase 4's `SsmSecrets(client, env)`, built with
`APP_ENV`, reads `/asmbly-ceramics/<APP_ENV>/<SecretName>` itself (`hash-key`,
`form-key`, `session-key`; `ProjectSlug` must stay `asmbly-ceramics` for the names to
agree). Which keys a function may read is set by its role alone: the form's role reads
`hash-key` and `form-key`, phase 8's console role `session-key` only, and the mailer
reads no key.

Tags come from the stack (`sam deploy --tags`, below); `PropagateTags: true` on every
SAM resource that has it, so the generated roles and the event-source mapping carry
them too. CloudFormation must send them in each create request: the execution role
can't tag an API afterwards, and tags a mapping only with the five tags, never by
import (phase 5, decision 0003).

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
BucketName: !Sub ${ProjectSlug}-${AppEnv}-photos-${PhotoBucketSuffix}
# No VersioningConfiguration: versioning stays off (never Enabled or Suspended).
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

Bucket names are global across all AWS accounts; `PhotoBucketSuffix`, a random value
in `samconfig.toml`, keeps the name unique. The name never holds the account ID: the
presigned POST's `url` and the form's CSP show the bucket's name to anyone who opens the
form (below). The name still starts with `asmbly-ceramics-`, and phase 5's boundary
pattern `${ProjectSlug}-*-photos-*` matches it. Changing `BucketName` replaces the
bucket (Retain keeps the old one).

**Versioning stays off.** `S3PhotoStore.delete_drop_off` deletes a drop-off's photos
without version IDs (phase 4), so on a versioned bucket each delete would only add a
delete marker and the photos would outlive the drop-off's close (#7). Phase 4's hand-off
defers this to here: the template sets no `VersioningConfiguration`, and
`test_app_template.py` fails if `PhotoBucket` has one. Turning versioning on later needs a
decision record and a delete that removes every version.

**Settled (phase 4's privacy review): no account ID in the bucket's name.** The presigned POST
that `S3PhotoStore.upload_slots` returns has a `url` naming the bucket
(`https://<bucket>.s3.<region>.amazonaws.com/`), and `WebSettings.photo_upload_origin`
puts the same name in the page's CSP: with the account ID in the bucket's name, the
public form would show the account ID to anyone who opens it. CLAUDE.md keeps the account
ID out of every file; a page served to the public is no better. So the bucket is named
`${ProjectSlug}-${AppEnv}-photos-${PhotoBucketSuffix}` (above), the suffix a template
parameter in `samconfig.toml`, which holds no account detail.

`PhotoBucketPolicy`: one statement, `Deny` `s3:*` to `*` on the bucket and its objects
when `aws:SecureTransport` is `false`. No `Allow`: access comes only from the functions'
roles.

The HTTP API is plain CloudFormation, not `AWS::Serverless::HttpApi`: SAM's imports an
OpenAPI body (`PUT /apis`, which takes no tags) and tags the API afterwards, and phase 5's
execution role has no API Gateway tagging right ([decision 0003](../../docs/decisions/0003-one-function-boundary-per-environment.md)).
So no function has an `HttpApi` event:

- `HttpApi` (`AWS::ApiGatewayV2::Api`): `Name: !Sub ${ProjectSlug}-${AppEnv}`,
  `ProtocolType: HTTP`, `DisableExecuteApiEndpoint: true`, no `Body` or `BodyS3Location`,
  `Tags` with the five tags (a map).
- `FormIntegration` (`AWS::ApiGatewayV2::Integration`): `IntegrationType: AWS_PROXY`,
  `IntegrationUri: !GetAtt FormFunction.Arn`, `PayloadFormatVersion: "2.0"`.
- `DefaultRoute` (`AWS::ApiGatewayV2::Route`): `RouteKey: $default`,
  `Target: !Sub integrations/${FormIntegration}`.
- `HttpApiStage` (`AWS::ApiGatewayV2::Stage`): `StageName: $default`, `AutoDeploy: true`,
  `DefaultRouteSettings: {ThrottlingBurstLimit: 20, ThrottlingRateLimit: 5}`,
  `AccessLogSettings` to `HttpApiLogGroup` with fields `requestId`, `routeKey`, `status`,
  `responseLength`, `integrationLatency`, and no source address, user agent or query
  string; `Tags` with the five tags. No `AWS::Logs::ResourcePolicy`: the bootstrap's
  `asmbly-ceramics-log-delivery` policy lets log delivery write
  `/aws/apigateway/asmbly-ceramics-*`, and the execution role is denied
  `logs:PutResourcePolicy` (decision 0003, with the fallback if the stage still asks
  for it). If the integration or route is refused because it doesn't see the API's
  tags, decision 0003's fallback applies (the API's ID as a bootstrap parameter).
- `FormInvokePermission` (`AWS::Lambda::Permission`): `Action: lambda:InvokeFunction`,
  `Principal: apigateway.amazonaws.com` (the only principal the execution role may
  grant), `SourceArn: !Sub arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${HttpApi}/*`.

`HttpApiMapping` (`AWS::ApiGatewayV2::ApiMapping`): `DomainName: {'Fn::ImportValue': !Sub '${ProjectSlug}-${AppEnv}-domain-name'}`
(phase 5's export; the long form, because CloudFormation refuses `!ImportValue` around a short-form `!Sub`), `ApiId: !Ref HttpApi`,
`Stage: !Ref HttpApiStage`.

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
# No Events: the API reaches it through FormIntegration and FormInvokePermission.
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
- Sid: ReadStudioAndSubmissions        # never a drop-off: the ID page reads the submission's summary;
  Effect: Allow                         # GetItem only: the form's use cases read by key, never query
  Action: dynamodb:GetItem
  Resource: !GetAtt RecordsTable.Arn
  Condition:
    ForAllValues:StringLike: {dynamodb:LeadingKeys: ["STUDIO", "SUBMISSION#*"]}
- Sid: CreateDropOffs                  # new items only, through the submit transaction; the
  Effect: Allow                         # studio's seeding puts STUDIO/CURRENT and STUDIO/HISTORY#…
  Action: dynamodb:PutItem              # commit sends only Put actions (phase 4): no ConditionCheckItem
  Resource: !GetAtt RecordsTable.Arn
  Condition:
    ForAllValues:StringLike:
      dynamodb:LeadingKeys: ["DROPOFF#*", "EMAIL#*", "SUBMISSION#*", "STUDIO"]
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
- Sid: TransactOnTheTable                # TransactWriteItems is authorised per item action above (PutItem)
  Effect: Allow
  Action: dynamodb:TransactWriteItems   # if the IAM reference lists it as an action; see Required reading
  Resource: !GetAtt RecordsTable.Arn
- Sid: Uploads                         # PutObject: the role that signs the POST must hold it;
  Effect: Allow                         # GetObject: read_upload; Put and Delete: discard_uploads
  Action: [s3:PutObject, s3:GetObject, s3:DeleteObject]
  Resource: !Sub ${PhotoBucket.Arn}/uploads/*
- Sid: KeepPhotos                      # DeleteObject: keep's own rollback and the submit's
  Effect: Allow                         # cleanup after a failed commit (phase 2b, step 7);
  Action: [s3:PutObject, s3:DeleteObject] # the backstop for a failed cleanup is #19
  Resource: !Sub ${PhotoBucket.Arn}/dropoffs/*
- Sid: ListUploads                     # read_upload lists uploads/<slot id>/ (the upload and
  Effect: Allow                         # its `used` marker): a GET's 403 can't tell "absent"
  Action: s3:ListBucket
  Resource: !GetAtt PhotoBucket.Arn
  Condition:
    StringLike: {s3:prefix: 'uploads/*'}
- Sid: ReadOwnKeys
  Effect: Allow
  Action: ssm:GetParameter
  Resource:
    - !Sub arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/${ProjectSlug}/${AppEnv}/hash-key
    - !Sub arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/${ProjectSlug}/${AppEnv}/form-key
```

The form never gets `s3:GetObject` on `dropoffs/*`, `s3:ListBucket` on any prefix but
`uploads/*` (it can't list kept photos' keys: `delete_drop_off` deletes 12 known keys
without listing, phase 4), any read of a `DROPOFF#`, `EMAIL#`
or `LOAD#` item, `UpdateItem` on them, `dynamodb:Scan`, any `Query` (its use cases read
by key only: the studio, a submission, a rate item), `ConditionCheckItem` (phase 4's
`commit` sends only `Put` actions, each with its own condition), the console's
`session-key`, or any SES right. IAM can't require
`attribute_not_exists` on a `PutItem`, so a form function whose code was taken over
could still overwrite a drop-off item with a `Put`; that is accepted in decision 0002
(the mailer re-reads each drop-off by key, so only an overwritten one could be
affected). `STUDIO` writes are for phase 2a's
`CurrentStudio` first-use seeding of the studio from `INITIAL_SENDING_ADDRESS` (a conditional put that
does nothing once it exists). Decision 0002 lets the form only read settings, so this
right, and the `DROPOFF#*`/`EMAIL#*` puts above, are in the decision record amending 0002
that the README's Admin actions ask for before this phase merges; the pull request's
**Risk** section names both. No other function exists in this phase to seed the studio
(the console comes in phase 8), and seeding from the deploy would give the deploy role
rights over the table's data. Decrypting the SecureStrings uses the AWS managed key for
SSM, which the boundary allows through `kms:ViaService` (phase 5).

Mailer function:

```yaml
- Sid: ReadWhatAnEmailNeeds            # the email, its drop-off and the studio (STUDIO/CURRENT);
  Effect: Allow                         # SendPendingEmail reads no load
  Action: dynamodb:GetItem
  Resource: !GetAtt RecordsTable.Arn
  Condition:
    ForAllValues:StringLike: {dynamodb:LeadingKeys: ["EMAIL#*", "DROPOFF#*", "STUDIO"]}
- Sid: MarkEmails                      # claim, sent, failed, cancelled: the only writes the mailer
  Effect: Allow                         # makes. Each is an `Update` that phase 4's commit sends as a
  Action: dynamodb:PutItem              # transactional Put of the whole item under its version
  Resource: !GetAtt RecordsTable.Arn    # check, so PutItem, not UpdateItem
  Condition:
    ForAllValues:StringLike: {dynamodb:LeadingKeys: ["EMAIL#*"]}
- Sid: TransactOnTheTable                # as the form's: authorised per item action (PutItem above)
  Effect: Allow
  Action: dynamodb:TransactWriteItems   # if the IAM reference lists it as an action; see Required reading
  Resource: !GetAtt RecordsTable.Arn
- Sid: ReadTheStream
  Effect: Allow
  Action: [dynamodb:DescribeStream, dynamodb:GetRecords, dynamodb:GetShardIterator]   # no ListStreams: it takes no resource, and the boundary leaves it out
  Resource: !GetAtt RecordsTable.StreamArn
- Sid: ReadKeptPhotos
  Effect: Allow
  Action: s3:GetObject
  Resource: !Sub ${PhotoBucket.Arn}/dropoffs/*
- Sid: ListKeptPhotos                  # read lists dropoffs/AC-n/ after a 403, so a gone
  Effect: Allow                         # photo is UploadMissing, not PhotosUnavailable (phase 4)
  Action: s3:ListBucket
  Resource: !GetAtt PhotoBucket.Arn
  Condition:
    StringLike: {s3:prefix: 'dropoffs/*'}
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
parameter_overrides = "AppEnv=stage SiteHost=ceramics-stage.asmbly.org PhotoBucketSuffix=<8 random hex characters>"

[prod.deploy.parameters]
stack_name = "asmbly-ceramics-prod"
# … the same, with Environment=prod, AppEnv=prod, SiteHost=ceramics.asmbly.org and
# prod's own PhotoBucketSuffix
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

Each creates its boto3 clients once (module-level cache), the DynamoDB, S3 and SSM
clients with `adapters.aws.clients.CLIENT_CONFIG` and the SES client with
`adapters.aws.mailer.SES_CLIENT_CONFIG` (phase 4: timeouts and tries that give up
before API Gateway's 30 s; botocore's defaults don't), builds phase 4's adapters
(`DynamoDbRecords`, `DynamoDbIdNumbers`, `DynamoDbRateLimiter`, `S3PhotoStore`,
`PillowPhotoInspector`, `SesMailer`, `SsmSecrets`, `SystemClock`) and phase 2's and 3's
use cases.

Two timeouts the composition sets, from phase 4's review:

- **The mailer's SES read timeout.** `SES_CLIENT_CONFIG`'s 10 s read is sized for a call
  behind API Gateway's 30 s (phase 9's test email). The mailer runs from the stream with
  no gateway and a 60 s timeout, and a slow answer to a six-photo message would turn into
  "may have been sent" (`SendFailed(<timeout class>)`, outside `REFUSED_CODES`).
  `build_mailer` builds its SES client with
  `SES_CLIENT_CONFIG.merge(Config(read_timeout=30))`: still one attempt, the same connect
  timeout, and well inside the function's 60 s with the photos' reads. The console's
  client (phase 9) keeps `SES_CLIENT_CONFIG` as it is. `test_the_mailer_builds` asserts
  the mailer's client has one attempt and the 30 s read.
- **A whole request's bound.** `clients.CLIENT_CONFIG` bounds each call (at most about
  18 s with its retries), not a request: a submit makes many calls in sequence (two rate
  hits, the studio and the submission, a listing and a read per photo, the ID, twelve
  photo puts, the commit, the discards), so a slow AWS could run it past the function's
  29 s and API Gateway's 30 s, ending in a gateway timeout with nothing logged by the
  app. The form function needs a bound for the request as a whole that ends it, logged,
  before 29 s: a per-request deadline (for example 25 s from the request's start) that
  the web layer checks between the submit's steps and answers with phase 6's 503 page
  and a `drop_off_unavailable` line, or a shorter per-call config for the form's clients
  with the worst case summed and shown under 29 s. Either way a submit cut short may
  already have committed, which phase 2b's repeat-with-the-same-token answers. `/prep`
  of this phase picks one and states it; phase 6's hand-off says where the web layer
  checks it.

`WebSettings.photo_upload_origin` is
`https://<bucket>.s3.<region>.amazonaws.com`, the host `S3PhotoStore.upload_slots`
presigns its POSTs to because the S3 client is built with `CLIENT_CONFIG` (its
`addressing_style="virtual"`; botocore's default would presign to the global
`https://<bucket>.s3.amazonaws.com`, which the CSP blocks). `test_form_services_build_on_stubbed_clients`
asserts a slot's `post.url` starts with `photo_upload_origin`; `WebSettings.cookie_key` is
`Secrets.get(SecretName.FORM_KEY)`, with `SsmSecrets(client, settings.app_env)`. The
form function reads `hash-key` and `form-key` only. Phase 8 adds `build_console_services` and
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

That holds only while API Gateway's HTTP API is the last hop before the function: it
appends the address it saw to whatever `X-Forwarded-For` the caller sent. A CDN, a
CloudFront distribution or another proxy put in front of it would make the last value
that hop's address (every person would share one rate-limit key) or, if it passes the
caller's header through, change which value is trustworthy; adding one needs this rule
re-decided first. Before this phase goes live, confirm in AWS's API Gateway
documentation (HTTP API, payload format 2.0, and the Lambda Web Adapter's mapping of it)
that the appended value is the caller's source address, and run phase 6's stage check
(a request sent with its own `X-Forwarded-For` reaches the function with the caller's
real address last). If either fails, the address limit is void and prod waits.

**Never import `web.local`.** `asmbly_ceramics.web.local` (phase 6) builds the
in-memory fakes on import and adds its own `X-Forwarded-For`; it is for `uv run` on a
laptop only. `run.sh` starts `web.app`'s factory and nothing else; `composition.py`,
`settings.py`, the entry points and anything they import never import `web.local`, and
the bundle leaves it out (or a test asserts that importing every entry point's module
leaves `asmbly_ceramics.web.local` out of `sys.modules`). The brand already moved to the
neutral `asmbly_ceramics.brand` (phase 6's review), so `mail/` no longer imports `web/`
and the mailer's bundle needs no Starlette (`tests/mail/test_compose.py` checks it).

`entry/mailer.py`:

```python
def handler(event: dict[str, Any], context: object) -> dict[str, list[dict[str, str]]]:
    """For each stream record, send its email; report the ones that failed to retry."""
```

For each record: read `PK`/`SK` from `dynamodb.Keys` (never the image's personal
fields), turn them into the email's key with phase 4's `keys.parse_email_key` (the
inverse of `email_key`; a key it refuses is logged as `mailer_bad_key` with no key text
and skipped, not retried), and call `SendPendingEmail(drop_off_id, kind, occasion)`; a
`SendFailed` is the use case's
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
3. `aws-actions/configure-aws-credentials@v6` with `role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}`
   (an environment secret: a role ARN holds the account ID, and GitHub prints a step's
   `with:` inputs in the public log),
   `aws-region: ${{ vars.AWS_REGION }}`, `mask-aws-account-id: true`; then, before any
   step that prints, `echo "::add-mask::$(aws sts get-caller-identity --query Account
   --output text)"`, so the account ID (in role ARNs) is masked in
   the public Actions log.
4. `sam build --config-env "$CONFIG_ENV"`, then **compose check**: `python3
   scripts/compose_check.py .aws-sam/build/MailerFunction`. Phase 2c checked the
   templates ship by listing a `uv build` wheel, but the functions deploy from `sam
   build` of `CodeUri: ../src/`, so this step proves the built artefact holds them: it
   puts the build directory first on `sys.path`, checks
   `asmbly_ceramics.mail.compose` loaded from there, composes `received`, `ready`,
   `rejected` and `test` with `JinjaComposer` from made-up data (names built in code,
   `example.org` addresses) and exits 1, naming the template, if one fails. It prints
   no body and sends nothing.
5. `sam deploy --config-env "$CONFIG_ENV" --no-progressbar --role-arn "$EXECUTION_ROLE"
   --s3-bucket "$ARTIFACTS_BUCKET" --parameter-overrides "$(python3 scripts/sam_parameters.py
   "$CONFIG_ENV" "AppVersion=${GITHUB_SHA::7}" "WebAdapterLayerArn=$WEB_ADAPTER_LAYER_ARN")"`,
   with those values in `env:`: `EXECUTION_ROLE` from `secrets.AWS_CFN_EXECUTION_ROLE_ARN`,
   the bucket and the layer ARN from `vars.*`. The addresses are SSM-typed parameters
   named in samconfig, so no address is in the command or its output.
6. **Smoke test**: `python3 scripts/smoke.py "https://<site host>" "${GITHUB_SHA::7}"`,
   no credentials needed (the step runs after the deploy; the job's credentials expire
   in an hour and the script doesn't use them).
7. Write only the site URL, the version and the smoke result to `GITHUB_STEP_SUMMARY`:
   no stack output or role ARN (a role ARN holds the account ID), no bucket name, and no
   address.

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
- `PhotoBucket`'s `BucketName` is `${ProjectSlug}-${AppEnv}-photos-${PhotoBucketSuffix}`
  (no `AWS::AccountId` in it), and `PhotoBucket` has no
  `VersioningConfiguration` (versioning stays off: `delete_drop_off` deletes without
  version IDs, so versions would outlive the close, #7);
- the bucket's four public-access settings are true, ownership is `BucketOwnerEnforced`,
  encryption is set, the policy denies non-TLS and has no `Allow` and no `Principal: "*"`
  other than in that Deny, the lifecycle expires `uploads/` after 1 day, CORS allows
  only `POST` from `https://${SiteHost}`. This test is the fence: phase 5's execution
  role changes the photo bucket by name, and no IAM condition sees these settings;
- no `AWS::Serverless::HttpApi`, no `HttpApi` event, no `Body` on the
  `AWS::ApiGatewayV2::Api`; every `AWS::Lambda::Permission` has
  `Principal: apigateway.amazonaws.com`; no `AWS::Logs::ResourcePolicy`;
- every IAM role's `AssumeRolePolicyDocument` trusts only `lambda.amazonaws.com` (or
  `scheduler.amazonaws.com` for phase 9's scheduler role): IAM has no condition on a
  trust policy's content, so this test is the fence;
- no statement in any role has `Resource: "*"`, `s3:*` with an `Allow`, or `iam:*`;
- the form's role has no `s3:GetObject` on `dropoffs/*`, no `s3:ListBucket` except with
  `s3:prefix` `uploads/*`, no `dynamodb:Scan`, no `dynamodb:Query`, no `ses:*`; the
  mailer's (and phase 8's console's) `s3:ListBucket` has `s3:prefix` `dropoffs/*`;
- the DynamoDB writes match phase 4's adapters: every role that commits has
  `dynamodb:PutItem` (a commit's `Update` is a conditional `Put`); `dynamodb:UpdateItem`
  appears only with `dynamodb:LeadingKeys` `COUNTER#*` (the ID counter); no role has
  `dynamodb:ConditionCheckItem`, `DeleteItem` or `Scan`; the mailer's only write is
  `PutItem` on `EMAIL#*`;
- the only `ses:SendEmail` is the mailer's, on the `asmbly.org` identity, with
  `ses:FromAddress` limited to that domain;
- the mailer's event filter matches `status = pending` and the outbox type, with retries
  bounded and an on-failure queue;
- every alarm has `AlarmActions` on `AlarmTopic` and `TreatMissingData: notBreaching`;
  `EmailFailuresAlarm` counts the `email_failed` event;
- the template holds no 12-digit number and no address with an `@` other than the
  `*@${EmailDomain}` pattern;
- every function has `PermissionsBoundary` from its own environment's bootstrap export
  (`${ProjectSlug}-${AppEnv}-function-boundary-arn`), `RolePath: /asmbly-ceramics-app/`,
  and a log group with retention.

And `tests/repo/test_deploy_workflow.py`: the two jobs, `prod` needs `stage`, both have
the tip-of-main step with identical text, the smoke step, `cancel-in-progress: false`;
the role ARNs come only from `secrets.AWS_DEPLOY_ROLE_ARN` and
`secrets.AWS_CFN_EXECUTION_ROLE_ARN`, never `vars.*`, and no other secret is read; no
step echoes a secret or writes one to `GITHUB_STEP_SUMMARY`.

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
- `tests/scripts/test_compose_check.py`: passes on a directory holding the package;
  fails, naming the template, on a copy with a template removed, and on a directory
  without the package (it must not fall back to the installed one).
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
   writes only `EMAIL#` items (`PutItem` with `dynamodb:LeadingKeys` `EMAIL#*`, since
   phase 4's `commit` sends every `Update` as a conditional `Put`; no `UpdateItem`, no
   `ConditionCheckItem`) and reads no `LOAD#` item; only the mailer can send
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
| A six-photo drop-off at the limits on stage | the maintainer, with made-up details: six photos of about 10 MB each | the ID page, not the 503 (the 14 s work budget fits); if not, the budget or the form's memory changes before prod's address is published | none: it closes like any other |
| A real drop-off on stage | the maintainer, with made-up details | the ID, the email with photos, no location in them | none: the drop-off closes like any other (phase 9) or stays waiting on stage |
| The alarm | the maintainer, on stage | the notification arrives | the alarm returns to OK by itself |

### If the first create of a stack fails

A first create that is refused rolls back to `ROLLBACK_COMPLETE`, keeps the retained
table and bucket, and can only be deleted, which the deploy roles can't do. The
maintainer's steps by hand (read why, check the table and bucket are empty, delete the
stack and them, fix, deploy again, and decision 0003's API fallback), each with its
Do, Check, Who confirms and Undo, are in the runbook:
[If the first create of a stack fails](../../docs/runbooks/operations.md#if-the-first-create-of-a-stack-fails).

Removing an environment entirely is a step for the maintainer by hand: delete the
stack, then, only if the data is truly not wanted, the retained table (turn deletion
protection off first) and the bucket. Nothing in the workflow deletes data.

The prod form is live from this phase but its address isn't published (phase 10 does
that), and no QR code points to it. Nobody is told yet.

## Admin actions

- Before merging (phase 2b's reviews): the maintainer's word on the four points the
  plan README's Admin actions lists, recorded in a new decision record that amends
  decision 0002 (CLAUDE.md: a past decision is changed only by a new record that says
  why; a Risk section is not enough): (1) the form function's role may delete photos
  under `dropoffs/` (for the submit's cleanup; it never lists them, phase 4), which
  decision 0002's role table gives the close only, and the backstop for photos left
  under `dropoffs/` with no record (#19) is decided and built before prod takes real
  drop-offs, so no photo outlives #7; (2) the form function's role may `PutItem` on
  `STUDIO` (phase 2a's first-use seeding), which 0002 does not allow the form; (3) the
  form's `PutItem` on `DROPOFF#*` and `EMAIL#*` can't require `attribute_not_exists`
  (restating what 0002 accepts); (4) the photo bucket is named
  `asmbly-ceramics-<env>-photos-<suffix>`, a random suffix, not 0002's
  `asmbly-ceramics-<env>-photos-<account>`, so the public form never shows the account
  ID (above).
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
- Before merging: in both GitHub environments, the secrets `AWS_DEPLOY_ROLE_ARN` and
  `AWS_CFN_EXECUTION_ROLE_ARN` and the variables `AWS_REGION`, `SAM_ARTIFACTS_BUCKET`
  (from phase 5's outputs) and `WEB_ADAPTER_LAYER_ARN` (the arm64 layer's published ARN
  for us-east-2, from the publisher account set in the bootstrap). No address is in
  GitHub.
- After the first deploy: confirm the SNS subscription from the email AWS sends to
  `/asmbly-ceramics/<env>/alert-email` for each environment.

## Hand-off

Built on 15 November 2026 (branch `feat/drop-off-and-firing-phases-7-9`). Where the
list below this paragraph differs from what was built, this paragraph wins:

- **Template** `infra/app.yaml`: the logical IDs listed below, except that the metric
  filters are `EmailFailuresFilter` (mailer only), `FormLoggedErrorsFilter` and
  `MailerLoggedErrorsFilter`; outputs `SiteUrl`, `PhotoBucketName`, `TableName` (no
  ARN). Phase 8's `ConsoleFunction` adds a `LoggedErrors` filter on its own group and a
  `MetricStat` to `FunctionErrorsAlarm`'s metric math, its own throttling on the
  console's routes, and a `test_app_template.py` row for its role.
- **Composition**: `asmbly_ceramics.settings.Settings.from_environment()`;
  `asmbly_ceramics.composition.build_form_services(settings=None, clients=None)` and
  `build_mailer(settings=None, clients=None)`; the client bundles
  `adapters.aws.clients.FormClients.build(region)` / `MailerClients.build(region)`
  (cached per container; phase 8 adds `ConsoleClients` there, never boto3 in
  `composition.py`); `web.app.create_from_environment()` (checks `APP_ROLE` against
  `web.app.APP_ROLES`, configures logging, adds `RequestDeadline`).
- **The request bound** (changed in review): `asmbly_ceramics.deadline`
  (`REQUEST_BUDGET_SECONDS = 14` for the work, `CLEANUP_BUDGET_SECONDS = 22` for what
  runs inside `deadline.cleanup()`: `S3PhotoStore`'s deletes and the submission re-read,
  so a submit cut off after keeping photos still deletes them; a commit refused by the
  deadline is `RecordsUnavailable`, not `CommitOutcomeUnknown`; the hook is registered
  first among `before-send` handlers),
  `web.app.RequestDeadline`, and `adapters.aws.deadline.check_deadline(client)`, which
  every client built by `adapters.aws.clients` carries: after the deadline an AWS call
  raises `DeadlinePassed` (a `BotoCoreError`), so the adapter raises its port's
  `Unavailable` (`DeadlinePassedOnRetry`, after an attempt that may have landed, is an
  unknown outcome, never "not sent"). The console's botocore calls follow it as they
  are; `adapters/aws/staff_tokens.py` calls Cognito with `urllib` (5 s each) and never
  sees the deadline, which phase 8 bounds itself.
- **Timeouts**: the mailer's SES client is `adapters.aws.mailer.STREAM_SES_CLIENT_CONFIG`
  (one attempt, 30 s read); the console's test email keeps `SES_CLIENT_CONFIG`.
- **Logging**: `asmbly_ceramics.logs.configure_logging(level, version)`; fields
  `level`, `logger`, `message` (a template, never its arguments), `version` and
  `use_cases.log.LOG_FIELDS`; an exception only as `error_code`.
- **Scripts**: `scripts/smoke.py <site> <version>` (check 3, `console`, is phase 8's to
  change), `scripts/sam_parameters.py <config-env> [Key=Value ...]`,
  `scripts/compose_check.py <build dir>`.
- **Names**: bucket suffixes `faa1243f` (stage) and `853de865` (prod) in
  `samconfig.toml`; the SAM CLI is `1.172.1` in both workflows' `env`.
- **Rights** (from review): every `PutItem` a role may make carries
  `StringEqualsIfExists dynamodb:ReturnValues NONE`, and the puts on drop-offs, emails,
  submissions and the studio also `ForAnyValue:StringEquals dynamodb:EnclosingOperation
  [TransactWriteItems]` (only inside `Records.commit`). Phase 8's console role and phase
  9's close role follow it, and `test_app_template.py`'s pin is extended to them.
- **Not yet known** (the first deploy settles them): S3's answer to the oversized POST
  (the smoke test prints it), the phone checks, that the submit's transaction is
  authorized item by item as the roles expect (with `EnclosingOperation`), whether Lambda
  wants `dynamodb:ListStreams` (which the role and the boundary leave out) to create the
  mailer's stream mapping (if so the first create rolls back: the recovery above), and
  whether a six-photo submit at the size limit fits the 14 s work budget: on stage,
  before prod's address is published, submit six photos of about 10 MB each and expect
  the ID page, not the 503.

The plan's list, as written before the build:

- **Template logical IDs**: `RecordsTable`, `PhotoBucket`, `PhotoBucketPolicy`, `HttpApi`,
  `FormIntegration`, `DefaultRoute`, `HttpApiStage`, `FormInvokePermission`,
  `HttpApiMapping`, `FormFunction`, `MailerFunction`, `MailerDeadLetterQueue`,
  `FormLogGroup`, `MailerLogGroup`, `HttpApiLogGroup`, `AlarmTopic`,
  `AlarmEmailSubscription`, `EmailFailuresAlarm`, `LoggedErrorsAlarm`,
  `MailerDeadLettersAlarm`, `FunctionErrorsAlarm`, `Api5xxAlarm`. Phase 8 adds
  `ConsoleFunction` with its own `AWS::ApiGatewayV2::Integration`, `Route`s
  `ANY /console` and `ANY /console/{proxy+}` (more specific than `$default`) and
  `AWS::Lambda::Permission` (no `HttpApi` events, decision 0003), and the parameters `StaffIssuer`, `StaffSignInUrl`,
  `StaffClientId`; phase 9 adds `CloseFunction`, `CloseSchedule`, `CloseDeadLetterQueue`.
- **Environment variables**: `APP_ENV`, `APP_VERSION`, `TABLE_NAME`, `PHOTO_BUCKET`,
  `SITE_URL`, `INITIAL_SENDING_ADDRESS`, `LOG_LEVEL` (no key's parameter name: `SsmSecrets`
  builds it from `APP_ENV`; the roles decide which keys each function reads), and on web functions `AWS_LAMBDA_EXEC_WRAPPER`, `PORT`,
  `AWS_LWA_READINESS_CHECK_PATH`, `APP_ROLE` (`form`). Phase 8 adds `STAFF_ISSUER`, `STAFF_SIGN_IN_URL`,
  `STAFF_CLIENT_ID`.
- **Log fields**: `level`, `message`, `event`, `drop_off_id`, `load_id`, `user`, `error_code`,
  `outcome`, `fields`, `version`; the `email_failed` event feeds `EmailFailuresAlarm`.
- **Composition**: `Settings.from_environment()`, `build_form_services()`,
  `build_mailer()`; `web.app.create_from_environment()`; `entry/run.sh`.
- **The smoke test**: `scripts/smoke.py <site> <version>`; check 3 is phase 8's to change.
- **Names**: stacks `asmbly-ceramics-stage` and `asmbly-ceramics-prod`; table
  `asmbly-ceramics-<env>-records`; bucket `asmbly-ceramics-<env>-photos-<suffix>`;
  alarm topic `asmbly-ceramics-<env>-alarms`.
- The S3 answer to a too-large POST, as the first smoke run printed it, and the phone
  tests' results (iOS version, JPEG or not).
- **Timeouts**: the mailer's SES client reads for 30 s (one attempt); the console's test
  email keeps `SES_CLIENT_CONFIG`'s 10 s. The bound chosen for a whole web request (the
  deadline, or the per-call worst case summed), which phase 8's console requests follow
  too.
- **Rights**: every role that commits holds `dynamodb:PutItem` (phase 4 sends a commit's
  `Update` as a conditional `Put`); `dynamodb:UpdateItem` only on `COUNTER#*`; no role
  holds `ConditionCheckItem`. Phase 8's console role and phase 9's close role follow it.

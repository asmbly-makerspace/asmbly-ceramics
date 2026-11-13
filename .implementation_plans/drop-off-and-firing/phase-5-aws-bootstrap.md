---
phase_id: 5
title: "AWS bootstrap: roles, boundary, addresses"
epic: 1
implements: []
depends_on: []
domain: [infra, docs]
estimated_size: M
---

# Phase 5: AWS bootstrap: roles, boundary, addresses

> **Status:** [ ] Pending

## Required reading

- [CLAUDE.md](../../CLAUDE.md): names start with `asmbly-ceramics-`, the five tags, tag
  conditions from the start, no account ID in a file, never touch another project's
  resources, AWS changes only by a runbook step the maintainer asks for.
- [The plan's README](README.md): Admin actions, Rollout, Security.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md),
  "The deploy: SAM, a bootstrap stack, stage then prod".
- The closest existing example: AsmblyMCPs' `infra/bootstrap.yaml` (the
  `GitHubDeployRole`, `CloudFormationExecutionRole`, `FunctionBoundary` and
  `ArtifactsBucket`; the Deny on `ProtectedProjectTag`; `GrantOnlyInsideTheBoundary`)
  and its `docs/runbooks/aws-bootstrap.md` §4–§5 (deploying by hand with a change set,
  then the GitHub variables). Copy the shape, not the names, and add what it lacks: tag
  conditions (`aws:RequestTag` on create, `aws:ResourceTag` afterwards; AsmblyMCPs#9)
  and the `Owner` and `ManagedBy` tags. asmbly-staff-login's
  `docs/runbooks/move-the-pool.md` for the check, undo and named confirmer on each step.
- AWS's documentation, read for this plan on 13 November 2026 (under
  `https://docs.aws.amazon.com`):
  - The Service Authorization Reference, one page per service
    (`/service-authorization/latest/reference/list_<service>.html` for `dynamodb`, `s3`,
    `lambda`, `apigateway`, `scheduler`, `sns`, `sqs`, `cloudwatch`, `logs`, `iam`,
    `acm`): which actions accept `aws:RequestTag`, `aws:ResourceTag` and
    `aws:TagKeys`. What they say is in the table under Implementation details.
  - "Set up a Regional custom domain name in API Gateway"
    `/apigateway/latest/developerguide/apigateway-regional-api-custom-domain-create.html`:
    the certificate must be in the API's Region; the DNS record points at the Regional
    domain name.
  - "Actions, resources, and condition keys for Amazon Simple Email Service v2"
    `/service-authorization/latest/reference/list_sesv2.html` and "Identity and access
    management in Amazon SES" `/ses/latest/dg/control-user-access.html`: `ses:SendEmail`
    on the identity ARN, `ses:FromAddress`.
  - "Using sending authorization with Amazon SES" `/ses/latest/dg/sending-authorization.html`:
    a sender in the same account needs only IAM; no identity policy.
  - "DeletionPolicy attribute" `/AWSCloudFormation/latest/TemplateReference/aws-attribute-deletionpolicy.html`.

## Goal

A plain CloudFormation template, `infra/bootstrap.yaml`, that a person with admin rights
deploys once by hand as the stack `asmbly-ceramics-bootstrap`, and a runbook that says
how, with a check and an undo for each step. After it is deployed:

- GitHub Actions, from the `stage` and `prod` environments of this repository only, can
  assume a deploy role that can do nothing but hand the two app stacks
  (`asmbly-ceramics-stage`, `asmbly-ceramics-prod`) to CloudFormation;
- CloudFormation deploys those stacks with an execution role that can create and change
  only `asmbly-ceramics-` resources carrying `Project=asmbly-ceramics`, can create roles
  only under the path `/asmbly-ceramics-app/` and only with the permissions boundary,
  and is denied everything on another project's resources and on the bootstrap itself;
- every function role is held inside a boundary that allows only what the app's
  adapters call (phase 4), with email only from `asmbly.org` addresses;
- the two addresses, `ceramics.asmbly.org` and `ceramics-stage.asmbly.org`, exist as API
  Gateway custom domain names with issued certificates and DNS records, ready for the
  app stacks to map their APIs to (phase 7).

CI checks the template with `cfn-lint` on every pull request, and `tests/repo/` pins its
security properties. Nothing in the template holds an account ID, an address of a
person, or a secret.

## Files to create

- `infra/bootstrap.yaml`: the template (below).
- `docs/runbooks/aws-bootstrap.md`: the runbook (below).
- `tests/repo/cloudformation.py`: `load_template(path) -> dict[str, Any]`, a
  `yaml.SafeLoader` subclass that reads CloudFormation's short tags (`!Ref`, `!Sub`,
  `!GetAtt`, `!Join`, `!If`, `!Equals`, `!Not`, `!Select`, `!Split`, `!ImportValue`,
  `!FindInMap`, `!Condition`, `!Base64`, `!GetAZs`) into their long forms
  (`{"Fn::Sub": ...}`), so tests can walk the template. Phase 7 reuses it for
  `infra/app.yaml`.
- `tests/repo/test_bootstrap.py`: the pins (Tests).

## Files to modify

- `CLAUDE.md`, "Done means verified": add the line
  `uvx cfn-lint==1.57.1 infra/*.yaml                      # after a template change`
  after the `pytest` line, and in its paragraph after the block, that `tests/repo/`
  also checks the bootstrap's roles. In the table at the top, the "Production tasks"
  row's "Read first" becomes the runbook's path (written in a code span until the file
  exists in the same commit; then as a link).
- `.github/workflows/pr-checks.yml`: a top-level `env:` with `CFN_LINT_VERSION: '1.57.1'`;
  a job `infra` (name `Templates`, `runs-on: ubuntu-24.04`, `timeout-minutes: 10`,
  steps: checkout, `astral-sh/setup-uv@v7`, then
  `run: uvx "cfn-lint==${CFN_LINT_VERSION}" infra/*.yaml`); `pr-check`'s `needs`
  becomes `[python, infra]`. No credentials, no environment: `test_workflows.py`'s
  checks stay as they are and still pass. The version appears only in `env`, which
  `test_each_workflow_spells_a_version_out_only_in_its_env` requires.
- `tests/repo/test_checks.py`: a new test,
  `test_claude_md_and_ci_use_the_same_cfn_lint`, that the `cfn-lint==<version>` in
  CLAUDE.md's block equals `workflow_version("pr-checks.yml", "CFN_LINT_VERSION")`,
  and that every document naming `cfn-lint==` names that version (extend
  `test_every_document_names_the_versions_the_workflows_use` with `pinned("cfn-lint", ...)`).
  `test_ci_runs_every_uv_command_claude_md_names` checks only `uv run` commands, so the
  `uvx` line needs no change there.
- `README.md` ("Run the checks") and `.github/PULL_REQUEST_TEMPLATE.md` (its checks
  list): add the `cfn-lint` line, so the three places that give the checks agree.
- `docs/README.md`, "Runbooks": replace "None yet…" with a link to
  `runbooks/aws-bootstrap.md` and one line: "Deploy the bootstrap stack (deploy roles,
  boundary, addresses) and set up the GitHub environments. Once, by hand."

## Implementation details

### infra: parameters

| Parameter | Type and default | Notes |
| --- | --- | --- |
| `ProjectSlug` | String, `asmbly-ceramics`, `AllowedPattern: '^asmbly-ceramics$'` | Every name and every IAM pattern is built from it. The pattern holds it to the repository's name, which is also the `Project` tag value (CLAUDE.md). |
| `GitHubSubjectPrefix` | String, no default, `AllowedPattern: '^repo:asmbly-makerspace@[0-9]+/asmbly-ceramics@[0-9]+$'` | The OIDC `sub` prefix in its numeric-ID form. Read it with `gh api repos/asmbly-makerspace/asmbly-ceramics/actions/oidc/customization/sub --jq .sub_claim_prefix` (runbook step 2). If the repository uses GitHub's default subject, the runbook sets the ID-based one first, as AsmblyMCPs did. |
| `ParentHostedZoneId` | `AWS::Route53::HostedZone::Id`, no default | The `asmbly.org` zone, which another project owns. Passed by hand. |
| `ProdDomainName` | String, `ceramics.asmbly.org` | |
| `StageDomainName` | String, `ceramics-stage.asmbly.org` | |
| `EmailIdentityDomain` | String, `asmbly.org` | The SES identity AsmblyMCPs' `mcp-bootstrap` owns. |
| `ProtectedProjectTags` | CommaDelimitedList, `mcp-platform,mcp-door,mcp-ceramics,staff-login,asmbly-login-service,shared,Shared,shared-infrastructure` | Resources tagged with any of these `Project` values are denied to every role here. Runbook step 1 lists the account's `Project` tag values (read only) so the maintainer can add any that are missing before deploying. |
| `CreateGitHubOidcProvider` | String, `false`, `AllowedValues: [true, false]` | The account already has the provider (another project made it); runbook step 1 checks. |

A condition `CreateOidcProvider` (`!Equals [!Ref CreateGitHubOidcProvider, 'true']`)
creates `GitHubOidcProvider` only when asked.

### infra: names, paths and tags

- Stack name: `asmbly-ceramics-bootstrap`.
- Roles and the boundary are under the IAM path `/asmbly-ceramics-bootstrap/`, and the
  app's function roles (phase 7) under `/asmbly-ceramics-app/`. Every name still starts
  with `asmbly-ceramics-` as CLAUDE.md requires; the **path** is what lets the execution
  role manage `role/asmbly-ceramics-app/*` and nothing at
  `role/asmbly-ceramics-bootstrap/*`, so no app stack can edit the roles that deploy
  it.
- Stack tags, set on the `deploy` command and propagated by CloudFormation:
  `Project=asmbly-ceramics Component=Bootstrap Environment=shared Owner=it-volunteers ManagedBy=cloudformation`.
  The template also sets them on each resource that takes `Tags` (roles, the bucket,
  the certificates, the domain names) so they don't depend on propagation.
  - **Open question for the maintainer:** CLAUDE.md lists `Environment=<prod or stage>`.
    The bootstrap serves both, so this plan uses `shared`, as AsmblyMCPs' bootstrap
    does. If the Asmbly AWS Tagging Guide allows only `prod` and `stage`, it becomes
    `prod`. The guide itself was not found in any of the three repositories; where it
    lives is asked in the README's report.

### infra: resources

**`GitHubOidcProvider`** (`AWS::IAM::OIDCProvider`, `Condition: CreateOidcProvider`):
`Url: https://token.actions.githubusercontent.com`, `ClientIdList: [sts.amazonaws.com]`.

**`GitHubDeployRole`** (`AWS::IAM::Role`): `RoleName: !Sub '${ProjectSlug}-gha-deploy'`,
`Path: /asmbly-ceramics-bootstrap/`, `MaxSessionDuration: 3600`.

```yaml
AssumeRolePolicyDocument:
  Version: '2012-10-17'
  Statement:
    - Effect: Allow
      Principal:
        Federated: !Sub 'arn:${AWS::Partition}:iam::${AWS::AccountId}:oidc-provider/token.actions.githubusercontent.com'
      Action: sts:AssumeRoleWithWebIdentity
      Condition:
        StringEquals:
          token.actions.githubusercontent.com:aud: sts.amazonaws.com
          token.actions.githubusercontent.com:sub:
            - !Sub '${GitHubSubjectPrefix}:environment:stage'
            - !Sub '${GitHubSubjectPrefix}:environment:prod'
Policies:
  - PolicyName: deploy-the-app-stacks
    PolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Sid: NeverTheBootstrap
          Effect: Deny
          Action: cloudformation:*
          Resource: !Sub 'arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/${AWS::StackName}/*'
        - Sid: TheAppStacks
          Effect: Allow
          Action:
            - cloudformation:CreateChangeSet
            - cloudformation:DescribeChangeSet
            - cloudformation:ExecuteChangeSet
            - cloudformation:DeleteChangeSet
            - cloudformation:DescribeStacks
            - cloudformation:DescribeStackEvents
            - cloudformation:GetTemplate
            - cloudformation:GetTemplateSummary
            - cloudformation:ListStackResources
          Resource:
            - !Sub 'arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/${ProjectSlug}-stage/*'
            - !Sub 'arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/${ProjectSlug}-prod/*'
        - Sid: SamTransform
          Effect: Allow
          Action: cloudformation:CreateChangeSet
          Resource: !Sub 'arn:${AWS::Partition}:cloudformation:${AWS::Region}:aws:transform/Serverless-2016-10-31'
        - Sid: TemplateChecksWithoutAResource
          Effect: Allow
          Action: [cloudformation:ValidateTemplate]
          Resource: '*'
        - Sid: HandStacksToTheExecutionRole
          Effect: Allow
          Action: iam:PassRole
          Resource: !GetAtt CloudFormationExecutionRole.Arn
          Condition:
            StringEquals:
              iam:PassedToService: cloudformation.amazonaws.com
        - Sid: Artifacts
          Effect: Allow
          Action: [s3:GetObject, s3:PutObject, s3:ListBucket, s3:GetBucketLocation]
          Resource:
            - !GetAtt ArtifactsBucket.Arn
            - !Sub '${ArtifactsBucket.Arn}/*'
```

It has nothing else: no right on any resource but the two stacks and the bucket. The
deploy workflow (phase 7) passes the execution role with `--role-arn`.

**`CloudFormationExecutionRole`** (`AWS::IAM::Role`): `RoleName: !Sub '${ProjectSlug}-cfn-exec'`,
`Path: /asmbly-ceramics-bootstrap/`, trusted by `cloudformation.amazonaws.com` with
`aws:SourceAccount` = `${AWS::AccountId}`. Its inline policy, statement by statement
(`P` below is `arn:${AWS::Partition}`, `R` the region, `A` the account, all through
`!Sub`; `${ProjectSlug}` is `asmbly-ceramics`):

| Sid | Effect | Actions | Resource | Condition |
| --- | --- | --- | --- | --- |
| `HandsOffOtherProjects` | Deny | `*` | `*` | `ForAnyValue:StringEquals` `aws:ResourceTag/Project` in `ProtectedProjectTags` |
| `HandsOffTheBootstrap` | Deny | `*` | the bootstrap stack; `role/asmbly-ceramics-bootstrap/*`; `policy/asmbly-ceramics-bootstrap/*` | — (the artifacts bucket is not in this Deny, because `ReadArtifacts` needs it; the role has no write right there) |
| `NoSignInRights` | Deny | `cognito-idp:*` | `*` | — |
| `NoEmailOrDnsRights` | Deny | `ses:*`, `route53:*`, `acm:*` | `*` | — |
| `SamTransform` | Allow | `cloudformation:CreateChangeSet` | `P:cloudformation:R:aws:transform/Serverless-2016-10-31` | — |
| `ReadArtifacts` | Allow | `s3:GetObject` | the artifacts bucket's objects | — |
| `CreateTagged` | Allow | `dynamodb:CreateTable`, `s3:CreateBucket`, `lambda:CreateFunction`, `lambda:CreateEventSourceMapping`, `sns:CreateTopic`, `sqs:CreateQueue`, `cloudwatch:PutMetricAlarm`, `logs:CreateLogGroup`, `apigateway:POST` | the name patterns below | `StringEquals aws:RequestTag/Project: asmbly-ceramics` and `ForAllValues:StringEquals aws:TagKeys: [Project, Component, Environment, Owner, ManagedBy]` |
| `TagOnCreate` | Allow | `dynamodb:TagResource`, `s3:PutBucketTagging`, `lambda:TagResource`, `sns:TagResource`, `sqs:TagQueue`, `cloudwatch:TagResource`, `logs:TagResource`, `logs:TagLogGroup`, `apigateway:PUT`, `iam:TagRole` | the name patterns below | `StringEquals aws:RequestTag/Project: asmbly-ceramics` |
| `ChangeOwn` | Allow | the services' update, configure, describe and delete actions (list below) | the name patterns below | `StringEquals aws:ResourceTag/Project: asmbly-ceramics` |
| `SchedulesByName` | Allow | `scheduler:CreateSchedule`, `UpdateSchedule`, `DeleteSchedule`, `GetSchedule` | `P:scheduler:R:A:schedule/default/asmbly-ceramics-*` | none (schedules take no tags: see the table below) |
| `FunctionRolesInsideTheBoundary` | Allow | `iam:CreateRole`, `iam:PutRolePermissionsBoundary`, `iam:PutRolePolicy`, `iam:AttachRolePolicy` | `P:iam::A:role/asmbly-ceramics-app/asmbly-ceramics-*` | `StringEquals iam:PermissionsBoundary: <FunctionBoundary ARN>` and, on `CreateRole`, the same `aws:RequestTag/Project` |
| `ManageFunctionRoles` | Allow | `iam:GetRole`, `iam:DeleteRole`, `iam:DeleteRolePolicy`, `iam:DetachRolePolicy`, `iam:GetRolePolicy`, `iam:UpdateAssumeRolePolicy`, `iam:UntagRole`, `iam:ListRolePolicies`, `iam:ListAttachedRolePolicies` | `role/asmbly-ceramics-app/*` | `aws:ResourceTag/Project = asmbly-ceramics` |
| `PassFunctionRoles` | Allow | `iam:PassRole` | `role/asmbly-ceramics-app/*` | `StringEquals iam:PassedToService: [lambda.amazonaws.com, scheduler.amazonaws.com]` |
| `ReadTheStaffSignInValues` | Allow | `ssm:GetParameters` | `P:ssm:R:A:parameter/config/cognito/staff/*` | — (CloudFormation resolves the app stacks' `AWS::SSM::Parameter::Value<String>` parameters with this role) |
| `DescribeWithoutAResource` | Allow | `lambda:GetEventSourceMapping`, `lambda:ListEventSourceMappings`, `logs:DescribeLogGroups`, `logs:DescribeMetricFilters`, `cloudwatch:DescribeAlarms`, `sns:ListTopics`, `apigateway:GET` on `/domainnames*`, `dynamodb:DescribeLimits`, `iam:GetPolicy` (the boundary) | `*` where the service has no resource-level read, otherwise the pattern | — (each listed as a documented `Resource: "*"` exception in the test) |

The name patterns, the only resources the Allow statements reach:

| Service | Pattern |
| --- | --- |
| DynamoDB | `table/asmbly-ceramics-*` (and `.../stream/*`, `.../index/*`) |
| S3 | `arn:aws:s3:::asmbly-ceramics-*-photos` (buckets) and `.../*` (objects, for the bucket policy's check) |
| Lambda | `function:asmbly-ceramics-*`; `event-source-mapping:*` (mappings have generated IDs; the tag conditions are their fence) |
| Logs | `log-group:/aws/lambda/asmbly-ceramics-*`, `log-group:/aws/apigateway/asmbly-ceramics-*`, `log-group:/aws/vendedlogs/asmbly-ceramics-*` |
| SNS | `asmbly-ceramics-*` |
| SQS | `asmbly-ceramics-*` |
| CloudWatch | `alarm:asmbly-ceramics-*` |
| API Gateway | `/apis`, `/apis/*`, `/tags/*`, and `/domainnames/<ProdDomainName>/apimappings*`, `/domainnames/<StageDomainName>/apimappings*` (no right to create or change a domain name: they are this stack's) |
| Scheduler | `schedule/default/asmbly-ceramics-*` |

`ChangeOwn`'s actions: `dynamodb:UpdateTable`, `UpdateTimeToLive`,
`UpdateContinuousBackups`, `DescribeTable`, `DescribeTimeToLive`,
`DescribeContinuousBackups`, `ListTagsOfResource`, `UntagResource`, `DeleteTable`;
`s3:PutBucketPolicy`, `GetBucketPolicy`, `DeleteBucketPolicy`,
`PutLifecycleConfiguration`, `GetLifecycleConfiguration`, `PutBucketCORS`,
`GetBucketCORS`, `PutBucketPublicAccessBlock`, `GetBucketPublicAccessBlock`,
`PutEncryptionConfiguration`, `GetEncryptionConfiguration`,
`PutBucketOwnershipControls`, `GetBucketOwnershipControls`, `GetBucketTagging`,
`DeleteBucket`; `lambda:UpdateFunctionCode`, `UpdateFunctionConfiguration`,
`GetFunction`, `GetFunctionConfiguration`, `DeleteFunction`, `AddPermission`,
`RemovePermission`, `PutFunctionConcurrency`, `DeleteFunctionConcurrency`,
`UpdateEventSourceMapping`, `DeleteEventSourceMapping`, `UntagResource`,
`ListTags`; `logs:PutRetentionPolicy`, `DeleteRetentionPolicy`, `PutMetricFilter`,
`DeleteMetricFilter`, `DeleteLogGroup`, `UntagResource`; `sns:SetTopicAttributes`,
`GetTopicAttributes`, `Subscribe`, `Unsubscribe`, `DeleteTopic`, `UntagResource`;
`sqs:SetQueueAttributes`, `GetQueueAttributes`, `GetQueueUrl`, `DeleteQueue`,
`UntagQueue`; `cloudwatch:DeleteAlarms`, `UntagResource`; `apigateway:PATCH`,
`apigateway:DELETE`, `apigateway:GET`.

**Tag-condition support**, from the Service Authorization Reference (read 13 November
2026 by downloading each page and extracting the condition keys per action):

| Service | Create accepts `aws:RequestTag` and `aws:TagKeys` | Later actions accept `aws:ResourceTag` | Notes |
| --- | --- | --- | --- |
| DynamoDB | `CreateTable`: yes | `UpdateTable`, `UpdateTimeToLive`, `UpdateContinuousBackups`, `DeleteTable`: yes | |
| S3 | `CreateBucket`: yes | `PutBucketPolicy`, `PutLifecycleConfiguration`, `PutBucketCORS`, `PutBucketPublicAccessBlock`, `PutEncryptionConfiguration`, `PutBucketOwnershipControls`, `PutBucketTagging`, `DeleteBucket`: yes | **To confirm in /prep**: whether CloudFormation passes the stack's tags to `CreateBucket` or adds them afterwards with `PutBucketTagging`; in the second case the first `PutBucketTagging` meets a bucket with no tags and `aws:ResourceTag` fails. Fallback, if the first stage deploy shows it: `PutBucketTagging` moves to `TagOnCreate` (it already carries `aws:RequestTag`). |
| Lambda | `CreateFunction`, `CreateEventSourceMapping`: yes | `UpdateFunctionCode`, `UpdateFunctionConfiguration`, `DeleteFunction`, `AddPermission`, `UpdateEventSourceMapping`, `DeleteEventSourceMapping`: yes | |
| API Gateway (`apigateway:` actions, which cover HTTP APIs) | `POST`: yes | `PATCH`, `PUT`, `DELETE`: yes; `GET`: `aws:ResourceTag` only | **To confirm in /prep**: routes, integrations, stages and API mappings carry no tags of their own; whether `aws:ResourceTag` on `/apis/<id>/routes` is evaluated against the API's tags. Fallback, if the first stage deploy fails on them: those sub-resources are reached by `/apis/*` with the `HandsOffOtherProjects` Deny as the fence, which is what AsmblyMCPs relies on, and the README's report says so. |
| EventBridge Scheduler | `CreateSchedule`: **no** (`aws:ResourceTag` only, on the schedule group) | `UpdateSchedule`, `DeleteSchedule`: yes | Schedules in the default group take no tags, so `SchedulesByName` scopes by name only. |
| SNS | `CreateTopic`: yes | `Subscribe`, `SetTopicAttributes`, `DeleteTopic`: yes | |
| SQS | `CreateQueue`, `TagQueue`: yes | `SetQueueAttributes`, `DeleteQueue`: yes | |
| CloudWatch | `PutMetricAlarm`: yes | `DeleteAlarms`: yes | `PutMetricAlarm` is both create and update; it carries the `aws:RequestTag` condition, so the template's alarms must list their tags (phase 7). |
| CloudWatch Logs | `CreateLogGroup`, `TagResource`, `TagLogGroup`: yes | `PutRetentionPolicy`, `PutMetricFilter`, `DeleteLogGroup`: yes | |
| IAM | `CreateRole`, `TagRole`, `PassRole`: yes | `PutRolePolicy`, `AttachRolePolicy`, `PutRolePermissionsBoundary`, `DeleteRole`: yes | |
| ACM | `RequestCertificate`: yes | `DeleteCertificate`: yes | Only the bootstrap makes certificates; the execution role is denied `acm:*`. |

Where a service accepts the keys, the statement uses both the name pattern and the tag
condition. Where it doesn't (Scheduler's create, event-source mappings' and API
sub-resources' generated IDs), the name pattern or the tag Deny is the fence, as said.
If a first deploy fails on a tag condition, the fix is a reviewed change to this
template that the maintainer asks for, not a quiet widening (CLAUDE.md: "Never weaken
the deploy role… without the maintainer asking").

**`FunctionBoundary`** (`AWS::IAM::ManagedPolicy`): `ManagedPolicyName:
!Sub '${ProjectSlug}-function-boundary'`, `Path: /asmbly-ceramics-bootstrap/`. The most
any function role (and the scheduler's role) can ever do; phase 7's roles each take a
part of it.

```yaml
Statement:
  - Sid: WriteOwnLogs
    Effect: Allow
    Action: [logs:CreateLogStream, logs:PutLogEvents]
    Resource: !Sub 'arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/${ProjectSlug}-*:*'
  - Sid: OwnTables
    Effect: Allow
    Action:
      - dynamodb:GetItem
      - dynamodb:Query
      - dynamodb:PutItem
      - dynamodb:UpdateItem
      - dynamodb:ConditionCheckItem
      - dynamodb:DescribeStream
      - dynamodb:GetRecords
      - dynamodb:GetShardIterator
      - dynamodb:ListStreams
    Resource:
      - !Sub 'arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${ProjectSlug}-*'
      - !Sub 'arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${ProjectSlug}-*/index/*'
      - !Sub 'arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${ProjectSlug}-*/stream/*'
  - Sid: OwnPhotos
    Effect: Allow
    Action: [s3:GetObject, s3:PutObject, s3:DeleteObject]
    Resource: !Sub 'arn:${AWS::Partition}:s3:::${ProjectSlug}-*-photos/*'
  - Sid: ListOwnPhotos
    Effect: Allow
    Action: s3:ListBucket
    Resource: !Sub 'arn:${AWS::Partition}:s3:::${ProjectSlug}-*-photos'
  - Sid: OwnSecrets
    Effect: Allow
    Action: ssm:GetParameter
    Resource: !Sub 'arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter/${ProjectSlug}/*'
  - Sid: DecryptOwnSecretsThroughSsm
    Effect: Allow
    Action: kms:Decrypt
    Resource: '*'
    Condition:
      StringEquals:
        kms:ViaService: !Sub 'ssm.${AWS::Region}.amazonaws.com'
  - Sid: SendFromAsmblyAddresses
    Effect: Allow
    Action: ses:SendEmail
    Resource: !Sub 'arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/${EmailIdentityDomain}'
    Condition:
      StringLike:
        ses:FromAddress: !Sub '*@${EmailIdentityDomain}'
  - Sid: RunOwnFunctions
    Effect: Allow
    Action: lambda:InvokeFunction
    Resource: !Sub 'arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:${ProjectSlug}-*'
  - Sid: OwnDeadLetterQueues
    Effect: Allow
    Action: sqs:SendMessage
    Resource: !Sub 'arn:${AWS::Partition}:sqs:${AWS::Region}:${AWS::AccountId}:${ProjectSlug}-*'
```

Nothing else: no `ses:` right but `SendEmail` on that identity, no Cognito, no IAM, no
other bucket or table. `ses:SendEmail` on a v2 call can also be evaluated against a
configuration set; the app uses none (decision 0002), so none is allowed. The agreement
that this project may send from the identity is AsmblyMCPs' to give (README,
Dependencies); a same-account sender needs no identity policy
(sending-authorization.html), so nothing changes in `mcp-bootstrap`.

**`ArtifactsBucket`** (`AWS::S3::Bucket`): `BucketName:
!Sub '${ProjectSlug}-artifacts-${AWS::AccountId}'` (the account ID comes from the
pseudo parameter at deploy time, never from a file), all four
`PublicAccessBlockConfiguration` settings `true`, `OwnershipControls`
`BucketOwnerEnforced`, `BucketEncryption` `AES256`, a lifecycle rule expiring objects
after 90 days and aborting incomplete multipart uploads after 1 day,
`DeletionPolicy: Retain`, `UpdateReplacePolicy: Retain`. **`ArtifactsBucketPolicy`**
denies `s3:*` when `aws:SecureTransport` is `false`.

**`ProdCertificate`, `StageCertificate`** (`AWS::CertificateManager::Certificate`):
`DomainName: !Ref ProdDomainName` (and stage), `ValidationMethod: DNS`,
`DomainValidationOptions: [{DomainName: ..., HostedZoneId: !Ref ParentHostedZoneId}]`,
so CloudFormation writes the validation records and waits for issue.
`DeletionPolicy: Delete`, `UpdateReplacePolicy: Retain` (as AsmblyMCPs' sign-in
certificate). In this stack's region (us-east-2), as a Regional custom domain requires.

**`ProdDomain`, `StageDomain`** (`AWS::ApiGatewayV2::DomainName`): `DomainName: !Ref
ProdDomainName`, `DomainNameConfigurations: [{CertificateArn: !Ref ProdCertificate,
EndpointType: REGIONAL, SecurityPolicy: TLS_1_2}]`, tags as above. The app stacks add
only an `AWS::ApiGatewayV2::ApiMapping` to these (phase 7).

**`ProdDnsRecord`, `StageDnsRecord`** (`AWS::Route53::RecordSet`, type `A`) and
**`ProdDnsRecordIpv6`, `StageDnsRecordIpv6`** (type `AAAA`): in `ParentHostedZoneId`,
`AliasTarget` to `!GetAtt ProdDomain.RegionalDomainName` and
`!GetAtt ProdDomain.RegionalHostedZoneId`. **To confirm in /prep**: that a Regional API
Gateway domain name answers on IPv6 (an `AAAA` alias to it); if not, drop the two
`AAAA` records.

### infra: outputs and exports

| Output | Value | Export |
| --- | --- | --- |
| `DeployRoleArn` | `GitHubDeployRole.Arn` | — |
| `ExecutionRoleArn` | `CloudFormationExecutionRole.Arn` | — |
| `ArtifactsBucketName` | `ArtifactsBucket` | — |
| `FunctionBoundaryArn` | `FunctionBoundary` | `asmbly-ceramics-function-boundary-arn` |
| `ProdDomainNameOut` | `ProdDomain` | `asmbly-ceramics-prod-domain-name` |
| `StageDomainNameOut` | `StageDomain` | `asmbly-ceramics-stage-domain-name` |

The first three are copied into the GitHub environments' variables (runbook step 5);
the exports are imported by `infra/app.yaml` (phase 7), which picks the domain export by
its `AppEnv` parameter.

### docs: `docs/runbooks/aws-bootstrap.md`

In AsmblyMCPs' style (prose, `bash` blocks, `# expect:` comments after read-only
commands) with asmbly-staff-login's shape for each step: **Do**, **Check**, **Who
confirms** (the maintainer), **Undo**. It starts with
`export AWS_PROFILE=asmbly AWS_REGION=us-east-2` and the rule that the maintainer runs
it, by hand, only when they asked for it in the conversation.

1. **Read-only checks.**
   `aws sts get-caller-identity` (expect: the Asmbly account and an admin role; nothing
   is printed into the runbook);
   `aws sesv2 get-account --query '{prod:ProductionAccessEnabled,status:EnforcementStatus}'`
   (expect: `true`, `HEALTHY`);
   `aws route53 list-resource-record-sets --hosted-zone-id "$PARENT_ZONE" --query
   "ResourceRecordSets[?starts_with(Name, 'ceramics')]"` (expect: `[]`, neither name
   exists);
   `aws iam list-open-id-connect-providers` (expect: the GitHub provider; if absent,
   pass `CreateGitHubOidcProvider=true`);
   `aws resourcegroupstaggingapi get-tag-values --key Project` (expect: compare with
   `ProtectedProjectTags`; add any other project's value).
   Undo: nothing to undo.
2. **The OIDC subject.** `gh api repos/asmbly-makerspace/asmbly-ceramics/actions/oidc/customization/sub`;
   if it doesn't use IDs, set `use_default: false` with
   `include_claim_keys: ["repository_owner_id", "repository_id", "environment"]`, as
   AsmblyMCPs' runbook does, and read the prefix again. Check: the prefix matches the
   parameter's pattern. Undo: set `use_default: true`.
3. **Deploy with a change set.**
   `aws cloudformation deploy --template-file infra/bootstrap.yaml --stack-name
   asmbly-ceramics-bootstrap --capabilities CAPABILITY_NAMED_IAM --no-execute-changeset
   --tags Project=asmbly-ceramics Component=Bootstrap Environment=shared
   Owner=it-volunteers ManagedBy=cloudformation --parameter-overrides
   "GitHubSubjectPrefix=$SUBJECT" "ParentHostedZoneId=$PARENT_ZONE"`; then
   `describe-change-set` (expect: only `Add` actions, 15 resources or 16 with the OIDC
   provider; nothing outside `asmbly-ceramics-` names but the DNS records for the two
   addresses and their validation records); then `execute-change-set` and
   `wait stack-create-complete`. Check: `describe-stacks` shows `CREATE_COMPLETE` and
   the six outputs; `aws acm describe-certificate` for both shows `ISSUED`;
   `dig +short ceramics.asmbly.org` returns addresses (it will answer 403/404 until
   phase 7 maps an API). Undo: `aws cloudformation delete-stack --stack-name
   asmbly-ceramics-bootstrap` (the artifacts bucket is retained; empty and delete it by
   hand if wanted). Only before phase 7 has deployed: after that, the app stacks import
   the exports and must be deleted first.
4. **The GitHub environments.** Create `stage` and `prod` in the repository's settings,
   each with deployment branches limited to `main`; `prod` may add the maintainer as a
   required reviewer if wanted. Check: `gh api repos/asmbly-makerspace/asmbly-ceramics/environments`
   lists both with their branch policy. Undo: delete the environments.
5. **The variables**, the same in both environments unless said: `AWS_REGION`
   (`us-east-2`), `AWS_DEPLOY_ROLE_ARN`, `AWS_CFN_EXECUTION_ROLE_ARN`,
   `SAM_ARTIFACTS_BUCKET` (from the outputs), `ALERT_EMAIL` (the maintainers' list,
   typed into GitHub, never into a file), and `INITIAL_SENDING_ADDRESS` (the studio's
   address at `asmbly.org` that emails come from until staff change it in the console).
   Check: `gh variable list --env stage` and `--env prod`. Undo: `gh variable delete`.
6. **The app's secrets**, for each environment: `aws ssm put-parameter --name
   /asmbly-ceramics/<env>/hash-key --type SecureString --value "$(openssl rand -base64 32)"`,
   and the same for `session-key`, with `--tags` for the five tags. The value is made
   by `openssl` in the command, never typed, pasted into a file or a chat, or printed.
   Check: `aws ssm describe-parameters --parameter-filters Key=Name,Option=BeginsWith,Values=/asmbly-ceramics/`
   lists four, type `SecureString`. Undo: `aws ssm delete-parameter`. Changing
   `session-key` later signs everyone out of the console; changing `hash-key` resets
   the rate-limit counts. Both are safe.

The runbook also has "Later changes to the bootstrap stack" (the same change-set steps,
with `describe-change-set` read for `Replacement: True` on a role, which would break the
GitHub variables) and "Who can merge to `main`", linking CONTRIBUTING.md.

## Tests

`tests/repo/test_bootstrap.py`, using `tests/repo/cloudformation.py`'s loader:

- `test_every_name_starts_with_the_project_slug`: every `RoleName`,
  `ManagedPolicyName`, `BucketName` and stack name built in the template starts with
  `${ProjectSlug}-`; the `ProjectSlug` pattern allows only `asmbly-ceramics`.
- `test_roles_and_boundary_live_under_the_bootstrap_path`
- `test_the_deploy_role_trusts_only_this_repositorys_stage_and_prod_environments`
- `test_the_deploy_role_can_only_hand_the_two_app_stacks_to_cloudformation`: its
  Allow resources are exactly the two stacks, the transform, the execution role and
  the artifacts bucket.
- `test_the_execution_role_creates_roles_only_inside_the_boundary_and_the_app_path`
- `test_every_create_statement_requires_the_project_request_tag`
- `test_every_change_statement_requires_the_project_resource_tag` (except the
  documented `SchedulesByName`)
- `test_other_projects_tags_and_the_bootstrap_are_denied`: the two Deny statements
  exist, cover `*`, and the protected list includes every `Project` value the sibling
  repositories use (`mcp-platform`, `mcp-door`, `mcp-ceramics`, `staff-login`).
- `test_no_sign_in_email_or_dns_rights_for_the_execution_role`
- `test_resource_star_only_where_documented`: `"*"` appears only in the Deny
  statements, `TemplateChecksWithoutAResource`, `DescribeWithoutAResource` and
  `DecryptOwnSecretsThroughSsm` (with its `kms:ViaService` condition).
- `test_the_boundary_sends_only_from_the_email_domain`: `ses:SendEmail` on the
  identity ARN only, with `StringLike ses:FromAddress` `*@${EmailIdentityDomain}`, and
  no other `ses:` action.
- `test_the_boundary_reaches_only_project_resources`: every Allow resource contains
  `${ProjectSlug}-` or `${ProjectSlug}/`.
- `test_the_artifacts_bucket_is_private_encrypted_and_retained`
- `test_certificates_validate_by_dns_in_the_parent_zone`
- `test_every_resource_that_takes_tags_has_the_five`
- `test_no_account_id_or_address_in_the_template` (the existing personal-data test
  covers this too; this one also refuses `arn:aws:...:<12 digits>` built by hand
  instead of `${AWS::AccountId}`).
- `test_only_the_deploy_workflow_may_get_credentials`: written now as "no workflow
  uses `configure-aws-credentials`" (as `test_workflows.py` does); phase 7 changes it
  to name `deploy.yml`'s two deploy jobs.

`tests/repo/test_checks.py`: `test_claude_md_and_ci_use_the_same_cfn_lint` (above).

Every test reads the files only; none calls AWS.

## Acceptance criteria

1. `uvx cfn-lint==1.57.1 infra/*.yaml` passes, in CI's new `Templates` job, which `PR
   check` waits for.
2. The deploy role can be assumed only from this repository's `stage` and `prod`
   GitHub environments, and its Allow statements reach only the stacks
   `asmbly-ceramics-stage` and `asmbly-ceramics-prod`, the SAM transform, the execution
   role (passed only to CloudFormation) and the artifacts bucket.
3. The execution role's create statements require `aws:RequestTag/Project =
   asmbly-ceramics` where the service supports the key; its change statements require
   `aws:ResourceTag/Project = asmbly-ceramics` where supported; every Allow is limited
   to `asmbly-ceramics-` names; the exceptions are exactly those in the support table.
4. The execution role is denied every action on resources tagged with another
   project's `Project` value, on the bootstrap stack and its roles, and every
   Cognito, SES, Route 53 and ACM action.
5. A role created by an app stack must be under `/asmbly-ceramics-app/` and carry
   `asmbly-ceramics-function-boundary`; the boundary allows SES only as
   `ses:SendEmail` on the `asmbly.org` identity from an `asmbly.org` From address.
6. The artifacts bucket blocks all public access, enforces bucket-owner ownership, is
   encrypted, refuses non-TLS requests and is retained.
7. No file holds an account ID, a person's address or a secret; the account ID enters
   only through `${AWS::AccountId}`.
8. The runbook gives each step a check, who confirms it, and an undo.
9. The checks in CLAUDE.md pass, and CLAUDE.md, the README, the pull request template
   and `pr-checks.yml` name the same `cfn-lint` version.

## Verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
uvx cfn-lint==1.57.1 infra/*.yaml
```

After the merge, the maintainer follows the runbook. It works when:
`aws cloudformation describe-stacks --stack-name asmbly-ceramics-bootstrap` shows
`CREATE_COMPLETE` with the six outputs; both certificates are `ISSUED`; `dig` returns
addresses for both names; and, as a negative check of the boundary,
`aws iam simulate-custom-policy` with the boundary's document and
`--action-names ses:SendEmail --context-entries` for a From address outside
`asmbly.org` answers `implicitDeny`. The deploy roles are first used for real by
phase 7's first deploy.

## Rollout

- **What is done:** the maintainer deploys `asmbly-ceramics-bootstrap` by hand after
  this phase merges, sets up the two GitHub environments and their variables, and sets
  the four SecureString parameters (runbook steps 1–6).
- **Check:** the runbook's per-step checks above; the stack's change set shows only
  `Add` actions and only the expected resources.
- **Who confirms:** the maintainer (@sababado).
- **Undo:** delete the stack (and the environments, variables and parameters) while no
  app stack exists. After phase 7, delete `asmbly-ceramics-prod` and
  `asmbly-ceramics-stage` first; their table and bucket are retained.
- Nothing else in the account changes: the `asmbly.org` zone gets the two names'
  records and the certificates' validation records, which no other project uses.

## Admin actions

- Before this phase merges: the maintainer confirms the two addresses
  `ceramics.asmbly.org` and `ceramics-stage.asmbly.org`, and the `Environment` tag value
  for the bootstrap (`shared` or `prod`).
- After it merges: deploy the bootstrap by hand with rights to the `asmbly.org` zone;
  create the `stage` and `prod` GitHub environments (deployments from `main` only) and
  their variables `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `AWS_CFN_EXECUTION_ROLE_ARN`,
  `SAM_ARTIFACTS_BUCKET`, `ALERT_EMAIL`, `INITIAL_SENDING_ADDRESS`; set
  `/asmbly-ceramics/<env>/hash-key` and `/asmbly-ceramics/<env>/session-key` for both
  environments. All by the runbook.

## Hand-off

Phase 7 can rely on:

- The stack `asmbly-ceramics-bootstrap` and its exports
  `asmbly-ceramics-function-boundary-arn`, `asmbly-ceramics-prod-domain-name`,
  `asmbly-ceramics-stage-domain-name` (each the custom domain's name, to map an API
  to).
- The GitHub environments `stage` and `prod` with the variables above.
- The SSM SecureString parameters `/asmbly-ceramics/stage/hash-key`,
  `/asmbly-ceramics/stage/session-key`, `/asmbly-ceramics/prod/hash-key`,
  `/asmbly-ceramics/prod/session-key`.
- What the execution role allows, which phase 7's template must fit:
  - every resource tagged with all five tags at creation, `Project=asmbly-ceramics`
    (stack tags plus explicit `Tags` on alarms, which `PutMetricAlarm` checks);
  - names: table `asmbly-ceramics-<env>-records`, bucket
    `asmbly-ceramics-<env>-photos`, functions `asmbly-ceramics-<env>-<job>`, log groups
    `/aws/lambda/asmbly-ceramics-<env>-<job>` and
    `/aws/apigateway/asmbly-ceramics-<env>`, topic `asmbly-ceramics-<env>-alarms`,
    alarms `asmbly-ceramics-<env>-*`, queue `asmbly-ceramics-<env>-close-dlq`, schedule
    `asmbly-ceramics-<env>-close` in the default group;
  - every function role with `RolePath: /asmbly-ceramics-app/`, a name starting
    `asmbly-ceramics-`, and `PermissionsBoundary` set to the imported boundary ARN; the
    scheduler's role the same, passed to `scheduler.amazonaws.com`;
  - no Cognito, SES, Route 53 or ACM resource in an app stack; only an
    `AWS::ApiGatewayV2::ApiMapping` to the bootstrap's domain name;
  - `AWS::SSM::Parameter::Value<String>` parameters only under `/config/cognito/staff/`.
- The boundary's statement Sids (`WriteOwnLogs`, `OwnTables`, `OwnPhotos`,
  `ListOwnPhotos`, `OwnSecrets`, `DecryptOwnSecretsThroughSsm`,
  `SendFromAsmblyAddresses`, `RunOwnFunctions`, `OwnDeadLetterQueues`), each function
  role taking a subset.
- `tests/repo/cloudformation.py`'s `load_template` for phase 7's template tests.

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

> **Status:** [~] In progress

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

## Revisions from /prep (2026-11-14)

`/prep` checked this document against the code, cfn-lint 1.57.1's CloudFormation
resource schemas (each type's handler permissions) and the account, read only. Where the
sections below disagree with this list, this list wins.

1. **Other projects' resources: a Deny on any other `Project` value, not a list.** The
   account holds many more `Project` values than `ProtectedProjectTags` named (the
   facilities automation's `facilities:*`, `purchase-request:*`, `problem-report:*`,
   `ceramics:kiln-dropoff-viewer`; `mcp`; `staff-login-rehearsal`; …). `HandsOffOtherProjects`
   denies `*` when `aws:ResourceTag/Project` is present (`Null: false`) and is not
   `${ProjectSlug}`. The parameter `ProtectedProjectTags` and runbook step 1's tag
   comparison go.
2. **The staff sign-in's parameters are excepted from that Deny.** `/config/cognito/staff/*`
   is tagged `Project=staff-login`, so the Deny would refuse `ResolveStackParameters`
   (phase 8). The Deny uses `NotResource` for that path; the role's only right there is
   `ssm:GetParameters`.
3. **No `aws:TagKeys` clause.** SAM adds `lambda:createdBy` and `httpapi:createdBy` tags
   and CloudFormation its `aws:cloudformation:*` ones, which a five-key
   `ForAllValues aws:TagKeys` refuses. Create statements require
   `aws:RequestTag/Project = asmbly-ceramics` and `Null: false` on
   `aws:RequestTag/Component`, `Environment`, `Owner` and `ManagedBy`: the five tags must
   be there, extra ones are allowed.
4. **Rights the CloudFormation handlers need**, missing above: `lambda:GetLayerVersion`
   on `layer:LambdaAdapterLayerArm64` (AWS's account, so `*` for the account: read only,
   `WebAdapterLayer`); the log-delivery and resource-policy actions API Gateway's access
   logs need, in `DescribeWithoutAResource`; the read-backs each handler calls
   (`dynamodb:DescribeContributorInsights`, `DescribeKinesisStreamingDestination`,
   `GetResourcePolicy`; the photo bucket's `Get*`; `lambda:GetFunctionCodeSigningConfig`,
   `GetFunctionRecursionConfig`, `GetRuntimeManagementConfig`, `GetPolicy`;
   `sns:ListSubscriptionsByTopic`, `GetDataProtectionPolicy`, `ListTagsForResource`;
   `sqs:ListQueueTags`; `cloudwatch:ListTagsForResource`; `logs:ListTagsForResource`);
   `s3:TagResource` and `apigateway:TagResource` in `TagOnCreate`; and SNS subscriptions
   (`SubscriptionsByName`, by name: a subscription takes no tags).
5. **API Gateway:** `apigateway:POST` with `aws:RequestTag` only on `/apis` (creating an
   API). Routes, integrations, stages and API mappings carry no tags of their own, so
   POST, PUT, PATCH, DELETE and GET under `/apis/*` and on the two domain names'
   `apimappings` sit in `ChangeOwn` under `aws:ResourceTag`, which API Gateway evaluates
   against the parent. If phase 7's first stage deploy shows otherwise, the fallback
   above applies, by a reviewed change the maintainer asks for.
6. **S3 bucket configuration by name.** S3 evaluates `aws:ResourceTag` on a bucket only
   when the bucket has ABAC on (`AbacStatus`, per the bucket schema and
   `buckets-tagging.html`), so the photo bucket's configuration actions are in
   `PhotoBucketsByName`, fenced by its global `asmbly-ceramics-*-photos-*` name and the
   tag Deny. Creating it still needs the tags.
7. **No Untag right anywhere**, so a resource can't drop its `Project` tag and slip out
   of the fences; `iam:DeleteRolePermissionsBoundary` is denied (`NoBoundaryRemoval`).
   The bootstrap's two domain names are added to `HandsOffTheBootstrap`, and the
   artifacts bucket is read only for the execution role (`ArtifactsAreReadOnly`).
8. **One deploy role per environment.** `asmbly-ceramics-gha-deploy-stage` is trusted
   only by `environment:stage` and may deploy only `asmbly-ceramics-stage`; `-prod` the
   same for prod. With one role for both, a stage job could deploy prod and a reviewer
   on prod would gate nothing. Outputs `StageDeployRoleArn` and `ProdDeployRoleArn`
   replace `DeployRoleArn`; each environment's `AWS_DEPLOY_ROLE_ARN` is its own. The
   split is by stack only: both pass the one execution role, and the one boundary
   covers both environments (Hand-off, open for the maintainer).
9. **No account ID in a GitHub variable.** A role ARN holds the account ID and GitHub
   prints a step's `with:` inputs unmasked, so `AWS_DEPLOY_ROLE_ARN` and
   `AWS_CFN_EXECUTION_ROLE_ARN` are **environment secrets** (phase 7 reads
   `secrets.`, not `vars.`). The artifacts bucket is
   `${ProjectSlug}-artifacts-${ArtifactsBucketSuffix}` (eight random hex characters, a
   parameter, as phase 7's photo bucket), so `SAM_ARTIFACTS_BUCKET` stays a variable.
10. **IPv6:** the domain names set `IpAddressType: dualstack` (the property exists in
    `AWS::ApiGatewayV2::DomainName`), so the `AAAA` aliases answer.
11. **Email:** `SendFromAsmblyAddresses` also lists `identity/*@${EmailIdentityDomain}`,
    in case an address identity at the domain exists (SES then authorizes against it);
    still only with `ses:FromAddress` like `*@${EmailIdentityDomain}`.
12. **The OIDC subject** already uses GitHub's immutable form
    (`use_immutable_subject: true`, prefix `repo:asmbly-makerspace@<id>/asmbly-ceramics@<id>`).
    Runbook step 2 checks that; `include_claim_keys` would change the subject's format
    and is not used.
13. **The runbook's order and checks:** the GitHub environments (deployments from `main`
    only) are created **before** the stack, since GitHub creates an unprotected
    environment when a job names one that doesn't exist. Step 1 adds the `asmbly.org`
    CAA records and a count (never a list) of address identities at `asmbly.org`. Each
    step has Do, Check, Who confirms, Undo, including the keys; the addresses are read
    with `read -r`, never typed into a command line. A section recovers a failed first
    create (`ROLLBACK_COMPLETE`), the undo checks the validation CNAMEs are gone,
    termination protection is turned on after the create, and the boundary check
    simulates both an `asmbly.org` From (allowed) and another (implicitDeny).
14. **Drift:** the `infra` job uses `astral-sh/setup-uv@v10.3.3` and
    `actions/checkout@v7` like the `python` job; the change set adds 17 resources (18
    with the OIDC provider, after revision 17); Rollout's keys are three SecureStrings and two Strings
    (steps 1 to 8); the hand-off's queues include `asmbly-ceramics-<env>-mailer-dlq`.
15. **Phase 7 must** set `RolePath: /asmbly-ceramics-app/` on every generated role (SAM
    `Globals.Function.RolePath`) and pin each function role's trust to
    `lambda.amazonaws.com` or `scheduler.amazonaws.com` in its template test: IAM can't
    condition a trust policy's content, so that test is the fence. `TransactWriteItems`
    is not an IAM action (cfn-lint's policy data), so neither the boundary nor a role
    lists it.
16. **Still open, the maintainer's:** the two addresses, before this phase merges. The
    bootstrap's `Environment` tag is `prod` by default (revision 19), as CLAUDE.md
    asks; `shared` only once CLAUDE.md is amended (the runbook's "Before you start").
17. **After the build's review:** the execution role's allows moved into three managed
    policies (one inline policy passed IAM's 10,240-character limit once filled in);
    `lambda:CreateEventSourceMapping` has no resource type, so it is on `*` fenced by
    `lambda:FunctionArn` and the tags (`CreateEventSourceMappings`); `apigateway:PUT` on
    `/apis` (an HTTP API's body is imported) was its own exception (`ImportApis`, gone
    after revision 18); `apigateway:TagResource` (not an IAM action in cfn-lint's data) and the role-wide
    `W3037` ignore are gone; the access-log writes are their own named exception
    (`ApiAccessLogDelivery`); `ReadTheBoundary` was dead under the bootstrap Deny and is
    gone.
18. **After two cold reviews (14 November 2026)**, each checked against the Service
    Authorization Reference's JSON (`servicereference.us-east-1.amazonaws.com`):
    - No `TagResource` on API Gateway (`/tags/*`, a resource with no condition key) or
      on event-source mappings: with generated IDs, another project's untagged API or
      mapping could be given `Project=asmbly-ceramics` and then changed (`ChangeOwn`).
      Mappings are created with their tags and reached only by `OwnEventSourceMappings`
      (`aws:ResourceTag` and `lambda:FunctionArn`, which Get, Update and Delete take).
      `ImportApis` is gone; phase 7's HTTP API is an `AWS::ApiGatewayV2::Api` with no
      `Body`, created with its tags ([decision 0003](../../docs/decisions/0003-one-function-boundary-per-environment.md)).
    - Two boundaries, `asmbly-ceramics-stage-function-boundary` and `-prod-`, each on
      its own environment's names; roles named `asmbly-ceramics-<env>-*` only with
      their environment's boundary (decision 0003). The exports are
      `asmbly-ceramics-<env>-function-boundary-arn`.
    - `lambda:AddPermission` and `RemovePermission` only with `lambda:Principal` =
      `apigateway.amazonaws.com` (`InvokePermissionsForApiGatewayOnly`). The
      scheduler invokes through its role, so it needs no resource-policy permission.
    - `s3:PutBucketTagging` takes no `aws:RequestTag`, so it is in `PhotoBucketsByName`.
      No condition key sees a public access block's settings, so phase 7's template
      test pins them, and the runbook proposes an account-level block (none exists).
    - `logs:PutResourcePolicy` (no resource, account-wide) is removed and denied: the
      account's four HTTP API stages log to `/aws/apigateway/` with no log resource
      policy. `logs:DescribeIndexPolicies` moved to `DescribeWithoutAResource`.
    - `lambda:GetLayerVersion` only from `WebAdapterPublisherAccount`, a parameter the
      maintainer sets by hand from the Web Adapter's README (no number in a file).
    - The deploy roles' `CreateChangeSet` and `cloudformation:TagResource` require the
      five request tags (`TaggedChangeSets`).
    - `dynamodb:ListStreams` (no resource) is out of the boundaries.
    - IAM has no condition on a trust policy's content (`CreateRole` takes only
      `iam:PermissionsBoundary`, `iam:RoleTemplateARN` and the tag keys;
      `UpdateAssumeRolePolicy` only `iam:PermissionsBoundary`): review and phase 7's
      template test are the fence, and the boundary caps any session.
    - `test_the_template_fits_cloudformations_inline_size_limit` keeps the template
      under 51,200 bytes; the change set adds 18 resources (19 with the provider).
19. **After the lead's re-review (14 November 2026)**; where it differs from 18, this wins:
    - Lambda needs `lambda:TagResource` for a mapping's tags in its create call
      (Lambda's "Using tags on event source mappings"). `TagEventSourceMappingsOnCreate`
      allows it on `event-source-mapping:*` with the five request tags only, and both
      deploy roles are denied import change sets (`NoResourceImport`), so the role can't
      reach an existing mapping. No key limits `TagResource` to the create call: the
      residual risk is in [decision 0003](../../docs/decisions/0003-one-function-boundary-per-environment.md).
    - The account's HTTP API log groups each hold a log-group policy
      (`describe-resource-policies --policy-scope RESOURCE`; the earlier check read the
      account scope only), made by CloudFormation's role with `logs:PutResourcePolicy`.
      That action takes no resource or key, so the role stays denied it and the
      bootstrap owns `LogDeliveryPolicy`, `asmbly-ceramics-log-delivery` (account scope,
      its own name, `/aws/apigateway/asmbly-ceramics-*` only). The change set adds 19
      resources (20 with the provider).
    - If an HTTP API's integration and route don't see the API's tags, they fail
      closed; the fallback (the API's ID as a bootstrap parameter, by ARN) is in
      decision 0003.
    - `EnvironmentTag` defaults to `prod`.

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
  steps: checkout, `astral-sh/setup-uv@v10.3.3`, then
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
  `Project=asmbly-ceramics Component=Bootstrap Environment=prod Owner=it-volunteers ManagedBy=cloudformation`.
  The template also sets them on each resource that takes `Tags` (roles, the bucket,
  the certificates, the domain names) so they don't depend on propagation.
  - **Open question for the maintainer:** CLAUDE.md lists `Environment=<prod or stage>`.
    The bootstrap serves both; it uses `prod` (revision 19), and `shared`, as
    AsmblyMCPs' bootstrap does, only once CLAUDE.md is amended to allow it. The guide itself was not found in any of the three repositories; where it
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
| `ResolveStackParameters` | Allow | `ssm:GetParameters` | `P:ssm:R:A:parameter/config/cognito/staff/*` and `P:ssm:R:A:parameter/asmbly-ceramics/*` | — (CloudFormation resolves the app stacks' `AWS::SSM::Parameter::Value<String>` parameters with this role: the staff sign-in values and this app's two address Strings. It never needs the SecureStrings, which the functions read at run time, and `ssm:GetParameters` without `kms:Decrypt` can't return a SecureString's value) |
| `DescribeWithoutAResource` | Allow | `lambda:GetEventSourceMapping`, `lambda:ListEventSourceMappings`, `logs:DescribeLogGroups`, `logs:DescribeMetricFilters`, `cloudwatch:DescribeAlarms`, `sns:ListTopics`, `apigateway:GET` on `/domainnames*`, `dynamodb:DescribeLimits`, `iam:GetPolicy` (the boundary) | `*` where the service has no resource-level read, otherwise the pattern | — (each listed as a documented `Resource: "*"` exception in the test) |

The name patterns, the only resources the Allow statements reach:

| Service | Pattern |
| --- | --- |
| DynamoDB | `table/asmbly-ceramics-*` (and `.../stream/*`, `.../index/*`) |
| S3 | `arn:aws:s3:::asmbly-ceramics-*-photos-*` (buckets: the name ends with a random suffix, never the account ID, phase 7) and `.../*` (objects, for the bucket policy's check) |
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
| S3 | `CreateBucket`: yes | Only with ABAC on the bucket; `PutBucketTagging` takes no `aws:RequestTag` | Corrected after review (revision 18): the bucket's configuration, `PutBucketTagging` included, is fenced by name (`PhotoBucketsByName`). Whether CloudFormation sends the tags on `CreateBucket` or adds them with `PutBucketTagging` afterwards, both are allowed. |
| Lambda | `CreateFunction`, `CreateEventSourceMapping`: yes | `UpdateFunctionCode`, `UpdateFunctionConfiguration`, `DeleteFunction`, `AddPermission`, `UpdateEventSourceMapping`, `DeleteEventSourceMapping`: yes | The mapping actions also take `lambda:FunctionArn`; `AddPermission` and `RemovePermission` take `lambda:Principal` (revision 18). |
| API Gateway (`apigateway:` actions, which cover HTTP APIs) | `POST`: yes | `PATCH`, `PUT`, `DELETE`: yes; `GET`: `aws:ResourceTag` only | **To confirm in /prep**: routes, integrations, stages and API mappings carry no tags of their own; whether `aws:ResourceTag` on `/apis/<id>/routes` is evaluated against the API's tags. Superseded (revision after the final reviews): an untagged `/apis/*` Allow with `HandsOffOtherProjects` as the fence would reach other projects' untagged APIs, so it is not the fallback. The fallback is [decision 0003](../../docs/decisions/0003-one-function-boundary-per-environment.md#the-apis-integration-route-and-stage-and-their-tags): the API's ID, read after a create with rollback disabled, as a bootstrap parameter, with all five methods allowed on `/apis/<that id>/*` by ARN. |
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
      - dynamodb:UpdateItem   # the ID counter only (phase 4); a commit sends Puts
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
    Resource: !Sub 'arn:${AWS::Partition}:s3:::${ProjectSlug}-*-photos-*/*'
  - Sid: ListOwnPhotos
    Effect: Allow
    Action: s3:ListBucket
    Resource: !Sub 'arn:${AWS::Partition}:s3:::${ProjectSlug}-*-photos-*'
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
   --tags Project=asmbly-ceramics Component=Bootstrap Environment=prod
   Owner=it-volunteers ManagedBy=cloudformation --parameter-overrides
   "GitHubSubjectPrefix=$SUBJECT" "ParentHostedZoneId=$PARENT_ZONE"`; then
   `describe-change-set` (expect: only `Add` actions, 15 resources or 16 with the OIDC
   provider; nothing outside `asmbly-ceramics-` names but the DNS records for the two
   addresses and their validation records); then `execute-change-set` and
   `wait stack-create-complete`. **Who confirms the DNS part**: besides the maintainer,
   whoever is responsible for the `asmbly.org` zone (the project that owns it) is told
   beforehand that the stack adds the two names, two `AAAA` records and the certificates'
   validation records, and confirms afterwards that nothing else in the zone changed.
   Check: `describe-stacks` shows `CREATE_COMPLETE` and
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
   `SAM_ARTIFACTS_BUCKET` (from the outputs), and phase 7's `WEB_ADAPTER_LAYER_ARN`. No
   address is a GitHub variable: the repository is public and so are its Actions logs.
   Check: `gh variable list --env stage` and `--env prod`. Undo: `gh variable delete`.
6. **The app's keys**, for each environment: `aws ssm put-parameter --name
   /asmbly-ceramics/<env>/hash-key --type SecureString --value "$(openssl rand -base64 32)"`,
   and the same for `form-key` (the public form's cookie, form function only) and
   `session-key` (the console's sign-in state and CSRF tokens, console only), with
   `--tags` for the five tags. The value is made by `openssl` in the command, never
   typed, pasted into a file or a chat, or printed. Changing `session-key` later signs
   everyone out of the console; changing `form-key` only expires open ID pages; changing
   `hash-key` resets the rate-limit counts and orphans every live submission: its ID
   page expires, and a form re-posted with the same submission token is not seen as a
   repeat, so it makes a second drop-off and sends a second received email (phase 2a's
   review). The first two are safe at any time; rotate `hash-key` only when the studio
   is closed and no one is mid-drop-off.
7. **The two addresses**, for each environment, as String parameters (not in GitHub):
   `aws ssm put-parameter --name /asmbly-ceramics/<env>/alert-email --type String
   --value '<the maintainers' address>'` and `/asmbly-ceramics/<env>/initial-sending-address`
   (the studio's address at `asmbly.org` that emails come from until staff change it in
   the console), each with `--tags`, typed at the prompt, never into a file. Check:
   `aws ssm describe-parameters --parameter-filters Key=Name,Option=BeginsWith,Values=/asmbly-ceramics/`
   lists five per environment: three `SecureString`, two `String`. Undo:
   `aws ssm delete-parameter`.

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
sam validate --lint -t infra/bootstrap.yaml --region us-east-2
```

After the merge, the maintainer follows the runbook. It works when
`aws cloudformation describe-stacks --stack-name asmbly-ceramics-bootstrap` shows
`CREATE_COMPLETE`, termination protection on and the eight outputs; both certificates
are `ISSUED`; `dig` returns addresses for both names; the GitHub environments hold the
secrets `AWS_DEPLOY_ROLE_ARN` and `AWS_CFN_EXECUTION_ROLE_ARN` and the variables
`AWS_REGION`, `SAM_ARTIFACTS_BUCKET` and `WEB_ADAPTER_LAYER_ARN`; and runbook step 8's
simulations answer, for each boundary, `allowed` for an `asmbly.org` From address and its
own table, and `implicitDeny` for a From address outside `asmbly.org` and the other
environment's table. The deploy roles are first used for real by phase 7's first deploy.

## Rollout

- **What is done:** the maintainer deploys `asmbly-ceramics-bootstrap` by hand after
  this phase merges, with the Web Adapter's publisher account and the `Environment`
  tag he decided; sets up the two GitHub environments, their secrets and variables;
  sets the three SecureStrings and two Strings per environment; and checks both
  boundaries (runbook steps 1 to 8).
- **Check:** the runbook's per-step checks; the change set shows 18 `Add` rows (19 with
  the OIDC provider) and nothing else.
- **Who confirms:** the maintainer (@sababado), and the `asmbly.org` zone's owner for
  the DNS records.
- **Undo:** delete the stack (and the environments, secrets, variables and parameters)
  while no app stack exists. After phase 7, delete `asmbly-ceramics-prod` and
  `asmbly-ceramics-stage` first; their table and bucket are retained. A later change to
  the stack follows the runbook's "Later changes", with its own check and undo.
- Nothing else in the account changes: the `asmbly.org` zone gets the two names'
  records and the certificates' validation records, which no other project uses.

## Admin actions

- Before this phase merges: the maintainer confirms the two addresses
  `ceramics.asmbly.org` and `ceramics-stage.asmbly.org`, and the `Environment` tag value
  for the bootstrap (`EnvironmentTag`: `prod` by default; `shared` needs CLAUDE.md's rule
  amended first).
- After it merges: deploy the bootstrap by hand with rights to the `asmbly.org` zone;
  create the `stage` and `prod` GitHub environments (deployments from `main` only) with
  the **secrets** `AWS_DEPLOY_ROLE_ARN` and `AWS_CFN_EXECUTION_ROLE_ARN` (a role ARN holds
  the account ID) and the **variables** `AWS_REGION`, `SAM_ARTIFACTS_BUCKET` and
  `WEB_ADAPTER_LAYER_ARN`; set `/asmbly-ceramics/<env>/hash-key`, `form-key` and
  `session-key` (SecureString) and `alert-email` and `initial-sending-address` (String)
  for both environments. All by the runbook.
- His decision, proposed: an account-level S3 public access block (the runbook's
  "Proposed admin actions"), after the account's other projects agree.

## Hand-off

Built on branch `feat/aws-bootstrap-phase-5` (2026-11-14). Nothing is in AWS until the
maintainer follows [the runbook](../../docs/runbooks/aws-bootstrap.md) after the merge.
The prep revisions above are what was built; where this section and the
Implementation details above differ, this section and `infra/bootstrap.yaml` are right.

Phase 7 can rely on:

- The stack `asmbly-ceramics-bootstrap` (termination protection on) and its exports
  `asmbly-ceramics-stage-function-boundary-arn`, `asmbly-ceramics-prod-function-boundary-arn`
  (each app stack imports its own: `{'Fn::ImportValue': !Sub '${ProjectSlug}-${AppEnv}-function-boundary-arn'}`),
  `asmbly-ceramics-prod-domain-name` and
  `asmbly-ceramics-stage-domain-name` (each the custom domain's name, to map an API
  to; the domains are dualstack).
- The GitHub environments `stage` and `prod`, deployments from `main` only, each with
  the **secrets** `AWS_DEPLOY_ROLE_ARN` (its own role: `asmbly-ceramics-gha-deploy-stage`
  or `-prod`, trusted only by that environment and allowed only its own stack) and
  `AWS_CFN_EXECUTION_ROLE_ARN`, and the **variables** `AWS_REGION`,
  `SAM_ARTIFACTS_BUCKET` (`asmbly-ceramics-artifacts-<suffix>`, no account ID) and
  `WEB_ADAPTER_LAYER_ARN`. `deploy.yml` reads the role ARNs as `secrets.`, not `vars.`.
- For each environment, the SSM SecureStrings `/asmbly-ceramics/<env>/hash-key`,
  `form-key` and `session-key`, and the Strings `/asmbly-ceramics/<env>/alert-email` and
  `initial-sending-address`.
- What the execution role allows, which `infra/app.yaml` must fit:
  - every taggable resource created with `Project=asmbly-ceramics` and the other four
    tags (stack tags; explicit `Tags` on alarms, which `PutMetricAlarm` checks); extra
    tags (SAM's `lambda:createdBy`, `httpapi:createdBy`) are fine;
  - names: table `asmbly-ceramics-<env>-records`, bucket
    `asmbly-ceramics-<env>-photos-<suffix>`, functions `asmbly-ceramics-<env>-<job>`,
    log groups `/aws/lambda/asmbly-ceramics-<env>-<job>`,
    `/aws/apigateway/asmbly-ceramics-<env>` (or `/aws/vendedlogs/asmbly-ceramics-…`),
    topic `asmbly-ceramics-<env>-alarms`, alarms `asmbly-ceramics-<env>-*`, queues
    `asmbly-ceramics-<env>-mailer-dlq` and `-close-dlq`, schedule
    `asmbly-ceramics-<env>-close` in the default group;
  - every function role (and the scheduler's) with `RolePath: /asmbly-ceramics-app/`
    (SAM's `Globals.Function.RolePath`), a name starting `asmbly-ceramics-<env>-` (SAM's
    generated `<stack>-<Function>Role-…` does, the stack being `asmbly-ceramics-<env>`),
    and `PermissionsBoundary` set to its own environment's imported boundary ARN; passed only to `lambda.amazonaws.com` or
    `scheduler.amazonaws.com`. IAM can't condition a trust policy's content, so
    `test_app_template.py` pins each role's trust to those principals;
  - the Web Adapter layer: `lambda:GetLayerVersion` on `layer:LambdaAdapterLayerArm64`
    in the publisher account the maintainer set (`WebAdapterPublisherAccount`) only;
  - no Cognito, SES, Route 53 or ACM resource in an app stack; only an
    `AWS::ApiGatewayV2::ApiMapping` to the bootstrap's domain name;
  - the HTTP API as an `AWS::ApiGatewayV2::Api` with no `Body` and its tags, plus its
    `Integration`, `Route`, `Stage` (with its tags) and an `AWS::Lambda::Permission`
    for `apigateway.amazonaws.com`: no `AWS::Serverless::HttpApi` or `HttpApi` event
    (it imports a body, then tags the API, and the role has no API Gateway tagging
    right; decision 0003); event-source mappings tagged (stack tags) and feeding an
    `asmbly-ceramics-` function;
  - `AWS::SSM::Parameter::Value<String>` parameters only under `/config/cognito/staff/`
    and `/asmbly-ceramics/<env>/alert-email` and `initial-sending-address`; the deploy
    workflow never runs `describe-stacks` or `describe-change-set`, which show the
    resolved values (phase 7 says so too);
  - no Untag right anywhere: a template that removes a tag fails.
- What only phase 7's `test_app_template.py` can fence, because the execution role
  changes the photo bucket by name (S3 checks tags only with ABAC on) and can't see a
  template's content: the photo bucket keeps all four public access block settings on,
  `BucketOwnerEnforced`, SSE-S3, the TLS-only Deny, no public principal in its policy,
  and versioning off (#7's deletes must be real); CORS only for `https://<SiteHost>`
  and `POST`; no `AWS::Logs::ResourcePolicy` (the bootstrap owns the access-log policy,
  and the role is denied it); the access-log group named
  `/aws/apigateway/asmbly-ceramics-<env>` (the bootstrap's policy covers only that); each
  role's trust is `lambda.amazonaws.com` or `scheduler.amazonaws.com` (IAM has no
  condition on a trust policy's content). The role itself refuses a `Lambda::Permission`
  for any principal but `apigateway.amazonaws.com`. The deploy
  workflow masks the account ID (`::add-mask::`) before `sam deploy` prints stack ARNs.
- Each boundary's statement Sids (`WriteOwnLogs`, `OwnTables`, `OwnPhotos`,
  `ListOwnPhotos`, `OwnSecrets`, `DecryptOwnSecretsThroughSsm`,
  `SendFromAsmblyAddresses`, `RunOwnFunctions`, `OwnDeadLetterQueues`), each function
  role taking a subset. `TransactWriteItems` is not an IAM action: a commit needs only
  `PutItem` (and `UpdateItem` for the counter). No `dynamodb:ListStreams` (it takes no
  resource); a role's stream statement leaves it out too.
- `tests/repo/cloudformation.py`'s `load_template` for `test_app_template.py`, and
  `tests/repo/test_bootstrap.py::test_only_the_deploy_workflow_may_get_credentials`,
  which phase 7 changes to name `deploy.yml`'s two deploy jobs.

To confirm on phase 7's first stage deploy (fail closed; a fix is a reviewed change to
`infra/bootstrap.yaml` the maintainer asks for, never a widening in the console):

- that CloudFormation sends the tags in `CreateApi` (`POST /apis`), `CreateStage` and
  `CreateEventSourceMapping`, rather than tagging afterwards (the role can't);
- that API Gateway evaluates `aws:ResourceTag` on routes, integrations, stages and API
  mappings against their API or domain name (`ChangeOwn`); if not, decision 0003's
  fallback;
- that CloudFormation sends `aws:SourceAccount` when it assumes the execution role
  (neither sibling's role has the condition); if it doesn't, the fix is removing that
  condition from the trust, as a reviewed change;
- that the handler permissions listed are all the deploy needs (SNS may check
  subscription actions on the topic, which `SubscriptionsByName`'s pattern covers), and
  that, with the bootstrap's `asmbly-ceramics-log-delivery` policy, the stage's access
  logs need no `logs:PutResourcePolicy` (if they do, decision 0003's fallback).

Also for phase 7: the execution role's rights are in three managed policies
(`asmbly-ceramics-cfn-exec-create`, `-change`, `-roles`) plus an inline Deny, because
one inline policy passed IAM's 10,240-character limit; `test_every_policy_fits_iams_size_limits`
measures each. Artifacts expire after 90 days: a rollback after a quiet quarter needs
the old code object, so phase 7's operations runbook says to redeploy instead.

Open for the maintainer: each environment now has its own boundary (decision 0003), but
stage and prod still share the execution role, so a stage template could name a prod
resource or pass a prod role. Both deploy roles also write to the one artifacts bucket,
so a stage job could place an object a prod deploy reuses (`sam` skips an upload whose
hash-named key exists). An execution role and an artifacts prefix or bucket per
environment would close it; that is his call. The keys use SSM's AWS
managed key, which anyone in the account with `ssm:GetParameter` on them can decrypt; a
customer-managed key is also his call.

Deferred: phase 9's document cites `scheduler:*` and `sqs:*` from this phase; the
execution role gives the four schedule actions in `SchedulesByName` and named SQS
actions, which is what phase 9 must fit (its `/prep` checks it).

# 0003: Each environment's functions have their own permissions boundary, and the HTTP API is created with its tags

Status: accepted, 15 November 2026 (proposed 14 November 2026), with phase 5 of the plan for epic #1
([phase 5](../../.implementation_plans/drop-off-and-firing/phase-5-aws-bootstrap.md)).
It amends [0002](0002-how-the-app-is-built-and-deployed.md), "The deploy", which named
one boundary for every function role. It becomes accepted when the maintainer approves
phase 5's pull request; he can reverse either choice with a new record.

Two cold reviews of the bootstrap template (`infra/bootstrap.yaml`) on 14 November 2026
found that one boundary covered both environments, so a stage template, which a merge
deploys before anyone looks at prod, could give a stage function prod's table, photos
and keys. They also found that the execution role could tag any API Gateway resource
and any Lambda event-source mapping. Those IDs are generated, so no name fenced the
right, and an untagged resource of another project could be given
`Project=asmbly-ceramics` and then changed or deleted. The account had one untagged
event-source mapping and three untagged REST APIs, all another project's.

## One boundary per environment

**Chosen:** two managed policies, `asmbly-ceramics-stage-function-boundary` and
`asmbly-ceramics-prod-function-boundary`, exported as
`asmbly-ceramics-<env>-function-boundary-arn`. Each allows only its own environment's
names: tables `asmbly-ceramics-<env>-*`, the bucket `asmbly-ceramics-<env>-photos-*`,
parameters `/asmbly-ceramics/<env>/*`, functions, queues and log groups
`asmbly-ceramics-<env>-*`. The execution role creates a role named
`asmbly-ceramics-stage-*` only with the stage boundary and `asmbly-ceramics-prod-*` only
with prod's. The app template imports its own environment's export.

**Why:** a merge reaches stage with no one watching, so stage is where a bad template
shows up first. With its own boundary, a stage function can't reach prod's data whatever
its role says. The other option the reviews named, one execution role per environment,
is larger, and the boundary is the part that limits the running code.

**Consequence, accepted:** the execution role and the artifacts bucket are still shared.
A stage template could still name a prod table in a resource property, or pass an
existing prod role to a stage function: the execution role is fenced by project, not
environment. Both environments deploy the same reviewed template from `main`, so this
needs a reviewed change to reach. A boundary change now has two documents to check
(runbook step 8 checks both).

**Revisit if:** the maintainer wants the execution role or the artifacts bucket split per
environment as well, or wants one boundary back for simplicity.

## The HTTP API and event-source mappings take their tags in the create request

**Chosen:** the execution role has no `TagResource` right on API Gateway (`/tags/*`).
An event-source mapping is created with its tags (`lambda:CreateEventSourceMapping`
with `aws:RequestTag`, see the next section for its `lambda:TagResource`), and is read,
changed or deleted only when it carries `Project=asmbly-ceramics` and feeds an
`asmbly-ceramics-` function (`lambda:FunctionArn`). The app's HTTP API is an
`AWS::ApiGatewayV2::Api` with no `Body`, created by `POST /apis` with its tags, and its
integration, route, stage and invoke permission are separate resources (phase 7). SAM's
`AWS::Serverless::HttpApi` is not used: it imports an OpenAPI body (`PUT /apis`), which
takes no tags, and then tags the API.

**Why:** API Gateway's `Tags` resource has no condition key, so no condition can say
"only this project's API", and the API's ID is generated, so no name can either.

**Consequence, accepted:** the app template is longer (four resources in place of SAM's
event). A later change to the API's tags fails until the bootstrap allows it, which
needs a reviewed change. If CloudFormation turns out to tag the API after creating it
instead of in the request, the first stage deploy fails closed.

**Revisit if:** API Gateway adds a condition key on its tagging resource, or the first
stage deploy shows the handler tags after creating.

## An event-source mapping's tags need `lambda:TagResource`, fenced by "no import"

Lambda's guide ("Using tags on event source mappings") says `lambda:TagResource` is
needed "to call `TagResource` or perform a tag on create", so without it phase 7's
mailer mapping, created with the stack's tags, is refused.

**Chosen:** `lambda:TagResource` on `event-source-mapping:*`, only with
`aws:RequestTag/Project=asmbly-ceramics` and the other four tags in the request
(`TagEventSourceMappingsOnCreate`). Both deploy roles are denied any import change set
(`cloudformation:CreateChangeSet` when `cloudformation:ImportResourceTypes` is present,
`NoResourceImport`). Still no `UntagResource`.

**Why:** no condition key limits `lambda:TagResource` to the create call: the Service
Authorization Reference gives it only `aws:RequestTag` and `aws:TagKeys`, not
`lambda:FunctionArn`, and an untagged mapping has no `aws:ResourceTag` either way. So
the fence is who can drive the role. Only CloudFormation can assume it (its trust
policy), and only the two deploy roles may hand it a stack. A template reaches an
existing mapping only by importing it, which they can't. Without import, every mapping
the role tags is one it creates, or one already tagged `Project=asmbly-ceramics` in
its stack (another project's tagged mappings are denied outright).

CloudFormation's automatic import (`--import-existing-resources` on a change set) also
exists. It sends no `ResourcesToImport`, so the `cloudformation:ImportResourceTypes`
Deny may not see it, but it adopts only a resource whose template gives a static name
(its identifier). An event-source mapping's identifier is a generated UUID, and so is
an HTTP API's, its routes', integrations' and mappings', with no name to set, so
automatic import can adopt none of them. It can adopt a named resource (a table, a
bucket, a function) that already exists, but every name the execution role may write
starts with `asmbly-ceramics-`.

**Residual risk, accepted for now:** the fence is outside IAM's evaluation of
`lambda:TagResource` itself. Someone with admin rights who passes the execution role
to an import, or a future CloudFormation feature that adopts existing resources
without an import change set, could give another project's untagged mapping
`Project=asmbly-ceramics`. Changing or deleting it then also checks
`lambda:FunctionArn`, but on an update that key may be the function the request names
rather than the one the mapping feeds, so it isn't a fence to rely on. The real second
fence is the function boundary: a mapping pointed at an `asmbly-ceramics-` function
runs it under its environment's boundary, which can't read another project's stream or
queue, so no other project's records reach this project's code. The account had one
untagged mapping (another project's) on 14 November 2026.

**Revisit if:** Lambda adds `lambda:FunctionArn` (or another create-only key) to
`TagResource`, or CloudFormation adds a way to adopt resources other than import.

## The bootstrap owns the access-log delivery policy

An HTTP API stage with access logs needs a CloudWatch Logs resource policy that lets
`delivery.logs.amazonaws.com` write the log group. In this account, CloudFormation's
role calls `logs:PutResourcePolicy` with the log group's ARN when it creates such a
stage (CloudTrail, October 2026; every active HTTP API log group has a log-group policy,
seen with `describe-resource-policies --policy-scope RESOURCE`). `logs:PutResourcePolicy`
takes no resource and no condition key (Service Authorization Reference), so allowing
it would let the role rewrite any project's log-group policy or the account's shared
ones.

**Chosen:** the bootstrap creates one account-scope policy of its own name,
`asmbly-ceramics-log-delivery` (`LogDeliveryPolicy`): `delivery.logs.amazonaws.com` may
`CreateLogStream` and `PutLogEvents` on `/aws/apigateway/asmbly-ceramics-*` only, from
this account. The execution role stays denied `logs:PutResourcePolicy` and
`DeleteResourcePolicy`. CloudWatch Logs' guide ("Logs sent to CloudWatch Logs") says
that when an account-level policy already grants this through wildcards, no
log-group policy is created, and that whoever sets up delivery then needs fewer rights.
That guide is about vended logs; whether an HTTP API stage's access logs follow it, so
that the stage's create skips `logs:PutResourcePolicy`, is unproven until phase 7's
first stage deploy. The fallback below stays for that reason.

**Why:** it can't overwrite anything: the policy has its own name, the maintainer
deploys it, and the deploys can't change it.

**Consequence, accepted:** one of the account's ten account-scope policies (none were
in use on 14 November 2026). Phase 7's access-log group must be named
`/aws/apigateway/asmbly-ceramics-<env>`.

**Fallback, if the first stage deploy still fails on `logs:PutResourcePolicy`:** the
bootstrap creates the two access-log groups as well, each with its own log-group policy,
and the app stacks import their names. Allowing `logs:PutResourcePolicy` to the
execution role is not the fallback.

## The API's integration, route and stage, and their tags

The execution role changes `/apis/*` only where `aws:ResourceTag/Project` is
`asmbly-ceramics`. The Service Authorization Reference lists `aws:ResourceTag` as a
condition key on HTTP API (V2) Integrations, Routes and Stages, but AWS documents that
sub-resources inherit their API's tags only for REST APIs (V1), not HTTP APIs. An
integration or a route takes no tags, and the stage's create is `POST
/apis/<id>/stages`, which is authorized on the `Stages` collection under the same
`aws:ResourceTag` check: the tags in its request satisfy `aws:RequestTag`, not that
check. So if HTTP APIs don't inherit, the integration, route and stage fail closed
(another project's API is never reachable).

**Fallback, decided now:** if phase 7's first stage deploy is refused on its
integration, route or stage, the maintainer recreates it with rollback disabled so the
API stays and reads its ID (phase 7, "If the first create of a stack fails"). A
reviewed bootstrap change then adds that ID as a parameter (`StageHttpApiId`, later
`ProdHttpApiId`) with an Allow, by ARN, of all five methods (`apigateway:GET`, `POST`,
`PUT`, `PATCH`, `DELETE`) on `/apis/<that id>/*`: the creates, the changes, the
deletes and the handlers' `GET` read-backs. The API itself stays tag checked; the ID
is passed at deploy time, never committed. The template has about 2,000 bytes to spare
under the inline limit, enough for this; a larger change trims comments or deploys
with `--s3-bucket` (the runbook's "Later changes to the bootstrap stack").

## An API mapping is checked against its domain's tags, not its API's

`POST`, `PATCH` and `DELETE` on `/domainnames/<name>/apimappings*` are fenced by the
two domain names and the domain's `Project` tag. The Service Authorization Reference
gives the `ApiMappings` and `ApiMapping` resources only `aws:ResourceTag`, and no
condition key carries the mapping's `ApiId`, so no condition can say "only this
project's API".

**Residual risk, accepted, low:** a reviewed app template could map this project's
domain to another project's API. That changes nothing in the other project's API or
data: it only routes `ceramics.asmbly.org` (or the stage address) to it, which the
smoke test after each deploy would show. No other project's domain can be touched.

**Revisit if:** API Gateway adds a condition key for a mapping's API.

## What has and has not been seen to work

Checked on 14 November 2026: the condition keys, from AWS's Service Authorization
Reference (the JSON at `servicereference.us-east-1.amazonaws.com`).
`lambda:Get/Update/DeleteEventSourceMapping` take `lambda:FunctionArn`;
`lambda:CreateEventSourceMapping` takes `aws:RequestTag` and `lambda:FunctionArn`;
`lambda:TagResource` takes only `aws:RequestTag` and `aws:TagKeys`;
`logs:PutResourcePolicy` has no resource type; API Gateway's `Tags` resource has no
condition key; `cloudformation:CreateChangeSet` takes
`cloudformation:ImportResourceTypes`.

CloudTrail in this account (October 2026, other projects' stacks) shows CloudFormation
sending the tags in the request of `CreateApi` and `CreateStage`, and calling
`logs:PutResourcePolicy` with a log group's ARN while creating a stage with access
logs.

The template passes `cfn-lint` and `sam validate --lint`, and
`tests/repo/test_bootstrap.py` pins these choices. Nothing is deployed: whether
CloudFormation sends the tags in `CreateEventSourceMapping`, whether the account-scope
log policy spares the stage `logs:PutResourcePolicy`, and whether an HTTP API's route,
integration and stage see its tags will only be seen on phase 7's first stage deploy.

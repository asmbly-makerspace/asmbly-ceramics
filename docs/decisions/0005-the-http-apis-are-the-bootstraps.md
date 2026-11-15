# 0005: The two HTTP APIs are the bootstrap's, and the execution role reads and deletes by name

Status: proposed, 15 November 2026 (accepted when the maintainer merges its pull request). Amends
[0003](0003-one-function-boundary-per-environment.md): replaces its fallback for the
API's integration, route and stage, and its API mapping fence moves into the same
by-ID statement.

The first stage deploy (the merge of #33, 15 November 2026) failed and rolled back.
The execution role (`asmbly-ceramics-cfn-exec`) was refused three times:

- `apigateway:POST` on `/tags/<the new API's ARN>`: creating the API was allowed, but
  API Gateway authorizes the tags as a separate call on the tags path, which no
  statement allowed.
- `sns:GetTopicAttributes` on the alarm topic: CloudFormation reads the topic while
  creating it, before the `aws:ResourceTag/Project` check can match.
- `logs:DeleteLogGroup` on the five log groups, in the rollback: their creates had been
  cancelled, so the groups didn't exist and had no tag to match. The stack ended in
  `ROLLBACK_FAILED`.

AWS documents that HTTP API (V2) routes and integrations take no tags and inherit
none (only REST API (V1) children inherit), so 0003's tag check on `/apis/*` could
never let the app create its routes either. 0003 had foreseen that and chosen a
fallback: recreate the stack with rollback disabled, read the API's ID, and add it to
the bootstrap as a parameter.

## The bootstrap creates each environment's HTTP API

**Chosen:** `infra/bootstrap.yaml` creates `StageApi` and `ProdApi`
(`AWS::ApiGatewayV2::Api`, `asmbly-ceramics-stage` and `-prod`, HTTP, the execute-api
endpoint off, the five tags) and exports their IDs as `asmbly-ceramics-<env>-api-id`.
The app stack imports its environment's ID and adds the integrations, routes, stage,
invoke permissions and API mapping to it. The execution role gets `ApisById`: all five
`apigateway:` methods on `/apis/<that ID>` and `/apis/<that ID>/*`, and on the two
domains' `apimappings`, with no tag condition. `TheApisAreReadOnly` denies everything
but `GET` on the two APIs themselves, so a deploy can't change or delete them.
`StageTagsById` allows `apigateway:POST` on the tags path of those two APIs' stages
only, with `aws:RequestTag/Project=asmbly-ceramics`. `CreateTagged` and `ChangeOwn`
no longer name any API Gateway resource.

**Why:** the same fence as 0003's fallback (two known IDs, by ARN, never another
project's API), without a failed create, a stack kept with rollback disabled, or an
ID passed by hand at each deploy. A tagging right on `/tags/*` was rejected: it would
let the role tag another project's untagged API with this Project and then change it.
An untagged `/apis/*` Allow was rejected for the same reason as before.

**Consequence, accepted:** the API's settings (its name, protocol, the execute-api
endpoint) change only through a bootstrap change, run by the maintainer. An app stack
can't be deleted and recreated with a new API: it reuses its environment's.

**Revisit if:** API Gateway adds an `ApiId` condition key for HTTP API sub-resources,
or tag inheritance for HTTP APIs.

## Reads and deletes by name

**Chosen:** `ReadAndDeleteByName` and `ReadAndDeleteRolesByName` allow, without a tag
condition, the reads and deletes CloudFormation's handlers make on this project's
names (`asmbly-ceramics-*` tables, functions, log groups, topics, queues and alarms,
and the function roles under `/asmbly-ceramics-app/`): `Get*`, `List*`, `Describe*`,
`Delete*` and `Detach*` only. They are in a fourth managed policy,
`asmbly-ceramics-cfn-exec-apis`, since one managed policy holds at most 6,144
characters.

**Why:** a read before a create, and a delete in the rollback of a create that never
ran, happen when the resource has no tag yet, or doesn't exist. Creating, changing and
tagging still need the tags.

**Consequence, accepted:** the role may read or delete a resource named
`asmbly-ceramics-*` that has no `Project` tag. `HandsOffOtherProjects` still denies
anything with another project's tag, and the prefix is this repository's (CLAUDE.md).

## The bootstrap template goes to S3

**Chosen:** the template is now over CloudFormation's 51,200-byte inline limit. An
update uploads it to the artifacts bucket (`--s3-bucket`), as the runbook's "Later
changes to the bootstrap stack" already allowed; the size test checks the 1 MB S3
limit.

**Consequence, accepted:** a rebuild from nothing (the stack deleted) uploads the
template to a bucket made by hand first, because the artifacts bucket is in the stack.

## What has and has not been seen to work

On 15 November 2026 the failures above were read from the stage stack's events, and
the leftover log groups were checked (read-only) to not exist. AWS's resource type
registry gave each resource type's handler permissions, and the IAM policy simulator
(read-only) showed which ones the role refused. The simulator can't show what a
handler actually calls, or how API Gateway names the tags path for a stage, so only the
next stage deploy proves this. The two forms of the tags path, with and without `/v2/`,
are both allowed for that reason.

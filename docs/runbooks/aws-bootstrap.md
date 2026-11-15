# Runbook: the AWS bootstrap

The bootstrap stack, `asmbly-ceramics-bootstrap`, holds what the app's deploys stand
on and can't create for themselves: a deploy role for each GitHub environment, the
CloudFormation execution role, the permissions boundary every function role carries,
the policy that lets log delivery write the HTTP APIs' access logs, the bucket
`sam deploy` uploads code to, and the two addresses
(`ceramics.asmbly.org` and `ceramics-stage.asmbly.org`: certificates, API Gateway
custom domain names and DNS records). Its template is
[`infra/bootstrap.yaml`](../../infra/bootstrap.yaml); `tests/repo/test_bootstrap.py`
pins what it allows.

It is deployed **once, by hand**, by the maintainer, and only when the maintainer has
asked for it in the conversation. An agent never runs a step of this runbook that
changes anything. Every step below has **Do**, **Check**, **Who confirms** and
**Undo**. Commands that only read are marked `# read only`; `# expect:` says what a
good answer looks like. Nothing a command prints goes into a file, an issue, a pull
request or a chat: the account ID, the role ARNs and the addresses stay on your screen.

## Before you start: the maintainer's questions

- **The `Environment` tag on the bootstrap's resources.** CLAUDE.md says every resource
  carries `Environment=prod` or `stage`; the bootstrap serves both environments. The
  template's parameter `EnvironmentTag` is `prod` by default, as CLAUDE.md asks, and
  the commands below pass `prod`. The maintainer may choose `shared` instead, but only
  after amending CLAUDE.md's tagging rule (and its tests) to allow it, in a reviewed
  pull request; then set `ENV_TAG=shared` in step 4 and in later changes.
- **An account-level S3 public access block** ([Proposed admin actions](#proposed-admin-actions)):
  yes or no.

Before any step, in a shell signed in to Asmbly's AWS account with admin rights:

```bash
export AWS_PROFILE=asmbly AWS_REGION=us-east-2
cd <your clone of asmbly-ceramics, on an up-to-date main>
```

## 1. Read-only checks

**Do:**

```bash
aws sts get-caller-identity --query Arn --output text        # read only
# expect: an admin role in the Asmbly account

aws sesv2 get-account --query '{prod:ProductionAccessEnabled,status:EnforcementStatus}'   # read only
# expect: {"prod": true, "status": "HEALTHY"}

# Address identities at asmbly.org, counted, never listed (they can be people's addresses).
aws sesv2 list-email-identities \
  --query "length(EmailIdentities[?IdentityType=='EMAIL_ADDRESS' && ends_with(IdentityName, '@asmbly.org')])"   # read only
# expect: a number. The boundary allows sending through the domain identity or an
# address identity at asmbly.org, so any number works.

export PARENT_ZONE=$(aws route53 list-hosted-zones-by-name --dns-name asmbly.org \
  --query "HostedZones[?Name=='asmbly.org.'].Id | [0]" --output text | sed 's|/hostedzone/||')   # read only
aws route53 list-resource-record-sets --hosted-zone-id "$PARENT_ZONE" \
  --query "ResourceRecordSets[?Name=='ceramics.asmbly.org.' || Name=='ceramics-stage.asmbly.org.' || ends_with(Name, '.ceramics.asmbly.org.') || ends_with(Name, '.ceramics-stage.asmbly.org.')].Name"   # read only
# expect: []  (neither name exists; ceramics.mcp.asmbly.org is AsmblyMCPs' and is not matched)

dig +short CAA asmbly.org                                     # read only
# expect: nothing, or a list that includes amazon.com (or amazontrust.com, awstrust.com,
# amazonaws.com). Otherwise ACM can't issue the certificates and step 4 waits until it
# times out: stop and ask whoever owns the zone.

aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?ends_with(Arn, 'token.actions.githubusercontent.com')] | length(@)"   # read only
# expect: 1 (another project made it). If 0, pass CreateGitHubOidcProvider=true in step 4.

aws cloudformation describe-stacks --stack-name asmbly-ceramics-bootstrap 2>&1 | tail -1   # read only
# expect: "Stack with id asmbly-ceramics-bootstrap does not exist"

aws logs describe-resource-policies --query 'length(resourcePolicies)'   # read only
# expect: at most 9 (0 on 14 November 2026). These are the account-scope policies,
# at most 10 per account; step 4 adds one, asmbly-ceramics-log-delivery.
aws logs describe-resource-policies --query "resourcePolicies[?policyName=='asmbly-ceramics-log-delivery'] | length(@)"   # read only
# expect: 0
aws logs describe-resource-policies --policy-scope RESOURCE --query 'length(resourcePolicies)'   # read only
# expect: a number (4 on 14 November 2026: other projects' HTTP API log groups, each
# with a log-group policy made when its stage was created). Don't print their content.
```

**Check:** every answer is as expected. **Who confirms:** the maintainer.
**Undo:** nothing to undo.

## 2. The OIDC subject

The deploy roles trust a GitHub token only when its `sub` is this repository's, in
GitHub's immutable form (the organization's and the repository's numeric IDs, so a
renamed or re-created repository of the same name doesn't match).

**Do:**

```bash
gh api repos/asmbly-makerspace/asmbly-ceramics/actions/oidc/customization/sub   # read only
# expect: "use_immutable_subject": true and a "sub_claim_prefix" of the form
#         repo:asmbly-makerspace@<number>/asmbly-ceramics@<number>
```

Only if `use_immutable_subject` is `false`:

```bash
gh api -X PUT repos/asmbly-makerspace/asmbly-ceramics/actions/oidc/customization/sub \
  -F use_default=true -F use_immutable_subject=true
```

Don't set `include_claim_keys`: it changes the subject's format and no role would match.

```bash
export SUBJECT=$(gh api repos/asmbly-makerspace/asmbly-ceramics/actions/oidc/customization/sub --jq .sub_claim_prefix)
[[ "$SUBJECT" =~ ^repo:asmbly-makerspace@[0-9]+/asmbly-ceramics@[0-9]+$ ]] && echo ok   # read only
# expect: ok
```

**Check:** `ok`. **Who confirms:** the maintainer. **Undo:** if you changed it, set
`use_immutable_subject=false` the same way.

## 3. The GitHub environments, before the roles exist

GitHub creates an environment, with no protection, the first time a job names one that
doesn't exist. So `stage` and `prod` are created, limited to `main`, **before** step 4
makes the roles that trust them: a job on any other branch, and every pull request
(whose jobs run in no environment), then gets nothing.

**Do:**

```bash
for env in stage prod; do
  gh api -X PUT "repos/asmbly-makerspace/asmbly-ceramics/environments/$env" --input - <<'JSON'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
  gh api -X POST "repos/asmbly-makerspace/asmbly-ceramics/environments/$env/deployment-branch-policies" \
    -f name=main -f type=branch
done
```

`prod` may also have the maintainer as a required reviewer (repository settings,
Environments, prod). Only a job in `prod` can deploy the prod stack. Each environment's
functions carry their own boundary, so a stage function can't reach prod's table,
photos or keys ([decision 0003](../decisions/0003-one-function-boundary-per-environment.md)).
The two stacks still share the execution role and the artifacts bucket, so a stage
template could still name a prod resource: the reviewer gates the prod deploy, not
everything a merge can reach.

**Check:**

```bash
for env in stage prod; do
  gh api "repos/asmbly-makerspace/asmbly-ceramics/environments/$env" --jq '{name, policy: .deployment_branch_policy}'
  gh api "repos/asmbly-makerspace/asmbly-ceramics/environments/$env/deployment-branch-policies" --jq '[.branch_policies[].name]'
done   # read only
# expect: each with custom_branch_policies true, and ["main"]
```

**Who confirms:** the maintainer. **Undo:** delete the environments
(`gh api -X DELETE repos/asmbly-makerspace/asmbly-ceramics/environments/<env>`); only
before step 5 has put secrets in them, or with those secrets set again afterwards.

## 4. Deploy the stack, with a change set

**Who confirms the DNS part, beforehand:** whoever is responsible for the `asmbly.org`
zone is told that the stack adds `ceramics.asmbly.org` and `ceramics-stage.asmbly.org`
(an `A` and an `AAAA` alias each) and one certificate validation `CNAME` for each name,
and nothing else in the zone.

**Do:**

The Lambda Web Adapter layer is published by an AWS account of its own, not Asmbly's.
Its README (github.com/awslabs/aws-lambda-web-adapter, "Zip Packages") lists the layer's
ARN, `arn:aws:lambda:<region>:<account>:layer:LambdaAdapterLayerArm64:<version>`. The
execution role may read the layer only from that account, so put the account number
in `ADAPTER_ACCOUNT` at the prompt. It never goes in a file.

```bash
printf "Web Adapter publisher account (from its README): "; read -r ADAPTER_ACCOUNT
[[ "$ADAPTER_ACCOUNT" =~ ^[0-9]{12}$ && "$ADAPTER_ACCOUNT" != "$(aws sts get-caller-identity --query Account --output text)" ]] && echo ok   # read only
# expect: ok (twelve digits, and not this account)
export ENV_TAG=prod   # shared only once CLAUDE.md allows it (above)
export ARTIFACTS_SUFFIX=$(python3 -c "import secrets; print(secrets.token_hex(4))")
aws cloudformation deploy \
  --template-file infra/bootstrap.yaml \
  --stack-name asmbly-ceramics-bootstrap \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-execute-changeset \
  --tags Project=asmbly-ceramics Component=Bootstrap "Environment=$ENV_TAG" Owner=it-volunteers ManagedBy=cloudformation \
  --parameter-overrides "GitHubSubjectPrefix=$SUBJECT" "ParentHostedZoneId=$PARENT_ZONE" \
    "ArtifactsBucketSuffix=$ARTIFACTS_SUFFIX" "WebAdapterPublisherAccount=$ADAPTER_ACCOUNT" \
    "EnvironmentTag=$ENV_TAG"
# add "CreateGitHubOidcProvider=true" to the overrides only if step 1 found no provider
```

It prints a `describe-change-set` command; read the change set before executing it:

```bash
aws cloudformation describe-change-set --stack-name asmbly-ceramics-bootstrap \
  --change-set-name <the name it printed> \
  --query 'Changes[].ResourceChange.[Action,LogicalResourceId,ResourceType]' --output table   # read only
# expect: 19 rows (20 with the OIDC provider), every Action "Add": the two deploy roles,
# the execution role and its three managed policies, the two boundaries (stage and
# prod), the log delivery policy, the artifacts bucket and its policy, two
# certificates, two domain names and four DNS records.

aws cloudformation execute-change-set --stack-name asmbly-ceramics-bootstrap \
  --change-set-name <the name it printed>
aws cloudformation wait stack-create-complete --stack-name asmbly-ceramics-bootstrap
aws cloudformation update-termination-protection --stack-name asmbly-ceramics-bootstrap \
  --enable-termination-protection
```

The wait includes the certificates' DNS validation; a few minutes is normal.

**Check:**

```bash
aws cloudformation describe-stacks --stack-name asmbly-ceramics-bootstrap \
  --query 'Stacks[0].[StackStatus,EnableTerminationProtection,length(Outputs)]'   # read only
# expect: ["CREATE_COMPLETE", true, 8]

aws logs describe-resource-policies --query "resourcePolicies[?policyName=='asmbly-ceramics-log-delivery'] | length(@)"   # read only
# expect: 1

for name in ceramics.asmbly.org ceramics-stage.asmbly.org; do
  aws acm list-certificates --query "CertificateSummaryList[?DomainName=='$name'].Status"
done   # read only
# expect: ["ISSUED"] twice

dig +short ceramics.asmbly.org A ceramics.asmbly.org AAAA ceramics-stage.asmbly.org A   # read only
# expect: addresses. Until phase 7 maps an API, a request to them gets an error page.
```

Afterwards, whoever is responsible for the `asmbly.org` zone confirms nothing else in it
changed.

**Who confirms:** the maintainer, and the zone's owner for the DNS records.

**Undo** (only while no app stack exists: after phase 7 the app stacks import the
exports, and `asmbly-ceramics-stage` and `asmbly-ceramics-prod` must be deleted first):

```bash
aws cloudformation update-termination-protection --stack-name asmbly-ceramics-bootstrap \
  --no-enable-termination-protection
aws cloudformation delete-stack --stack-name asmbly-ceramics-bootstrap
aws cloudformation wait stack-delete-complete --stack-name asmbly-ceramics-bootstrap
aws route53 list-resource-record-sets --hosted-zone-id "$PARENT_ZONE" \
  --query "ResourceRecordSets[?Name=='ceramics.asmbly.org.' || Name=='ceramics-stage.asmbly.org.' || ends_with(Name, '.ceramics.asmbly.org.') || ends_with(Name, '.ceramics-stage.asmbly.org.')].[Name,Type]"   # read only
# expect: []. A validation CNAME left behind (_<hash>.ceramics.asmbly.org) is deleted
# by hand in the zone, after telling its owner.
```

The artifacts bucket is retained: empty it and delete it by hand if it isn't wanted.

### If the first create fails

A failed create rolls back and leaves the stack in `ROLLBACK_COMPLETE`, which can't be
updated, only deleted.

```bash
aws cloudformation describe-stack-events --stack-name asmbly-ceramics-bootstrap \
  --query "StackEvents[?ends_with(ResourceStatus, 'FAILED')].[LogicalResourceId,ResourceStatusReason]" \
  --max-items 10 --output table   # read only: the first failure is the cause
aws cloudformation delete-stack --stack-name asmbly-ceramics-bootstrap
aws cloudformation wait stack-delete-complete --stack-name asmbly-ceramics-bootstrap
aws s3api head-bucket --bucket "asmbly-ceramics-artifacts-$ARTIFACTS_SUFFIX" 2>&1 | tail -1   # read only
# expect: Not Found. If the retained bucket exists, delete it (it is empty) or make a
# new suffix, then run step 4 again.
```

If the cause is a right or a tag condition in the template, the fix is a pull request
to `infra/bootstrap.yaml`, reviewed and merged, never a change made in the console.

## 5. The GitHub secrets and variables

A role ARN holds the account ID, and GitHub prints a step's `with:` inputs in the
public Actions logs, so the role ARNs are **environment secrets**. The bucket's name
has no account ID in it and is a variable. No address is in GitHub at all.

**Do:**

The Web Adapter layer's ARN comes from the Lambda Web Adapter's README (arm64,
us-east-2, version 27 or later); phase 7 needs it. Its account must be the
`ADAPTER_ACCOUNT` of step 4: the execution role reads no layer from anywhere else, so a
wrong variable fails the deploy. Put it in `LAYER_ARN` first.

```bash
LAYER_ARN='<from the Lambda Web Adapter README>'
out() { aws cloudformation describe-stacks --stack-name asmbly-ceramics-bootstrap \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
gh secret set AWS_DEPLOY_ROLE_ARN --env stage --body "$(out StageDeployRoleArn)"
gh secret set AWS_DEPLOY_ROLE_ARN --env prod --body "$(out ProdDeployRoleArn)"
for env in stage prod; do
  gh secret set AWS_CFN_EXECUTION_ROLE_ARN --env "$env" --body "$(out ExecutionRoleArn)"
  gh variable set AWS_REGION --env "$env" --body us-east-2
  gh variable set SAM_ARTIFACTS_BUCKET --env "$env" --body "$(out ArtifactsBucketName)"
  gh variable set WEB_ADAPTER_LAYER_ARN --env "$env" --body "$LAYER_ARN"
done
```

**Check:**

```bash
for env in stage prod; do gh secret list --env "$env"; gh variable list --env "$env"; done   # read only
# expect: in each, the secrets AWS_DEPLOY_ROLE_ARN and AWS_CFN_EXECUTION_ROLE_ARN, and the
# variables AWS_REGION, SAM_ARTIFACTS_BUCKET and WEB_ADAPTER_LAYER_ARN
```

**Who confirms:** the maintainer. **Undo:** `gh secret delete <name> --env <env>` and
`gh variable delete <name> --env <env>`.

## 6. The app's keys

For each environment, three SecureStrings of 32 random bytes. The value is made by
`openssl` inside the command: never typed, pasted into a file or a chat, or printed.

**Do:**

```bash
for env in stage prod; do
  for key in hash-key form-key session-key; do
    aws ssm put-parameter --name "/asmbly-ceramics/$env/$key" --type SecureString \
      --value "$(openssl rand -base64 32)" \
      --tags Key=Project,Value=asmbly-ceramics Key=Component,Value=App "Key=Environment,Value=$env" \
             Key=Owner,Value=it-volunteers Key=ManagedBy,Value=manual
  done
done
```

What each key is for, and what changing it does:

- `form-key` (the public form's cookie; the form function only): changing it only
  expires open ID pages. Safe at any time.
- `session-key` (the console's sign-in state and CSRF tokens; the console only):
  changing it signs everyone out of the console. Safe at any time.
- `hash-key` (the rate limit's and the submission tokens' keyed hashes): changing it
  resets the rate-limit counts and orphans every live submission: its ID page expires,
  and a form sent again with the same submission token is not seen as a repeat, so it
  makes a second drop-off and a second received email. Change it only when the studio
  is closed and no one is mid-drop-off. To rotate any key, run its `put-parameter` with
  `--overwrite` (and without `--tags`).

**Check:**

```bash
aws ssm describe-parameters --parameter-filters Key=Name,Option=BeginsWith,Values=/asmbly-ceramics/ \
  --query 'Parameters[].[Name,Type]' --output table   # read only: names and types, never values
# expect: six rows, all SecureString
```

**Who confirms:** the maintainer. **Undo:** `aws ssm delete-parameter --name <name>`,
only before phase 7 has deployed: afterwards the functions read these at run time and
fail without them.

## 7. The two addresses

For each environment, two Strings: where the alarms go (the maintainers' address) and
the studio's `asmbly.org` address that emails come from until staff change it in the
console. They are read at the prompt into a variable, so they are never on a command
line (or in shell history), in a file, or in GitHub. CloudFormation resolves them when
phase 7 deploys. `describe-stacks` and `describe-change-set` show the resolved values,
so no workflow may run or print either for an app stack: the Actions logs are public.

**Do:**

```bash
for env in stage prod; do
  printf "Alert address for %s: " "$env"; read -r ADDRESS
  aws ssm put-parameter --name "/asmbly-ceramics/$env/alert-email" --type String --value "$ADDRESS" \
    --tags Key=Project,Value=asmbly-ceramics Key=Component,Value=App "Key=Environment,Value=$env" \
           Key=Owner,Value=it-volunteers Key=ManagedBy,Value=manual
  printf "Initial sending address (at asmbly.org) for %s: " "$env"; read -r ADDRESS
  aws ssm put-parameter --name "/asmbly-ceramics/$env/initial-sending-address" --type String --value "$ADDRESS" \
    --tags Key=Project,Value=asmbly-ceramics Key=Component,Value=App "Key=Environment,Value=$env" \
           Key=Owner,Value=it-volunteers Key=ManagedBy,Value=manual
done
unset ADDRESS
```

**Check:**

```bash
aws ssm describe-parameters --parameter-filters Key=Name,Option=BeginsWith,Values=/asmbly-ceramics/ \
  --query 'Parameters[].[Name,Type]' --output table   # read only
# expect: ten rows: per environment three SecureString (step 6) and two String
```

**Who confirms:** the maintainer. **Undo:** `aws ssm delete-parameter --name <name>`,
before phase 7 has deployed.

## 8. Check the boundaries

For each environment's boundary, simulations of its own document: one that must be
allowed, one that must not (a From address outside `asmbly.org`), and one on the other
environment's table, which must not be allowed either. A boundary that denied
everything would fail the first; one that covered both environments would fail the
third.

**Do:**

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
DOMAIN=asmbly.org OTHER=example.com
for env in stage prod; do
  other=$([ "$env" = stage ] && echo prod || echo stage)
  key=$([ "$env" = stage ] && echo Stage || echo Prod)
  BOUNDARY=$(aws cloudformation describe-stacks --stack-name asmbly-ceramics-bootstrap \
    --query "Stacks[0].Outputs[?OutputKey=='${key}FunctionBoundaryArn'].OutputValue" --output text)
  VERSION=$(aws iam get-policy --policy-arn "$BOUNDARY" --query Policy.DefaultVersionId --output text)
  DOCUMENT=$(aws iam get-policy-version --policy-arn "$BOUNDARY" --version-id "$VERSION" \
    --query PolicyVersion.Document --output json)
  for from in "studio@$DOMAIN" "studio@$OTHER"; do
    aws iam simulate-custom-policy --policy-input-list "$DOCUMENT" \
      --action-names ses:SendEmail \
      --resource-arns "arn:aws:ses:us-east-2:$ACCOUNT:identity/$DOMAIN" \
      --context-entries "ContextKeyName=ses:FromAddress,ContextKeyValues=$from,ContextKeyType=string" \
      --query 'EvaluationResults[0].EvalDecision' --output text
  done
  for table in "$env" "$other"; do
    aws iam simulate-custom-policy --policy-input-list "$DOCUMENT" \
      --action-names dynamodb:GetItem \
      --resource-arns "arn:aws:dynamodb:us-east-2:$ACCOUNT:table/asmbly-ceramics-$table-records" \
      --query 'EvaluationResults[0].EvalDecision' --output text
  done
done   # read only
# expect, for each environment: allowed, implicitDeny, allowed, implicitDeny
unset ACCOUNT
```

**Check:** `allowed`, `implicitDeny`, `allowed`, `implicitDeny`, twice. **Who confirms:**
the maintainer. **Undo:** nothing to undo.

The deploy roles are first used for real by phase 7's first deploy.

## Later changes to the bootstrap stack

A change to `infra/bootstrap.yaml` is a reviewed pull request like any other; a merge
deploys nothing. Changing the stack changes what the deploys may do (the roles) and
what every function may do (the boundaries), so it gets the same four parts as the
steps above. The maintainer runs it, only when he has asked for it.

**Do**, from an up-to-date `main`: make a change set. No `--parameter-overrides`: every
parameter keeps its value (a new `ArtifactsBucketSuffix` would replace the artifacts
bucket). Use the same `Environment` tag value as step 4.

```bash
git rev-parse --short HEAD   # note the commit; the undo goes back to the one before it
export ENV_TAG=prod   # step 4's value: the stack's EnvironmentTag parameter
aws cloudformation deploy \
  --template-file infra/bootstrap.yaml \
  --stack-name asmbly-ceramics-bootstrap \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-execute-changeset \
  --tags Project=asmbly-ceramics Component=Bootstrap "Environment=$ENV_TAG" Owner=it-volunteers ManagedBy=cloudformation
aws cloudformation describe-change-set --stack-name asmbly-ceramics-bootstrap \
  --change-set-name <the name it printed> \
  --query 'Changes[].ResourceChange.[Action,LogicalResourceId,Replacement]' --output table   # read only
# expect: only the resources the pull request changed, each "Modify" with Replacement
# "False", unless the pull request says otherwise
```

The template is sent inline, and `test_the_template_fits_cloudformations_inline_size_limit`
keeps it under 51,200 bytes. It had about 2,000 bytes to spare on 14 November 2026. If a
change doesn't fit, trim the template's comments (keeping what they say), or, since the
artifacts bucket exists after the first create, add
`--s3-bucket <the ArtifactsBucketName output>` to the `deploy` command above, which
uploads the template there and lifts the limit to 1 MB.

Before executing, read the change set:

- `Replacement: True` on a role or the artifacts bucket changes its ARN or name: the
  GitHub secrets and variables (step 5) must be set again.
- An export the app stacks import (a boundary's ARN, the two domain names) can't be
  changed or removed while they import it; CloudFormation refuses the update.
- A boundary has no stage step: an edit to prod's boundary reaches prod's functions at
  once.

If the change set isn't what the pull request said, delete it
(`aws cloudformation delete-change-set --stack-name asmbly-ceramics-bootstrap --change-set-name <name>`)
and stop. Otherwise, execute it:

```bash
aws cloudformation execute-change-set --stack-name asmbly-ceramics-bootstrap \
  --change-set-name <the name it printed>
aws cloudformation wait stack-update-complete --stack-name asmbly-ceramics-bootstrap
```

**Check:**

```bash
aws cloudformation describe-stacks --stack-name asmbly-ceramics-bootstrap \
  --query 'Stacks[0].[StackStatus,EnableTerminationProtection,length(Outputs)]'   # read only
# expect: ["UPDATE_COMPLETE", true, 8]
```

Then run step 8 again (both boundaries). After a change to a deploy role or the
execution role, the next deploy of stage (a merge, or the deploy workflow run by hand
on `main`) must go green before prod's.

**Who confirms:** the maintainer, who reads the change set before executing it.

**Undo:** a failed update rolls back by itself (`UPDATE_ROLLBACK_COMPLETE`, the old
template and rights). To undo an update that succeeded, revert the pull request, merge
the revert, and run this section again from the new `main`. In an emergency, run the
same `deploy` from a checkout of the commit noted above. Neither undoes a replaced
role's or bucket's new name: set step 5's secrets and variables again.

Termination protection stays on; turn it off only for the undo in step 4.

## Proposed admin actions

These are for the maintainer to decide; nothing in this repository depends on them.

**An account-level S3 public access block.** The execution role can change the photo
bucket's own public access block, policy and CORS rules by name, and no IAM condition
can see their content. Phase 7's template test pins them, and an account-level block
would hold even if a bucket's own block were turned off. Whether the account has one
is the **Check** command below, run before deciding (step 1 doesn't check it). It
applies to every bucket in the account, so first ask whether any other project serves
a public bucket.

- **Do:** `aws s3control put-public-access-block --account-id "$(aws sts get-caller-identity --query Account --output text)" --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true`
- **Check:** `aws s3control get-public-access-block --account-id "$(aws sts get-caller-identity --query Account --output text)"`
  (read only); expect all four `true`.
- **Who confirms:** the maintainer, after the owners of the account's other projects agree.
- **Undo:** `aws s3control delete-public-access-block --account-id "$(aws sts get-caller-identity --query Account --output text)"`.

## Who can merge to `main`

Changes reach the live app only through a merge to `main` and its deploy (phase 7 adds
the deploy). Who can merge, and how, is in [CONTRIBUTING.md](../../CONTRIBUTING.md).

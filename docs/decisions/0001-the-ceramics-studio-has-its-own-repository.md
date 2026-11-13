# 0001: The ceramics studio has its own repository

Status: accepted by the maintainer (@sababado), 12 November 2026, in the **Decided**
section of epic #1. This record writes those decisions down with their reasons; the
epic is where they were made.

Asmbly's ceramics studio takes about 80 drop-offs and runs about 6 firings a week. Drop-offs
go through a ClickUp form, which can't show the person an ID to write on their slip, and
whose emails don't work. Ceramics staff asked for a drop-off form that shows the ID
straight away, emails that reach people with their photos, and a way to build kiln
loads from a waiting list made for it.

## A repository of its own

**Chosen:** a new repository, `asmbly-makerspace/asmbly-ceramics`, for the drop-off
form, the staff console, and everything they need in AWS.

**Why:** it is an app with its own users, data and deploy, and nothing in the existing
repositories fits it. AsmblyMCPs serves Claude connectors for staff; asmbly-staff-login
is the staff sign-in, which this app uses but doesn't own; the facilities repository
automates facilities work. Putting the app in one of them would tie its deploys and its
rights to theirs.

**Revisit if:** another studio needs the same drop-off and firing flow, and a shared app
would serve both better.

## Public

**Chosen:** the repository is public.

**Why:** the maintainer chose it (epic #1). The code holds nothing secret, and members
and volunteers can see how the studio's app works and suggest changes.

**Consequence, accepted:** the rules are stricter than in a private repository. No
secret, AWS account ID, internal address or personal detail is ever committed, and
issues and pull requests refer to drop-offs by ID and staff by username
([CLAUDE.md](../../CLAUDE.md#this-repository-is-public)). A pull request from a fork is
untrusted code, so CI holds no credentials. Being public, the repository has the
protection on `main` and private vulnerability reporting regardless of the
organization's plan.

## Python with uv, set up like the sibling repositories

**Chosen:** Python 3.14 managed with uv, checked with ruff, strict mypy and pytest with
a coverage floor, as AsmblyMCPs and asmbly-staff-login are; and the same setup:
`CLAUDE.md` as the rules for AI agents, `.claude/` skills, agents and settings,
`docs/decisions/`, a pull request template with **Risk**, CODEOWNERS, a ruleset on
`main`, Dependabot and the dependency audit, `PR check` as the required check, squash
merges and Conventional Commits.

**Why:** the same maintainer works in all three, and the same rules and tools keep the
same mistakes out. The app is a package under `src/asmbly_ceramics/` from the start, so
that its tests import it as the deployed app will.

**Revisit if:** the plan for epic #1 finds that a part of the app (the pages, for
example) is better written in another language; that part's choice gets its own record.

## Clean code, built for later features

**Chosen:** the app is planned around a domain model (drop-offs, loads, kilns, firing
types, settings) in plain Python, with storage, photos, email and sign-in behind
interfaces that AWS adapters implement. Kilns, firing types, glaze types, rejection
reasons and the email settings are data managed in the console, not code. The
framework, the hosting, the data store and the deploy are left to the technical plan
([still to be decided](../architecture.md#still-to-be-decided)).

**Why:** the maintainer asked for clean code and for later features (a kiln schedule,
#9; perhaps a glaze log) to fit without rework. A domain that knows nothing about AWS
can be tested fast and fully, and a new feature is a new use case on the same model.

## Staff sign in through asmbly-staff-login

**Chosen:** ceramics staff sign in with Asmbly's staff sign-in, which
asmbly-staff-login owns. That repository adds a sign-in client for this app that admits
its `ceramics` staff group; members of that group can open the console. This repository
holds no rights over the staff sign-in.

**Why:** staff already have a staff sign-in, and one place deciding who may sign in to
what is easier to keep right than a second user list. asmbly-staff-login decided that
every app's client is defined there.

**Consequence, accepted:** the console can't go live before asmbly-staff-login has the
`ceramics` group (asmbly-staff-login#4) and this app's client.

## The drop-off form has no sign-in

**Chosen:** the form is public, with no sign-in and no membership check; it asks for a
name, an email and a phone number, all required.

**Why:** anyone dropping off at the studio, member or not, uses the form from their
phone, and a sign-in would stand between them and their ID.

**Consequence, accepted:** the form is untrusted input from anyone, which the server
checks and rate-limits (#2), and the app holds contact details of people who may not be
members, which it deletes when a drop-off closes (#7).

## A clean start: no ClickUp migration

**Chosen:** the app starts empty, with IDs from `AC-1`. Nothing is imported from
ClickUp, and ClickUp's `KO-` numbers are not reused. Drop-offs already in ClickUp at the
switch are finished there (#8).

**Why:** the maintainer decided it (epic #1). Starting empty means the app never takes
in ClickUp's records and the personal details in them, and a new prefix keeps the two
sets of numbers apart on the studio's slips.

## No fees

**Chosen:** the app takes no payment and charges no firing fee.

**Why:** the maintainer decided it (epic #1). Payments would bring a payment provider,
and its data and rules, into an app that otherwise needs neither.

**Revisit if:** the studio decides to charge for firing; that is a new epic.

## What has and has not been seen to work

Nothing has been built yet. On 12 November 2026 the repository held only its README, and
epic #1 with stories #2 to #9 was written. The ClickUp figures in the epic (drop-offs a
week, firing types, photos per drop-off, load sizes) were read from ClickUp that day,
counts only.

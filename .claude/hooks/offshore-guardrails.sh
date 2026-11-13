#!/usr/bin/env bash
# PreToolUse guardrail for unattended /offshore runs (.claude/skills/offshore/SKILL.md).
#
# Active only for the Claude Code session that runs /offshore, and the subagents it
# spawns; every other session, in this folder or any other, is left alone, and several
# runs can go on at once.
#
# How a session is claimed. The run starts with the exact Bash command
#     : offshore-start <run-slug>
# (a shell no-op). Seeing it, this hook writes a claim for the call's session_id at
#     $(git rev-parse --git-common-dir)/offshore/sessions/<session_id>
# which every worktree of the repository shares, and makes the run's state folder
# <checkout>/.offshore/<run-slug>/. Claiming again is harmless (a resume). The run ends
# with the exact command
#     : offshore-end <run-slug>
# which removes that session's claim and nothing else. Claude Code gives a subagent's
# tool calls the session_id of the session that spawned it (hooks reference, SubagentStop
# input: "The transcript_path is the main session's transcript"), and, as a fallback, a
# subagent's transcript_path lies under <session_id>/subagents/, so either one finds the
# claim. A session without a claim is allowed everything, and the hook writes nothing
# for it. Two runs can't claim the same run slug.
#
# While a session is claimed, it blocks (exit code 2; the message on stderr says what to do
# instead):
#   - the AskUserQuestion tool: no one is there to answer
#   - git push to main: plain names, refspecs (HEAD:main, x:refs/heads/main), deletes
#     (:main, --delete main), --all/--mirror, and a push with no refspec while main is
#     checked out
#   - bare force pushes: --force, -f, or a +refspec (--force-with-lease is allowed, on
#     the run's own branch, for the squash and rebase steps)
#   - hook bypass: --no-verify, git commit -n, core.hooksPath overrides
#   - git reset --hard and git commit --amend
#   - merging a pull request: gh pr merge (with or without --admin), the merge API, and
#     the GitHub merge tools; starting a workflow or changing repository settings
#   - deploying: sam deploy, sync, delete, remote, publish, package, pipeline
#   - any aws command that isn't read-only, and any aws command at all that doesn't run
#     with the profile `asmbly` (--profile asmbly, or AWS_PROFILE=asmbly); reading a
#     secret's value
#   - editing uv.lock by hand (Edit/Write tools, or a shell write to it)
#   - lowering the coverage floor (fail_under in pyproject.toml, or --cov-fail-under)
#   - writing `pull_request_target` into anything under .github/
#   - changing this hook, .claude/settings*.json, or the claims, by any tool
#
# Quoted strings are neutralized and heredoc bodies dropped before commands are
# matched, so a commit message that mentions a flag ("never use --no-verify") is not a
# flag. `bash -c '...'`, `sh -c` and `eval` strings are checked as commands.
#
# This is a guardrail, not a sandbox. Code that calls AWS or git from inside a script
# gets past it; the rules in the skill apply whether or not the hook catches something.
#
# Portable: bash 3.2 (macOS) and Linux. Reads the payload with jq when it is installed,
# otherwise with a small awk JSON reader, so the checks hold either way.
#
# Logs, per run: .offshore/<run-slug>/guardrails.log (every decision) and
# .offshore/<run-slug>/agents.log (Agent spawns).
# Exit codes: 0 allow, 2 block. An internal error never blocks: it is logged and the
# call is allowed.
#
# Tests: uv run pytest tests/repo/test_offshore_guardrails.py

set -euo pipefail
set -f # never glob: command words are split into tokens, not expanded
export LC_ALL=C

BLOCKED=0
LOG=/dev/null

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG" 2>/dev/null || true
}

# Any non-zero exit that isn't a deliberate block becomes "allow", so a parsing problem
# can't fail closed and stop the run.
on_exit() {
  rc=$?
  if [ "$rc" -ne 0 ] && [ "$BLOCKED" -ne 1 ]; then
    log "WARN internal error (exit $rc); call allowed"
    exit 0
  fi
}
trap on_exit EXIT

PROFILE_REQUIRED=asmbly
PAYLOAD=$(cat 2>/dev/null || true)

# ---------------------------------------------------------------------------
# Reading the payload: jq when it is there, otherwise awk.

if command -v jq >/dev/null 2>&1; then
  READER=jq
else
  READER=awk
fi

# Every string value stored under "key" anywhere in the payload, JSON escapes decoded,
# joined with newlines. The awk reader matches the key by name at any depth, which is
# enough for the few keys read here.
json_all() { # $1: key
  if [ "$READER" = jq ]; then
    printf '%s' "$PAYLOAD" | jq -r --arg k "$1" '[.. | objects | .[$k]? | strings] | join("\n")' 2>/dev/null || true
    return 0
  fi
  printf '%s' "$PAYLOAD" | awk -v key="$1" '
    { s = s $0 "\n" }
    END {
      hex = "0123456789abcdef"
      pat = "\"" key "\""
      n = length(s); pos = 1; first = 1
      while (pos <= n) {
        rest = substr(s, pos)
        i = index(rest, pat)
        if (i == 0) break
        at = pos + i - 1
        pos = at + length(pat)
        if (at > 1 && substr(s, at - 1, 1) == "\\") continue
        j = pos
        while (j <= n && substr(s, j, 1) ~ /[ \t\r\n]/) j++
        if (substr(s, j, 1) != ":") continue
        j++
        while (j <= n && substr(s, j, 1) ~ /[ \t\r\n]/) j++
        if (substr(s, j, 1) != "\"") continue
        j++
        out = ""
        while (j <= n) {
          c = substr(s, j, 1)
          if (c == "\"") break
          if (c == "\\") {
            j++; e = substr(s, j, 1)
            if (e == "n") out = out "\n"
            else if (e == "t") out = out "\t"
            else if (e == "r") out = out "\r"
            else if (e == "b" || e == "f") out = out " "
            else if (e == "u") {
              v = 0
              for (k = 1; k <= 4; k++) v = v * 16 + index(hex, tolower(substr(s, j + k, 1))) - 1
              j += 4
              out = out ((v > 0 && v < 128) ? sprintf("%c", v) : "?")
            } else out = out e
          } else out = out c
          j++
        }
        pos = j + 1
        if (!first) printf "\n"
        printf "%s", out
        first = 0
      }
    }' 2>/dev/null || true
}

json_first() { # $1: key; the first value only, on one line
  json_all "$1" | head -n 1
}

CWD=$(json_first cwd)
[ -d "${CWD:-/nonexistent}" ] || CWD=""
SESSION=$(json_first session_id)
TRANSCRIPT=$(json_first transcript_path)
TOOL=$(json_first tool_name)

# A session ID as a file name: letters, digits, dot, dash and underscore only.
sanitize() {
  printf '%s' "$1" | tr -cd 'A-Za-z0-9._-' | cut -c1-128
}

# The repository's common git directory (shared by all its worktrees), as an absolute
# path, for a directory; nothing outside a repository.
common_dir() { # $1: a directory
  local d
  [ -n "$1" ] && [ -d "$1" ] || return 0
  d=$(git -C "$1" rev-parse --git-common-dir 2>/dev/null) || return 0
  case $d in
    /*) printf '%s' "$d" ;;
    *) (cd "$1" && cd "$d" && pwd) 2>/dev/null || true ;;
  esac
}

# The IDs that identify this call's session: its session_id, and the session whose
# transcript folder holds a subagent's transcript.
SESSION_IDS=$(sanitize "$SESSION")
case $TRANSCRIPT in
  */subagents/*)
    parent=${TRANSCRIPT%%/subagents/*}
    SESSION_IDS="$SESSION_IDS $(sanitize "${parent##*/}")"
    ;;
  *.jsonl)
    base=${TRANSCRIPT##*/}
    SESSION_IDS="$SESSION_IDS $(sanitize "${base%.jsonl}")"
    ;;
esac

# Where claims can be: the repository of the call's folder, and of Claude Code's
# project folder.
CLAIM_DIRS=""
for d in "$CWD" "${CLAUDE_PROJECT_DIR:-}"; do
  c=$(common_dir "$d")
  [ -n "$c" ] || continue
  case "
$CLAIM_DIRS
" in
    *"
$c/offshore/sessions
"*) ;;
    *) CLAIM_DIRS="$CLAIM_DIRS
$c/offshore/sessions" ;;
  esac
done

# How long a claimed run may be silent before another session may take it over.
STALE_MINUTES=30
TAKEN_OVER=""

claim_value() { # $1: claim file, $2: key
  [ -f "$1" ] || return 0
  sed -n "s/^$2=//p" "$1" 2>/dev/null | head -n 1 || true
}

# The exact start and end commands. Anything else that touches a claim is blocked
# below, for a claimed session.
COMMAND=""
if [ "$TOOL" = Bash ]; then
  COMMAND=$(json_all command | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
fi
case $COMMAND in
  ": offshore-start "* | ": offshore-end "*)
    verb=${COMMAND#: offshore-}
    verb=${verb%% *}
    slug=${COMMAND#: offshore-"$verb" }
    own=$(sanitize "$SESSION")
    here=$(common_dir "${CWD:-${CLAUDE_PROJECT_DIR:-$PWD}}")
    top=$(git -C "${CWD:-${CLAUDE_PROJECT_DIR:-$PWD}}" rev-parse --show-toplevel 2>/dev/null || true)
    refuse() {
      BLOCKED=1
      printf 'OFFSHORE GUARDRAIL: blocked offshore-%s %s.\n%s\n' "$verb" "$slug" "$1" >&2
      exit 2
    }
    case $slug in
      *[!a-z0-9-]* | '' | -*) refuse "A run slug is lowercase letters, digits and dashes, for example 3-drop-off-form." ;;
    esac
    [ -n "$own" ] || refuse "This call carries no session_id, so the guardrail can't be scoped to this session. Stop the run: it can't start safely here."
    [ -n "$here" ] && [ -n "$top" ] || refuse "Start the run inside a git checkout of the repository."
    sessions="$here/offshore/sessions"
    claim="$sessions/$own"
    if [ "$verb" = end ]; then
      if [ -f "$claim" ]; then
        mkdir -p "$(claim_value "$claim" state)" 2>/dev/null || true
        LOG="$(claim_value "$claim" state)/guardrails.log"
        if [ "$(claim_value "$claim" run)" = "$slug" ]; then
          log "END run=$slug session=$own"
          rm -f "$claim"
        else
          log "END run=$slug ignored: this session runs $(claim_value "$claim" run)"
        fi
      fi
      exit 0
    fi
    [ "$verb" = start ] || refuse "The commands are : offshore-start <run-slug> and : offshore-end <run-slug>."
    if [ -f "$claim" ] && [ "$(claim_value "$claim" run)" != "$slug" ]; then
      refuse "This session already runs $(claim_value "$claim" run). End it with : offshore-end $(claim_value "$claim" run) first."
    fi
    if [ -d "$sessions" ]; then
      for name in $(ls "$sessions" 2>/dev/null); do # globbing is off; IDs have no spaces
        other="$sessions/$name"
        [ -f "$other" ] && [ "$other" != "$claim" ] || continue
        if [ "$(claim_value "$other" run)" = "$slug" ]; then
          # A live run logs every tool call of its session and subagents, polls included
          # (every few minutes at most). Silent for STALE_MINUTES: that session is gone,
          # and a new session may take the run over to resume it.
          activity="$(claim_value "$other" state)/guardrails.log"
          [ -f "$activity" ] || activity=$other
          if [ -n "$(find "$activity" -mmin +"$STALE_MINUTES" 2>/dev/null)" ]; then
            rm -f "$other"
            mkdir -p "$(claim_value "$claim" state)" 2>/dev/null || true
            TAKEN_OVER=$name
          else
            refuse "Run $slug is held by another session that is still active (claimed $(claim_value "$other" started)). Two sessions never work on one run: start a run for different work, or wait. A run silent for $STALE_MINUTES minutes can be taken over to resume it."
          fi
        fi
      done
    fi
    started=$(claim_value "$claim" started)
    [ -n "$started" ] || started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    state="$top/.offshore/$slug"
    mkdir -p "$sessions" "$state"
    printf 'run=%s\nroot=%s\nstate=%s\nstarted=%s\n' "$slug" "$top" "$state" "$started" >"$claim"
    LOG="$state/guardrails.log"
    [ -z "$TAKEN_OVER" ] || log "TAKEOVER run=$slug from silent session $TAKEN_OVER"
    log "START run=$slug session=$own"
    exit 0
    ;;
esac

# Is this call's session claimed?
CLAIM=""
while IFS= read -r dir; do
  [ -n "$dir" ] || continue
  for id in $SESSION_IDS; do
    if [ -n "$id" ] && [ -f "$dir/$id" ]; then
      CLAIM="$dir/$id"
      break 2
    fi
  done
done <<EOF
$CLAIM_DIRS
EOF

# Not an /offshore run's session: allow everything, and write nothing.
[ -n "$CLAIM" ] || exit 0

RUN=$(claim_value "$CLAIM" run)
ROOT=$(claim_value "$CLAIM" root)
STATE_DIR=$(claim_value "$CLAIM" state)
[ -n "$ROOT" ] || ROOT=${CWD:-${CLAUDE_PROJECT_DIR:-$PWD}}
[ -n "$STATE_DIR" ] || STATE_DIR="$ROOT/.offshore/${RUN:-run}"
mkdir -p "$STATE_DIR" 2>/dev/null || true
LOG="$STATE_DIR/guardrails.log"
AGENTS_LOG="$STATE_DIR/agents.log"
[ "$READER" = jq ] || log "WARN jq not found; reading the payload with awk"
[ -n "$CWD" ] || CWD=$ROOT

FOOTER="(This guardrail is on because this session runs /offshore ($RUN): it claimed itself with : offshore-start $RUN. Other sessions aren't affected. Never touch the claim or edit this hook to get past a block; the run ends its claim with : offshore-end $RUN when it stops.)"

block() { # $1: short reason for the log, $2: what to do instead
  BLOCKED=1
  log "BLOCK tool=$TOOL $1"
  printf 'OFFSHORE GUARDRAIL: blocked %s.\n%s\n%s\n' "$1" "$2" "$FOOTER" >&2
  exit 2
}

MSG_ASK="No one is there to answer. Decide using CLAUDE.md, the docs for the area, and the plan, and record the decision (orchestrator: a decision event in CHECKPOINT.json; sub-agent: the decisions list in your result). If the decision truly isn't yours (a product, privacy or security call the plan doesn't settle), stop that unit as blocked with the question, so the briefing asks it."
MSG_PROTECTED="Offshore work is pushed only to its own branch, feat/<run> (and offshore/<run>/<phase> for a parked phase). main changes only through a pull request that the maintainer merges. Push your branch by name: git push --force-with-lease origin feat/<run> (plain git push origin feat/<run> if you didn't rewrite history)."
MSG_FORCE="A bare force push can overwrite work someone else pushed. Use --force-with-lease on your own branch. If the lease is rejected: git fetch origin, look at what arrived (git log HEAD..origin/<branch>), rebase onto it, and push with --force-with-lease again."
MSG_HOOKS="Hooks must run on every commit and push (CLAUDE.md: never bypass hooks). Fix what the hook reports and try again. If you can't fix it, record the failure (a blocked result, or an Action Item for the briefing) instead of bypassing the hook."
MSG_RESET="git reset --hard throws work away. To squash, use git reset --soft <sha> and commit. To drop a file's changes, git restore <path>. To set work aside, git stash."
MSG_AMEND="Make a new commit instead; the run squashes its units later. To record a squashed commit's SHA, write it to CHECKPOINT.json and let that ride in the next commit. Don't amend it in."
MSG_MERGE="The maintainer merges, on his word, for that pull request (CLAUDE.md). Leave the pull request open and green, and say in the briefing that it's ready for review."
MSG_GH_SETTINGS="Starting a workflow or changing the repository's settings, variables, secrets or rulesets is the maintainer's call. List it as an Action Item for the briefing."
MSG_SAM="Offshore never deploys: a change reaches AWS only through a merge's deploy or a runbook step the maintainer asked for. Use sam build and sam validate --lint to check a template, and list any deploy step as an Action Item for the briefing."
MSG_AWS="Offshore is read-only against AWS (CLAUDE.md). Put the change in the template, or list it as an Action Item for the briefing."
MSG_PROFILE="Every aws command runs against Asmbly's account with the profile asmbly, in us-east-2: add --profile asmbly (or AWS_PROFILE=asmbly) and keep it read-only. Never use another profile or the default one: other profiles reach other accounts."
MSG_SECRET="Offshore never reads secret values. Check that a parameter or secret exists with describe-parameters, get-parameter without --with-decryption, or describe-secret, or list it as an Action Item for the briefing."
MSG_LOCK="uv.lock is written only by uv (CLAUDE.md). Change pyproject.toml with uv add or uv remove, or run uv lock, and commit the uv.lock it writes."
MSG_COVERAGE="The coverage floor (fail_under in pyproject.toml) is raised as coverage grows and never lowered (CLAUDE.md). Add the tests that bring coverage back up. If you can't, record it as blocked so the briefing raises it."
MSG_PRT="Workflows run pull requests with pull_request, never pull_request_target: the repository is public and a fork's pull request is untrusted code (CLAUDE.md). Use pull_request."
MSG_SELF="This hook, .claude/settings*.json, the session claims (<git common dir>/offshore/sessions/) and the runs' state folders (.offshore/) hold the guardrails. Don't change, move or delete them during a run. If one is wrong, list it as an Action Item for the briefing. The run ends its own claim only with : offshore-end <run-slug>."
MSG_AWS_READ="CLAUDE.md forbids reading a drop-off's personal details or photos, even read-only. Look at a table's or a bucket's shape with describe-table, list-objects-v2 or head-object, and test with the in-memory fakes."
MSG_MCP_AWS="Offshore reaches AWS only through the aws CLI with --profile asmbly, read-only, where this hook can check it. The AWS MCP tools that run code or touch resources aren't checked, so they are off during a run; its documentation tools are fine."
MSG_MCP_GITHUB="Offshore changes GitHub only through git and the gh CLI, where this hook can check it: push feat/<run> with git, and open or update the pull request with gh. The GitHub tools that merge, push or write files are off during a run."

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

less_than() { # $1 < $2, as numbers
  awk -v a="$1" -v b="$2" 'BEGIN { exit !((a + 0) < (b + 0)) }'
}

# The floor the repository has now, from pyproject.toml on disk (a PreToolUse hook runs
# before the edit lands).
FLOOR=""
if [ -f "$ROOT/pyproject.toml" ]; then
  FLOOR=$(sed -n 's/^[[:space:]]*fail_under[[:space:]]*=[[:space:]]*\([0-9.][0-9.]*\).*/\1/p' "$ROOT/pyproject.toml" | head -n 1)
fi

# The lowest fail_under value in a text, or nothing.
lowest_fail_under() {
  printf '%s\n' "$1" | sed -n 's/.*fail_under[[:space:]]*=[[:space:]]*\([0-9.][0-9.]*\).*/\1/p' |
    sort -n | head -n 1
}

# The lowest --cov-fail-under value in a text, or nothing.
lowest_cov_flag() {
  printf '%s\n' "$1" | tr ' \t' '\n\n' | awk '
    prev == "--cov-fail-under" && $0 ~ /^[0-9.]+$/ { print }
    /^--cov-fail-under=[0-9.]+$/ { sub(/^--cov-fail-under=/, ""); print }
    { prev = $0 }' | sort -n | head -n 1
}

check_cov_flag() { # $1: text that may pass --cov-fail-under
  local low
  case $1 in *--cov-fail-under*) ;; *) return 0 ;; esac
  low=$(lowest_cov_flag "$1")
  [ -n "$low" ] && [ -n "$FLOOR" ] || return 0
  if less_than "$low" "$FLOOR"; then
    block "--cov-fail-under $low, below the floor of $FLOOR" "$MSG_COVERAGE"
  fi
}

# ---------------------------------------------------------------------------
# Edit, Write, MultiEdit, NotebookEdit

check_file_edit() {
  local path base new old low rel
  path=$(json_first file_path)
  [ -n "$path" ] || path=$(json_first notebook_path)
  [ -n "$path" ] || return 0
  base=${path##*/}
  case $path in
    /*) rel=${path#"$ROOT"/} ;;
    *) rel=${path#./} ;;
  esac
  new="$(json_all new_string)
$(json_all content)
$(json_all new_source)"
  old=$(json_all old_string)

  case /$rel in
    */.claude/hooks/* | */.claude/settings*.json | */offshore/sessions/* | */offshore/sessions)
      block "editing $rel" "$MSG_SELF"
      ;;
  esac

  if [ "$base" = uv.lock ]; then
    block "editing uv.lock by hand" "$MSG_LOCK"
  fi

  case $rel in
    .github/*)
      case $new in
        *pull_request_target*) block "pull_request_target in $rel" "$MSG_PRT" ;;
      esac
      ;;
  esac

  if [ "$base" = pyproject.toml ]; then
    low=$(lowest_fail_under "$new")
    if [ "$TOOL" = Write ]; then
      # A whole new file: it must keep a floor at least as high as today's.
      if [ -n "$FLOOR" ] && [ -z "$low" ]; then
        block "removing the coverage floor from pyproject.toml" "$MSG_COVERAGE"
      fi
    else
      case $old in
        *fail_under*)
          if [ -z "$low" ]; then
            block "removing the coverage floor from pyproject.toml" "$MSG_COVERAGE"
          fi
          ;;
      esac
    fi
    if [ -n "$low" ] && [ -n "$FLOOR" ] && less_than "$low" "$FLOOR"; then
      block "lowering the coverage floor from $FLOOR to $low" "$MSG_COVERAGE"
    fi
  fi
  # Any other file that sets a floor (a workflow, another config file).
  check_cov_flag "$new"
  case $base in
    pyproject.toml) ;;
    .coveragerc | setup.cfg | tox.ini)
      low=$(lowest_fail_under "$new")
      if [ -n "$low" ] && [ -n "$FLOOR" ] && less_than "$low" "$FLOOR"; then
        block "a coverage floor of $low in $rel, below $FLOOR" "$MSG_COVERAGE"
      fi
      ;;
  esac
  return 0
}

# ---------------------------------------------------------------------------
# Bash: parsing

current_branch() { # $1: directory
  git -C "$1" symbolic-ref --short -q HEAD 2>/dev/null || true
}

# Drop heredoc bodies (commit messages written with <<EOF): they are data, not commands.
drop_heredocs() {
  local out="" delim="" line rest trimmed tab nl
  tab=$(printf '\t')
  nl='
'
  while IFS= read -r line || [ -n "$line" ]; do
    if [ -n "$delim" ]; then
      trimmed=${line#"${line%%[!$tab]*}"} # <<- allows leading tabs
      if [ "$trimmed" = "$delim" ]; then delim=""; fi
      continue
    fi
    out="$out$line$nl"
    case $line in
      *'<<<'*) ;; # a here-string, not a heredoc
      *'<<'*)
        rest=${line#*<<}
        rest=${rest#-}
        rest=${rest#"${rest%%[! ]*}"}
        rest=${rest#[\'\"\\]}
        delim=${rest%%[!A-Za-z0-9_]*}
        case $delim in
          [A-Za-z_]*) ;;
          *) delim="" ;;
        esac
        ;;
    esac
  done <<<"$1"
  printf '%s' "$out"
}

# Replace each quoted string. A quoted single word (no spaces or shell operators) is kept
# without its quotes, so "feat/$PLAN" is still a branch name. Anything longer becomes
# _Q_, so flags inside messages don't count. A double-quoted string holding a command
# substitution is processed recursively, so "$(git push ...)" is still checked.
neutralize_quotes() {
  local rest=$1 out="" buf part c closed
  while [ -n "$rest" ]; do
    part=${rest%%[\"\'\\]*}
    out="$out$part"
    rest=${rest#"$part"}
    [ -n "$rest" ] || break
    c=${rest%"${rest#?}"}
    rest=${rest#?}
    case $c in
      \\) # an escaped character outside quotes is literal
        out="$out$c${rest%"${rest#?}"}"
        rest=${rest#?}
        continue
        ;;
      \')
        closed=0
        case $rest in *\'*) closed=1 ;; esac
        buf=${rest%%\'*}
        rest=${rest#"$buf"}
        rest=${rest#\'}
        ;;
      \")
        closed=0
        buf=""
        while [ -n "$rest" ]; do
          part=${rest%%[\"\\]*}
          buf="$buf$part"
          rest=${rest#"$part"}
          [ -n "$rest" ] || break
          c=${rest%"${rest#?}"}
          rest=${rest#?}
          if [ "$c" = '"' ]; then
            closed=1
            break
          fi
          buf="$buf$c${rest%"${rest#?}"}" # backslash escape inside double quotes
          rest=${rest#?}
        done
        ;;
    esac
    if [ "$closed" -eq 0 ]; then
      out="$out _Q_" # unterminated quote: the shell would reject the command anyway
      break
    fi
    case $buf in
      *'$('* | *'`'*) out="$out$(neutralize_quotes "$buf")" ;;
      '') out="${out}_Q_" ;;
      *[[:space:]]* | *[\;\&\|\(\)\<\>]*) out="${out}_Q_" ;;
      *) out="$out$buf" ;;
    esac
  done
  printf '%s' "$out"
}

# Does a command text write to a path matching the extended regex $2? Redirections, tee,
# in-place sed or perl, and cp/mv/install onto it count; reading it doesn't.
writes_to() { # $1: text, $2: path regex
  local p=$2 q="['\"]?"
  printf '%s\n' "$1" | grep -Eq \
    -e ">[>|]?[[:space:]]*$q[^[:space:];&|]*$p" \
    -e "(^|[[:space:];&|(])tee[[:space:]]+(-[a-z]+[[:space:]]+)*$q[^[:space:];&|]*$p" \
    -e "(^|[[:space:];&|(])(sed|perl|ruby)[[:space:]]([^;&|]*[[:space:]])?(-[a-zA-Z]*i|--in-place)[^;&|]*$p" \
    -e "(^|[[:space:];&|(])(cp|mv|install)[[:space:]][^;&|]*[[:space:]]$q[^[:space:];&|]*$p$q[[:space:]]*($|[;&|)])" \
    -e "(^|[[:space:];&|(])(rm|truncate)[[:space:]][^;&|]*$p"
}

# Does a command text change a path matching $2 in any way: a write as above, or a move,
# link, permission change or deletion of it, or a script that names it.
touches() { # $1: text, $2: path regex
  writes_to "$1" "$2" && return 0
  printf '%s\n' "$1" | grep -Eq \
    -e "(^|[[:space:];&|(])(mv|ln|chmod|chflags|unlink|shred|rsync|dd)[[:space:]][^;&|]*$2" \
    -e "(^|[[:space:];&|(])find[[:space:]][^;&|]*$2[^;&|]*-(delete|exec)" \
    -e "(^|[[:space:];&|(])(python3?|node|perl|ruby|osascript)[[:space:]][^;&|]*$2"
}

# A git long option, written in full or abbreviated as git allows (--no-verif, --amen).
# --no-verb... is --no-verbose, not --no-verify.
is_no_verify() {
  case ${1:-} in
    --no-verb*) return 1 ;;
    --no-v*) return 0 ;;
  esac
  return 1
}

SEEN="" # git/gh/aws/sam commands seen, for the ALLOW log line
CMD_PROFILE=${AWS_PROFILE:-${AWS_DEFAULT_PROFILE:-}} # what an aws command would use without a flag
SEG_PROFILE=""

check_config_value() { # a -c key=value passed to git
  case $(lower "${1:-}") in
    core.hookspath | core.hookspath=*) block "core.hooksPath override" "$MSG_HOOKS" ;;
  esac
}

check_git_config() { # git config ... core.hooksPath <value>
  local a sets=0 reads=0
  for a in "$@"; do
    case $(lower "$a") in
      core.hookspath) sets=1 ;;
      --get | --get-all | --get-regexp | --list | -l | --unset | --unset-all | get | list | unset) reads=1 ;;
    esac
  done
  if [ "$sets" -eq 1 ] && [ "$reads" -eq 0 ]; then
    block "git config core.hooksPath" "$MSG_HOOKS"
  fi
}

check_commit() {
  local skip=0 flags ch
  while [ $# -gt 0 ]; do
    if [ "$skip" -eq 1 ]; then
      skip=0
      shift
      continue
    fi
    case $1 in
      --am*) block "git commit $1 (--amend)" "$MSG_AMEND" ;;
      --no-v*) if is_no_verify "$1"; then block "git commit $1 (--no-verify)" "$MSG_HOOKS"; fi ;;
      --) break ;;
      -m | -F | -C | -c | -t | --message | --file | --reuse-message | --reedit-message | \
        --template | --author | --date | --cleanup | --trailer | --fixup | --squash)
        skip=1
        ;;
      --*) ;;
      -?*)
        flags=${1#-}
        while [ -n "$flags" ]; do
          ch=${flags%"${flags#?}"}
          flags=${flags#?}
          case $ch in
            n) block "git commit -n (--no-verify)" "$MSG_HOOKS" ;;
            m | F | C | c | t)
              if [ -z "$flags" ]; then skip=1; fi
              flags=""
              ;;
            u | S) flags="" ;; # the rest of the cluster is this option's value
          esac
        done
        ;;
    esac
    shift
  done
}

check_push() { # $1: directory, then the push arguments
  local dir=$1 remote="" specs="" force="" all="" delete=0 skip=0 spec dst
  shift
  while [ $# -gt 0 ]; do
    if [ "$skip" -eq 1 ]; then
      skip=0
      shift
      continue
    fi
    case $1 in
      --force-with-lease | --force-with-lease=* | --force-if-includes) ;;
      --force | --force=*) force=$1 ;;
      --de*) delete=1 ;;
      --al* | --mi* | --branches) all=$1 ;;
      --no-v*) if is_no_verify "$1"; then block "git push $1 (--no-verify)" "$MSG_HOOKS"; fi ;;
      --repo | --push-option | --receive-pack | --exec) skip=1 ;;
      --*) ;;
      -?*)
        case $1 in *f*) force=$1 ;; esac
        case $1 in *d*) delete=1 ;; esac
        case $1 in *o) skip=1 ;; esac
        ;;
      *'>'* | *'<'*) ;; # redirection
      *)
        if [ -z "$remote" ]; then remote=$1; else specs="$specs $1"; fi
        ;;
    esac
    shift
  done
  SEEN="$SEEN git push $remote$specs;"

  if [ -n "$force" ]; then block "bare force push ($force)" "$MSG_FORCE"; fi
  if [ -n "$all" ]; then
    block "git push $all" "$all can update or delete main. $MSG_PROTECTED"
  fi

  for spec in $specs; do
    case $spec in
      +*) block "force push with a + refspec ($spec)" "$MSG_FORCE" ;;
    esac
    case $spec in
      *:*) dst=${spec##*:} ;;
      *) dst=$spec ;;
    esac
    if [ "$dst" = HEAD ] || [ "$dst" = @ ]; then dst=$(current_branch "$dir"); fi
    dst=${dst#refs/heads/}
    if [ "$dst" = main ]; then
      case $spec in
        :*) block "deleting main" "Deleting main is never allowed. $MSG_PROTECTED" ;;
      esac
      if [ "$delete" -eq 1 ]; then
        block "deleting main" "Deleting main is never allowed. $MSG_PROTECTED"
      fi
      block "git push to main" "$MSG_PROTECTED"
    fi
  done

  if [ -z "$specs" ] && [ "$delete" -eq 0 ]; then
    dst=$(current_branch "$dir")
    if [ "$dst" = main ]; then
      block "git push while main is checked out" "This push would update main. Switch to your branch (git switch feat/<run>) and push it by name. $MSG_PROTECTED"
    fi
  fi
}

check_git() { # $1: directory, then everything after "git"
  local dir=$1 sub a
  shift
  while [ $# -gt 0 ]; do
    case $1 in
      -C)
        shift
        if [ $# -gt 0 ]; then
          case $1 in
            /*) dir=$1 ;;
            *) dir="$dir/$1" ;;
          esac
          shift
        fi
        ;;
      -c)
        shift
        if [ $# -gt 0 ]; then
          check_config_value "$1"
          shift
        fi
        ;;
      -c?*)
        check_config_value "${1#-c}"
        shift
        ;;
      --git-dir | --work-tree | --namespace | --config-env)
        shift
        [ $# -eq 0 ] || shift
        ;;
      -*) shift ;;
      *) break ;;
    esac
  done
  [ $# -gt 0 ] || return 0
  sub=$1
  shift
  case $sub in
    push) check_push "$dir" "$@" ;;
    commit)
      SEEN="$SEEN git commit;"
      check_commit "$@"
      ;;
    reset)
      SEEN="$SEEN git reset;"
      for a in "$@"; do
        case $a in --ha*) block "git reset $a (--hard)" "$MSG_RESET" ;; esac
      done
      ;;
    config) check_git_config "$@" ;;
    merge | pull | rebase | am | cherry-pick | revert)
      SEEN="$SEEN git $sub;"
      for a in "$@"; do
        if is_no_verify "$a"; then block "git $sub $a (--no-verify)" "$MSG_HOOKS"; fi
      done
      ;;
  esac
  return 0
}

# gh api calls that change something: a method other than GET, or fields (-f, -F,
# --field, --raw-field, --input), which make gh send a POST. Only the writes a run needs
# are allowed: comments and replies on its pull request and issues, an issue's labels
# and sub-issues, and opening an issue.
check_gh_api() { # everything after "gh api"
  local a endpoint="" method="" fields=0 skip=""
  for a in "$@"; do
    if [ -n "$skip" ]; then
      [ "$skip" != method ] || method=$a
      skip=""
      continue
    fi
    case $a in
      -X | --method) skip=method ;;
      -X?*) method=${a#-X} ;;
      --method=*) method=${a#--method=} ;;
      -f | -F | --field | --raw-field | --input) fields=1 skip=value ;;
      -f?* | -F?* | --field=* | --raw-field=* | --input=*) fields=1 ;;
      -H | --header | -q | --jq | -t | --template | --hostname | -p | --preview | --cache) skip=value ;;
      -*) ;;
      *) [ -n "$endpoint" ] || endpoint=$a ;;
    esac
  done
  method=$(printf '%s' "$method" | tr '[:lower:]' '[:upper:]')
  if [ -z "$method" ]; then
    if [ "$fields" -eq 1 ]; then method=POST; else method=GET; fi
  fi
  endpoint=${endpoint#/}
  case $endpoint in
    */pulls/*/merge | */pulls/*/merge/ | */merges) block "merging through the API ($endpoint)" "$MSG_MERGE" ;;
    */rulesets* | */branches/*/protection* | */dispatches* | */secrets* | */variables* | \
      */actions/workflows/*/enable | */actions/workflows/*/disable)
      [ "$method" = GET ] || block "$method $endpoint" "$MSG_GH_SETTINGS"
      ;;
  esac
  [ "$method" != GET ] || return 0
  case $endpoint in
    graphql) return 0 ;; # mutations are checked on the raw text (check_text)
    repos/*/*/pulls/*/comments | repos/*/*/pulls/*/comments/*/replies | \
      repos/*/*/issues/*/comments | repos/*/*/issues | repos/*/*/issues/*/labels | \
      repos/*/*/issues/*/sub_issues | repos/*/*/issues/*/sub_issues/priority) return 0 ;;
    repos/* | /repos/*)
      block "gh api $method $endpoint" "A run changes the repository only by pushing its branch and through its pull request (gh pr create, gh pr edit, gh pr comment, review replies). $MSG_GH_SETTINGS"
      ;;
  esac
  return 0
}

check_gh() { # everything after "gh"
  local words="" a skip=0 first=""
  for a in "$@"; do
    if [ "$skip" -eq 1 ]; then
      skip=0
      continue
    fi
    case $a in
      -R | --repo) skip=1 ;;
      -*) ;;
      *)
        words="$words $a"
        [ -n "$first" ] || first=$a
        ;;
    esac
  done
  if [ "$first" = api ]; then
    while [ $# -gt 0 ] && [ "$1" != api ]; do shift; done
    shift
    check_gh_api "$@"
    return 0
  fi
  case "$words " in
    " pr merge "*) block "gh pr merge" "$MSG_MERGE" ;;
    " workflow run "* | " workflow enable "* | " workflow disable "* | " run rerun "*)
      block "gh${words}" "$MSG_GH_SETTINGS"
      ;;
    " variable set "* | " variable delete "* | " secret set "* | " secret delete "* | \
      " repo edit "* | " repo delete "* | " repo rename "* | " repo archive "* | " ruleset "*)
      block "changing the repository's settings, variables or secrets" "$MSG_GH_SETTINGS"
      ;;
  esac
  return 0
}

# Read-only AWS operations: the whole word, or the word then a hyphen (get, get-item).
# start-query and stop-query are whole words only: they are CloudWatch Logs Insights,
# and start-query-execution is Athena, which can write.
is_aws_read() { # $1: the operation
  case ${1:-} in
    start-query | stop-query) return 0 ;;
    describe | describe-* | get | get-* | list | list-* | lookup | lookup-* | search | search-* | \
      filter | filter-* | tail | tail-* | validate | validate-* | estimate | estimate-* | \
      wait | wait-* | help | ls | head | head-* | batch-get | batch-get-* | scan | scan-* | \
      query | query-* | select | select-* | simulate | simulate-*) return 0 ;;
  esac
  return 1
}

check_aws() { # everything after "aws"
  local service="" operation="" skip="" a profile=""
  for a in "$@"; do
    if [ -n "$skip" ]; then
      if [ "$skip" = profile ]; then profile=$a; fi
      skip=""
      continue
    fi
    case $a in
      --profile) skip=profile ;;
      --profile=*) profile=${a#--profile=} ;;
      --region | --output | --endpoint-url | --query | --cli-read-timeout | \
        --cli-connect-timeout | --color | --ca-bundle | --cli-binary-format)
        skip=value
        ;;
      -*) ;;
      *'>'* | *'<'*) ;; # redirection
      *)
        if [ -z "$service" ]; then
          service=$a
        elif [ -z "$operation" ]; then
          operation=$a
        fi
        ;;
    esac
  done
  SEEN="$SEEN aws $service $operation;"

  # aws --version and aws help reach no account.
  [ -n "$service" ] || return 0
  [ "$service" != help ] || return 0
  [ "$operation" != help ] || return 0

  [ -n "$profile" ] || profile=$SEG_PROFILE
  [ -n "$profile" ] || profile=$CMD_PROFILE
  if [ "$profile" != "$PROFILE_REQUIRED" ]; then
    block "aws $service $operation with profile '${profile:-default}'" "$MSG_PROFILE"
  fi

  case "$service $operation" in
    "secretsmanager get-secret-value" | "secretsmanager batch-get-secret-value")
      block "aws $service $operation" "$MSG_SECRET"
      ;;
    "ssm get-parameter" | "ssm get-parameters" | "ssm get-parameters-by-path" | "ssm get-parameter-history")
      case " $* " in
        *" --with-decryption"*) block "aws $service $operation --with-decryption" "$MSG_SECRET" ;;
      esac
      ;;
    # Reads CLAUDE.md forbids: a drop-off's details (the table's items), photos (objects
    # in the bucket), staff accounts, and the addresses SES holds.
    "dynamodb scan" | "dynamodb query" | "dynamodb get-item" | "dynamodb batch-get-item" | \
      "dynamodb execute-statement" | "dynamodb batch-execute-statement" | \
      "dynamodb execute-transaction" | "dynamodb transact-get-items" | \
      "s3 cp" | "s3 sync" | "s3 mv" | "s3 presign" | \
      "s3api get-object" | "s3api get-object-torrent" | "s3api select-object-content" | \
      "cognito-idp list-users" | "cognito-idp list-users-in-group" | "cognito-idp admin-get-user" | \
      "cognito-idp get-user" | "sesv2 list-suppressed-destinations" | "sesv2 get-suppressed-destination")
      block "aws $service $operation" "$MSG_AWS_READ"
      ;;
  esac
  if [ -z "$operation" ] || ! is_aws_read "$operation"; then
    block "aws $service $operation" "$MSG_AWS"
  fi
  return 0
}

check_sam() { # everything after "sam"
  local skip=0 a
  for a in "$@"; do
    if [ "$skip" -eq 1 ]; then
      skip=0
      continue
    fi
    case $a in
      --config-file | --config-env | --region | --profile) skip=1 ;;
      -*) ;;
      *)
        SEEN="$SEEN sam $a;"
        case $a in
          deploy | sync | delete | remote | publish | package | pipeline)
            block "sam $a" "$MSG_SAM"
            ;;
        esac
        return 0
        ;;
    esac
  done
  return 0
}

# Tools other than SAM that would deploy or destroy infrastructure.
check_deployer() { # $1: the tool, then its arguments
  local tool=$1 a
  shift
  for a in "$@"; do
    case $a in
      -*) ;;
      *)
        SEEN="$SEEN $tool $a;"
        case "$tool $a" in
          "cdk deploy" | "cdk destroy" | "cdk bootstrap" | "cdk import" | "cdk watch" | \
            "terraform apply" | "terraform destroy" | "terraform import" | "terraform taint" | \
            "tofu apply" | "tofu destroy" | "tofu import" | \
            "pulumi up" | "pulumi update" | "pulumi destroy" | "pulumi import" | "pulumi refresh")
            block "$tool $a" "$MSG_SAM"
            ;;
        esac
        return 0
        ;;
    esac
  done
  return 0
}

check_segment() { # one simple command
  local seg=$1 w wrap="" a
  SEG_PROFILE=""
  set -- $seg
  while [ $# -gt 0 ]; do
    # A backslash in a command word changes nothing for the shell (\aws runs aws).
    w=${1//\\/}
    shift
    set -- "$w" "$@"
    # Options of the wrapper before this word that take a value.
    if [ -n "$wrap" ] && [ "${1#-}" != "$1" ]; then
      case "$wrap $1" in
        "env -u" | "env --unset" | "env -C" | "env --chdir" | "env -S" | \
          "sudo -u" | "sudo -g" | "sudo -C" | "sudo -h" | "sudo -p" | "sudo -U" | "sudo -D" | \
          "nice -n" | "nice --adjustment" | "time -f" | "time -o" | \
          "xargs -I" | "xargs -L" | "xargs -n" | "xargs -P" | "xargs -s" | "xargs -E" | "xargs -d" | "xargs -a")
          shift 2 || set --
          continue
          ;;
      esac
    fi
    case $1 in
      AWS_PROFILE=* | AWS_DEFAULT_PROFILE=*)
        SEG_PROFILE=${1#*=}
        shift
        ;;
      [A-Za-z_]*=*) shift ;; # environment assignment
      sudo | env | command | builtin | exec | nohup | time | nice | xargs | if | then | else | elif | \
        do | while | until | '!' | '{')
        wrap=$1
        shift
        ;;
      timeout | gtimeout) # takes a duration before the command
        shift
        while [ $# -gt 0 ] && [ "${1#-}" != "$1" ]; do
          case $1 in
            -k | -s | --kill-after | --signal) shift 2 || set -- ;;
            *) shift ;;
          esac
        done
        [ $# -eq 0 ] || shift
        ;;
      uv) # uv run [options] <command>
        [ "${2:-}" = run ] || break
        shift 2
        while [ $# -gt 0 ] && [ "${1#-}" != "$1" ]; do
          case $1 in
            --with | --from | --python | -p | --directory | --project | --group | --extra | --env-file | --package)
              shift 2 || set --
              ;;
            *) shift ;;
          esac
        done
        ;;
      uvx | pipx | npx) # uvx [--from X] <command>, pipx run <command>, npx [-p X] <command>
        shift
        [ "${1:-}" != run ] || shift
        while [ $# -gt 0 ] && [ "${1#-}" != "$1" ]; do
          case $1 in
            --from | --with | --python | -p | --spec | --package) shift 2 || set -- ;;
            *) shift ;;
          esac
        done
        ;;
      -*) shift ;; # a wrapper's flag
      *) break ;;
    esac
  done
  # A segment that only sets the profile changes what later aws commands use.
  if [ $# -eq 0 ]; then
    [ -z "$SEG_PROFILE" ] || CMD_PROFILE=$SEG_PROFILE
    return 0
  fi
  case $1 in
    export)
      for a in "$@"; do
        case $a in AWS_PROFILE=* | AWS_DEFAULT_PROFILE=*) CMD_PROFILE=${a#*=} ;; esac
      done
      ;;
    unset)
      for a in "$@"; do
        case $a in AWS_PROFILE | AWS_DEFAULT_PROFILE) CMD_PROFILE="" ;; esac
      done
      ;;
    git | */git)
      shift
      check_git "$CWD" "$@"
      ;;
    gh | */gh)
      shift
      SEEN="$SEEN gh;"
      check_gh "$@"
      ;;
    aws | */aws)
      shift
      check_aws "$@"
      ;;
    sam | */sam)
      shift
      check_sam "$@"
      ;;
    cdk | */cdk | terraform | */terraform | tofu | */tofu | pulumi | */pulumi)
      check_deployer "${1##*/}" "${@:2}"
      ;;
    pytest | */pytest | python | python3 | */python | */python3)
      check_cov_flag "$*"
      ;;
  esac
  return 0
}

# Strings passed to bash -c, sh -c, zsh -c or eval are commands: check them too.
INNER_RE="(^|[[:space:];&|(])(bash|sh|zsh|eval)[[:space:]]+(-[a-zA-Z]*c[[:space:]]+)?(\"([^\"]*)\"|'([^']*)')"
check_inner() { # $1: command text, $2: depth
  local rest=$1 inner
  [ "$2" -lt 3 ] || return 0
  while [[ $rest =~ $INNER_RE ]]; do
    inner=${BASH_REMATCH[5]}
    [ -n "$inner" ] || inner=${BASH_REMATCH[6]}
    check_text "$inner" $(($2 + 1))
    rest=${rest#*"${BASH_REMATCH[0]}"}
  done
  return 0
}

check_text() { # $1: command text, $2: depth
  local cmd=$1 text seg nl
  nl='
'
  # A backslash at the end of a line continues the command on the next one.
  cmd=${cmd//\\$nl/ }

  # Writes checked on the text with its quotes (paths are often quoted).
  text=$(drop_heredocs "$cmd")
  if writes_to "$text" 'uv\.lock($|[^A-Za-z0-9._-])'; then
    block "writing uv.lock by hand" "$MSG_LOCK"
  fi
  # The guardrail itself: the hook, the settings that run it, the claims, the runs' state.
  if touches "$text" '\.claude/hooks(/|$|[[:space:]"'"'"';&|)])'; then
    block "changing .claude/hooks/ from the shell" "$MSG_SELF"
  fi
  if touches "$text" '\.claude/settings[^/[:space:]]*' ||
    touches "$text" '\.claude/?($|[[:space:]"'"'"';&|)])'; then
    block "changing .claude/settings from the shell" "$MSG_SELF"
  fi
  if touches "$text" 'offshore/sessions' || touches "$text" '\.git/offshore' ||
    touches "$text" '\.git/?($|[[:space:]"'"'"';&|)])' ||
    touches "$text" '\.offshore/?($|[[:space:]"'"'"';&|)])'; then
    block "changing the session claims or the runs' state from the shell" "$MSG_SELF"
  fi
  # GraphQL mutations that merge or write to a branch, before quotes hide them.
  case $cmd in
    *graphql*)
      if printf '%s\n' "$cmd" | grep -Eq 'mergePullRequest|enablePullRequestAutoMerge|mergeBranch|createCommitOnBranch|updateRef|createRef|deleteRef|updateRepository|createRepositoryRuleset|updateRepositoryRuleset|deleteRepositoryRuleset|updateBranchProtectionRule|deleteBranchProtectionRule'; then
        block "a GraphQL mutation that merges or changes the repository" "$MSG_MERGE"
      fi
      ;;
  esac
  # Heredoc bodies are what gets written, so these two look at the whole command.
  case $cmd in
    *fail_under*)
      if writes_to "$cmd" 'pyproject\.toml($|[^A-Za-z0-9._-])'; then
        block "changing fail_under in pyproject.toml from the shell" "Change pyproject.toml with the Edit tool, which checks the floor. $MSG_COVERAGE"
      fi
      ;;
  esac
  case $cmd in
    *pull_request_target*)
      if writes_to "$cmd" '\.github/'; then
        block "writing pull_request_target under .github/" "$MSG_PRT"
      fi
      ;;
  esac

  check_inner "$text" "$2"

  text=$(neutralize_quotes "$text")
  # Split into simple commands at ; & | ( ) ` and newlines.
  text=$(printf '%s\n' "$text" | tr ';&|()`' '\n\n\n\n\n\n')
  while IFS= read -r seg || [ -n "$seg" ]; do
    check_segment "$seg"
  done <<<"$text"
}

check_bash() {
  local cmd
  cmd=$(json_all command)
  [ -n "$cmd" ] || return 0
  check_text "$cmd" 0
}

# MCP tools reach AWS and GitHub around the CLI checks above.
check_mcp() {
  local name
  name=$(lower "$TOOL")
  case $name in
    *aws*)
      case $name in
        *documentation* | *retrieve_skill* | *list_regions* | *regional_availability* | *get_tasks*) ;;
        *) block "the AWS tool $TOOL" "$MSG_MCP_AWS" ;;
      esac
      ;;
    *github*)
      case $name in
        *merge* | *push* | *create_or_update_file* | *delete_file* | *upload* | *create_branch* | \
          *create_ref* | *update_ref* | *run_workflow* | *rerun* | *dispatch* | *cancel_workflow* | \
          *secret* | *variable* | *create_repository* | *update_repository* | *delete_repository* | \
          *fork_repository* | *ruleset* | *protection*)
          block "the GitHub tool $TOOL" "$MSG_MCP_GITHUB"
          ;;
      esac
      ;;
  esac
  return 0
}

case $TOOL in
  AskUserQuestion)
    block "AskUserQuestion" "$MSG_ASK"
    ;;
  *merge_pull_request* | *enable_pr_auto_merge* | *merge_pr*)
    block "merging a pull request ($TOOL)" "$MSG_MERGE"
    ;;
  Agent | Task)
    agent="$(json_first subagent_type) | $(json_first description | tr '\t\r' '  ')"
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$agent" >>"$AGENTS_LOG" 2>/dev/null || true
    log "ALLOW tool=$TOOL spawn: $agent"
    ;;
  Bash)
    check_bash
    log "ALLOW tool=Bash${SEEN}"
    ;;
  mcp__*)
    check_mcp
    log "ALLOW tool=$TOOL"
    ;;
  Edit | Write | MultiEdit | NotebookEdit)
    check_file_edit
    log "ALLOW tool=$TOOL"
    ;;
  '')
    log "WARN no tool_name in payload; call allowed"
    ;;
  *)
    log "ALLOW tool=$TOOL"
    ;;
esac
exit 0

---
name: rigor
description: The person is telling you to stop cutting corners and do the work properly. Use only when the person runs /rigor.
argument-hint: [what was wrong, optional]
disable-model-invocation: true
---

The person is telling you to stop cutting corners and do the work properly. This is a
correction, not a request for something new.

**Why they said it:** you were hasty. You assumed instead of checking, patched a symptom
instead of finding the cause, or answered confidently without reading the code, the
test or AWS's documentation.

**What to do now:**

1. **Stop.** Don't continue what you were doing, and don't defend it.
2. **Say what you got wrong.** Re-read the code, the test, the workflow, the template or
   the error output. State what you assumed and what is actually true. If you don't know
   yet, say so and find out before going on.
3. **Trace the whole path.** For a drop-off: from the form on a phone, through the
   server's checks, the use case, the domain's rules, the store, the photo upload and the
   email, to what the person sees. For the console: from the staff sign-in and the
   token check, through the use case and the domain, to the page. For a deploy: from the
   merge through the workflow, the deploy role and each resource it touches. Read every
   file on the way, and check the account with read-only commands. Don't skip a layer
   because you think you know what it does.
4. **Fix the cause, not the symptom.** If the cause is in the domain model and the
   symptom on a page, fix the domain. If that means changing the tests, the plan and the
   docs too, change all of them.
5. **Verify before you answer.** Not "I think" or "it should". Read the code, grep for the
   name, run the checks from `CLAUDE.md`. Then state facts.
6. **Go back to the task** with that rigor.

The person's additional context, if any:

$ARGUMENTS

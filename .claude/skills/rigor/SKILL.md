---
name: rigor
description: A correction from the person to stop cutting corners. Stop, name what was assumed instead of checked, trace the root cause through the whole path, and redo the current task properly. Use only when the person runs /rigor.
argument-hint: "[what went wrong, optional]"
disable-model-invocation: true
---

# Rigor

The person is telling you to stop cutting corners and do the work properly. This is a
correction, not a request for something new.

**Why they said it:** you were hasty. You assumed instead of checking, patched a symptom
instead of finding the cause, or answered confidently without reading the code, the
test, the plan or AWS's documentation.

**What to do now:**

1. **Stop.** Don't continue what you were doing, and don't defend your previous
   approach.
2. **Name what you got wrong.** Re-read the code, the test, the phase document, the
   workflow, the template or the error output. State what you assumed and what is
   actually true. If you don't know what you got wrong, say so and investigate before
   you go on.
3. **Trace the whole path.** Follow the data end to end, and read every file in the
   chain. Check each assumption against the code. Don't skip a layer because you think
   you know what it does.
   - **A drop-off:** from the form on a phone, through the server's checks of every
     field and photo, the use case, the domain's rules, the store, the photo upload and
     the email, to what the person sees and what is logged (`AC-12`, never their
     details).
   - **The console:** from the staff sign-in and the token and `ceramics` group check,
     through the use case and the domain, to the page and what it changes.
   - **A deploy:** from the merge, through the workflow, the deploy role and its tag
     conditions, to each resource it touches. Check the account with read-only commands
     (`AWS_PROFILE=asmbly`, us-east-2), never a drop-off's details or photos.
4. **Find the right fix, not the fast fix.** The right fix addresses the root cause; the
   fast fix papers over the symptom. If the cause is in the domain model and the symptom
   shows on a page, fix the domain. If that means changing the tests, the plan and the
   docs too, change all of them.
5. **Verify before you answer.** No "I believe", "I think" or "it should be". Read the
   code, grep for the name, check the template, run the checks from `CLAUDE.md`. Then
   state facts.
6. **Go back to the task.** Resume whatever you were working on, with this rigor. The
   person's added context, if any:

$ARGUMENTS

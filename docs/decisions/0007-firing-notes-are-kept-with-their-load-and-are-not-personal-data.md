# 0007: A firing note's text is kept with its load past the close, because a note is not personal data

Status: proposed. It adds to [0001](0001-the-ceramics-studio-has-its-own-repository.md)'s
rule that the close (#7) deletes personal details once a drop-off closes.

On 16 November 2026 ceramics staff asked (#17) to keep notes on firings, such as whether
a glaze or clay may be tested and why, and to find them again years later. The close
deletes a drop-off's name, email, phone, rejection message and photos. A note is text
that staff type on a load, so a decision was needed on whether the close touches it.

## A note is kept with its load, and the server keeps personal details out of it

**Chosen:** a firing note (`domain/notes.py`, `FiringNote`) is not personal data. The
close never reads or deletes it. A note is kept as long as its load, as a firing record
and a load's history are. Because the close won't remove it, the server refuses text of
1 to 2,000 characters that holds something shaped like an email address or a phone
number, and the note form tells staff that notes hold no personal details. A note's text
is never logged (logs carry the note ID, such as `N-12`), never shown on the public
form and never put in an email. A removed note is kept, listed nowhere, and its
text stays in the table.

**Why:** the notes are only useful if they outlast the drop-offs they came from; a note
deleted at the close would defeat the search. Notes are about glazes, clays and
firings, not people, and staff write them under a username. The alternative was to run
the close over notes as well, which loses what staff asked to keep.

**Consequence, accepted:** the check is by shape, so it can't catch a name typed into
a note, and a ramp written as three numbers of 3, 3 and 4 digits looks like a phone
number and is refused (the form says to write it with units or commas). A person who
types a name into a note has put a personal detail where the close doesn't reach.

**Revisit if:** notes start holding personal details in practice, or a rule about
how long a firing's records may be kept is set.

## What has and has not been seen to work

Checked on 17 November 2026: the shape check, the length limit and the removal are tested
without AWS (`tests/domain/`, `tests/use_cases/test_notes.py`), and the console's notes
pages in `tests/web/console/`. Only the stage check in the plan's Rollout shows the
pages against the real table.

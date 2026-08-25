---
description: Start or continue the current roadmap milestone
---

Read `docs/ROADMAP.md` and find the first milestone that is not `[x]`.

Then:
1. State which milestone you are working on and its exit criteria.
2. Read the relevant sections of `docs/SPEC.md`. Do not invent design that the
   spec already decides.
3. Propose a short plan as a numbered list of commits. Wait for me to approve
   before writing code.
4. After approval, work commit by commit. Run `make test` and `make lint`
   before each commit.
5. When the exit criteria pass, update the marker in `docs/ROADMAP.md` and stop.
   Do not roll into the next milestone.

If the exit criteria cannot be met as written, say so and tell me what you would
change about the spec rather than quietly building something else.

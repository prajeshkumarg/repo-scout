---
paths: ["web/**"]
---

# Frontend rules

- Server components by default. `"use client"` only where there is real
  interactivity.
- The SSE event types are mirrored in `web/lib/events.ts` and must stay in sync
  with the backend contract. Change both or neither.
- The step trace is the centrepiece. Each step renders as soon as its event
  arrives, is collapsible, and shows the tool name plus the one-line summary.
  Never buffer the trace until the run finishes.
- Citations are clickable and drive the code viewer. A citation that does not
  scroll and highlight is broken.
- Loading states are real. Indexing shows live per-stage progress, not a
  generic spinner.
- No component library beyond Puppertino and Tailwind, plus a headless
  primitive where needed. Controls (buttons, inputs, modals, segmented
  controls) use Puppertino classes. Layout uses Tailwind. Do not hand-roll a
  control Puppertino already ships, and do not restyle a Puppertino control
  with a pile of Tailwind overrides -- if it needs that, it is custom layout,
  not a control.

---
paths: ["backend/**", "evals/**"]
---

# Testing rules

- Unit test the chunker against small fixture files checked into
  `tests/fixtures/`. Assert exact line ranges. This is the highest value test
  in the codebase.
- Tool implementations get tests with a fixture repo, no network.
- Agent loop tests use a scripted fake model that returns a fixed tool sequence.
  Do not call a real model in unit tests.
- The eval suite is not a test. It is slow, it costs money, and it runs via
  `make eval`, not `make test`.

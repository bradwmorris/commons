# Working on Commons

This repository owns the reusable Commons application: Rust API, React UI,
PostgreSQL storage and local semantic retrieval. External agents provide reasoning
and execution. Personal/business workflows and installation-specific data belong
outside this repository.

## Find the relevant guidance

- [README](README.md): product overview and repository documentation.
- [Requirements](docs/requirements.md) and [architecture](docs/architecture.md):
  product behavior and design; read the sections relevant to the change.
- [Development](docs/development-guidelines.md): implementation and delivery.
- [Getting started](docs/getting-started.md) and [testing](docs/testing.md): setup,
  prerequisites and executable checks.
- [API](docs/foundation-api.md), [schema](docs/schema.md) and feature-specific
  documents: contracts for the area being changed.

Inspect the owning code and current Issue before changing behavior. Ask when scope
or a consequential product decision is unclear. No private overlay, Task database,
specific agent or historical assignment is required to contribute.

## Implement, verify and deliver

Make focused changes, preserve unrelated work, and follow existing module patterns.
Use synthetic data in isolated test installations. Keep credentials, private records,
transcripts, local source archives and personal configuration out of the repository.
Preserve the licence and [third-party notices](THIRD_PARTY_NOTICES.md).

Run checks appropriate to the change through `scripts/testing/run`; application
checks are `check` and `verify`. Required database/browser checks must not silently
skip. Inspect affected rendered UI states and exercise changed interactions.
For documentation-only changes, check links and consistency with code/contracts.

Use the maintainer-authorized delivery procedure; never force-push shared history.
Report verification and whether changes are committed, pushed, merged or deployed.
Deployment, live migrations and access changes require authorization for those actions.

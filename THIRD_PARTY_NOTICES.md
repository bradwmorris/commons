# Third-party notices

Commons is Apache-2.0. It selectively adapts Centaur Context's Object/Task field names,
operation conventions, explained relationship kinds, RFC3339 and GitHub Issue validation,
and React Context shell, rows, details, forms, inline editing and graph presentation
under MIT. [Frontend reuse inventory](web/REUSE.md) lists the retained components and
necessary Commons adaptations; the complete notice is also in `web/CONTEXT-LICENSE`.

Inspected source: `bradwmorris/centaur-context` at
`91b31f49327f3723b863049d4e5061c072633104`: `src/db/models.rs`,
`src/domain.rs`, `src/universal.rs`, `migrations/0027_actionable_tasks.sql`,
`contract/context-contract.json`, `web/src/App.tsx`, `web/src/types.ts`.
Affected Commons files: `src/main.rs`, `migrations/0001_foundation.sql`,
and the frontend components/styles listed in `web/REUSE.md`. Modified: independent
authenticated identity/policy, required due dates and optional canonical Issue links for new Tasks, partial foundation
operations, JSON subtype storage and canonical Context UI adapted to real Commons APIs.
This is not the complete upstream contract or its runtime implementation.

The README documentation structure and `docs/schema.md`, `docs/context-contract.md`,
`docs/agent-integration.md`, `docs/ui-modules.md` and `docs/foundation-api.md` also
adapt concepts and guidance from that revision's `README.md`, `docs/schema.md`,
`docs/context-contract.md`, `docs/centaur-integration.md`, `docs/ui-modules.md`,
`docs/setup.md` and `docs/api.md`. They describe Commons' standalone installation,
external-agent boundary and HTTP/schema/UI support, not upstream runtime,
capture, curation, tool or external-module compatibility. This notice preserves
source attribution; Centaur is not an installation dependency.

## Centaur Context — MIT License

Copyright (c) 2026 Centaur Context contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Dependency boundary

Cargo.lock and web/package-lock.json pin dependencies; their upstream licences
continue to apply. React/React DOM/Vite/react-markdown use MIT; TypeScript uses Apache-2.0. Rust direct dependencies
declare MIT or MIT/Apache-2.0 compatible alternatives (Axum, Tokio, SQLx, Serde,
serde_json, UUID, Chrono, chrono-tz, Argon2, SHA2, regex, url, tower-http, image, base64). Locked Cargo metadata
was inspected: permissive alternatives are available; Unicode-3.0 and BSD notices also
apply. Frontend transitive metadata includes MIT, ISC and BSD-3-Clause. Preserve packaged
dependency notices when distributing; no completed release/distribution audit is claimed.
No source, prompts, configuration or data from unlicensed private overlays is copied.

## Local retrieval packages (Issue #8)

EmbeddingGemma 2 is by Google DeepMind, distributed under Apache-2.0 according to
its [model card](https://huggingface.co/google/embeddinggemma-2) and
[licence](https://ai.google.dev/gemma/docs/gemma_4_license). Commons downloads the
unmodified Ollama text-only 270M Q8_0 conversion, not the original 300M EmbeddingGemma
or multimodal encoders. The immutable manifest/model hashes are in
`scripts/provision-model`; Apache-2.0 text is retained in `LICENSE` and copied with
this notice into the Ollama image. The model card also describes intended use,
limitations and the Gemma prohibited-use policy. Selection is not a public-release
or completed redistribution-audit claim.

Ollama 0.40.5 uses MIT (Copyright (c) Ollama); its complete licence is retained in
`docker/OLLAMA-LICENSE` and the packaged image. Its bundled native libraries retain
their upstream notices. pgvector 0.8.1 uses the PostgreSQL licence; its complete
upstream `LICENSE` is copied into `/usr/share/doc/pgvector/LICENSE` in the database
image. No pgvector/Ollama source is modified. Reqwest uses MIT or Apache-2.0.

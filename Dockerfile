# Locked build inputs; refresh intentionally and reverify both installation lanes.
FROM node:26.10.0-bookworm-slim@sha256:3ffc19ea878019d9e9ae8971732ad4a03cda44f167107173174b60ed7c65bed3 AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ARG VITE_PUBLISHING_CALENDAR_URL=
RUN npm run build

FROM rust:1.90.0-bookworm@sha256:3914072ca0c3b8aad871db9169a651ccfce30cf58303e5d6f2db16d1d8a7e58f AS rust
WORKDIR /build
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY src/ src/
COPY assets/ assets/
COPY migrations/ migrations/
COPY skills/commons-evals/SKILL.md skills/commons-evals/SKILL.md
COPY docs/evals.md docs/evals.md
RUN cargo build --release --locked

FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 commons && useradd --uid 10001 --gid commons --no-create-home commons
WORKDIR /app
COPY --from=rust /build/target/release/commons /usr/local/bin/commons
COPY --from=web /build/web/dist/ web/dist/
COPY LICENSE THIRD_PARTY_NOTICES.md ./
USER 10001:10001
EXPOSE 3000
ENTRYPOINT ["commons"]
CMD ["serve"]

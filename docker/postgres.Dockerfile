FROM postgres:16.15-bookworm@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4 AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential postgresql-server-dev-16 curl ca-certificates
RUN curl -fsSL https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.1.tar.gz -o /tmp/vector.tar.gz \
    && echo 'a9094dfb85ccdde3cbb295f1086d4c71a20db1d26bf1d6c39f07a7d164033eb4  /tmp/vector.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/vector.tar.gz -C /tmp \
    && make -C /tmp/pgvector-0.8.1 OPTFLAGS='' \
    && make -C /tmp/pgvector-0.8.1 install
FROM postgres:16.15-bookworm@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4
COPY --from=build /usr/lib/postgresql/16/lib/vector.so /usr/lib/postgresql/16/lib/
COPY --from=build /usr/share/postgresql/16/extension/vector* /usr/share/postgresql/16/extension/
COPY --from=build /tmp/pgvector-0.8.1/LICENSE /usr/share/doc/pgvector/LICENSE

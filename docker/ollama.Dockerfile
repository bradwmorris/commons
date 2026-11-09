FROM ollama/ollama:0.40.5@sha256:5d3a2f25f9825628daba94dc0b1d421c7d57d6c03ae5faa9ba050e058bab8241
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/provision-model /usr/local/bin/provision-model
COPY LICENSE THIRD_PARTY_NOTICES.md docker/OLLAMA-LICENSE /usr/share/doc/commons-retrieval/

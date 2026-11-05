# Official Elasticsearch patch release; preserve upstream Java, modules and entrypoint.
FROM docker.elastic.co/elasticsearch/elasticsearch-wolfi:9.4.9@sha256:12eb0ef6a23181c096061b766c0806fbcc3c48ac413b293ef82d8442769a68b6

ARG RELEASE_VERSION=2.2.3-rc1
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="Elasticrune" \
      org.opencontainers.image.version="${RELEASE_VERSION}" \
      org.opencontainers.image.description="Elasticsearch packaging with upstream security updates" \
      org.opencontainers.image.source="https://github.com/Jahrkor/elasticrune" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.licenses="Elastic-License-2.0" \
      org.opencontainers.image.base.name="docker.elastic.co/elasticsearch/elasticsearch-wolfi:9.4.9" \
      org.opencontainers.image.base.digest="sha256:12eb0ef6a23181c096061b766c0806fbcc3c48ac413b293ef82d8442769a68b6"

# This upstream digest already contains no setuid/setgid files. The build and
# validation scripts assert this as root; no mutable package or JAR edits occur.
USER 1000:0

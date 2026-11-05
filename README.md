# Elasticrune

Standalone packaging for the official Elasticsearch container. Docker Hub image:
`hrafnox/elasticrune`. Elasticsearch remains the engine.

The proposed `2.2.3-rc1` uses Elasticsearch **9.4.9**, its bundled OpenJDK
**27.0.1.0.3**, and the official Chainguard/Wolfi image pinned to the amd64
manifest digest in `Dockerfile`. A candidate tag is not a security approval.

## Upstream and licensing

The maintained upstream is [elastic/elasticsearch](https://github.com/elastic/elasticsearch),
particularly [distribution/docker](https://github.com/elastic/elasticsearch/tree/main/distribution/docker).
The historical `elastic/elasticsearch-docker` repository is archived.
This is a small standalone repository, not a fork of the Elasticsearch monorepo.
See `NOTICE` and `LICENSE` for packaging attribution. Elasticsearch binaries are
distributed under Elastic License 2.0; the image retains upstream `LICENSE.txt`,
`NOTICE.txt`, and third-party notices. The packaging license does not relicense
the bundled software.

## Build locally

Requirements: Docker with BuildKit, Git, Python 3.11+; Trivy for scanning.

```sh
python scripts/build.py --evidence-dir /absolute/path/outside/repository
python scripts/validate.py --evidence-dir /absolute/path/outside/repository
python scripts/scan.py --evidence-dir /absolute/path/outside/repository --cache-dir /absolute/path/to/trivy-cache
```

The build refuses to overwrite a local tag, records the source revision, uses
the commit timestamp for reproducibility, and never pushes. For a repeat build,
pass a new `--tag`. The Docker context allows only `Dockerfile`; no credentials,
reports or runtime configuration are copied into the image. OS and Java changes
come from the digest-pinned upstream release. No dependency overrides or JAR
repacking are performed.

## Runtime compatibility

The upstream `/sbin/tini -- /usr/local/bin/docker-entrypoint.sh` entrypoint,
`eswrapper` command, ports 9200/9300, and UID:GID **1000:0** are preserved.
Data lives at `/usr/share/elasticsearch/data`. The image does not declare an
automatic Docker volume: supply a dedicated named volume or a prepared bind mount.
Config, data and logs must be writable by UID 1000 or group 0; never use world-writable
permissions. The bundled `repository-azure` module requires no separate plugin
installation. External plugins must match Elasticsearch 9.4.9.

Use unique node names, a common cluster name, reachable transport addresses and
`discovery.seed_hosts` for multiple nodes. Set `cluster.initial_master_nodes`
only when bootstrapping a new cluster; remove it afterward. Configure transport
TLS and authentication for production. Set file descriptor limits and host
`vm.max_map_count` according to the [upstream production guide](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-prod).

The validation harness creates only isolated synthetic test data on a Docker
`--internal` network, publishes no ports, and removes only resources it created.
It tests authentication and transport TLS with freshly generated test certificates.
HTTP requests run through `docker exec` to each node's loopback interface; external
HTTPS termination is not covered. The certificates and volumes are removed afterward.
This test fixture is not a production deployment example.

Upgrading 9.4.8 to 9.4.9 is a patch-level engine upgrade. Follow the
[rolling upgrade procedure](https://www.elastic.co/docs/deploy-manage/upgrade/deployment-or-cluster/elasticsearch),
take snapshots first, upgrade master-eligible nodes last, and complete the
upgrade across all nodes. Elasticsearch does not support an in-place downgrade.
Application/client behavior and external snapshot backends need separate acceptance
testing; this repository does not connect to production systems.

## Release gate

All severities and unfixed vulnerabilities are retained in scan output. No ignore
file or vulnerability suppression is permitted. Critical/High findings block
release. Exact reconciliation with an external scan requires its CVE IDs,
package paths and image digest. Store raw scans and operational evidence outside
this public repository. Docker Hub publishing requires explicit approval.

The initial 9.4.9 assessment still detects High-severity Guava and shaded Jackson
findings, plus Medium-severity dependencies. This candidate is **not approved for
release**. Use the final local scan and readiness report to assess its exact state.

"""Isolated authenticated smoke test and three-node synthetic rolling upgrade."""
import argparse
import base64
import json
import secrets
import time
import uuid
from common import BASELINE, DEFAULT_TAG, evidence_dir, run, save

p = argparse.ArgumentParser()
p.add_argument("--evidence-dir", required=True)
p.add_argument("--tag", default=DEFAULT_TAG)
p.add_argument("--baseline", default=BASELINE)
a = p.parse_args()
out = evidence_dir(a.evidence_dir)
prefix = "elasticrune-test-" + uuid.uuid4().hex[:10]
network = prefix + "-net"
containers = set()
volumes = set()
network_created = False
checks = []
password = secrets.token_urlsafe(32)


def record(name, detail):
    checks.append({"name": name, "result": "PASS", "detail": detail})
    save(out / "functional-tests.json", checks)
    print(f"PASS: {name}", flush=True)


def start(node, image, single=False, bootstrap=False):
    name = prefix + "-" + node
    volume = prefix + "-" + node + "-data"
    if volume not in volumes:
        run("docker", "volume", "create", "--label", f"elasticrune.test={prefix}", volume)
        volumes.add(volume)
    args = ["docker", "run", "-d", "--name", name, "--hostname", node,
            "--label", f"elasticrune.test={prefix}", "--network", network,
            "--network-alias", node, "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true", "--memory=3g", "--cpus=2",
            "--ulimit", "nofile=65535:65535", "--mount",
            f"type=volume,source={volume},target=/usr/share/elasticsearch/data",
            "-e", "ES_JAVA_OPTS=-Xms1g -Xmx1g", "-e", f"node.name={node}",
            "-e", f"cluster.name={prefix}", "-e", "xpack.ml.enabled=false"]
    if single:
        args += ["-e", "discovery.type=single-node", "-e", "xpack.security.enabled=true",
                 "-e", "xpack.security.http.ssl.enabled=false", "-e", "ELASTIC_PASSWORD=" + password]
    else:
        # Test-only: internal network, no published ports, synthetic data only.
        args += ["-e", "xpack.security.enabled=false", "-e", "discovery.seed_hosts=master",
                 "-e", "node.roles=" + ("master" if node == "master" else "data,ingest,remote_cluster_client")]
        if bootstrap:
            args += ["-e", "cluster.initial_master_nodes=master"]
    run(*args, image)
    containers.add(name)
    return name


def api(container, path, method="GET", data=None, auth=False):
    cmd = ["docker", "exec", "-i", container, "curl", "--silent", "--show-error",
           "--fail-with-body", "--max-time", "35", "-X", method]
    if auth:
        cmd += ["-u", "elastic:" + password]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
    result = run(*cmd, "http://127.0.0.1:9200" + path,
                 input=json.dumps(data) if data is not None else None, timeout=45)
    return json.loads(result.stdout)


def ready(container, nodes=1, auth=False):
    deadline = time.monotonic() + 240
    last_error = ""
    while time.monotonic() < deadline:
        try:
            health = api(container, f"/_cluster/health?wait_for_nodes={nodes}&wait_for_status=yellow&timeout=5s", auth=auth)
            if not health.get("timed_out") and health["number_of_nodes"] == nodes:
                return health
        except (RuntimeError, json.JSONDecodeError) as error:
            last_error = str(error)[-1000:]
        time.sleep(2)
    raise RuntimeError(f"Cluster readiness timeout: {last_error}")


def green(container):
    health = api(container, "/_cluster/health?wait_for_status=green&wait_for_no_relocating_shards=true&timeout=30s")
    assert health["status"] == "green" and not health["timed_out"], health
    return health


def stop(container, phase):
    run("docker", "stop", "--time", "60", container, timeout=75)
    state = json.loads(run("docker", "inspect", container).stdout)[0]["State"]
    logs = run("docker", "logs", container, check=False)
    (out / f"{container}-{phase}.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
    assert state["ExitCode"] == 0 and not state["OOMKilled"], state
    assert 'closed' in logs.stdout + logs.stderr, "Missing graceful node closure"
    run("docker", "rm", container)
    containers.remove(container)
    record("graceful-shutdown-" + phase, {"exit_code": state["ExitCode"], "oom": state["OOMKilled"]})


try:
    run("docker", "network", "create", "--internal", "--label", f"elasticrune.test={prefix}", network)
    network_created = True
    image = json.loads(run("docker", "image", "inspect", a.tag).stdout)[0]
    assert image["Config"]["User"] == "1000:0"
    assert image["Config"]["Entrypoint"] == ["/sbin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
    single = start("single", a.tag, single=True)
    ready(single, auth=True)
    root = api(single, "/", auth=True)
    assert root["version"]["number"] == "9.4.9"
    record("authenticated-startup", {"version": root["version"]["number"]})
    status = run("docker", "exec", single, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9200/").stdout
    assert status == "401", status
    record("anonymous-access-rejected", status)
    permissions = run("docker", "exec", single, "sh", "-c",
        'set -eu; test "$(id -u)" = 1000; test -w data; test -w config; test -w logs; '
        'test -z "$(find / -xdev -type f \\( -perm -4000 -o -perm -2000 \\) -print -quit 2>/dev/null)"; '
        'stat -c "%u:%g %a %n" data config logs; cat /proc/sys/vm/max_map_count').stdout
    record("non-root-volume-and-setid", permissions)
    info = api(single, "/_nodes/jvm,plugins", auth=True)
    for node in info["nodes"].values():
        assert node["jvm"]["version"] == "27.0.1.0.3"
        assert not node["plugins"], node["plugins"]
        assert any(m["name"] == "repository-azure" for m in node["modules"])
    save(out / "candidate-nodes.json", info)
    record("bundled-java-and-modules", "Java 27.0.1.0.3; repository-azure loaded; no external plugins")
    api(single, "/synthetic", "PUT", {"settings": {"number_of_shards": 1, "number_of_replicas": 0}}, auth=True)
    api(single, "/synthetic/_doc/1?refresh=true", "PUT", {"message": "synthetic validation", "value": 42}, auth=True)
    assert api(single, "/synthetic/_search", "POST", {"query": {"match": {"message": "validation"}}}, auth=True)["hits"]["total"]["value"] == 1
    api(single, "/_ingest/pipeline/attachment-test", "PUT", {"processors": [{"attachment": {"field": "data", "remove_binary": True}}]}, auth=True)
    attached = api(single, "/_ingest/pipeline/attachment-test/_simulate", "POST",
                   {"docs": [{"_source": {"data": base64.b64encode(b"Synthetic attachment compatibility").decode()}}]}, auth=True)
    assert "Synthetic attachment compatibility" in attached["docs"][0]["doc"]["_source"]["attachment"]["content"]
    record("crud-search-attachment", "Index/write/search and Tika attachment pipeline passed")
    stop(single, "single")
    single = start("single", a.tag, single=True)
    ready(single, auth=True)
    assert api(single, "/synthetic/_doc/1", auth=True)["_source"]["value"] == 42
    record("data-volume-restart", "Synthetic document persisted")
    stop(single, "single-restart")

    master = start("master", a.baseline, bootstrap=True)
    data1 = start("data1", a.baseline)
    data2 = start("data2", a.baseline)
    ready(data1, nodes=3)
    api(data1, "/rolling", "PUT", {"settings": {"number_of_shards": 2, "number_of_replicas": 1}})
    for i in range(20):
        api(data1, f"/rolling/_doc/{i}", "PUT", {"value": i, "message": "synthetic rolling upgrade"})
    api(data1, "/rolling/_refresh", "POST")
    green(data1)
    record("baseline-three-node-cluster", "9.4.8: 20 documents, 2 shards, 1 replica, green")
    cluster_uuid = api(data1, "/")["cluster_uuid"]
    for node in ("data1", "data2", "master"):
        current = prefix + "-" + node
        stop(current, "before-upgrade-" + node)
        start(node, a.tag)
        ready(data1, nodes=3)
        health = green(data1)
        assert api(data1, "/rolling/_count")["count"] == 20
        assert api(data1, "/")["cluster_uuid"] == cluster_uuid
        versions = [n["version"] for n in api(data1, "/_nodes")["nodes"].values()]
        record("rolling-upgrade-" + node, {"versions": versions, "health": health["status"], "documents": 20})
    assert set(versions) == {"9.4.9"}
    for node in (data1, data2):
        assert api(node, "/rolling/_search", "POST", {"query": {"match_all": {}}})["hits"]["total"]["value"] == 20
    result = api(data1, "/_query", "POST", {"query": "FROM rolling | STATS total = COUNT(*)"})
    assert result["values"][0][0] == 20
    record("candidate-multinode-replication-and-esql", "All nodes 9.4.9; both data nodes return 20 documents; ES|QL passed")
    for node in (data1, data2, master):
        stop(node, "final-" + node.rsplit("-", 1)[-1])
except Exception as error:
    checks.append({"name": "validation", "result": "FAIL", "detail": str(error)})
    save(out / "functional-tests.json", checks)
    raise
finally:
    cleanup_errors = []
    for container in list(containers):
        logs = run("docker", "logs", container, check=False)
        (out / f"{container}-failure.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        result = run("docker", "rm", "-f", container, check=False)
        if result.returncode:
            cleanup_errors.append(container)
    for volume in volumes:
        if run("docker", "volume", "rm", volume, check=False).returncode:
            cleanup_errors.append(volume)
    if network_created and run("docker", "network", "rm", network, check=False).returncode:
        cleanup_errors.append(network)
    save(out / "validation-cleanup.json", {"prefix": prefix, "remaining": cleanup_errors})
    if cleanup_errors:
        raise RuntimeError("Test resource cleanup incomplete; see validation-cleanup.json")

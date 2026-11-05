"""Build a new local tag without overwriting any existing release."""
import argparse
import json
import subprocess
from common import DEFAULT_TAG, ROOT, evidence_dir, run, save

p = argparse.ArgumentParser()
p.add_argument("--evidence-dir", required=True)
p.add_argument("--tag", default=DEFAULT_TAG)
a = p.parse_args()
out = evidence_dir(a.evidence_dir)
if run("docker", "image", "inspect", a.tag, check=False).returncode == 0:
    raise SystemExit(f"Refusing to overwrite existing local tag: {a.tag}")
revision = run("git", "-C", str(ROOT), "rev-parse", "HEAD").stdout.strip()
if run("git", "-C", str(ROOT), "status", "--porcelain").stdout.strip():
    raise SystemExit("Commit the reviewed source before building")
epoch = run("git", "-C", str(ROOT), "show", "-s", "--format=%ct", "HEAD").stdout.strip()
version = json.loads((ROOT / "version.json").read_text())["version"]
name = a.tag.replace("/", "_").replace(":", "_")
metadata = out / f"{name}-build-metadata.json"
cmd = ["docker", "buildx", "build", "--load", "--pull", "--no-cache",
       "--network=none", "--platform=linux/amd64", "--provenance=false",
       "--build-arg", f"SOURCE_DATE_EPOCH={epoch}",
       "--build-arg", f"SOURCE_REVISION={revision}",
       "--build-arg", f"RELEASE_VERSION={version}",
       "--metadata-file", str(metadata), "-t", a.tag, str(ROOT)]
with (out / f"{name}-build.log").open("w", encoding="utf-8") as log:
    result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
if result.returncode:
    raise SystemExit(f"Build failed; see {log.name}")
inspection = json.loads(run("docker", "image", "inspect", a.tag).stdout)[0]
save(out / f"{name}-image.json", inspection)
setid = run("docker", "run", "--rm", "--network", "none", "--user", "0",
            "--entrypoint", "sh", inspection["Id"], "-c",
            "find / -xdev -type f \\( -perm -4000 -o -perm -2000 \\) -print").stdout.strip()
save(out / f"{name}-setid.json", {"image_id": inspection["Id"], "setid_paths": setid.splitlines()})
if setid:
    raise SystemExit("Build gate failed: setuid/setgid files remain; see evidence")
print(json.dumps({"tag": a.tag, "source_commit": revision,
                  "image_id": inspection["Id"], "metadata": str(metadata)}))

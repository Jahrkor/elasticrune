"""All-severity scan and final CycloneDX SBOM, with an unsuppressed release gate."""
import argparse
import collections
import json
import os
import pathlib
from common import BASELINE, DEFAULT_TAG, evidence_dir, run, save

p = argparse.ArgumentParser()
p.add_argument("--evidence-dir", required=True)
p.add_argument("--tag", default=DEFAULT_TAG)
p.add_argument("--baseline", default=BASELINE)
p.add_argument("--trivy", default="trivy")
p.add_argument("--cache-dir", required=True)
a = p.parse_args()
# Ambient TRIVY_* settings must not silently change the release policy.
for key in list(os.environ):
    if key.startswith("TRIVY_"):
        del os.environ[key]
out = evidence_dir(a.evidence_dir)
cache = evidence_dir(a.cache_dir)
# Explicitly empty config/ignore files outside the repository prevent ambient
# Trivy configuration from silently suppressing findings.
empty_config = out / "scan-config.yaml"
empty_config.write_text("{}\n", encoding="utf-8")
empty_ignore = out / "scan-ignore.txt"
empty_ignore.write_text("", encoding="utf-8")
base_args = [a.trivy, "--config", str(empty_config), "image", "--image-src", "docker",
             "--cache-dir", str(cache), "--timeout", "20m", "--no-progress",
             "--ignorefile", str(empty_ignore), "--ignore-unfixed=false",
             "--severity", "UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL", "--list-all-pkgs"]
save(out / "scanner-version.json", {"trivy": run(a.trivy, "--version").stdout})
for label, tag in (("baseline", a.baseline), ("candidate", a.tag)):
    scan = run(*base_args, "--scanners", "vuln,secret", "--format", "json",
               "--output", str(out / f"{label}-trivy.json"), tag, timeout=1500)
    (out / f"{label}-scan.log").write_text(scan.stderr, encoding="utf-8")
    print(f"Scanned {label}", flush=True)
run(*base_args, "--scanners", "vuln", "--format", "cyclonedx",
    "--output", str(out / "candidate.cdx.json"), a.tag, timeout=1500)


def findings(path):
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    result = {}
    secrets = []
    for target in report.get("Results", []):
        secrets.extend(target.get("Secrets", []))
        for v in target.get("Vulnerabilities", []):
            # Target JAR filenames change across versions; use the containing
            # module plus exact package identity/CVE, retaining every occurrence.
            location = v.get("PkgPath") or target["Target"]
            if location.endswith(".jar"):
                location = str(pathlib.PurePosixPath(location).parent)
            if target.get("Class") == "os-pkgs":
                location = "os-packages"
            key = (location, v["PkgName"], v["VulnerabilityID"])
            result[key] = {"target": v.get("PkgPath") or target["Target"], "package": v["PkgName"],
                           "id": v["VulnerabilityID"], "severity": v["Severity"],
                           "installed": v["InstalledVersion"],
                           "fixed_version": v.get("FixedVersion", ""),
                           "url": v.get("PrimaryURL", "")}
    return result, secrets


before, baseline_secrets = findings(out / "baseline-trivy.json")
after, candidate_secrets = findings(out / "candidate-trivy.json")
summary = {"comparison_unit": "CVE + exact package name + module directory (OS normalized)",
           "before": dict(collections.Counter(v["severity"] for v in before.values())),
           "candidate": dict(collections.Counter(v["severity"] for v in after.values())),
           "fixed": [before[k] for k in sorted(before.keys() - after.keys())],
           "remaining": [after[k] for k in sorted(before.keys() & after.keys())],
           "new": [after[k] for k in sorted(after.keys() - before.keys())],
           "baseline_secret_findings": len(baseline_secrets),
           "candidate_secret_findings": len(candidate_secrets),
           "original_external_findings": "Unverified without original CVE/path/digest evidence"}
save(out / "scan-comparison.json", summary)
print(json.dumps({k: v for k, v in summary.items() if k not in ("fixed", "remaining", "new")}))
if candidate_secrets or any(v["severity"] in ("CRITICAL", "HIGH") for v in after.values()):
    raise SystemExit("NO_GO: Critical/High vulnerabilities or secret findings remain")

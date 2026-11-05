"""Shared local-only tooling. Evidence must never be written into this repository."""
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_TAG = "hrafnox/elasticrune:2.2.3-rc1"
BASELINE = "hrafnox/elasticrune@sha256:0b57752b2be0bfa01d696d7ae214b87e4feee609389047b085a8f74f6dd29e55"


def evidence_dir(value):
    path = pathlib.Path(value).expanduser().resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError("Evidence must be outside the public repository")
    path.mkdir(parents=True, exist_ok=True)
    return path


def run(*args, check=True, input=None, timeout=120):
    result = subprocess.run(args, input=input, text=True, encoding="utf-8",
                            errors="replace", capture_output=True, timeout=timeout)
    if check and result.returncode:
        # Do not echo command arguments: validation can pass ephemeral credentials.
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr[-4000:]}")
    return result


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

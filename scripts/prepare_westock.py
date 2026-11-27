#!/usr/bin/env python3
"""Download a pinned official CLI to local-results/bin; never runs vendor code.

Pins are an observed 2026-11-27 snapshot, not a promise about future releases.
No global installation, shell profile changes, credentials, or automatic update.
"""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import zipfile
from urllib.parse import urlsplit

ZIP_URL = "https://api.skillhub.cn/api/v1/download?slug=westock-data&namespace=tencent-adm"
CONTENT_SHA = "5ea98262ef1f3191c591e487316e4ce1c637bba6c37230c629157e8fa2dd2907"
MANIFEST_SHA = "1e87706dbd7b968f21f44b3e8c12d83bac4cb7ad37528c584df4704d3d9fd9b5"
BASE = "https://stockbuddy.qq.com/release/skillhub/cli/v0.0.2/"


def download(url, dest):
    allowed = {"api.skillhub.cn", "skillhub-1388575217.cos.accelerate.myqcloud.com", "stockbuddy.qq.com"}
    for _ in range(4):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.port:
            raise ValueError("Unapproved download redirect; stop for review")
        result = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--max-time", "60",
            "--max-filesize", "67108864", "--proto", "=https", url, "--output", str(dest),
            "--write-out", "%{http_code}\n%{redirect_url}"], check=True, capture_output=True, text=True)
        status, _, redirect = result.stdout.partition("\n")
        if status == "200":
            return dest.read_bytes()
        if status in ("301", "302", "303", "307", "308") and redirect:
            url = redirect
            continue
        raise ValueError("Unexpected download HTTP status: " + status)
    raise ValueError("Too many download redirects")


def check(data, expected):
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError("SHA256 mismatch; stop and review official release, never disable checking")
    return actual


def main():
    systems = {"Darwin": "darwin", "Linux": "linux"}
    architectures = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64", "AMD64": "amd64"}
    artifact = "westock-{}-{}".format(systems[platform.system()], architectures[platform.machine()])
    dest = Path("local-results/bin/westock")
    if dest.exists():
        raise ValueError("Destination exists; inspect it, do not silently overwrite an executable")
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        archive = download(ZIP_URL, root / "skill.zip")
        with zipfile.ZipFile(root / "skill.zip") as package:
            # Pin content independently of ZIP container metadata, using
            # SkillHub's hash_version 1 (already signature-verified in Phase 0).
            entries = []
            paths = package.namelist()
            if len(paths) != len(set(paths)) or len(paths) != 10:
                raise ValueError("Unexpected package members")
            for path in paths:
                if path.startswith("/") or ".." in Path(path).parts:
                    raise ValueError("Unsafe archive path")
                if path != "_meta.json":
                    entries.append((path, hashlib.sha256(package.read(path)).hexdigest()))
            canonical = "".join("{}:{}\n".format(*entry) for entry in sorted(entries)).encode()
            check(canonical, CONTENT_SHA)
            if json.loads(package.read("_meta.json"))["version"] != "1.0.7":
                raise ValueError("Skill version mismatch")
            setup = package.read("scripts/setup.sh").decode()
            if MANIFEST_SHA not in setup or BASE.removesuffix("v0.0.2/")[:-1] not in setup:
                raise ValueError("Pinned release no longer matches reviewed package")
        manifest = download(BASE + "SHA256.txt", root / "SHA256.txt")
        check(manifest, MANIFEST_SHA)
        entries = dict((line.split()[1], line.split()[0]) for line in manifest.decode().splitlines())
        binary = download(BASE + artifact, root / "binary")
        sha = check(binary, entries[artifact])
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents a race from overwriting a local executable.
        with dest.open("xb") as out:
            out.write(binary)
        dest.chmod(0o700)
        print(json.dumps({"path": str(dest), "artifact": artifact, "sha256": sha,
            "archive_sha256": hashlib.sha256(archive).hexdigest(), "content_sha256": CONTENT_SHA, "executed": False}))


if __name__ == "__main__":
    main()

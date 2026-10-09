"""Publish private Quantumult X resources behind an Nginx bearer URL.

Runtime settings, access keys and node exports remain outside the Git checkout.
The published tree excludes .git and server-side keys/configuration.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def private_base(settings):
    base = settings["public_base"].rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("public_base must be an HTTPS origin with a plain path")
    key = settings["access_key"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", key):
        raise ValueError("Access key must contain 32-128 URL-safe characters")
    return f"{base}/{key}/"


def collect_nodes(files):
    lines = []
    tags = set()
    for number, file in enumerate(files, 1):
        content = Path(file).read_text()
        source = [line for line in content.splitlines() if line.strip() and not line.startswith(("#", ";"))]
        if not source:
            raise ValueError(f"Node source {number} is empty")
        for line in source:
            if not line.startswith(("vless=", "anytls=")):
                raise ValueError(f"Node source {number} has an unsupported node")
            tag = re.search(r"(?:^|,)\s*tag=([^,]+)", line)
            if not tag or tag.group(1) in tags:
                raise ValueError(f"Node source {number} has a missing or duplicate node tag")
            if line.startswith("anytls=") and "tls-verification=true" not in line:
                raise ValueError(f"Node source {number} disables certificate verification")
            tags.add(tag.group(1))
            lines.append(line)
    if not lines:
        raise ValueError("At least one node source is required")
    return "\n".join(lines) + "\n"


def make_public_directory(path):
    missing = []
    parent = path
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    path.mkdir(parents=True, exist_ok=True, mode=0o2750)
    for directory in missing:
        directory.chmod(0o2750)
    path.chmod(0o2750)


def write_text(path, text):
    make_public_directory(path.parent)
    path.write_text(text)
    path.chmod(0o640)


def write_private_text(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", prefix=".private-", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(text)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def validate_repository(repository):
    # Execute only the installed, reviewed validator; the fetched checkout is data.
    validator = Path(__file__).resolve().with_name("sync_upstream.py")
    result = subprocess.run([sys.executable, str(validator), "--root", str(repository), "--check"],
                            capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError("Repository resource validation failed; publication was not changed")


def main_configuration(repository, config, private_config=None):
    public = (repository / config).read_text()
    if not private_config:
        return public
    private_path = Path(private_config).resolve()
    if private_path == repository or repository in private_path.parents:
        raise ValueError("Private configuration must remain outside the Git checkout")
    private = private_path.read_text()
    # Keep personal sections private while refreshing generated resource selections.
    for section in ("filter_remote", "rewrite_remote"):
        begin, end = f"# BEGIN blackmatrix7 {section}", f"# END blackmatrix7 {section}"
        if any(text.count(begin) != 1 or text.count(end) != 1 for text in (public, private)):
            raise ValueError(f"Expected one managed resource block for {section}")
        pattern = re.compile(rf"^# BEGIN blackmatrix7 {section}\n.*?^# END blackmatrix7 {section}$", re.M | re.S)
        blocks = pattern.findall(public)
        if len(blocks) != 1 or len(pattern.findall(private)) != 1:
            raise ValueError(f"Expected one managed resource block for {section}")
        private = pattern.sub(lambda match: blocks[0], private)
    return private


def publish(settings, node_files):
    repository = Path(settings["repository"]).resolve()
    destination = Path(settings["destination"]).resolve()
    current = Path(settings["current"])
    if destination == repository or repository in destination.parents or current.exists() and not current.is_symlink():
        raise ValueError("Publication paths must be separate from the repository and current must be a symlink")
    base = private_base(settings)
    profile = json.loads((repository / "profiles/blackmatrix7.json").read_text())
    config = profile["config"]
    if Path(config).name != config:
        raise ValueError("Main configuration must be a root-level filename")
    nodes = collect_nodes(node_files)
    dirty = subprocess.check_output(["git", "-C", str(repository), "status", "--porcelain"], text=True)
    if dirty:
        raise ValueError("Repository has local modifications; refusing to publish")
    revision = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    config_text = main_configuration(repository, config, settings.get("private_config"))
    node_placeholder = "https://example.invalid/quanx/nodes.conf"
    if config_text.count(node_placeholder) != 1:
        raise ValueError("Main configuration must contain exactly one self-hosted node subscription")
    identity = {
        "revision": revision,
        "nodes_sha256": hashlib.sha256(nodes.encode()).hexdigest(),
        "base_sha256": hashlib.sha256(base.encode()).hexdigest(),
        "config_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
    }
    state = current / ".publication.json"
    if state.exists() and json.loads(state.read_text()) == identity:
        return False
    if not state.exists() or json.loads(state.read_text())["revision"] != revision:
        validate_repository(repository)
    raw_base = profile["raw_base"]
    rendered = {config: config_text.replace(raw_base, base).replace(node_placeholder, base + "nodes.conf"),
                "nodes.conf": nodes}
    for path in sorted((repository / "quantumultx").rglob("*")):
        if path.is_file():
            rendered[path.relative_to(repository).as_posix()] = path.read_text().replace(raw_base, base)
    if any(raw_base in text for text in rendered.values()):
        raise ValueError("A private GitHub raw URL remains in rendered resources")
    for name in ("rule", "rewrite", "script", "dependencies", "LICENSES"):
        if not (repository / name).is_dir():
            raise ValueError(f"Required resource directory is absent: {name}")
    make_public_directory(destination)
    stage = Path(tempfile.mkdtemp(prefix="release-", dir=destination))
    stage.chmod(0o2750)
    switched = False
    link = current.with_name(current.name + ".next")
    try:
        # Copy resources so a subsequent Git pull cannot mutate the live release.
        for name in ("rule", "rewrite", "script", "dependencies", "LICENSES"):
            shutil.copytree(repository / name, stage / name)
            # Git updates run with a private umask; normalize only published copies.
            for path in [stage / name, *(stage / name).rglob("*")]:
                path.chmod(0o2750 if path.is_dir() else 0o640)
        for name, text in rendered.items():
            write_text(stage / name, text)
        shutil.copyfile(repository / "UPSTREAM_README.md", stage / "UPSTREAM_README.md")
        (stage / "UPSTREAM_README.md").chmod(0o640)
        write_text(stage / ".publication.json", json.dumps(identity, sort_keys=True) + "\n")
        make_public_directory(current.parent)
        link.unlink(missing_ok=True)
        link.symlink_to(stage, target_is_directory=True)
        os.replace(link, current)
        switched = True
        releases = sorted(destination.glob("release-*"), key=lambda path: path.stat().st_mtime, reverse=True)
        for old in releases[3:]:
            if old != stage:
                shutil.rmtree(old)
        return True
    finally:
        link.unlink(missing_ok=True)
        if not switched:
            shutil.rmtree(stage)


def nginx_snippet(settings):
    base = urlsplit(private_base(settings))
    path = base.path
    denied = urlsplit(settings["public_base"]).path.rstrip("/") + "/"
    current = Path(settings["current"])
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+/", path) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(current)):
        raise ValueError("Nginx paths contain unsupported characters")
    return f"""# Generated locally; this file contains a private bearer key.
# Use a dedicated subscription HTTPS server: normalized paths may leave a location.
access_log off;
error_log /dev/null;
location ^~ {path} {{
    alias {current}/;
    autoindex off;
    access_log off;
    error_log /dev/null;
    default_type text/plain;
    charset utf-8;
    add_header Cache-Control "private, no-store" always;
    add_header X-Content-Type-Options nosniff always;
}}
location ^~ {denied} {{
    access_log off;
    error_log /dev/null;
    return 404;
}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--nodes", type=Path, nargs="+", required=True)
    parser.add_argument("--nginx-output", type=Path)
    args = parser.parse_args()
    try:
        settings = json.loads(args.settings.read_text())
        snippet = nginx_snippet(settings) if args.nginx_output else None
        changed = publish(settings, args.nodes)
        if args.nginx_output:
            write_private_text(args.nginx_output, snippet)
        print("Published private configuration and node subscription" if changed else "Private subscription is unchanged")
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Private publication failed ({type(error).__name__}); check runtime settings and publication files\n")


if __name__ == "__main__":
    main()

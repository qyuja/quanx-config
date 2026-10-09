#!/bin/sh
set -eu
umask 077

subscription_root="${1:-/opt/projects/quanx-subscription}"
exec 9>"$subscription_root/update.lock"
if ! flock -n 9; then
    exit 0
fi

work="$(mktemp -d "$subscription_root/work.XXXXXXXX")"
trap 'rm -rf "$work"' EXIT HUP INT TERM
export GIT_SSH_COMMAND="ssh -F $subscription_root/ssh.conf"
git -C "$subscription_root/repository" -c core.hooksPath=/dev/null pull --quiet --ff-only origin master

python3 - "$subscription_root" "$work" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

root, work = map(Path, sys.argv[1:])
try:
    settings = json.loads((root / "settings.json").read_text())
    local = settings.get("local_node")
    if local:
        command = [sys.executable, str(root / "bin/export_nodes.py"),
                   "--config", local["config"], "--server", local["server"],
                   "--country", local["country"], "--output", str(work / "local.conf")]
        if local.get("pin_anytls"):
            command.append("--pin-anytls")
        subprocess.run(command, check=True, capture_output=True, timeout=60)
    remote = settings.get("remote_node")
    if remote:
        with (work / "remote.conf").open("wb") as output:
            subprocess.run(["ssh", "-F", str(root / "ssh.conf"), remote],
                           check=True, stdout=output, stderr=subprocess.PIPE, timeout=60)
except (KeyError, ValueError, OSError, subprocess.SubprocessError):
    sys.exit("Node export failed; check private runtime settings and node services")
PY
python3 "$subscription_root/bin/publish_subscription.py" \
    --settings "$subscription_root/settings.json" --nodes "$work/"*.conf

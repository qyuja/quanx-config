"""Export supported sing-box inbounds as native Quantumult X nodes.

Output contains client credentials. Use a private file or an encrypted SSH pipe.
Server private keys are used only to derive their public counterpart.
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def openssl(arguments, data=None):
    result = subprocess.run(["openssl", *arguments], input=data, capture_output=True, timeout=15)
    if result.returncode:
        raise ValueError("OpenSSL could not read the configured key or certificate")
    return result.stdout


def public_key(private_key):
    raw = base64.urlsafe_b64decode(private_key + "=" * (-len(private_key) % 4))
    if len(raw) != 32:
        raise ValueError("REALITY requires a 32-byte X25519 private key")
    private_der = bytes.fromhex("302e020100300506032b656e04220420") + raw
    public_der = openssl(["pkey", "-inform", "DER", "-pubout", "-outform", "DER"], private_der)
    prefix = bytes.fromhex("302a300506032b656e032100")
    if len(public_der) != len(prefix) + 32 or not public_der.startswith(prefix):
        raise ValueError("OpenSSL returned an unexpected X25519 public key")
    return base64.urlsafe_b64encode(public_der[len(prefix):]).decode().rstrip("=")


def certificate_pin(path):
    public_pem = openssl(["x509", "-in", str(path), "-pubkey", "-noout"])
    public_der = openssl(["pkey", "-pubin", "-outform", "DER"], public_pem)
    return hashlib.sha256(public_der).hexdigest()


def field(value, name):
    text = str(value)
    if not text or text != text.strip() or any(char in text for char in ",\r\n"):
        raise ValueError(f"{name} cannot be represented in native node syntax")
    return text


def render_nodes(config, server, country, pin_anytls=False):
    address = field(server, "server")
    country = field(country, "country")
    if ":" in address and not address.startswith("["):
        address = f"[{address}]"
    nodes = []
    for inbound in config.get("inbounds", []):
        protocol = inbound.get("type")
        if protocol not in ("vless", "anytls"):
            continue
        if inbound.get("transport"):
            raise ValueError(f"Unsupported {protocol} transport")
        users = inbound.get("users", [])
        if len(users) != 1:
            raise ValueError(f"Expected one client user for {protocol}")
        tls = inbound.get("tls", {})
        if not tls.get("enabled"):
            raise ValueError(f"{protocol} requires TLS")
        port = inbound["listen_port"]
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f"Invalid {protocol} listen port")
        host = field(tls.get("server_name", ""), "TLS server name")
        if protocol == "vless":
            reality = tls.get("reality", {})
            if not reality.get("enabled"):
                raise ValueError("This exporter requires VLESS with REALITY")
            short_ids = reality.get("short_id", [])
            if not short_ids:
                raise ValueError("REALITY short ID is missing")
            flow = users[0].get("flow", "")
            if flow not in ("", "xtls-rprx-vision"):
                raise ValueError("Unsupported VLESS flow")
            parts = [
                f"vless={address}:{port}", "method=none",
                "password=" + field(users[0]["uuid"], "VLESS UUID"),
                "obfs=over-tls", f"obfs-host={host}",
                "reality-base64-pubkey=" + public_key(reality["private_key"]),
                "reality-hex-shortid=" + field(short_ids[0], "REALITY short ID"),
            ]
            if flow:
                parts.append(f"vless-flow={flow}")
            label = "VLESS-REALITY"
        else:
            parts = [
                f"anytls={address}:{port}",
                "password=" + field(users[0]["password"], "AnyTLS password"),
                "over-tls=true", f"tls-host={host}", "tls-verification=true",
            ]
            if pin_anytls:
                parts.append("tls-pubkey-sha256=" + certificate_pin(tls["certificate_path"]))
            label = "AnyTLS"
        parts.extend(["fast-open=false", "udp-relay=true", f"tag={country}-{label}"])
        nodes.append(", ".join(parts))
    if not nodes:
        raise ValueError("No supported proxy inbounds found")
    return "\n".join(nodes) + "\n"


def write_private(path, text):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".nodes-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--country", required=True)
    parser.add_argument("--pin-anytls", action="store_true")
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--output", type=Path)
    output.add_argument("--stdout", action="store_true", help="For an encrypted SSH pipe only")
    args = parser.parse_args()
    try:
        nodes = render_nodes(json.loads(args.config.read_text()), args.server, args.country, args.pin_anytls)
        if args.output:
            write_private(args.output, nodes)
            print(f"Exported {len(nodes.splitlines())} native nodes to a private file")
        else:
            print(nodes, end="")
    except (KeyError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Node export failed ({type(error).__name__}); check configuration and certificate fields\n")


if __name__ == "__main__":
    main()

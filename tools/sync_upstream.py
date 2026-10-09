#!/usr/bin/env python3
"""Mirror upstream resources verbatim and render a native Quantumult X profile."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

UPSTREAM_REPO = "https://github.com/blackmatrix7/ios_rule_script.git"
UPSTREAM_RAW = "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/"
MIRROR_ROOTS = ("rule", "rewrite", "script")
FILTER_TYPES = {"host", "host-suffix", "host-keyword", "host-wildcard", "user-agent",
                "ip-cidr", "ip6-cidr", "ip-asn", "geoip"}
SCRIPT_URL = re.compile(r"\burl\s+script-\S+\s+(https?://\S+)")
SECTION = re.compile(r"^\[([a-z_]+)\][ \t]*$", re.M)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def section_body(text, name):
    headers = list(SECTION.finditer(text))
    for index, header in enumerate(headers):
        if header.group(1) == name:
            end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
            return header.end(), end, text[header.end():end]
    raise ValueError(f"Missing configuration section [{name}]")


def managed_block(section, content):
    return (f"# BEGIN blackmatrix7 {section}\n" + content.rstrip() + "\n"
            + f"# END blackmatrix7 {section}")


def update_section(text, section, content, replace_initial=False):
    start, end, body = section_body(text, section)
    begin = f"# BEGIN blackmatrix7 {section}"
    finish = f"# END blackmatrix7 {section}"
    block = managed_block(section, content)
    if begin in body or finish in body:
        if body.count(begin) != 1 or body.count(finish) != 1:
            raise ValueError(f"Malformed managed block in [{section}]")
        first, last = body.index(begin), body.index(finish) + len(finish)
        if first >= last - len(finish):
            raise ValueError(f"Reversed managed markers in [{section}]")
        body = body[:first] + block + body[last:]
    elif replace_initial:
        body = "\n\n" + block + "\n\n\n"
    else:
        body = body.rstrip() + "\n\n" + block + "\n\n\n"
    return text[:start] + body + text[end:]


def filter_paths(root):
    return sorted(str(path.relative_to(root))
                  for directory in ("rule/QuantumultX", "rewrite/QuantumultX")
                  for path in (root / directory).rglob("*.list"))


def rewrite_paths(root):
    return sorted(str(path.relative_to(root))
                  for path in (root / "rewrite/QuantumultX").rglob("*.conf"))


def rule_count(path):
    total = 0
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, 1):
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            fields = [field.strip() for field in line.split(",")]
            if len(fields) < 3 or fields[0].lower() not in FILTER_TYPES or not fields[1]:
                raise ValueError(f"Invalid native filter: {path.name}:{number}")
            total += 1
    return total


def validate_selection(root, profile):
    active = profile["filters"]
    selected = {entry["path"] for entry in active}
    if len(selected) != len(active):
        raise ValueError("Duplicate selected filter paths")
    if not selected <= set(filter_paths(root)):
        raise ValueError(f"Selected filters missing upstream: {sorted(selected - set(filter_paths(root)))}")
    enabled = set(profile["rewrite_enabled"])
    names = {Path(path).stem for path in rewrite_paths(root)}
    if not enabled <= names:
        raise ValueError(f"Selected rewrites missing upstream: {sorted(enabled - names)}")
    exclusive = [{"Advertising", "AdvertisingLite"}, {"Redirect", "SafeRedirect"}]
    if "AllInOne" in enabled:
        exclusive.append({"AllInOne", "Advertising", "AdvertisingLite", "AdvertisingScript",
                          "Redirect", "SafeRedirect"})
    for group in exclusive:
        if len(enabled & group) > 1:
            raise ValueError(f"Overlapping rewrites enabled: {sorted(enabled & group)}")
    for name in enabled:
        pair = f"rewrite/QuantumultX/{name}/{name}.list"
        if (root / pair).is_file() and pair not in selected:
            raise ValueError(f"Enabled rewrite {name} requires filter {pair}")
        if pair in selected and next(entry["policy"] for entry in active if entry["path"] == pair) != "reject":
            raise ValueError(f"Paired rewrite filter must use reject: {pair}")


def resource_line(url, tag, interval, enabled, policy=None):
    params = [f"tag={tag}"]
    if policy is not None:
        params.append(f"force-policy={policy}")
    params.extend([f"update-interval={interval}", "opt-parser=false",
                   f"enabled={str(enabled).lower()}"])
    return url + ", " + ", ".join(params)


def recovered_dependencies(root, profile):
    path = profile.get("dependency_overrides_file")
    if not path:
        return {}
    overrides = read_json(root / path)
    for url, entry in overrides.items():
        data = (root / entry["path"]).read_bytes()
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if (len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]
                or blob != entry["git_blob"]):
            raise ValueError(f"Archived dependency changed: {entry['path']}")
    return overrides


def render(root, profile, dependency_root=None):
    validate_selection(root, profile)
    base, interval = profile["raw_base"], profile["update_interval"]
    overrides = recovered_dependencies(dependency_root or root, profile)
    disabled_scripts = set(profile.get("disabled_script_urls", []))
    selected = {entry["path"]: entry for entry in profile["filters"]}
    category_policies = {Path(entry["path"]).parent.name: entry["policy"]
                         for entry in profile["filters"] if entry["path"].startswith("rule/")}
    category_policies.update(profile["optional_policies"])
    paths = list(selected) + [path for path in filter_paths(root) if path not in selected]
    filter_lines = ["# 全量原生分流；常用规则启用，其余规则按需打开并选择 force-policy。"]
    table = ["# Quantumult X 全量资源索引", "", "由 tools/sync_upstream.py 生成。主配置已列出全部资源。",
             "未单独指定策略的可选资源沿用兜底分流；启用前按用途调整 force-policy。", "",
             "## 分流规则", "", "| 资源 | 实际条数 | 策略 | 默认状态 |", "| --- | ---: | --- | --- |"]
    for path in paths:
        file = Path(path)
        paired = path.startswith("rewrite/")
        tag = selected[path]["tag"] if path in selected else (
            ("BM配套_" if paired else "BM规则_")
            + str(Path(*file.parts[2:]).with_suffix("")).replace("/", "-"))
        policy = selected[path]["policy"] if path in selected else (
            "reject" if paired else category_policies.get(file.parent.name, profile["default_policy"]))
        enabled = path in selected
        if len(filter_lines) == len(selected) + 1:
            filter_lines.extend(["", "# 以下为完整可选资源；默认关闭以避免聚合规则互相覆盖。"])
        filter_lines.append(resource_line(base + path, tag, interval, enabled, policy))
        table.append(f"| [{path}]({base + path}) | {rule_count(root / path)} | {policy} | {'启用' if enabled else '关闭'} |")

    outputs = {}
    rewrite_lines = ["# 全部原生 rewrite；AllInOne 与组成模块互斥，GetCookie 按需启用。"]
    table.extend(["", "## 重写模块", "", "| 资源 | 配套分流 | 默认状态 |", "| --- | --- | --- |"])
    external_scripts = set()
    for path in rewrite_paths(root):
        relative = Path(path).relative_to("rewrite/QuantumultX")
        target = str(Path("quantumultx/rewrite") / relative)
        original = (root / path).read_text(encoding="utf-8")
        rewritten = original
        for url in SCRIPT_URL.findall(original):
            if url in disabled_scripts:
                continue
            if url.startswith(UPSTREAM_RAW):
                dependency = url.removeprefix(UPSTREAM_RAW)
                if (root / dependency).is_file():
                    rewritten = rewritten.replace(url, base + dependency)
                elif url in overrides:
                    rewritten = rewritten.replace(url, base + overrides[url]["path"])
                else:
                    raise ValueError(f"Missing upstream script dependency: {path}")
            else:
                external_scripts.add(url)
        lines = []
        for line in rewritten.splitlines():
            if any(url in disabled_scripts for url in SCRIPT_URL.findall(line)):
                # The deleted DivineEngine repository has no verifiable upstream copy.
                line = "# DISABLED: upstream script returns 404 | " + line
            lines.append(line)
        outputs[target] = "\n".join(lines) + "\n"
        enabled = relative.stem in profile["rewrite_enabled"]
        rewrite_lines.append(resource_line(base + target, "BM重写_" + relative.stem,
                                           interval, enabled))
        pair = str(Path(path).with_suffix(".list"))
        pair_link = f"[{relative.stem}.list]({base + pair})" if (root / pair).is_file() else "无"
        table.append(f"| [{relative.stem}]({base + target}) | {pair_link} | {'启用' if enabled else '关闭'} |")
    table.extend(["", "## 保留的外部脚本依赖", "", "以下脚本属于 Gist 或其他作者的仓库，保留上游地址：", ""])
    table.extend(f"- {url}" for url in sorted(external_scripts))
    table.extend(["", "## 历史恢复与失效依赖", "",
                  "上游删除的脚本从明确的历史 commit 恢复，固定版本与哈希记录在 dependencies/manifest.json。",
                  "恢复文件的存在不代表原有签到接口仍可用；相关模块默认关闭。", ""])
    for url, entry in sorted(overrides.items()):
        table.append(f"- [{entry['path']}]({base + entry['path']})；[历史来源]({entry['source_url']})")
    table.extend(["", "以下来源已失效，订阅版本注释相关条目，上游原文完整保留：", ""])
    table.extend(f"- {url}" for url in sorted(disabled_scripts))
    filters, rewrites = "\n".join(filter_lines) + "\n", "\n".join(rewrite_lines) + "\n"
    outputs["quantumultx/filter_remote.conf"] = "[filter_remote]\n\n" + filters
    outputs["quantumultx/rewrite_remote.conf"] = "[rewrite_remote]\n\n" + rewrites
    outputs["quantumultx/catalog.md"] = "\n".join(table) + "\n"
    return outputs, filters, rewrites, sorted(external_scripts)


def snapshot(upstream):
    tree = subprocess.check_output(["git", "ls-tree", "-r", "-z", "HEAD", "--",
                                    *MIRROR_ROOTS], cwd=upstream).split(b"\0")
    files = {}
    counts = {name: {"files": 0, "bytes": 0} for name in MIRROR_ROOTS}
    for entry in tree:
        if not entry:
            continue
        info, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = info.decode().split()
        path = raw_path.decode()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"Unsupported upstream entry: {path}")
        data = (upstream / path).read_bytes()
        actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if actual != oid:
            raise ValueError(f"Upstream working copy differs from its commit: {path}")
        files[path] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        group = counts[path.split("/")[0]]
        group["files"] += 1
        group["bytes"] += len(data)
    for name, count in counts.items():
        if count["files"] == 0:
            raise ValueError(f"Missing upstream directory: {name}")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    commit_time = subprocess.check_output(["git", "show", "-s", "--format=%cI", "HEAD"], cwd=upstream, text=True).strip()
    return {"repository": UPSTREAM_REPO.removesuffix(".git"), "branch": "master",
            "revision": revision, "commit_time": commit_time, "counts": counts, "files": files}


def sync(root, upstream):
    if upstream == root or root in upstream.parents:
        raise ValueError("Upstream checkout must be outside the destination repository")
    profile = read_json(root / "profiles/blackmatrix7.json")
    manifest = snapshot(upstream)
    present = {str(path.relative_to(upstream)) for name in MIRROR_ROOTS
               for path in (upstream / name).rglob("*") if path.is_file()}
    if present != set(manifest["files"]):
        raise ValueError("Upstream mirror directories contain untracked or missing files")
    attribution = {
        "UPSTREAM_README.md": (upstream / "README.md").read_text(encoding="utf-8"),
        "LICENSES/blackmatrix7-GPL-2.0.txt": (upstream / "LICENSE").read_text(encoding="utf-8")
    }
    manifest["attribution_files"] = {
        path: hashlib.sha256(content.encode()).hexdigest() for path, content in attribution.items()
    }
    outputs, filters, rewrites, external = render(upstream, profile, dependency_root=root)
    manifest["external_script_dependencies"] = external
    manifest["disabled_script_dependencies"] = profile.get("disabled_script_urls", [])
    config = root / profile["config"]
    previous = config.read_text(encoding="utf-8")
    updated = update_section(previous, "filter_remote", filters, replace_initial=True)
    updated = update_section(updated, "rewrite_remote", rewrites)
    # Validate the complete source before replacing directories owned by the mirror.
    for name in MIRROR_ROOTS:
        destination = root / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(upstream / name, destination)
    if (root / "quantumultx/rewrite").exists():
        shutil.rmtree(root / "quantumultx/rewrite")
    for path, content in outputs.items():
        write_text(root / path, content)
    write_text(config, updated)
    for path, content in attribution.items():
        write_text(root / path, content)
    write_text(root / "UPSTREAM.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Synced upstream {manifest['revision']}: {manifest['counts']}")


def check(root):
    profile = read_json(root / "profiles/blackmatrix7.json")
    manifest = read_json(root / "UPSTREAM.json")
    present = {str(path.relative_to(root)) for name in MIRROR_ROOTS
               for path in (root / name).rglob("*") if path.is_file()}
    if present != set(manifest["files"]):
        raise ValueError("Mirror file inventory differs from UPSTREAM.json")
    for path, expected in manifest["files"].items():
        data = (root / path).read_bytes()
        if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError(f"Mirror content changed: {path}")
    for path, expected in manifest["attribution_files"].items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Upstream attribution changed: {path}")
    outputs, filters, rewrites, external = render(root, profile)
    for path, content in outputs.items():
        if (root / path).read_text(encoding="utf-8") != content:
            raise ValueError(f"Generated resource is stale: {path}")
    if external != manifest["external_script_dependencies"]:
        raise ValueError("External rewrite dependencies differ from manifest")
    if profile.get("disabled_script_urls", []) != manifest["disabled_script_dependencies"]:
        raise ValueError("Disabled rewrite dependencies differ from manifest")
    text = (root / profile["config"]).read_text(encoding="utf-8")
    policy_body = section_body(text, "policy")[2]
    policies = {"direct", "reject", "proxy"}
    policies.update(line.split("=", 1)[1].split(",", 1)[0].strip()
                    for line in policy_body.splitlines()
                    if line.strip() and not line.lstrip().startswith(("#", ";")) and "=" in line)
    for name, content in [("filter_remote", filters), ("rewrite_remote", rewrites)]:
        body = section_body(text, name)[2]
        if managed_block(name, content) not in body:
            raise ValueError(f"Configuration managed block is stale: [{name}]")
        for line in body.splitlines():
            if not line.startswith(profile["raw_base"]):
                continue
            url = line.split(",", 1)[0]
            if not (root / url.removeprefix(profile["raw_base"])).is_file():
                raise ValueError(f"Missing self-hosted resource in [{name}]")
            policy = re.search(r"(?:^|,)\s*force-policy=([^,]+)", line)
            if policy and policy.group(1).strip() not in policies:
                raise ValueError(f"Undefined policy: {policy.group(1).strip()}")
    for path, content in outputs.items():
        if not path.startswith("quantumultx/rewrite/"):
            continue
        active_lines = "\n".join(line for line in content.splitlines()
                                 if not line.lstrip().startswith(("#", ";")))
        for url in SCRIPT_URL.findall(active_lines):
            if url.startswith(profile["raw_base"]) and not (root / url.removeprefix(profile["raw_base"])).is_file():
                raise ValueError(f"Missing self-hosted rewrite script: {path}")
    print(f"Validated {len(present)} mirrored files, {len(filter_paths(root))} native filters, "
          f"{len(rewrite_paths(root))} native rewrites, policies and script dependencies.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, help="Existing clean upstream Git checkout")
    parser.add_argument("--check", action="store_true", help="Validate current snapshot offline")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Configuration checkout to validate or synchronize")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.check:
        check(root)
        return
    if args.upstream:
        sync(root, args.upstream.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="quanx-upstream-") as directory:
            upstream = Path(directory) / "upstream"
            subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--single-branch",
                            "--branch", "master", UPSTREAM_REPO, str(upstream)], check=True, timeout=300)
            sync(root, upstream)
    check(root)


if __name__ == "__main__":
    main()

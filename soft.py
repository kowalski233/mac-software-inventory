#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import concurrent.futures
import datetime
import html
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPORT_NAME = "software_report.html"
TIMEOUT = 15
MAX_WORKERS = 12


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def shell(cmd):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def shell_json(cmd):
    code, out, err = shell(cmd)
    if code != 0 or not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def fetch_json(url, headers=None):
    req = urllib.request.Request(
        url,
        headers=headers or {
            "User-Agent": "Mozilla/5.0 software-inventory-report/1.0"
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        data = resp.read().decode(charset, errors="replace")
        return json.loads(data)


def fetch_text(url, headers=None):
    req = urllib.request.Request(
        url,
        headers=headers or {
            "User-Agent": "Mozilla/5.0 software-inventory-report/1.0"
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def path_size(path_str):
    path = Path(path_str)
    if not path.exists():
        return None
    try:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for root, _, files in os.walk(path, onerror=lambda *_: None):
            for name in files:
                fp = os.path.join(root, name)
                try:
                    if not os.path.islink(fp):
                        total += os.path.getsize(fp)
                except Exception:
                    pass
        return total
    except Exception:
        return None


def bytes_to_human(size):
    if size is None:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return str(size)


def safe_get(dct, *keys, default=""):
    cur = dct
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur if cur is not None else default


def unique_list(items):
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def make_record(
    ecosystem,
    name,
    version="",
    description="",
    developer="",
    release_time="",
    size_bytes=None,
    install_path="",
    homepage="",
    license_name="",
    dependencies=None,
    reverse_dependencies=None,
    purpose="",
    source="local",
    extra=None,
):
    return {
        "ecosystem": ecosystem,
        "name": name or "",
        "version": version or "",
        "description": description or "",
        "purpose": purpose or description or "",
        "developer": developer or "",
        "release_time": release_time or "",
        "size_bytes": size_bytes,
        "size_human": bytes_to_human(size_bytes),
        "install_path": install_path or "",
        "homepage": homepage or "",
        "license": license_name or "",
        "dependencies": unique_list(dependencies or []),
        "reverse_dependencies": unique_list(reverse_dependencies or []),
        "source": source,
        "extra": extra or {},
    }


def scan_brew():
    if not shutil.which("brew"):
        return []

    results = []
    formulae = shell_json(["brew", "info", "--json=v2", "--installed"])
    if formulae:
        formulae_items = formulae.get("formulae", [])
        casks_items = formulae.get("casks", [])

        reverse_map = {}
        for item in formulae_items:
            for dep in item.get("dependencies", []):
                reverse_map.setdefault(dep, []).append(item.get("name", ""))

        for item in formulae_items:
            name = item.get("name", "")
            installed = item.get("installed", [])
            version = installed[-1].get("version", "") if installed else item.get("versions", {}).get("stable", "")
            desc = item.get("desc", "")
            homepage = item.get("homepage", "")
            developer = ""
            release_time = ""
            pkg_path = ""

            prefix = item.get("installed", [{}])[-1].get("installed_as_dependency", None)
            linked_keg = item.get("linked_keg", "")
            code, out, _ = shell(["brew", "--prefix", name])
            if code == 0:
                pkg_path = out.strip()

            size_bytes = path_size(pkg_path) if pkg_path else None

            results.append(
                make_record(
                    ecosystem="Homebrew Formula",
                    name=name,
                    version=version,
                    description=desc,
                    developer=developer,
                    release_time=release_time,
                    size_bytes=size_bytes,
                    install_path=pkg_path,
                    homepage=homepage,
                    license_name=item.get("license", ""),
                    dependencies=item.get("dependencies", []),
                    reverse_dependencies=reverse_map.get(name, []),
                    source="local+brew",
                    extra={
                        "tap": item.get("tap", ""),
                        "linked_keg": linked_keg,
                        "installed_as_dependency": prefix,
                    },
                )
            )

        for item in casks_items:
            name = item.get("token", "")
            version = item.get("version", "")
            desc = item.get("desc", "")
            homepage = item.get("homepage", "")
            app_paths = item.get("artifacts", [])
            size_bytes = None
            install_path = ""

            candidate_paths = []
            for artifact in app_paths:
                if isinstance(artifact, list):
                    for part in artifact:
                        if isinstance(part, str) and part.endswith(".app"):
                            candidate_paths.append(f"/Applications/{part}")
                elif isinstance(artifact, dict):
                    for _, value in artifact.items():
                        if isinstance(value, str) and value.endswith(".app"):
                            candidate_paths.append(f"/Applications/{value}")

            for candidate in candidate_paths:
                if os.path.exists(candidate):
                    install_path = candidate
                    size_bytes = path_size(candidate)
                    break

            results.append(
                make_record(
                    ecosystem="Homebrew Cask",
                    name=name,
                    version=version,
                    description=desc,
                    size_bytes=size_bytes,
                    install_path=install_path,
                    homepage=homepage,
                    license_name="",
                    dependencies=[],
                    reverse_dependencies=[],
                    source="local+brew",
                    extra={
                        "full_token": item.get("full_token", ""),
                    },
                )
            )
    return results


def scan_pip():
    if not shutil.which("python3"):
        return []

    results = []
    code, out, _ = shell([sys.executable, "-m", "pip", "list", "--format=json"])
    if code != 0 or not out:
        code, out, _ = shell(["python3", "-m", "pip", "list", "--format=json"])
    if code != 0 or not out:
        return []

    try:
        packages = json.loads(out)
    except Exception:
        return []

    reverse_map = {}
    detail_cache = {}

    for pkg in packages:
        name = pkg.get("name", "")
        code, show_out, _ = shell(["python3", "-m", "pip", "show", name])
        info = {}
        if code == 0 and show_out:
            for line in show_out.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    info[key.strip()] = value.strip()
        detail_cache[name] = info
        reqs = [x.strip() for x in info.get("Requires", "").split(",") if x.strip()]
        for dep in reqs:
            reverse_map.setdefault(dep, []).append(name)

    for pkg in packages:
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        info = detail_cache.get(name, {})
        install_path = info.get("Location", "")
        size_bytes = path_size(install_path) if install_path else None
        results.append(
            make_record(
                ecosystem="Python",
                name=name,
                version=version,
                description=info.get("Summary", ""),
                developer=info.get("Author", "") or info.get("Author-email", ""),
                release_time="",
                size_bytes=size_bytes,
                install_path=install_path,
                homepage=info.get("Home-page", ""),
                license_name=info.get("License", ""),
                dependencies=[x.strip() for x in info.get("Requires", "").split(",") if x.strip()],
                reverse_dependencies=reverse_map.get(name, []),
                source="local+pip",
            )
        )
    return results


def scan_npm():
    if not shutil.which("npm"):
        return []

    results = []
    code, root_out, _ = shell(["npm", "root", "-g"])
    if code != 0 or not root_out:
        return []
    npm_root = root_out.strip()

    data = shell_json(["npm", "ls", "-g", "--depth=0", "--json"])
    if not data:
        return []

    dependencies = data.get("dependencies", {})
    for name, info in dependencies.items():
        version = info.get("version", "")
        package_path = os.path.join(npm_root, name)
        size_bytes = path_size(package_path)
        pkg_json_path = os.path.join(package_path, "package.json")
        pkg_json = {}
        if os.path.exists(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    pkg_json = json.load(f)
            except Exception:
                pass

        deps = list((pkg_json.get("dependencies") or {}).keys())
        results.append(
            make_record(
                ecosystem="Node.js",
                name=name,
                version=version,
                description=pkg_json.get("description", ""),
                developer=(
                    pkg_json.get("author", {}).get("name", "")
                    if isinstance(pkg_json.get("author"), dict)
                    else (pkg_json.get("author", "") if isinstance(pkg_json.get("author"), str) else "")
                ),
                size_bytes=size_bytes,
                install_path=package_path,
                homepage=pkg_json.get("homepage", ""),
                license_name=pkg_json.get("license", ""),
                dependencies=deps,
                reverse_dependencies=[],
                source="local+npm",
            )
        )

    reverse_map = {}
    for item in results:
        for dep in item["dependencies"]:
            reverse_map.setdefault(dep, []).append(item["name"])
    for item in results:
        item["reverse_dependencies"] = reverse_map.get(item["name"], [])
    return results


def scan_gem():
    if not shutil.which("gem"):
        return []

    results = []
    code, out, _ = shell(["gem", "list", "--local"])
    if code != 0 or not out:
        return []

    for line in out.splitlines():
        line = line.strip()
        if not line or " (" not in line:
            continue
        name, versions_part = line.split(" (", 1)
        versions = versions_part.rstrip(")")
        version = versions.split(",")[0].strip()

        code, spec_out, _ = shell(["gem", "specification", name, "--yaml"])
        description = ""
        homepage = ""
        developer = ""
        license_name = ""
        dependencies = []
        install_path = ""

        if code == 0 and spec_out:
            for raw in spec_out.splitlines():
                txt = raw.strip()
                if txt.startswith("summary:"):
                    description = txt.split("summary:", 1)[1].strip().strip('"').strip("'")
                elif txt.startswith("homepage:"):
                    homepage = txt.split("homepage:", 1)[1].strip()
                elif txt.startswith("name:"):
                    pass
                elif txt.startswith("licenses:"):
                    pass
                elif txt.startswith("-"):
                    pass

        code, dir_out, _ = shell(["gem", "which", name])
        if code == 0 and dir_out:
            install_path = dir_out.strip()
        size_bytes = path_size(install_path) if install_path else None

        results.append(
            make_record(
                ecosystem="Ruby",
                name=name,
                version=version,
                description=description,
                developer=developer,
                size_bytes=size_bytes,
                install_path=install_path,
                homepage=homepage,
                license_name=license_name,
                dependencies=dependencies,
                reverse_dependencies=[],
                source="local+gem",
            )
        )
    return results


def scan_cargo():
    if not shutil.which("cargo"):
        return []

    results = []
    code, out, _ = shell(["cargo", "install", "--list"])
    if code != 0 or not out:
        return []

    cargo_home = os.environ.get("CARGO_HOME", str(Path.home() / ".cargo"))
    bin_dir = os.path.join(cargo_home, "bin")

    current_name = None
    current_version = None
    for line in out.splitlines():
        if not line.startswith(" "):
            if " v" in line:
                name_part, _rest = line.split(" v", 1)
                current_name = name_part.strip()
                current_version = line.split(" v", 1)[1].split(":", 1)[0].strip()
                bin_path = os.path.join(bin_dir, current_name)
                size_bytes = path_size(bin_path) if os.path.exists(bin_path) else None
                results.append(
                    make_record(
                        ecosystem="Rust",
                        name=current_name,
                        version=current_version,
                        size_bytes=size_bytes,
                        install_path=bin_path if os.path.exists(bin_path) else "",
                        source="local+cargo",
                    )
                )
    return results


def read_plist(path):
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except Exception:
        return {}


def app_info(app_path):
    info_plist = os.path.join(app_path, "Contents", "Info.plist")
    info = read_plist(info_plist)
    name = info.get("CFBundleName") or info.get("CFBundleDisplayName") or Path(app_path).stem
    version = info.get("CFBundleShortVersionString") or info.get("CFBundleVersion", "")
    desc = info.get("NSHumanReadableCopyright", "")
    homepage = ""
    developer = info.get("CFBundleIdentifier", "")
    size_bytes = path_size(app_path)
    ctime = ""
    try:
        stat = os.stat(app_path)
        ctime = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    except Exception:
        pass
    return make_record(
        ecosystem="Application",
        name=name,
        version=version,
        description=desc,
        developer=developer,
        release_time=ctime,
        size_bytes=size_bytes,
        install_path=app_path,
        homepage=homepage,
        source="local+appbundle",
    )


def scan_apps():
    results = []
    app_dirs = ["/Applications", str(Path.home() / "Applications")]
    seen = set()
    for base in app_dirs:
        if not os.path.isdir(base):
            continue
        try:
            for entry in os.listdir(base):
                if not entry.endswith(".app"):
                    continue
                full = os.path.join(base, entry)
                if full in seen:
                    continue
                seen.add(full)
                results.append(app_info(full))
        except Exception:
            pass
    return results


def scan_pkgutil():
    if not shutil.which("pkgutil"):
        return []

    results = []
    code, out, _ = shell(["pkgutil", "--pkgs"])
    if code != 0 or not out:
        return []

    for pkgid in out.splitlines()[:400]:
        pkgid = pkgid.strip()
        if not pkgid:
            continue
        code, info_out, _ = shell(["pkgutil", "--pkg-info", pkgid])
        version = ""
        install_time = ""
        install_location = ""

        if code == 0 and info_out:
            for line in info_out.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if key == "version":
                        version = value
                    elif key == "location":
                        install_location = value

        results.append(
            make_record(
                ecosystem="PKG Receipt",
                name=pkgid,
                version=version,
                release_time=install_time,
                install_path=install_location,
                source="local+pkgutil",
            )
        )
    return results


def enrich_pypi(item):
    name = item["name"]
    try:
        data = fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
        info = data.get("info", {})
        releases = data.get("releases", {})
        release_time = ""
        if item["version"] in releases and releases[item["version"]]:
            release_time = safe_get(releases[item["version"]][0], "upload_time_iso_8601", default="")
        elif info.get("version") in releases and releases[info.get("version")] :
            release_time = safe_get(releases[info.get("version")][0], "upload_time_iso_8601", default="")
        item["description"] = item["description"] or info.get("summary", "")
        item["purpose"] = item["purpose"] or info.get("summary", "")
        item["developer"] = item["developer"] or info.get("author", "") or info.get("author_email", "")
        item["homepage"] = item["homepage"] or info.get("home_page", "") or safe_get(info, "project_urls", "Homepage", default="")
        item["license"] = item["license"] or info.get("license", "")
        item["release_time"] = item["release_time"] or release_time
        item["source"] += "+pypi"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def enrich_npm(item):
    name = item["name"]
    try:
        data = fetch_json(f"https://registry.npmjs.org/{urllib.parse.quote(name)}")
        latest = safe_get(data, "dist-tags", "latest", default=item["version"])
        versions = data.get("versions", {})
        ver_info = versions.get(item["version"]) or versions.get(latest, {})
        time_map = data.get("time", {})
        item["description"] = item["description"] or ver_info.get("description", "")
        author = ver_info.get("author", {})
        if isinstance(author, dict):
            author_name = author.get("name", "")
        else:
            author_name = author if isinstance(author, str) else ""
        item["developer"] = item["developer"] or author_name
        item["homepage"] = item["homepage"] or ver_info.get("homepage", "")
        item["license"] = item["license"] or ver_info.get("license", "")
        item["release_time"] = item["release_time"] or time_map.get(item["version"], "") or time_map.get(latest, "")
        if not item["dependencies"]:
            item["dependencies"] = list((ver_info.get("dependencies") or {}).keys())
        item["source"] += "+npm-registry"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def enrich_rubygems(item):
    name = item["name"]
    try:
        data = fetch_json(f"https://rubygems.org/api/v1/gems/{urllib.parse.quote(name)}.json")
        item["description"] = item["description"] or data.get("info", "")
        item["purpose"] = item["purpose"] or data.get("info", "")
        authors = data.get("authors", "")
        item["developer"] = item["developer"] or authors
        item["homepage"] = item["homepage"] or data.get("homepage_uri", "") or data.get("project_uri", "")
        item["license"] = item["license"] or ", ".join(data.get("licenses", []) or [])
        item["release_time"] = item["release_time"] or data.get("version_created_at", "")
        item["source"] += "+rubygems"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def enrich_crates(item):
    name = item["name"]
    try:
        data = fetch_json(f"https://crates.io/api/v1/crates/{urllib.parse.quote(name)}")
        crate = data.get("crate", {})
        newest = crate.get("newest_version", "")
        versions = data.get("versions", [])
        release_time = ""
        for ver in versions:
            if ver.get("num") == item["version"] or ver.get("num") == newest:
                release_time = ver.get("created_at", "")
                break
        item["description"] = item["description"] or crate.get("description", "")
        item["purpose"] = item["purpose"] or crate.get("description", "")
        item["developer"] = item["developer"] or crate.get("repository", "") or crate.get("homepage", "")
        item["homepage"] = item["homepage"] or crate.get("homepage", "") or crate.get("repository", "")
        item["license"] = item["license"] or crate.get("license", "")
        item["release_time"] = item["release_time"] or release_time
        item["source"] += "+cratesio"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def enrich_brew_formula(item):
    name = item["name"]
    try:
        data = fetch_json(f"https://formulae.brew.sh/api/formula/{urllib.parse.quote(name)}.json")
        item["description"] = item["description"] or data.get("desc", "")
        item["purpose"] = item["purpose"] or data.get("desc", "")
        item["homepage"] = item["homepage"] or data.get("homepage", "")
        item["license"] = item["license"] or data.get("license", "")
        versions = data.get("versions", {})
        item["release_time"] = item["release_time"] or ""
        if not item["dependencies"]:
            item["dependencies"] = data.get("dependencies", []) or []
        item["source"] += "+brew-api"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def enrich_app(item):
    install_path = item.get("install_path", "")
    if not install_path or not os.path.exists(install_path):
        return False, "app path missing"
    developer = item.get("developer", "")

    code, out, _ = shell(["mdls", "-name", "kMDItemAppStoreHasReceipt", "-name", "kMDItemKind", install_path])
    if code == 0 and out:
        if not item["description"]:
            item["description"] = "macOS Application Bundle"
            item["purpose"] = item["description"]

    code, out, _ = shell(["codesign", "-dv", install_path])
    if out and not developer:
        for line in out.splitlines():
            if "Authority=" in line:
                item["developer"] = line.split("Authority=", 1)[1].strip()
                break
    item["source"] += "+metadata"
    return True, ""


def enrich_item(item):
    eco = item["ecosystem"]
    try:
        if eco == "Python":
            return enrich_pypi(item)
        if eco == "Node.js":
            return enrich_npm(item)
        if eco == "Ruby":
            return enrich_rubygems(item)
        if eco == "Rust":
            return enrich_crates(item)
        if eco == "Homebrew Formula":
            return enrich_brew_formula(item)
        if eco in ("Application", "Homebrew Cask"):
            return enrich_app(item)
        return False, "no enrich provider"
    except Exception as exc:
        return False, str(exc)


def enrich_all(items):
    failures = []

    def worker(item):
        missing = (
            not item.get("description")
            or not item.get("developer")
            or not item.get("release_time")
            or not item.get("homepage")
        )
        if not missing:
            return None
        ok, err = enrich_item(item)
        if not ok:
            return {"ecosystem": item["ecosystem"], "name": item["name"], "error": err}
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(worker, item) for item in items]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                failures.append(result)
    return failures


def build_dependency_edges(items):
    edges = []
    for item in items:
        src = f'{item["ecosystem"]}:{item["name"]}'
        for dep in item.get("dependencies", []):
            edges.append((src, dep))
    return edges


def tab_button(tab_id, label, active=False):
    cls = "tab-button active" if active else "tab-button"
    return f'<button class="{cls}" onclick="showTab(\'{html.escape(tab_id)}\', this)">{html.escape(label)}</button>'


def render_table(items):
    headers = [
        "包名",
        "版本",
        "描述/用途",
        "开发者",
        "发布时间/安装时间",
        "大小",
        "依赖",
        "反向依赖",
        "主页",
        "安装路径",
        "来源",
    ]
    parts = ['<div class="table-wrap"><table><thead><tr>']
    for header in headers:
        parts.append(f"<th>{html.escape(header)}</th>")
    parts.append("</tr></thead><tbody>")

    for item in sorted(items, key=lambda x: (x.get("name", "").lower(), x.get("version", ""))):
        homepage = item.get("homepage", "")
        homepage_html = (
            f'<a href="{html.escape(homepage)}" target="_blank">{html.escape(homepage)}</a>'
            if homepage else ""
        )
        row = [
            item.get("name", ""),
            item.get("version", ""),
            item.get("purpose", "") or item.get("description", ""),
            item.get("developer", ""),
            item.get("release_time", ""),
            item.get("size_human", ""),
            ", ".join(item.get("dependencies", [])),
            ", ".join(item.get("reverse_dependencies", [])),
            homepage_html,
            item.get("install_path", ""),
            item.get("source", ""),
        ]
        parts.append("<tr>")
        for idx, cell in enumerate(row):
            if idx == 8:
                parts.append(f"<td>{cell}</td>")
            else:
                parts.append(f"<td>{html.escape(str(cell))}</td>")
        parts.append("</tr>")

    parts.append("</tbody></table></div>")
    return "".join(parts)


def render_summary(items, failures):
    total_size = sum(x.get("size_bytes") or 0 for x in items)
    ecosystems = {}
    for item in items:
        ecosystems[item["ecosystem"]] = ecosystems.get(item["ecosystem"], 0) + 1

    parts = ['<div class="cards">']
    cards = [
        ("总条目", str(len(items))),
        ("统计时间", now_iso()),
        ("累计大小", bytes_to_human(total_size)),
        ("补全失败", str(len(failures))),
    ]
    for title, value in cards:
        parts.append(f'<div class="card"><div class="card-title">{html.escape(title)}</div><div class="card-value">{html.escape(value)}</div></div>')
    parts.append("</div>")

    parts.append('<div class="table-wrap"><table><thead><tr><th>分类</th><th>数量</th></tr></thead><tbody>')
    for name, count in sorted(ecosystems.items(), key=lambda x: x[0]):
        parts.append(f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def render_dependencies(items):
    parts = ['<div class="table-wrap"><table><thead><tr><th>软件</th><th>依赖</th><th>反向依赖</th></tr></thead><tbody>']
    for item in sorted(items, key=lambda x: (x["ecosystem"], x["name"].lower())):
        title = f'{item["ecosystem"]} / {item["name"]}'
        deps = ", ".join(item.get("dependencies", []))
        revs = ", ".join(item.get("reverse_dependencies", []))
        parts.append(
            f"<tr><td>{html.escape(title)}</td><td>{html.escape(deps)}</td><td>{html.escape(revs)}</td></tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def render_failures(failures):
    if not failures:
        return "<p>没有补全失败项。</p>"
    parts = ['<div class="table-wrap"><table><thead><tr><th>分类</th><th>名称</th><th>失败原因</th></tr></thead><tbody>']
    for item in failures:
        parts.append(
            f"<tr><td>{html.escape(item.get('ecosystem', ''))}</td><td>{html.escape(item.get('name', ''))}</td><td>{html.escape(item.get('error', ''))}</td></tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def generate_html(items, failures):
    groups = {}
    for item in items:
        groups.setdefault(item["ecosystem"], []).append(item)

    tabs = [
        ("summary", "总览"),
        ("brew_formula", "Homebrew Formula"),
        ("brew_cask", "Homebrew Cask"),
        ("python", "Python"),
        ("node", "Node"),
        ("ruby", "Ruby"),
        ("rust", "Rust"),
        ("app", "Applications"),
        ("pkg", "PKG Receipt"),
        ("deps", "依赖关系"),
        ("fail", "补全失败"),
    ]

    tab_buttons = []
    tab_contents = []

    for idx, (tab_id, label) in enumerate(tabs):
        tab_buttons.append(tab_button(tab_id, label, active=(idx == 0)))

    mapping = {
        "brew_formula": "Homebrew Formula",
        "brew_cask": "Homebrew Cask",
        "python": "Python",
        "node": "Node.js",
        "ruby": "Ruby",
        "rust": "Rust",
        "app": "Application",
        "pkg": "PKG Receipt",
    }

    tab_contents.append(
        f'<div id="summary" class="tab-content active">{render_summary(items, failures)}</div>'
    )

    for tab_id, eco_name in mapping.items():
        tab_contents.append(
            f'<div id="{html.escape(tab_id)}" class="tab-content">{render_table(groups.get(eco_name, []))}</div>'
        )

    tab_contents.append(
        f'<div id="deps" class="tab-content">{render_dependencies(items)}</div>'
    )
    tab_contents.append(
        f'<div id="fail" class="tab-content">{render_failures(failures)}</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>本机软件包信息报告</title>
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  margin: 0;
  background: #f5f7fb;
  color: #1f2937;
}}
header {{
  background: #111827;
  color: white;
  padding: 20px 24px;
}}
header h1 {{
  margin: 0 0 6px;
  font-size: 24px;
}}
header p {{
  margin: 0;
  color: #d1d5db;
}}
.container {{
  padding: 20px 24px 40px;
}}
.tabs {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}}
.tab-button {{
  border: none;
  background: #e5e7eb;
  color: #111827;
  padding: 10px 14px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 14px;
}}
.tab-button.active {{
  background: #2563eb;
  color: white;
}}
.tab-content {{
  display: none;
}}
.tab-content.active {{
  display: block;
}}
.cards {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}}
.card {{
  background: white;
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.06);
}}
.card-title {{
  color: #6b7280;
  font-size: 13px;
}}
.card-value {{
  margin-top: 8px;
  font-size: 22px;
  font-weight: 700;
}}
.table-wrap {{
  overflow: auto;
  background: white;
  border-radius: 14px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.06);
}}
table {{
  width: 100%;
  border-collapse: collapse;
  min-width: 1200px;
}}
th, td {{
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid #e5e7eb;
  vertical-align: top;
  font-size: 13px;
}}
th {{
  position: sticky;
  top: 0;
  background: #f9fafb;
  z-index: 1;
}}
a {{
  color: #2563eb;
  text-decoration: none;
}}
a:hover {{
  text-decoration: underline;
}}
.footer {{
  margin-top: 20px;
  font-size: 12px;
  color: #6b7280;
}}
</style>
<script>
function showTab(tabId, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-button').forEach(el => el.classList.remove('active'));
  document.getElementById(tabId).classList.add('active');
  btn.classList.add('active');
}}
</script>
</head>
<body>
<header>
  <h1>本机软件包信息报告</h1>
  <p>生成时间：{html.escape(now_iso())}</p>
</header>
<div class="container">
  <div class="tabs">
    {''.join(tab_buttons)}
  </div>
  {''.join(tab_contents)}
  <div class="footer">
    说明：开发时间字段优先显示公开仓库发布时间，其次为本地可推断时间；部分 app/pkg 无法获得完整依赖关系。
  </div>
</div>
</body>
</html>
"""


def main():
    print("开始扫描本机软件与包管理器信息，请稍候...")
    all_items = []

    scanners = [
        scan_brew,
        scan_pip,
        scan_npm,
        scan_gem,
        scan_cargo,
        scan_apps,
        scan_pkgutil,
    ]

    for scanner in scanners:
        try:
            print(f"正在执行: {scanner.__name__}")
            items = scanner()
            all_items.extend(items)
            print(f"完成: {scanner.__name__} -> {len(items)} 条")
        except Exception as exc:
            print(f"扫描器异常: {scanner.__name__}: {exc}")

    merged = {}
    for item in all_items:
        key = (item["ecosystem"], item["name"], item["version"], item["install_path"])
        if key not in merged:
            merged[key] = item
    all_items = list(merged.values())

    print(f"本地扫描完成，共 {len(all_items)} 条，开始联网补全...")
    failures = enrich_all(all_items)
    print(f"联网补全结束，失败 {len(failures)} 条。")

    report_html = generate_html(all_items, failures)
    report_path = Path(__file__).resolve().parent / REPORT_NAME
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_html)

    print(f"报告已生成: {report_path}")


if __name__ == "__main__":
    main()
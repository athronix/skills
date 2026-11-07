#!/usr/bin/env python3
"""Scan owner's GitHub repos, detect skill repos via .skill marker, rebuild
aggregate-marketplace artifacts (marketplace.json + <skill>.link.json).

Single writer design: this script is the ONLY producer of marketplace.json.
Run modes:
  scan   : read-only, print JSON summary (used locally, never writes remote)
  sync   : full rebuild + write files into the aggregate repo working tree
           (used by aggregate repo CI; commit/push is done by the workflow)

Env:
  GH_TOKEN or GITHUB_READ_TOKEN : PAT for API (repo scope needed to see private)
  OWNER           : repo owner, default athronix
  MARKETPLACE     : aggregate repo, default athronix/skills
  WORKDIR         : local checkout root of aggregate repo (sync mode, required)
  SKIP_PRIVATE    : "1" to skip private repos (degraded public-only scan)

No credential is ever printed. Output JSON only contains counts and metadata.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

OWNER = os.environ.get("OWNER", "athronix")
MARKETPLACE = os.environ.get("MARKETPLACE", "athronix/skills")
WORKDIR = os.environ.get("WORKDIR", ".")
SKIP_PRIVATE = os.environ.get("SKIP_PRIVATE") == "1"
EXEMPT = {"skills"}  # aggregate repo never counts as a skill repo
API = "https://api.github.com"

FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)
FM_KV = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", re.M)


def token():
    for k in ("GH_TOKEN", "GITHUB_READ_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    envf = os.path.expanduser("~/.workbuddy/.env")
    if os.path.exists(envf):
        import re as _re
        for line in open(envf, encoding="utf-8", errors="replace"):
            m = _re.match(r"^\s*(GITHUB_READ_TOKEN|GH_TOKEN)\s*=\s*(\S+)", line)
            if m:
                return m.group(2).strip("\"'")
    return ""


def api(path, need_auth=True):
    req = urllib.request.Request(API + path)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "skill-matrix-sync")
    t = token()
    if need_auth and t:
        req.add_header("Authorization", "Bearer " + t)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def list_repos():
    """List owner's repos INCLUDING private ones. REST /users/{o}/repos never
    returns private repos even for authenticated tokens — use GraphQL
    viewer.repositories (viewer is authenticated; owner must equal token owner)."""
    cursor, repos = None, []
    if not token():  # degraded: no credential -> REST public listing only
        page = 1
        while True:
            batch = api(f"/users/{OWNER}/repos?per_page=100&page={page}", need_auth=False) or []
            if not batch:
                break
            for b in batch:
                repos.append({"name": b["name"], "isPrivate": False, "visibility": "PUBLIC",
                              "url": b["html_url"], "pushedAt": b.get("pushed_at", ""),
                              "description": b.get("description"),
                              "defaultBranchRef": {"name": b["default_branch"]}})
            if len(batch) < 100:
                break
            page += 1
        return repos
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        q = {"query": "query{user(login:" + json.dumps(OWNER) + "){repositories(first:100"
                      + after + ",orderBy:{field:PUSHED_AT,direction:DESC}){pageInfo{hasNextPage endCursor}"
                        "nodes{name visibility isPrivate url pushedAt description"
                        " defaultBranchRef{name}}}}}"}
        req = urllib.request.Request("https://api.github.com/graphql",
                                     data=json.dumps(q).encode(), method="POST")
        req.add_header("Authorization", "Bearer " + token())
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "skill-matrix-sync")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        if data.get("errors"):
            raise RuntimeError("graphql: " + json.dumps(data["errors"])[:300])
        nodes = (data.get("data", {}).get("user") or {}).get("repositories", {}).get("nodes", [])
        repos.extend(nodes)
        pinfo = (data.get("data", {}).get("user") or {}).get("repositories", {})
        if not pinfo.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = pinfo["pageInfo"]["endCursor"]
    return repos


def read_marker(repo):
    """GET /repos/{r}/contents/.skill on default branch. Returns dict or None."""
    data = api(f"/repos/{repo}/contents/.skill")
    if not data:
        return None
    try:
        raw = __import__("base64").b64decode(data.get("content", "")).decode("utf-8", "replace")
    except Exception:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return {}  # legacy empty marker: still a skill repo, no pointer info


def read_frontmatter(repo, ref):
    """Read SKILL.md frontmatter (root or pointer path) via contents API."""
    path = "SKILL.md"
    data = api(f"/repos/{repo}/contents/{path}?ref={ref}")
    if not data:
        return {}
    raw = __import__("base64").b64decode(data.get("content", "")).decode("utf-8", "replace")
    m = FRONT_RE.match(raw)
    if not m:
        return {}
    out = {}
    for k, v in FM_KV.findall(m.group(1)):
        v = v.strip().strip('"').strip("'")
        out[k] = v
    return out


def latest_release(repo):
    rel = api(f"/repos/{repo}/releases/latest")
    if not rel:
        return None
    asset = ""
    for a in rel.get("assets", []):
        if a["name"].endswith(".zip"):
            asset = a["browser_download_url"]
            break
    return {"tag": rel.get("tag_name", ""), "url": rel.get("html_url", ""),
            "asset": asset, "published": rel.get("published_at", "")}


def repo_license(repo):
    data = api(f"/repos/{repo}")
    if not data:
        return ""
    return (data.get("license") or {}).get("spdx_id") or ""


def collect():
    skills, warnings = [], []
    for r in list_repos():   # GraphQL nodes: name/visibility/isPrivate/url/pushedAt/description/defaultBranchRef
        name = r["name"]
        if name in EXEMPT:
            continue
        is_private = r.get("isPrivate") or r.get("visibility") == "PRIVATE"
        if is_private and SKIP_PRIVATE:
            warnings.append({"repo": name, "warning": "private-skipped"})
            continue
        full = f"{OWNER}/{name}"
        marker = read_marker(full)
        if marker is None:
            continue
        default_branch = (r.get("defaultBranchRef") or {}).get("name") or "main"
        fm = read_frontmatter(full, default_branch)
        skill_name = fm.get("name") or marker.get("skill_name") or name
        if skill_name != name:
            warnings.append({"repo": full, "warning": f"name-mismatch frontmatter={skill_name} repo={name}"})
        rel = latest_release(full)
        version = (rel or {}).get("tag", "").lstrip("v") or fm.get("version", "")
        if rel and fm.get("version") and rel["tag"] != "v" + fm["version"]:
            warnings.append({"repo": full, "warning": f"version-drift tag={rel['tag']} frontmatter={fm.get('version')}"})
        lic = repo_license(full)
        entry = {
            "name": name, "full_name": full, "skill_name": skill_name,
            "version": version, "description": fm.get("description") or r.get("description") or "",
            "license": lic,
            "visibility": "private" if is_private else "public",
            "repo_url": r["url"], "clone_url": r["url"] + ".git",
            "default_branch": default_branch, "topics": [],
            "updated_at": r.get("pushedAt", ""),
            "release": rel, "marker": marker, "frontmatter_keys": sorted(fm.keys()),
        }
        skills.append(entry)
    skills.sort(key=lambda s: s["name"])
    return skills, warnings


def build_marketplace(skills):
    plugins = []
    for s in skills:
        p = {
            "name": s["name"],
            "description": s["description"][:512],
            "version": s["version"] or "0.0.0",
            "source": s["repo_url"],
        }
        if s["license"]:
            p["license"] = s["license"]
        p["x-athronix"] = {
            "fullName": s["full_name"], "visibility": s["visibility"],
            "cloneUrl": s["clone_url"], "defaultBranch": s["default_branch"],
            "topics": s["topics"], "pushedAt": s["updated_at"],
            "release": s["release"] or {}, "marker": s["marker"],
        }
        plugins.append(p)
    return {
        "name": "athronix-skills",
        "description": "athronix 技能矩阵聚合市场：每个 skill 独立 repo（athronix/<skill>，含 .skill 标记），本文件与 <skill>.link.json 由 CI scan_and_sync 全量重建，请勿手工编辑。Aggregate marketplace of athronix skill repos; machine-generated, do not edit.",
        "owner": {"name": "athronix"},
        "plugins": plugins,
    }


def write_outputs(skills):
    root = os.path.abspath(WORKDIR)
    mp = build_marketplace(skills)
    mp["x-athronix-market"] = {
        "marketplaceRepo": MARKETPLACE,
        "skillRepoPattern": "github.com/athronix/<skill> (root .skill marker = skill repo)",
        "markerSpec": {"file": ".skill", "format": "single-line JSON pointer, never gitignored"},
        "linkFiles": "<skill>.link.json = machine-generated repo hyperlink",
        "consumerNotes": "Any AI agent may install a skill: git clone a <skill>.link.json target repo (private needs PAT) or download release asset zip from release.asset.",
        "syncedBy": "github.com/skills/.github/workflows/sync-marketplace.yml",
        "syncedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
    }
    with open(os.path.join(root, "marketplace.json"), "w", encoding="utf-8") as f:
        json.dump(mp, f, ensure_ascii=False, indent=2)
        f.write("\n")
    names = set()
    for s in skills:
        names.add(s["name"])
        link = {
            "skill": s["name"], "repo": s["repo_url"], "clone": s["clone_url"],
            "visibility": s["visibility"], "version": s["version"],
            "defaultBranch": s["default_branch"],
            "release": (s["release"] or {}).get("url", ""),
            "package": (s["release"] or {}).get("asset", ""),
        }
        with open(os.path.join(root, f"{s['name']}.link.json"), "w", encoding="utf-8") as f:
            json.dump(link, f, ensure_ascii=False, indent=2)
            f.write("\n")
    # prune stale link files
    removed = []
    for fn in os.listdir(root):
        if fn.endswith(".link.json") and fn[: -len(".link.json")] not in names:
            os.remove(os.path.join(root, fn))
            removed.append(fn)
    return removed


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    skills, warnings = collect()
    if mode == "scan":
        json.dump({"count": len(skills), "skills": skills, "warnings": warnings},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    if mode == "sync":
        removed = write_outputs(skills)
        json.dump({"count": len(skills), "pruned": removed, "warnings": warnings,
                   "changed": changed_files()}, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    print("usage: scan_and_sync.py [scan|sync]", file=sys.stderr)
    return 2


def changed_files():
    import subprocess
    r = subprocess.run(["git", "-C", os.path.abspath(WORKDIR), "status", "--porcelain"],
                       capture_output=True, text=True)
    return [ln.strip() for ln in r.stdout.splitlines()]


if __name__ == "__main__":
    sys.exit(main())

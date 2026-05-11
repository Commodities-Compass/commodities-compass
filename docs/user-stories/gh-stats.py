#!/usr/bin/env python3
"""
gh-stats.py — Collecte des stats GitHub pour le Founding Engineer Report.

Périmètre : un seul repo, une fenêtre de dates.
Sortie : un fichier JSON consolidé prêt à être transformé en data-story.

Pré-requis :
  - gh CLI authentifié      (gh auth login)
  - git                     (déjà installé sur macOS)
  - Python 3.8+             (stdlib uniquement)

Usage :
  cd /chemin/vers/commodities-compass
  python3 gh-stats.py --since 2026-02-11 --until 2026-05-04 --output stats.json

Le script doit être lancé depuis la racine du repo (clone local à jour).
Pense à 'git pull' avant pour avoir tous les commits.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ─────────────────────────────────────────── helpers ──

def run(cmd: list[str], check: bool = True) -> str:
    """Run a command, return stdout. Raises on non-zero unless check=False."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=check)
        return res.stdout
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"\n[ERROR] {' '.join(cmd)}\n{e.stderr}\n")
        raise


def gh_json(args: list[str]) -> object:
    """Run a gh command that returns JSON, parse it."""
    out = run(["gh", *args])
    return json.loads(out) if out.strip() else None


def detect_repo() -> str:
    """Return 'owner/repo' from the current git remote."""
    out = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()
    if not out:
        sys.exit("Impossible de détecter le repo. Lance le script depuis le clone local.")
    return out


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


# ─────────────────────────────────────────── commits ──

def collect_commits(since: str, until: str) -> dict:
    """Parse `git log --numstat` between two dates."""
    # NOTE: we use BEL (\x07) instead of \x1e because Python's splitlines()
    # treats \x1e as a line boundary, which silently destroys the parser.
    SEP = "\x07"
    fmt = f"{SEP}COMMIT{SEP}%H{SEP}%an{SEP}%ae{SEP}%aI{SEP}%s"
    out = run([
        "git", "log",
        f"--since={since} 00:00:00",
        f"--until={until} 23:59:59",
        "--no-merges",
        f"--pretty=format:{fmt}",
        "--numstat",
    ])

    commits = []
    current = None
    for raw in out.split("\n"):
        if raw.startswith(f"{SEP}COMMIT{SEP}"):
            if current is not None:
                commits.append(current)
            _, _, h, an, ae, ai, subj = raw.split(SEP, 6)
            current = {
                "hash": h, "author": an, "email": ae,
                "datetime": ai, "subject": subj,
                "added": 0, "removed": 0, "files": [],
            }
        elif raw.strip() and current is not None:
            parts = raw.split("\t")
            if len(parts) == 3:
                added, removed, fname = parts
                a = 0 if added == "-" else int(added)
                r = 0 if removed == "-" else int(removed)
                current["added"] += a
                current["removed"] += r
                current["files"].append({"path": fname, "added": a, "removed": r})
    if current is not None:
        commits.append(current)

    # Aggregations
    by_author = Counter()
    by_author_lines = defaultdict(lambda: {"added": 0, "removed": 0})
    by_day = Counter()
    by_hour = Counter()
    by_weekday = Counter()
    by_ext = Counter()

    for c in commits:
        dt = parse_iso(c["datetime"])
        # local time stays UTC here for consistency; tweak if you want Europe/Paris
        by_author[c["author"]] += 1
        by_author_lines[c["author"]]["added"] += c["added"]
        by_author_lines[c["author"]]["removed"] += c["removed"]
        by_day[dt.date().isoformat()] += 1
        by_hour[dt.hour] += 1
        by_weekday[dt.strftime("%A")] += 1
        for f in c["files"]:
            ext = Path(f["path"]).suffix or "(none)"
            by_ext[ext] += f["added"] + f["removed"]

    # Active days / max streak
    days_active = sorted(by_day.keys())
    max_streak = 0
    cur_streak = 0
    prev = None
    for d in days_active:
        cur = datetime.fromisoformat(d).date()
        if prev is not None and (cur - prev).days == 1:
            cur_streak += 1
        else:
            cur_streak = 1
        max_streak = max(max_streak, cur_streak)
        prev = cur

    biggest = sorted(commits, key=lambda c: c["added"] + c["removed"], reverse=True)[:5]
    biggest = [
        {"hash": c["hash"][:7], "author": c["author"],
         "subject": c["subject"], "added": c["added"], "removed": c["removed"]}
        for c in biggest
    ]

    return {
        "total": len(commits),
        "lines_added": sum(c["added"] for c in commits),
        "lines_removed": sum(c["removed"] for c in commits),
        "files_changed": len({f["path"] for c in commits for f in c["files"]}),
        "by_author": dict(by_author),
        "by_author_lines": {k: dict(v) for k, v in by_author_lines.items()},
        "by_day": [{"date": d, "count": by_day[d]} for d in sorted(by_day)],
        "by_hour": {str(h): by_hour.get(h, 0) for h in range(24)},
        "by_weekday": dict(by_weekday),
        "by_extension": dict(by_ext.most_common(15)),
        "active_days": len(days_active),
        "max_streak_days": max_streak,
        "biggest_commits": biggest,
        "first_commit": commits[-1]["datetime"] if commits else None,
        "last_commit": commits[0]["datetime"] if commits else None,
    }


# ─────────────────────────────────────────── PRs / issues ──

def in_window(iso: str | None, since: datetime, until: datetime) -> bool:
    if not iso:
        return False
    return since <= parse_iso(iso) <= until


def collect_prs(repo: str, since: datetime, until: datetime) -> dict:
    fields = "number,title,state,createdAt,closedAt,mergedAt,author,additions,deletions,changedFiles"
    prs = gh_json(["pr", "list", "--repo", repo, "--state", "all",
                   "--limit", "1000", "--json", fields]) or []

    opened = [p for p in prs if in_window(p.get("createdAt"), since, until)]
    merged = [p for p in prs if in_window(p.get("mergedAt"), since, until)]
    closed = [p for p in prs if in_window(p.get("closedAt"), since, until) and not p.get("mergedAt")]

    by_author = Counter(p["author"]["login"] for p in opened if p.get("author"))
    merge_durations = []
    for p in merged:
        c = parse_iso(p["createdAt"])
        m = parse_iso(p["mergedAt"])
        merge_durations.append({
            "pr": p["number"], "title": p["title"],
            "hours": round((m - c).total_seconds() / 3600, 1),
        })
    merge_durations.sort(key=lambda x: x["hours"])
    avg = round(sum(x["hours"] for x in merge_durations) / len(merge_durations), 1) if merge_durations else None

    return {
        "opened": len(opened),
        "merged": len(merged),
        "closed_unmerged": len(closed),
        "by_author_opened": dict(by_author),
        "avg_merge_hours": avg,
        "fastest_merge": merge_durations[0] if merge_durations else None,
        "slowest_merge": merge_durations[-1] if merge_durations else None,
        "total_additions": sum(p.get("additions", 0) for p in merged),
        "total_deletions": sum(p.get("deletions", 0) for p in merged),
    }


def collect_issues(repo: str, since: datetime, until: datetime) -> dict:
    fields = "number,title,state,createdAt,closedAt,author,labels"
    issues = gh_json(["issue", "list", "--repo", repo, "--state", "all",
                      "--limit", "1000", "--json", fields]) or []

    opened = [i for i in issues if in_window(i.get("createdAt"), since, until)]
    closed = [i for i in issues if in_window(i.get("closedAt"), since, until)]

    durations = []
    for i in closed:
        c = parse_iso(i["createdAt"])
        x = parse_iso(i["closedAt"])
        durations.append((x - c).total_seconds() / 3600)
    avg_res = round(sum(durations) / len(durations), 1) if durations else None

    label_counter = Counter()
    for i in opened:
        for l in i.get("labels") or []:
            label_counter[l["name"]] += 1

    return {
        "opened": len(opened),
        "closed": len(closed),
        "avg_resolution_hours": avg_res,
        "top_labels": dict(label_counter.most_common(10)),
    }


# ─────────────────────────────────────────── repo meta ──

def collect_repo_meta(repo: str) -> dict:
    info = gh_json(["repo", "view", repo, "--json",
                    "name,nameWithOwner,description,createdAt,pushedAt,"
                    "stargazerCount,forkCount,isPrivate,defaultBranchRef,"
                    "primaryLanguage"]) or {}
    languages = gh_json(["api", f"repos/{repo}/languages"]) or {}
    total = sum(languages.values()) or 1
    lang_pct = {k: round(v / total * 100, 1) for k, v in languages.items()}
    return {
        "name": info.get("name"),
        "full_name": info.get("nameWithOwner"),
        "description": info.get("description"),
        "created_at": info.get("createdAt"),
        "last_push": info.get("pushedAt"),
        "stars": info.get("stargazerCount"),
        "forks": info.get("forkCount"),
        "private": info.get("isPrivate"),
        "default_branch": (info.get("defaultBranchRef") or {}).get("name"),
        "primary_language": (info.get("primaryLanguage") or {}).get("name"),
        "languages_pct": lang_pct,
        "languages_bytes": languages,
    }


# ─────────────────────────────────────────── main ──

def main() -> int:
    parser = argparse.ArgumentParser(description="Collecte stats GitHub pour Founding Engineer Report.")
    parser.add_argument("--since", required=True, help="Date de début (YYYY-MM-DD).")
    parser.add_argument("--until", required=True, help="Date de fin (YYYY-MM-DD), incluse.")
    parser.add_argument("--output", default="stats.json", help="Fichier JSON de sortie.")
    parser.add_argument("--repo", default=None, help="owner/repo (auto-détecté sinon).")
    args = parser.parse_args()

    repo = args.repo or detect_repo()
    since_dt = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    until_dt = datetime.fromisoformat(args.until).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    days = (until_dt.date() - since_dt.date()).days + 1

    print(f"→ Repo       : {repo}")
    print(f"→ Période    : {args.since} → {args.until} ({days} jours)")
    print(f"→ Collecte commits…")
    commits = collect_commits(args.since, args.until)
    print(f"   {commits['total']} commits, {commits['active_days']} jours actifs.")
    print(f"→ Collecte PRs…")
    prs = collect_prs(repo, since_dt, until_dt)
    print(f"   {prs['opened']} ouvertes / {prs['merged']} mergées.")
    print(f"→ Collecte issues…")
    issues = collect_issues(repo, since_dt, until_dt)
    print(f"   {issues['opened']} ouvertes / {issues['closed']} fermées.")
    print(f"→ Métadonnées repo…")
    meta = collect_repo_meta(repo)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"from": args.since, "to": args.until, "days": days},
        "repo": meta,
        "commits": commits,
        "prs": prs,
        "issues": issues,
    }

    Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n✅ Écrit : {args.output}  ({Path(args.output).stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

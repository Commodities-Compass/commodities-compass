# Gitignored Artifacts — Repatriate Before They Vanish

> Origin: 2026-07-17 — the EN/Ghana edition was built in a `commodities-compass-i18n` worktree. Its 21k implementation report + PR body lived in `docs/user-stories/`, which is **gitignored** (`.gitignore:138`), so they existed only inside that worktree's working directory — invisible from the main tree. During cleanup, `git worktree remove` on the `-landing` worktree **deleted its `docs/user-stories/`**, taking `P1-landing-deploy-gcp.md` (11k, a real US doc) with it. It survived only because an audit had repatriated it ~10 minutes earlier. Git could not have recovered it: never committed, never stashed, no reflog, no remote. It would simply have ceased to exist.

## The Principle

**Gitignored files do not travel.** Git has no record of them, so:

- They do **not** follow branches — switching branches leaves them where they are.
- They do **not** exist in other worktrees — each worktree has its own working directory.
- `git worktree remove` / `git clean -xdf` **delete them silently**, with no reflog, stash, or remote to recover from.
- `git status` hides them by default → they are invisible during review, and their absence is invisible too.

When work happens in parallel across worktrees/branches, the durable artefacts (reports, US docs, handoffs, decision notes) are exactly the things most likely to be gitignored — and therefore most likely to be silently lost.

**The main tree is the canonical home** for anything gitignored-but-precious. Anything hand-authored in a worktree must be repatriated *before* that worktree dies.

## What counts as precious

**Precious — repatriate (hand-authored, not reproducible):**
- `docs/user-stories/` — **gitignored** (`.gitignore:138`): EPICs, US docs, implementation reports, PR bodies, handoffs. The #1 risk area.
- Any report / brief / decision note / handoff `.md` written during a session.
- `.local/` (prod-access helpers), and `.env` **only if it differs** from the main tree's copy (compare by checksum, never by printing it).

**Not precious — never repatriate (regenerable):**
`node_modules/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `dist/`, `build/`, `.next/`, `.astro/`, `.vite/`, `.terraform/`, `htmlcov/`, `coverage`, `.husky/_/`, `*.pyc`, `.DS_Store`, `playwright-report/`, `test-results/`.

## Rules

### 1. NEVER remove or prune a worktree before auditing it

`git worktree remove`, `git worktree prune`, `git clean -xdf`, `rm -rf <worktree>` — all destroy gitignored files unrecoverably. Treat every "let's clean up the worktrees" task as **destructive by default**: audit first, repatriate, then remove.

### 2. Partial removal is still removal — audit BEFORE, never after

`git worktree remove` can fail with `Directory not empty` **and still** deregister the worktree *and* delete files (observed 2026-07-17: it wiped `docs/user-stories/` while leaving a `node_modules/.vite` shell behind). A non-zero exit does not mean "nothing happened". There is no second chance after the fact.

### 3. Auditing means diffing against the main tree, not listing files

"The file exists in the worktree" is not the question. The question is: **does it exist in the main tree, and is it identical?** The main tree often holds an *older* copy of the same gitignored doc. Compare content, not just presence — and never assume the main tree's copy is the current one.

### 4. Durable docs belong in the main tree from the start

Don't let an implementation report live only in a feature worktree for days. If a document is worth reading tomorrow, write it to (or copy it into) the main tree as soon as it matters — not at cleanup time, when it's one command away from deletion.

### 5. Resuming in the main tree: ask "what did git never see?"

When picking work back up in the main tree after building elsewhere, gitignored artefacts will be **missing without any signal** — no diff, no status entry, nothing. Explicitly check the other working directories for docs that never got committed.

## The audit (run before removing ANY worktree)

```bash
WT=/path/to/worktree ; MAIN=/path/to/main-tree
NOISE='node_modules|\.venv|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|/dist/|/build/|\.next/|\.astro/|\.vite|\.terraform|htmlcov|coverage|\.egg-info|\.DS_Store|\.pyc$|playwright-report|test-results|\.husky/_'

# 1. Untracked but NOT ignored
git -C "$WT" ls-files --others --exclude-standard | grep -vE "$NOISE"

# 2. IGNORED minus regenerable noise  ← the dangerous set
git -C "$WT" ls-files --others --ignored --exclude-standard --directory | grep -vE "$NOISE"

# 3. For each candidate dir, diff against the main tree
for f in "$WT"/docs/user-stories/*.md; do
  b=$(basename "$f")
  if [ -f "$MAIN/docs/user-stories/$b" ]; then
    diff -q "$f" "$MAIN/docs/user-stories/$b" >/dev/null || echo "DIFFERS  → review: $b"
  else
    echo "UNIQUE   → repatriate: $b"
  fi
done

# 4. .env & co — compare by checksum, never print contents
shasum -a 256 "$WT/backend/.env" "$MAIN/backend/.env" 2>/dev/null | awk '{print substr($1,1,12), $2}'
```

Repatriate with `cp -n` (never clobber), then re-verify with `diff -q` **before** removing anything.

## When to check

Before **any** of: `git worktree remove` · `git worktree prune` · `git clean -xdf` · `rm -rf <worktree>` · deleting a branch whose only worktree is going away · "clean up my worktrees/branches".

And whenever resuming work in the main tree after a stint in another worktree — the artefacts git never saw are the ones you'll miss last and regret most.

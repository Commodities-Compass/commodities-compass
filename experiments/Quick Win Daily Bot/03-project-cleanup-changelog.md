# Project Cleanup — Technical Changelog

**Date**: 2026-02-13
**Author**: Hedi Blagui
**Scope**: pnpm migration completion, dead config removal, Docker optimization, cleanup scripts

---

## Summary

Completed the partial npm-to-pnpm migration and removed dead configuration files. The project now uses pnpm exclusively across all config files, Dockerfiles, and git hooks.

---

## Changes

### Deleted

| File | Reason |
|------|--------|
| `.github/workflows/frontend-build.yml` | Dead CI pipeline. Built frontend artifacts that were never consumed. Used deprecated `actions/upload-artifact@v3`. Railway deploys independently via git push. |
| `package-lock.json` (648KB) | Legacy npm lock file. Project uses `pnpm@9.15.0` (declared in `packageManager` field). |
| `frontend/nixpacks.toml` | Dead build config. Railway uses `frontend/railway.toml` with `builder = "DOCKERFILE"`, not Nixpacks. |

### Modified

| File | Change |
|------|--------|
| `frontend/Dockerfile` | Replaced all `npm` commands with `pnpm` via `corepack enable`. Added `pnpm-lock.yaml` copy for deterministic builds. |
| `.husky/pre-commit` | `npm run lint:fix` → `pnpm run lint:fix` |
| `package.json` | Added cleanup scripts: `clean`, `clean:frontend`, `clean:backend`, `clean:all`, `reinstall` |
| `.gitignore` | Added `pnpm-debug.log*` |
| `backend/scraper.py` | Added reservation header: "Reserved for later implementation" |

### Created

| File | Purpose |
|------|---------|
| `backend/.dockerignore` | Excludes `__pycache__`, `.pytest_cache`, `.env`, `tests`, `scraper.py` from Docker build context |
| `frontend/.dockerignore` | Excludes `node_modules`, `dist`, `.vite`, `.env` from Docker build context |

---

## Cleanup Scripts Added

```
pnpm clean            # Remove frontend + backend build artifacts
pnpm clean:frontend   # rm -rf node_modules dist .vite (in frontend/)
pnpm clean:backend    # rm -rf __pycache__ .pytest_cache .ruff_cache etc. (in backend/)
pnpm clean:all        # clean + rm root node_modules
pnpm reinstall        # clean:all + pnpm install + poetry install
```

---

## Verification Checklist

- [ ] `pnpm install` works from root
- [ ] `pnpm run clean` removes artifacts
- [ ] `git commit` triggers `pnpm run lint:fix` (not npm)
- [ ] Push to main → Railway frontend deploy succeeds with new Dockerfile
- [ ] `grep -r "npm " *.json *.toml *.sh Dockerfile` returns no hits in project config files

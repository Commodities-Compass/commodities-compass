# User Story: Major Dependency Upgrades

**Date:** 2026-04-01
**Priority:** P1 (before next feature sprint)
**Risk:** Medium — each major bump may require code changes
**Strategy:** One batch per stack (backend, frontend), test thoroughly, deploy separately

---

## Backend — Python

### Tier 1: High priority (security, EOL, or actively blocking)

| Package | Current | Target | Impact | Migration effort |
|---------|---------|--------|--------|-----------------|
| **openai** | 1.109 | **2.x** | All 4 agents + daily-analysis use it. v2 rewrites client init, streaming, and tool use APIs. | 1-2d — update all `openai.OpenAI()` calls, response parsing, streaming patterns |
| **anthropic** | 0.45 | **0.87** | Press review agent (Claude provider). SDK changes in message API. | 0.5d — update `anthropic.Anthropic()` calls in `llm_client.py` |
| **fastapi** | 0.110 | **0.135** | Main app. Tied to starlette upgrade. Deprecation warnings likely. | 0.5d — update `fastapi` + `starlette` together, check middleware changes |
| **ruff** | 0.3 | **0.15** | Linter/formatter. Calver — usually safe but new rules may flag code. | 0.5d — update, run `ruff check --fix`, review new warnings |

### Tier 2: Medium priority (performance, ecosystem alignment)

| Package | Current | Target | Impact | Migration effort |
|---------|---------|--------|--------|-----------------|
| **numpy** | 1.26 | **2.x** | Engine computation (`app/engine/`). v2 removes deprecated aliases, changes default dtypes. | 1d — run engine tests, fix any `np.float_` → `np.float64` etc. |
| **pandas** | 2.3 | **3.x** | ICE stocks scraper (XLS parsing). v3 removes deprecated `.append()`, changes copy behavior. | 0.5d — small usage, test XLS parsing |
| **httpx** | 0.26 | **0.28** | Used by scrapers + LLM clients. Minor API changes in transport/auth. | 0.5d — test all HTTP calls |
| **pytest** | 8.x | **9.x** | Test framework. Usually smooth, may deprecate some fixtures. | 0.5d — run tests, fix any deprecation |
| **pytest-asyncio** | 0.23 | **1.x** | Async test support. Major rewrite of fixture scoping. | 0.5d — update `asyncio_mode` config, check fixture lifecycle |
| **pre-commit** | 3.x | **4.x** | Git hooks. Usually smooth upgrade. | 0.25d |

### Tier 3: Low priority (nice to have, no urgency)

| Package | Current | Target | Notes |
|---------|---------|--------|-------|
| google-genai | 1.2 | 1.70 | Only used for Gemini testing (not production). Update when needed. |
| cffi | 1.17 | 2.0 | Transitive dep. Will come with cryptography update. |
| protobuf | 5.x | 7.x | Transitive dep of google-api-*. Update with google SDK. |

### Recommended order (backend)

```
1. ruff 0.3 → 0.15         (dev tool, zero runtime risk)
2. pytest + pytest-asyncio  (dev tool, verify tests still pass)
3. fastapi + starlette      (core app, test all endpoints)
4. openai 1.x → 2.x        (all agents, test each agent dry-run)
5. anthropic 0.45 → 0.87   (press-review only, small surface)
6. numpy 1.x → 2.x         (engine, run compute-indicators --dry-run)
7. pandas 2.x → 3.x        (ICE scraper, test XLS parsing)
8. httpx 0.26 → 0.28       (all HTTP clients)
```

---

## Frontend — React/TypeScript

### Tier 1: High priority

| Package | Current | Target | Impact | Migration effort |
|---------|---------|--------|--------|-----------------|
| **tailwindcss** | 3.4 | **4.x** | Entire UI. v4 rewrites config from `tailwind.config.js` to CSS-first `@theme`. | 2-3d — config migration, check all utility classes |
| **vite** | 6.4 | **8.x** | Build tool. Major config changes, plugin API updates. | 1d — update config, test build + dev server |
| **recharts** | 2.15 | **3.x** | PriceChart component. API changes in chart components. | 1d — rewrite chart props, test rendering |
| **typescript** | 5.7 | **6.x** | Type system. New strictness rules, may surface new type errors. | 0.5d — `tsc --noEmit`, fix errors |

### Tier 2: Medium priority

| Package | Current | Target | Impact | Migration effort |
|---------|---------|--------|--------|-----------------|
| **eslint** | 9.x | **10.x** | Linter. Flat config changes. | 0.5d |
| **date-fns** | 3.6 | **4.x** | Date formatting. API changes in function signatures. | 0.5d |
| **lucide-react** | 0.477 | **1.x** | Icons. Import path changes. | 0.5d — search-replace imports |
| **vitest** | 3.x | **4.x** | Test framework. Usually smooth. | 0.25d |
| **@vitejs/plugin-react** | 4.x | **6.x** | Vite plugin. Tied to vite version. | Update with vite |

### Tier 3: Low priority

| Package | Current | Target | Notes |
|---------|---------|--------|-------|
| jsdom | 25 | 29 | Dev dep. Update with vitest. |
| globals | 15 | 17 | Dev dep. Update with eslint. |
| @types/node | 22 | 25 | Dev dep. Types only, no runtime impact. |
| eslint-plugin-react-hooks | 5 | 7 | Update with eslint. |
| @eslint/js | 9 | 10 | Update with eslint. |

### Recommended order (frontend)

```
1. typescript 5 → 6          (types only, no runtime risk)
2. eslint 9 → 10 + plugins   (dev tool, zero runtime risk)
3. vite 6 → 8 + plugin-react (build tool, test dev + prod build)
4. vitest 3 → 4 + jsdom      (dev tool, run test suite)
5. tailwindcss 3 → 4         (biggest migration — UI-wide impact)
6. recharts 2 → 3            (single component, isolated)
7. date-fns 3 → 4            (small usage, search-replace)
8. lucide-react 0.x → 1.x   (icons, search-replace imports)
```

---

## Execution plan

| Sprint | Scope | Effort | Risk |
|--------|-------|--------|------|
| **Sprint A** | Backend dev tools (ruff, pytest, pre-commit) | 1d | Low |
| **Sprint B** | Backend core (fastapi, openai, anthropic) | 2-3d | Medium |
| **Sprint C** | Backend data (numpy, pandas, httpx) | 1-2d | Low |
| **Sprint D** | Frontend dev tools (typescript, eslint, vite, vitest) | 1-2d | Low |
| **Sprint E** | Frontend UI (tailwindcss, recharts, date-fns, lucide) | 3-4d | Medium |

**Total estimate:** 8-12d across 5 sprints. Can be interleaved with feature work.

## Acceptance criteria

- [ ] All 198 backend tests pass after each sprint
- [ ] Frontend builds + type-checks after each sprint
- [ ] All scraper/agent `--dry-run` pass after Sprint B/C
- [ ] Dashboard renders correctly after Sprint E
- [ ] No deprecation warnings in CI logs
- [ ] `poetry show --outdated` and `pnpm outdated` show zero items (except intentionally pinned)

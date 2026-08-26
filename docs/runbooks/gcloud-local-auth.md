# gcloud Local Auth — Reauthentication Policy

## When to use this runbook

Use it when `gcloud` on a developer machine suddenly demands a password again —
typically mid-task, and always at the worst moment. Symptoms:

- `gcloud` commands fail with a credentials refresh error
- Terraform fails on the GCS backend (ADC hits the same wall)
- The prompt appears roughly once a day, even though nothing was revoked

This is **not** an expired refresh token. It is a Workspace policy.

## Diagnosis

`gcloud` writes a dated log for every command. The real error is in there:

```bash
cd ~/.config/gcloud/logs
grep -rhoiE "ReauthRequiredError|Reauthentication failed" . | sort | uniq -c
```

A hit on `ReauthRequiredError: reauth is required.` confirms the cause: the
**Google Cloud session control** policy of the Workspace domain, which governs
reauthentication for both the Cloud Console and the `gcloud` CLI.

Cross-check the credential store — the refresh token is intact, only the
reauth proof token (`rapt_token`) is missing:

```bash
python3 - <<'PY'
import sqlite3, json, os
p = os.path.expanduser("~/.config/gcloud/credentials.db")
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
for acct, val in con.execute("select account_id, value from credentials"):
    d = json.loads(val)
    print(acct, "refresh_token:", bool(d.get("refresh_token")),
                "rapt_token:", bool(d.get("rapt_token")))
PY
```

To date the occurrences (the log filename is the command's local timestamp):

```bash
grep -rl "ReauthRequiredError" ~/.config/gcloud/logs | sort | tail -15
```

## Current setting (2026-08-26)

**Admin console → Security → Access and data control → Google Cloud session
control**, applied at the root OU `commodities compass`:

| Field | Value |
| --- | --- |
| Reauthentication policy | **Never require reauthentication** |
| Applied at | root OU (`commodities compass`) — covers every current and future user |

Before this change the policy was `Require reauthentication` at the 16-hour
default, which fired ~daily (observed 2026-08-14 → 2026-08-26, 37 commands hit).

### Why "Never" and not a longer window

The UI caps the custom frequency at **24 hours** — there is no 7-day tier. So
the choice is binary: challenged at least once a day, or never. A daily
interactive password prompt is incompatible with operating the pipeline
remotely (phone, Remote Control, no keyboard), which is the whole point.

### What was accepted in exchange

A stolen **unlocked** Mac keeps indefinite `gcloud` access to `cacaooo`,
production included. Reauth was the last net behind FileVault and the screen
lock. Mitigations that must stay in place:

- FileVault on, short screen-lock delay
- **Move unattended ops off the personal credential onto a scoped service
  account** — the personal account sits close to Workspace admin rights.
  Still open as of 2026-08-26.

## Applying the change

1. **admin.google.com** as a super-admin of the domain (check the browser
   profile — with several Google accounts the page loads but the setting is
   greyed out).
2. Security → Access and data control → Google Cloud session control.
3. Select **Never require reauthentication** → Save. If Save is refused, reset
   the frequency dropdown to a preset first: leaving it on `Custom` with an
   empty Hours field raises a validation error that blocks the form.
4. Propagation is usually a few minutes. Prior changes are visible in the
   Workspace **Audit log**.

No re-login is needed: an existing credential picks up the new policy on its
next token refresh.

## Verification

`CLOUDSDK_CORE_DISABLE_PROMPTS=1` makes gcloud fail instead of hanging on an
interactive prompt — always use it when verifying from a script or an agent.

```bash
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
gcloud auth print-access-token >/dev/null && echo "user credential OK"
gcloud run jobs list --region=europe-west9 --project=cacaooo --limit=5 --format="value(name)"
gcloud auth application-default print-access-token >/dev/null && echo "ADC OK"
```

Never print the token itself. To prove a **real** refresh happened rather than
a cache hit, check that the stored expiry is ~60 minutes out:

```bash
python3 - <<'PY'
import sqlite3, os, datetime
p = os.path.expanduser("~/.config/gcloud/access_tokens.db")
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
cols = [c[1] for c in con.execute("PRAGMA table_info(access_tokens)")]
for row in con.execute(f"select {','.join(cols)} from access_tokens"):
    d = dict(zip(cols, row))
    if "@" in str(d.get("account_id")):
        print(d["account_id"], "expires:", d.get("token_expiry"), "(UTC)")
PY
```

Verified 2026-08-26: token refreshed live against the token endpoint (the exact
call that previously raised `ReauthRequiredError`), Cloud Run Jobs listed, ADC
valid.

## Reverting

Same page, select `Require reauthentication` and set a frequency. Revert when:

- a second user joins the Workspace — the policy is set at the root OU and they
  would inherit "never"
- unattended ops have moved to a service account, making the human credential's
  lifetime irrelevant

## Related

- [db-sync-from-gcp.md](db-sync-from-gcp.md) — needs a live ADC
- [../../.claude/rules/migrations-prod-via-main-only.md](../../.claude/rules/migrations-prod-via-main-only.md) — what is and isn't allowed against the prod DB

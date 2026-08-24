"""Backfill every existing Auth0 login onto a full-access ``internal`` account.

This is the **mandatory prerequisite** to flipping ``ENTITLEMENTS_ENFORCED`` on
(rollout §10 of docs/architecture/entitlement-and-tenancy-for-USERS.md).

Why it is mandatory: ``resolve_principal`` joins ``tenant_user`` → ``tenant_account``
and, finding no row, returns an EMPTY entitlement set (default-deny, decision #5).
So on the day the flag flips, any Auth0 login without a seat gets a blank dashboard
— including yours. The ``internal`` tier is the grandfather marker: it resolves
read-time to the COMPLETE catalogue, so a seeded login keeps exactly what it sees
today in dark mode, and automatically gains any key added later.

Usage::

    poetry run seed-internal-tenants --sub "auth0|abc" --sub "auth0|def" --dry-run
    poetry run seed-internal-tenants --from-file subs.txt
    poetry run seed-internal-tenants --sub "auth0|abc" --code internal

``--from-file`` takes one entry per line, ``sub`` or ``sub,email``; blank lines and
``#`` comments are ignored. Get the ``sub`` values from the Auth0 dashboard
(Users → the ``user_id`` column, e.g. ``auth0|68f3c…``, ``google-oauth2|1234…``).

Idempotent: re-running skips logins that already hold a seat, so it is safe to run
again after adding a user. Append-only, like the rest of the tenant CLI — it never
UPDATEs or DELETEs a grant.

Writes via ``DATABASE_SYNC_URL`` (scripts.db.get_session): localhost:5433 locally,
Cloud SQL against prod — same posture as the other ops CLIs.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import func, select

from app.core.entitlements import INTERNAL, expand_tier, max_seats_for
from app.models.tenant import TenantAccount, TenantUser
from scripts.db import get_session
from scripts.tenant_admin import _append_grant

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

DEFAULT_CODE = "internal"
DEFAULT_NAME = "Compass CC — internal"


@dataclass(frozen=True)
class SeatEntry:
    """One Auth0 identity to seat. Immutable — parsed once, never mutated."""

    auth0_sub: str
    email: str | None = None


def _parse_sub(raw: str, origin: str) -> SeatEntry:
    """Parse ``sub`` or ``sub,email`` — fail loud on anything that isn't a sub.

    A typo'd sub is the worst possible failure here: it writes a seat nobody owns
    while the real login stays unseeded, and the damage only shows up as a blank
    dashboard on flip day. So validate rather than trust.
    """
    parts = [p.strip() for p in raw.split(",")]
    sub = parts[0]
    email = parts[1] if len(parts) > 1 and parts[1] else None
    if len(parts) > 2:
        raise SystemExit(f"{origin}: expected 'sub' or 'sub,email', got {raw!r}")
    if "|" not in sub:
        raise SystemExit(
            f"{origin}: {sub!r} does not look like an Auth0 sub "
            "(expected a connection prefix, e.g. 'auth0|68f3c…')"
        )
    return SeatEntry(auth0_sub=sub, email=email)


def _read_file(path: Path) -> list[SeatEntry]:
    if not path.is_file():
        raise SystemExit(f"--from-file: no such file {path}")
    entries: list[SeatEntry] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            entries.append(_parse_sub(stripped, f"{path}:{lineno}"))
    return entries


def _collect(args: argparse.Namespace) -> list[SeatEntry]:
    """Merge --sub and --from-file, de-duplicated, first occurrence wins."""
    entries = [_parse_sub(s, "--sub") for s in (args.sub or [])]
    if args.from_file:
        entries.extend(_read_file(Path(args.from_file)))
    if not entries:
        raise SystemExit("Nothing to seed: pass --sub and/or --from-file.")

    seen: dict[str, SeatEntry] = {}
    for entry in entries:
        seen.setdefault(entry.auth0_sub, entry)
    return list(seen.values())


def _lookup_account(session, code: str) -> TenantAccount | None:
    """Find the account by code, refusing to repurpose a non-internal one."""
    account = session.execute(
        select(TenantAccount).where(TenantAccount.code == code)
    ).scalar_one_or_none()
    if account is not None and account.tier != INTERNAL:
        raise SystemExit(
            f"tenant_account {code!r} exists but its tier is {account.tier!r}, "
            f"not {INTERNAL!r}. Refusing to repurpose a client account — "
            "pass a different --code."
        )
    return account


def _create_account(session, code: str, name: str) -> TenantAccount:
    account = TenantAccount(
        code=code,
        name=name,
        tier=INTERNAL,
        locale="fr",
        max_seats=max_seats_for(INTERNAL),
    )
    session.add(account)
    session.flush()
    # The runtime short-circuits on tier == INTERNAL and never reads these rows,
    # but create-tenant writes them for provenance — keep the two paths identical.
    for key in sorted(expand_tier(INTERNAL)):
        _append_grant(session, account.id, key, active=True)
    return account


@dataclass(frozen=True)
class SeedOutcome:
    """What the run did (or would do). Immutable result object."""

    account_created: bool
    seated: int
    already_here: int
    elsewhere: int
    active_seats: int = 0


def _find_seat(session, sub: str) -> TenantUser | None:
    """Return the existing seat row for ``sub``, if any."""
    return session.execute(
        select(TenantUser).where(TenantUser.auth0_sub == sub)
    ).scalar_one_or_none()


def _report(session, code: str, entries: list[SeatEntry]) -> SeedOutcome:
    """--dry-run: say what would happen, write nothing. The pre-flip readiness check."""
    account = _lookup_account(session, code)
    account_id = account.id if account is not None else None
    if account is None:
        logger.info("Account %r: would be created.", code)

    seated = already_here = elsewhere = 0
    for entry in entries:
        existing = _find_seat(session, entry.auth0_sub)
        if existing is None:
            seated += 1
            logger.info("  + %s would be seated.", entry.auth0_sub)
        elif account_id is not None and existing.account_id == account_id:
            already_here += 1
            logger.info("  = %s already seated here — skipped.", entry.auth0_sub)
        else:
            elsewhere += 1
            logger.warning(
                "  ! %s already seated on account_id=%s — would be left untouched.",
                entry.auth0_sub,
                existing.account_id,
            )
    return SeedOutcome(account is None, seated, already_here, elsewhere)


def _apply(session, code: str, name: str, entries: list[SeatEntry]) -> SeedOutcome:
    """Create-or-reuse the internal account and seat every unseated login."""
    account = _lookup_account(session, code)
    created = account is None
    if account is None:
        account = _create_account(session, code, name)
        logger.info("Account %r created.", code)

    seated = already_here = elsewhere = 0
    for entry in entries:
        existing = _find_seat(session, entry.auth0_sub)
        if existing is not None:
            if existing.account_id == account.id:
                already_here += 1
                logger.info("  = %s already seated here — skipped.", entry.auth0_sub)
            else:
                elsewhere += 1
                logger.warning(
                    "  ! %s already seated on account_id=%s — left untouched "
                    "(a provisioned client keeps its own tier).",
                    entry.auth0_sub,
                    existing.account_id,
                )
            continue

        session.add(
            TenantUser(
                account_id=account.id,
                auth0_sub=entry.auth0_sub,
                email=entry.email,
                role="viewer",
            )
        )
        seated += 1
        logger.info("  + %s seated.", entry.auth0_sub)

    session.flush()
    active_seats = session.execute(
        select(func.count())
        .select_from(TenantUser)
        .where(TenantUser.account_id == account.id, TenantUser.is_active.is_(True))
    ).scalar_one()
    return SeedOutcome(created, seated, already_here, elsewhere, active_seats)


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Seat existing Auth0 logins on a full-access 'internal' account "
            "(prerequisite to flipping ENTITLEMENTS_ENFORCED)."
        )
    )
    p.add_argument(
        "--sub",
        action="append",
        metavar="AUTH0_SUB",
        help="Auth0 sub to seat, repeatable. Optionally 'sub,email'.",
    )
    p.add_argument(
        "--from-file",
        default=None,
        metavar="PATH",
        help="File of 'sub' or 'sub,email' lines ('#' comments allowed).",
    )
    p.add_argument("--code", default=DEFAULT_CODE, help="tenant_account.code")
    p.add_argument("--name", default=DEFAULT_NAME, help="tenant_account.name")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report per-sub what WOULD happen. Also the pre-flip readiness check.",
    )
    args = p.parse_args()

    entries = _collect(args)
    logger.info(
        "Seeding %d Auth0 login(s) onto account %r (tier=%s)%s",
        len(entries),
        args.code,
        INTERNAL,
        " [DRY RUN]" if args.dry_run else "",
    )

    with get_session() as session:
        outcome = (
            _report(session, args.code, entries)
            if args.dry_run
            else _apply(session, args.code, args.name, entries)
        )

    verb = "would be seated" if args.dry_run else "seated"
    logger.info(
        "Done: %d %s, %d already here, %d on another account.",
        outcome.seated,
        verb,
        outcome.already_here,
        outcome.elsewhere,
    )
    if not args.dry_run:
        logger.info(
            "Account %r now holds %d active seat(s), each resolving to the FULL "
            "catalogue. ENTITLEMENTS_ENFORCED can be flipped once every live login "
            "appears above (re-run with --dry-run to re-check).",
            args.code,
            outcome.active_seats,
        )
    if outcome.elsewhere:
        logger.warning(
            "%d login(s) are seated elsewhere — verify their tier grants what they "
            "should see BEFORE flipping, they will not get the internal catalogue.",
            outcome.elsewhere,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

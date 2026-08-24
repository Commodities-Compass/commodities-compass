"""Tests for the ENTITLEMENTS_ENFORCED backfill CLI.

Unit: sub parsing / file parsing / de-duplication (pure, fail-loud on a typo).
Integration: account creation, seating, idempotence, dry-run writes nothing,
and the two refusals — never repurpose a client account, never move a login
that already belongs to one.

The "a seeded internal login resolves to the full catalogue" property is already
covered by ``test_entitlements.py::test_internal_tier_is_full_catalogue`` and its
integration counterpart; not duplicated here.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.entitlements import INTERNAL
from app.models.tenant import TenantAccount, TenantUser
from scripts import seed_internal_tenants as seeder

SUB_A = "auth0|aaaa1111"
SUB_B = "google-oauth2|bbbb2222"


def _run_cli(monkeypatch, session: Session, argv: list[str]) -> int:
    @contextmanager
    def _fake_session(url=None):
        yield session  # test transaction owns rollback — the CLI commit is a no-op

    monkeypatch.setattr(seeder, "get_session", _fake_session)
    monkeypatch.setattr(sys, "argv", ["seed-internal-tenants", *argv])
    return seeder.main()


def _account(session: Session, code: str) -> TenantAccount | None:
    return session.execute(
        select(TenantAccount).where(TenantAccount.code == code)
    ).scalar_one_or_none()


def _seats(session: Session, account_id) -> list[TenantUser]:
    return list(
        session.execute(
            select(TenantUser).where(TenantUser.account_id == account_id)
        ).scalars()
    )


# --------------------------------------------------------------------------- #
# Unit — parsing (a typo'd sub must never become a silent blank dashboard)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_parse_sub_accepts_bare_sub_and_sub_with_email() -> None:
    assert seeder._parse_sub(SUB_A, "--sub") == seeder.SeatEntry(SUB_A, None)
    assert seeder._parse_sub(f"{SUB_A},x@acme.com", "--sub") == seeder.SeatEntry(
        SUB_A, "x@acme.com"
    )


@pytest.mark.unit
def test_parse_sub_rejects_something_that_is_not_a_sub() -> None:
    with pytest.raises(SystemExit, match="does not look like an Auth0 sub"):
        seeder._parse_sub("x@acme.com", "--sub")


@pytest.mark.unit
def test_parse_sub_rejects_extra_fields() -> None:
    with pytest.raises(SystemExit, match="expected 'sub' or 'sub,email'"):
        seeder._parse_sub(f"{SUB_A},a@b.c,extra", "--sub")


@pytest.mark.unit
def test_read_file_skips_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "subs.txt"
    path.write_text(
        f"# staff\n\n{SUB_A},a@acme.com\n  \n{SUB_B}  # trailing comment\n",
        encoding="utf-8",
    )
    assert seeder._read_file(path) == [
        seeder.SeatEntry(SUB_A, "a@acme.com"),
        seeder.SeatEntry(SUB_B, None),
    ]


@pytest.mark.unit
def test_read_file_missing_file_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no such file"):
        seeder._read_file(tmp_path / "nope.txt")


@pytest.mark.unit
def test_collect_dedupes_first_occurrence_wins(tmp_path: Path) -> None:
    path = tmp_path / "subs.txt"
    path.write_text(f"{SUB_A},from-file@acme.com\n", encoding="utf-8")

    collected = seeder._collect(
        argparse.Namespace(
            sub=[f"{SUB_A},from-flag@acme.com", SUB_B], from_file=str(path)
        )
    )
    assert collected == [
        seeder.SeatEntry(SUB_A, "from-flag@acme.com"),
        seeder.SeatEntry(SUB_B, None),
    ]


@pytest.mark.unit
def test_collect_requires_at_least_one_source() -> None:
    with pytest.raises(SystemExit, match="Nothing to seed"):
        seeder._collect(argparse.Namespace(sub=None, from_file=None))


# --------------------------------------------------------------------------- #
# Integration — the backfill itself
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_creates_internal_account_and_seats_logins(
    monkeypatch, sync_db_session: Session
) -> None:
    rc = _run_cli(
        monkeypatch,
        sync_db_session,
        ["--code", "internal-t1", "--sub", SUB_A, "--sub", f"{SUB_B},b@acme.com"],
    )
    assert rc == 0

    account = _account(sync_db_session, "internal-t1")
    assert account is not None
    assert account.tier == INTERNAL

    seats = _seats(sync_db_session, account.id)
    assert {s.auth0_sub for s in seats} == {SUB_A, SUB_B}
    assert {s.email for s in seats} == {None, "b@acme.com"}


@pytest.mark.integration
def test_rerun_is_idempotent(monkeypatch, sync_db_session: Session) -> None:
    argv = ["--code", "internal-t2", "--sub", SUB_A]
    assert _run_cli(monkeypatch, sync_db_session, argv) == 0
    assert _run_cli(monkeypatch, sync_db_session, argv) == 0

    account = _account(sync_db_session, "internal-t2")
    assert account is not None
    assert len(_seats(sync_db_session, account.id)) == 1


@pytest.mark.integration
def test_dry_run_writes_nothing(monkeypatch, sync_db_session: Session) -> None:
    rc = _run_cli(
        monkeypatch,
        sync_db_session,
        ["--code", "internal-t3", "--sub", SUB_A, "--dry-run"],
    )
    assert rc == 0
    assert _account(sync_db_session, "internal-t3") is None
    assert (
        sync_db_session.execute(
            select(TenantUser).where(TenantUser.auth0_sub == SUB_A)
        ).scalar_one_or_none()
        is None
    )


@pytest.mark.integration
def test_refuses_to_repurpose_a_client_account(
    monkeypatch, sync_db_session: Session
) -> None:
    sync_db_session.add(
        TenantAccount(
            code="acme-t4",
            name="Acme",
            tier="export_premium",
            locale="fr",
            max_seats=3,
        )
    )
    sync_db_session.flush()

    with pytest.raises(SystemExit, match="Refusing to repurpose"):
        _run_cli(monkeypatch, sync_db_session, ["--code", "acme-t4", "--sub", SUB_A])


@pytest.mark.integration
def test_login_already_seated_elsewhere_is_left_untouched(
    monkeypatch, sync_db_session: Session
) -> None:
    client_account = TenantAccount(
        code="acme-t5", name="Acme", tier="export_premium", locale="fr", max_seats=3
    )
    sync_db_session.add(client_account)
    sync_db_session.flush()
    sync_db_session.add(
        TenantUser(account_id=client_account.id, auth0_sub=SUB_A, role="viewer")
    )
    sync_db_session.flush()

    assert (
        _run_cli(
            monkeypatch,
            sync_db_session,
            ["--code", "internal-t5", "--sub", SUB_A, "--sub", SUB_B],
        )
        == 0
    )

    # SUB_A keeps its real tier; only SUB_B lands on the internal account.
    seat_a = sync_db_session.execute(
        select(TenantUser).where(TenantUser.auth0_sub == SUB_A)
    ).scalar_one()
    assert seat_a.account_id == client_account.id

    internal = _account(sync_db_session, "internal-t5")
    assert internal is not None
    assert {s.auth0_sub for s in _seats(sync_db_session, internal.id)} == {SUB_B}

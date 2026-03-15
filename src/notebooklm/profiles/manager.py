"""Profile CRUD and auth snapshot persistence for the local SQLite cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from notebooklm.local.schema import APP_STATE_SINGLETON_KEY


_UNSET = object()


def _utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(path: str | Path) -> str:
    """Persist local profile paths in normalized absolute form."""
    return str(Path(path).expanduser().resolve())


@dataclass(frozen=True)
class ProfileRecord:
    """Persisted profile row."""

    profile_id: str
    display_name: str
    account_email: str | None
    is_default: bool
    storage_state_path: Path
    browser_profile_path: Path
    created_at: str
    updated_at: str
    approval_policy_json: str | None
    last_login_at: str | None


@dataclass(frozen=True)
class AuthSnapshotRecord:
    """Persisted auth snapshot for a profile."""

    profile_id: str
    cookie_fingerprint: str
    csrf_token: str
    session_id: str
    build_label: str
    captured_at: str
    validated_at: str | None
    status: str
    source: str


class ProfileManager:
    """CRUD and switching operations backed by the local SQLite cache."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: str | Path | None = None) -> "ProfileManager":
        """Open a migration-ready local DB and return a profile manager for it."""
        from notebooklm.local.db import connect_db

        return cls(connect_db(path))

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    def list_profiles(self) -> list[ProfileRecord]:
        """List profiles with the default profile first."""
        rows = self._connection.execute(
            """
            SELECT
                profile_id,
                display_name,
                account_email,
                is_default,
                storage_state_path,
                browser_profile_path,
                created_at,
                updated_at,
                approval_policy_json,
                last_login_at
            FROM profiles
            ORDER BY is_default DESC, created_at ASC, profile_id ASC
            """
        ).fetchall()
        return [self._row_to_profile(row) for row in rows]

    def get_profile(self, profile_id: str) -> ProfileRecord | None:
        """Fetch a single profile row by identifier."""
        row = self._connection.execute(
            """
            SELECT
                profile_id,
                display_name,
                account_email,
                is_default,
                storage_state_path,
                browser_profile_path,
                created_at,
                updated_at,
                approval_policy_json,
                last_login_at
            FROM profiles
            WHERE profile_id = ?
            """,
            (profile_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_profile(row)

    def create_profile(
        self,
        *,
        profile_id: str,
        display_name: str,
        storage_state_path: str | Path,
        browser_profile_path: str | Path,
        account_email: str | None = None,
        is_default: bool | None = None,
        approval_policy_json: str | None = None,
        last_login_at: str | None = None,
    ) -> ProfileRecord:
        """Create a profile row and optionally make it the default/active profile."""
        existing_count = self._connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        default_value = is_default if is_default is not None else existing_count == 0
        created_at = _utc_now()

        with self._connection:
            if default_value:
                self._clear_default_profile()

            self._connection.execute(
                """
                INSERT INTO profiles (
                    profile_id,
                    display_name,
                    account_email,
                    is_default,
                    storage_state_path,
                    browser_profile_path,
                    created_at,
                    updated_at,
                    approval_policy_json,
                    last_login_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    display_name,
                    account_email,
                    int(default_value),
                    _normalize_path(storage_state_path),
                    _normalize_path(browser_profile_path),
                    created_at,
                    created_at,
                    approval_policy_json,
                    last_login_at,
                ),
            )

            if self.get_active_profile() is None:
                self._set_active_profile(profile_id)

        return self.require_profile(profile_id)

    def update_profile(
        self,
        profile_id: str,
        *,
        display_name: str | object = _UNSET,
        account_email: str | None | object = _UNSET,
        is_default: bool | object = _UNSET,
        storage_state_path: str | Path | object = _UNSET,
        browser_profile_path: str | Path | object = _UNSET,
        approval_policy_json: str | None | object = _UNSET,
        last_login_at: str | None | object = _UNSET,
    ) -> ProfileRecord:
        """Update mutable profile fields and return the refreshed row."""
        current = self.require_profile(profile_id)
        assignments: list[str] = []
        params: list[object] = []

        if display_name is not _UNSET:
            assignments.append("display_name = ?")
            params.append(display_name)
        if account_email is not _UNSET:
            assignments.append("account_email = ?")
            params.append(account_email)
        if storage_state_path is not _UNSET:
            assignments.append("storage_state_path = ?")
            params.append(_normalize_path(storage_state_path))
        if browser_profile_path is not _UNSET:
            assignments.append("browser_profile_path = ?")
            params.append(_normalize_path(browser_profile_path))
        if approval_policy_json is not _UNSET:
            assignments.append("approval_policy_json = ?")
            params.append(approval_policy_json)
        if last_login_at is not _UNSET:
            assignments.append("last_login_at = ?")
            params.append(last_login_at)

        with self._connection:
            if is_default is True and not current.is_default:
                self._clear_default_profile()
                assignments.append("is_default = 1")
            elif is_default is False and current.is_default:
                assignments.append("is_default = 0")

            assignments.append("updated_at = ?")
            params.append(_utc_now())
            params.append(profile_id)

            self._connection.execute(
                f"UPDATE profiles SET {', '.join(assignments)} WHERE profile_id = ?",
                params,
            )

        return self.require_profile(profile_id)

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a profile row and any cascading auth snapshot state."""
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM profiles WHERE profile_id = ?",
                (profile_id,),
            )
        return cursor.rowcount > 0

    def switch_profile(self, profile_id: str) -> ProfileRecord:
        """Make the requested profile active in app_state."""
        profile = self.require_profile(profile_id)
        with self._connection:
            self._set_active_profile(profile.profile_id)
        return profile

    def get_active_profile(self) -> ProfileRecord | None:
        """Return the active profile from app_state, if one is set."""
        row = self._connection.execute(
            """
            SELECT
                p.profile_id,
                p.display_name,
                p.account_email,
                p.is_default,
                p.storage_state_path,
                p.browser_profile_path,
                p.created_at,
                p.updated_at,
                p.approval_policy_json,
                p.last_login_at
            FROM app_state AS app
            LEFT JOIN profiles AS p
                ON p.profile_id = app.active_profile_id
            WHERE app.singleton_key = ?
            """,
            (APP_STATE_SINGLETON_KEY,),
        ).fetchone()
        if row is None or row["profile_id"] is None:
            return None
        return self._row_to_profile(row)

    def upsert_auth_snapshot(
        self,
        profile_id: str,
        *,
        cookie_fingerprint: str,
        csrf_token: str,
        session_id: str,
        build_label: str,
        captured_at: str | None = None,
        validated_at: str | None = None,
        status: str = "valid",
        source: str = "login",
    ) -> AuthSnapshotRecord:
        """Insert or replace the auth snapshot for a profile."""
        self.require_profile(profile_id)
        snapshot_captured_at = captured_at or _utc_now()

        with self._connection:
            self._connection.execute(
                """
                INSERT INTO auth_snapshots (
                    profile_id,
                    cookie_fingerprint,
                    csrf_token,
                    session_id,
                    build_label,
                    captured_at,
                    validated_at,
                    status,
                    source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    cookie_fingerprint = excluded.cookie_fingerprint,
                    csrf_token = excluded.csrf_token,
                    session_id = excluded.session_id,
                    build_label = excluded.build_label,
                    captured_at = excluded.captured_at,
                    validated_at = excluded.validated_at,
                    status = excluded.status,
                    source = excluded.source
                """,
                (
                    profile_id,
                    cookie_fingerprint,
                    csrf_token,
                    session_id,
                    build_label,
                    snapshot_captured_at,
                    validated_at,
                    status,
                    source,
                ),
            )

        return self.require_auth_snapshot(profile_id)

    def get_auth_snapshot(self, profile_id: str) -> AuthSnapshotRecord | None:
        """Fetch the persisted auth snapshot for a profile."""
        row = self._connection.execute(
            """
            SELECT
                profile_id,
                cookie_fingerprint,
                csrf_token,
                session_id,
                build_label,
                captured_at,
                validated_at,
                status,
                source
            FROM auth_snapshots
            WHERE profile_id = ?
            """,
            (profile_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_auth_snapshot(row)

    def delete_auth_snapshot(self, profile_id: str) -> bool:
        """Delete a persisted auth snapshot by profile id."""
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM auth_snapshots WHERE profile_id = ?",
                (profile_id,),
            )
        return cursor.rowcount > 0

    def require_profile(self, profile_id: str) -> ProfileRecord:
        """Return a profile or raise KeyError if it does not exist."""
        profile = self.get_profile(profile_id)
        if profile is None:
            raise KeyError(f"Unknown profile: {profile_id}")
        return profile

    def require_auth_snapshot(self, profile_id: str) -> AuthSnapshotRecord:
        """Return a snapshot or raise KeyError if it does not exist."""
        snapshot = self.get_auth_snapshot(profile_id)
        if snapshot is None:
            raise KeyError(f"Unknown auth snapshot for profile: {profile_id}")
        return snapshot

    def _clear_default_profile(self) -> None:
        self._connection.execute("UPDATE profiles SET is_default = 0 WHERE is_default = 1")

    def _set_active_profile(self, profile_id: str) -> None:
        self._connection.execute(
            """
            UPDATE app_state
            SET active_profile_id = ?
            WHERE singleton_key = ?
            """,
            (profile_id, APP_STATE_SINGLETON_KEY),
        )

    @staticmethod
    def _row_to_profile(row: sqlite3.Row) -> ProfileRecord:
        return ProfileRecord(
            profile_id=row["profile_id"],
            display_name=row["display_name"],
            account_email=row["account_email"],
            is_default=bool(row["is_default"]),
            storage_state_path=Path(row["storage_state_path"]),
            browser_profile_path=Path(row["browser_profile_path"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            approval_policy_json=row["approval_policy_json"],
            last_login_at=row["last_login_at"],
        )

    @staticmethod
    def _row_to_auth_snapshot(row: sqlite3.Row) -> AuthSnapshotRecord:
        return AuthSnapshotRecord(
            profile_id=row["profile_id"],
            cookie_fingerprint=row["cookie_fingerprint"],
            csrf_token=row["csrf_token"],
            session_id=row["session_id"],
            build_label=row["build_label"],
            captured_at=row["captured_at"],
            validated_at=row["validated_at"],
            status=row["status"],
            source=row["source"],
        )


__all__ = ["AuthSnapshotRecord", "ProfileManager", "ProfileRecord"]

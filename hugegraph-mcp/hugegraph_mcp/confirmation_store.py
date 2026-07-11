# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Persistent, atomic ledger for single-use write confirmations."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import time

from hugegraph_mcp.config import MCPConfig


class ConfirmationAlreadyUsedError(Exception):
    """The nonce has already authorized a write attempt."""


class ConfirmationStoreUnavailableError(Exception):
    """The durable confirmation ledger cannot safely record a write."""


class ConfirmationStore:
    """SQLite-backed confirmation ledger with a globally unique nonce digest."""

    DATABASE_NAME = "confirmations.sqlite3"

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.database_path = self.state_dir / self.DATABASE_NAME

    @classmethod
    def from_config(cls) -> "ConfirmationStore":
        return cls(MCPConfig.from_env().state_dir)

    def has_consumed(self, nonce: str | None) -> bool:
        """Check whether a nonce was consumed without creating persistent state."""
        if not nonce or not self.database_path.exists():
            return False
        nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        try:
            with sqlite3.connect(self.database_path, timeout=30) as connection:
                row = connection.execute(
                    """
                    SELECT 1 FROM consumed_confirmations
                    WHERE nonce_digest = ? LIMIT 1
                    """,
                    (nonce_digest,),
                ).fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise ConfirmationStoreUnavailableError from exc
        return row is not None

    def consume(self, *, nonce: str, plan_hash: str, expires_at: int) -> None:
        """Atomically record a nonce before its associated write starts."""
        nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        consumed_at = int(time.time())

        try:
            self._prepare_storage()
            with sqlite3.connect(self.database_path, timeout=30) as connection:
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS consumed_confirmations (
                        nonce_digest TEXT PRIMARY KEY,
                        plan_hash TEXT NOT NULL,
                        expires_at INTEGER NOT NULL,
                        consumed_at INTEGER NOT NULL
                    )
                    """
                )
                connection.commit()
                try:
                    self._cleanup_expired(connection, consumed_at)
                except sqlite3.Error:
                    connection.rollback()
                try:
                    connection.execute(
                        """
                        INSERT INTO consumed_confirmations (
                            nonce_digest, plan_hash, expires_at, consumed_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (nonce_digest, plan_hash, int(expires_at), consumed_at),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ConfirmationAlreadyUsedError from exc
        except ConfirmationAlreadyUsedError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ConfirmationStoreUnavailableError from exc

    def _cleanup_expired(
        self, connection: sqlite3.Connection, current_time: int
    ) -> None:
        """Best-effort cleanup that never authorizes or blocks a current plan."""
        connection.execute(
            "DELETE FROM consumed_confirmations WHERE expires_at < ?",
            (current_time,),
        )
        connection.commit()

    def _prepare_storage(self) -> None:
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        _restrict_permissions(self.state_dir, 0o700)

        descriptor = os.open(
            self.database_path,
            os.O_CREAT | os.O_APPEND | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        _restrict_permissions(self.database_path, 0o600)


def _restrict_permissions(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except (NotImplementedError, OSError):
        if os.name == "posix":
            raise

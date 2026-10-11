from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

from runtime.S15_transition_reference import (
    OperationStatus,
)
from runtime.db.models import IdempotencyKeyRow


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class IdempotencySummary:
    key: str
    run_id: str
    status: OperationStatus
    result: Any
    error: str
    created_at: datetime
    updated_at: datetime


def row_to_summary(
    row: IdempotencyKeyRow,
) -> IdempotencySummary:
    return IdempotencySummary(
        key=row.key,
        run_id=row.run_id,
        status=OperationStatus(row.status),
        result=row.result,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class IdempotencyRepository:
    def __init__(
        self,
        session_factory: Any,
    ) -> None:
        self.session_factory = session_factory

    def begin(
        self,
        key: str,
        run_id: str,
    ) -> tuple[bool, IdempotencySummary]:
        with self.session_factory() as session:
            existing = session.get(
                IdempotencyKeyRow,
                key,
            )

            if existing is not None:
                return row_to_summary(existing), False

            row = IdempotencyKeyRow(
                key=key,
                run_id=run_id,
                status=(
                    OperationStatus.STARTED.value
                ),
                result=None,
                error="",
            )
            session.add(row)

            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.get(
                    IdempotencyKeyRow,
                    key,
                )
                if existing is None:
                    raise
                return (
                    row_to_summary(existing),
                    False,
                )

            session.refresh(row)
            return row_to_summary(row), True

    def get(
        self,
        key: str,
    ) -> IdempotencySummary | None:
        with self.session_factory() as session:
            row = session.get(
                IdempotencyKeyRow,
                key,
            )

            if row is None:
                return None

            return row_to_summary(row)

    def complete(
        self,
        key: str,
        result: Any,
    ) -> IdempotencySummary | None:
        with self.session_factory() as session:
            row = session.get(
                IdempotencyKeyRow,
                key,
            )

            if row is None:
                return None

            row.status = (
                OperationStatus.SUCCEEDED.value
            )
            row.result = result
            row.error = ""

            session.commit()
            session.refresh(row)
            return row_to_summary(row)

    def fail(
        self,
        key: str,
        error: str,
    ) -> IdempotencySummary | None:
        with self.session_factory() as session:
            row = session.get(
                IdempotencyKeyRow,
                key,
            )

            if row is None:
                return None

            row.status = (
                OperationStatus.FAILED.value
            )
            row.error = error

            session.commit()
            session.refresh(row)
            return row_to_summary(row)
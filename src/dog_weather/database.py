from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import Float, Integer, String, Text, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notify_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notify_minute: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # JSON list of ints, e.g. [6, 7, 8]
    intervals: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Data Transfer Object (plain dataclass, no SQLAlchemy magic)
# ---------------------------------------------------------------------------

@dataclass
class UserData:
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    notify_hour: Optional[int] = None
    notify_minute: Optional[int] = None
    intervals: list[int] = field(default_factory=list)  # start hours

    def is_fully_configured(self) -> bool:
        return (
            self.latitude is not None
            and self.longitude is not None
            and self.timezone is not None
            and self.notify_hour is not None
            and bool(self.intervals)
        )

    @classmethod
    def from_row(cls, row: UserRow) -> "UserData":
        intervals: list[int] = []
        if row.intervals:
            try:
                intervals = json.loads(row.intervals)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls(
            telegram_id=row.telegram_id,
            username=row.username,
            first_name=row.first_name,
            latitude=row.latitude,
            longitude=row.longitude,
            timezone=row.timezone,
            notify_hour=row.notify_hour,
            notify_minute=row.notify_minute,
            intervals=intervals,
        )


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    def __init__(self, path: str) -> None:
        url = f"sqlite+aiosqlite:///{path}"
        self._engine = create_async_engine(url, echo=False)
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialised")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_user(self, telegram_id: int) -> Optional[UserData]:
        async with self._session_factory() as session:
            row = await session.get(UserRow, telegram_id)
            return UserData.from_row(row) if row else None

    async def get_all_users(self) -> list[UserData]:
        async with self._session_factory() as session:
            result = await session.execute(select(UserRow))
            return [UserData.from_row(r) for r in result.scalars()]

    # ------------------------------------------------------------------
    # Write helpers (upsert specific fields)
    # ------------------------------------------------------------------

    async def _get_or_create(
        self, session: AsyncSession, telegram_id: int
    ) -> UserRow:
        row = await session.get(UserRow, telegram_id)
        if row is None:
            row = UserRow(telegram_id=telegram_id)
            session.add(row)
        return row

    async def update_identity(
        self,
        telegram_id: int,
        username: Optional[str],
        first_name: Optional[str],
    ) -> None:
        async with self._session_factory() as session:
            row = await self._get_or_create(session, telegram_id)
            row.username = username
            row.first_name = first_name
            await session.commit()

    async def update_location(
        self, telegram_id: int, lat: float, lon: float, tz: str
    ) -> None:
        async with self._session_factory() as session:
            row = await self._get_or_create(session, telegram_id)
            row.latitude = lat
            row.longitude = lon
            row.timezone = tz
            await session.commit()

    async def update_notify_time(
        self, telegram_id: int, hour: int, minute: int
    ) -> None:
        async with self._session_factory() as session:
            row = await self._get_or_create(session, telegram_id)
            row.notify_hour = hour
            row.notify_minute = minute
            await session.commit()

    async def update_intervals(
        self, telegram_id: int, intervals: list[int]
    ) -> None:
        async with self._session_factory() as session:
            row = await self._get_or_create(session, telegram_id)
            row.intervals = json.dumps(intervals)
            await session.commit()

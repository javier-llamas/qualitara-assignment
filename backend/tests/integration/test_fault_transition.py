from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models import MaintenanceReport, MaintenanceStatus, Mission, MissionStatus
from app.services.faults import transition_to_fault


async def _seed_active_mission(vehicle_id: str) -> int:
    factory = get_session_factory()
    async with factory() as s:
        async with s.begin():
            m = Mission(
                vehicle_id=vehicle_id,
                status=MissionStatus.CURRENT,
                description="seed",
                started_at=datetime.now(UTC),
            )
            s.add(m)
            await s.flush()
            return m.id


@pytest.mark.asyncio
async def test_single_fault_cancels_mission_and_creates_maintenance(
    db_session: AsyncSession,
) -> None:
    mid = await _seed_active_mission("v-1")
    factory = get_session_factory()
    async with factory() as s:
        async with s.begin():
            res = await transition_to_fault(s, "v-1", diagnostics="test")
    assert res.cancelled_mission_id == mid
    assert res.maintenance_report_id is not None
    assert res.already_open is False

    async with factory() as s:
        mission = (
            await s.execute(select(Mission).where(Mission.id == mid))
        ).scalar_one()
        assert mission.status == MissionStatus.CANCELED
        assert mission.ended_at is not None
        reports = (await s.execute(select(MaintenanceReport))).scalars().all()
        assert len(reports) == 1
        assert reports[0].status == MaintenanceStatus.QUEUED


@pytest.mark.asyncio
async def test_concurrent_faults_same_vehicle_idempotent(
    db_session: AsyncSession,
) -> None:
    """20 concurrent fault transitions for the same vehicle:
    exactly one mission canceled, exactly one maintenance report, no exceptions."""
    await _seed_active_mission("v-burst")
    factory = get_session_factory()

    async def one() -> object:
        async with factory() as s:
            async with s.begin():
                return await transition_to_fault(s, "v-burst")

    results = await asyncio.gather(*(one() for _ in range(20)), return_exceptions=True)
    for r in results:
        assert not isinstance(r, Exception), f"unexpected exception: {r!r}"

    async with factory() as s:
        canceled = (
            (
                await s.execute(
                    select(Mission).where(
                        Mission.vehicle_id == "v-burst",
                        Mission.status == MissionStatus.CANCELED,
                    )
                )
            )
            .scalars()
            .all()
        )
        reports = (
            (
                await s.execute(
                    select(MaintenanceReport).where(
                        MaintenanceReport.vehicle_id == "v-burst"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(canceled) == 1
    assert len(reports) == 1
    assert reports[0].status == MaintenanceStatus.QUEUED


@pytest.mark.asyncio
async def test_concurrent_faults_50_different_vehicles(
    db_session: AsyncSession,
) -> None:
    mission_ids = await asyncio.gather(
        *(_seed_active_mission(f"v-multi-{i}") for i in range(50))
    )
    assert len(set(mission_ids)) == 50

    factory = get_session_factory()

    async def one(vid: int) -> object:
        async with factory() as s:
            async with s.begin():
                return await transition_to_fault(s, f"v-multi-{vid}")

    results = await asyncio.gather(*(one(i) for i in range(50)))
    assert all(r.cancelled_mission_id is not None for r in results)

    async with factory() as s:
        canceled = (
            (
                await s.execute(
                    select(Mission).where(Mission.status == MissionStatus.CANCELED)
                )
            )
            .scalars()
            .all()
        )
        reports = (await s.execute(select(MaintenanceReport))).scalars().all()
    assert len(canceled) == 50
    assert len(reports) == 50


@pytest.mark.asyncio
async def test_fault_with_no_active_mission_still_creates_maintenance(
    db_session: AsyncSession,
) -> None:
    """Vehicle has no active mission — transition still creates a maintenance report
    (cancelled_mission_id NULL)."""
    factory = get_session_factory()
    async with factory() as s:
        async with s.begin():
            res = await transition_to_fault(s, "v-no-mission")
    assert res.cancelled_mission_id is None
    assert res.maintenance_report_id is not None

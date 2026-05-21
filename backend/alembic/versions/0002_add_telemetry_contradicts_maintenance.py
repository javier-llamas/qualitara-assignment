"""add telemetry_contradicts_maintenance incident type

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
    # Postgres; autocommit_block makes alembic commit before issuing it.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE incident_type ADD VALUE IF NOT EXISTS 'telemetry_contradicts_maintenance'"
        )


def downgrade() -> None:
    # Postgres has no DROP VALUE for an enum. Down-migrating would require
    # rebuilding the type and rewriting every row that uses the removed value.
    # Out of scope for this slice.
    pass

"""Configurable floor plans: grid positions, floors, hallway, members only rooms

Revision ID: 0002
Revises: 0001
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Where the fixed layouts of 0001 sat on the two column plan.
OLD = {"dispatch": (0, 0, 2, 1), "sales": (0, 1, 1, 1), "warehouse": (1, 1, 1, 1), "quiet": (0, 2, 1, 1)}


def upgrade() -> None:
    default_floors = json.dumps([{"id": "main", "name": "Office", "columns": 2}])
    op.add_column("organization", sa.Column("floors", postgresql.JSONB(), nullable=False, server_default=sa.text(f"'{default_floors}'::jsonb")))
    for name, default in (("floor_id", "'main'"), ("col", "0"), ("row", "0"), ("col_span", "1"), ("row_span", "1"), ("members_only", "false")):
        typ = sa.String(40) if name == "floor_id" else sa.Boolean() if name == "members_only" else sa.Integer()
        op.add_column("room", sa.Column(name, typ, nullable=False, server_default=sa.text(default)))
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, layout, position FROM room ORDER BY position")).all()
    extra_row = 3
    for rid, layout, _ in rows:
        col, row, cs, rs = OLD.get(layout, (0, extra_row, 2, 1))
        if layout not in OLD:
            extra_row += 1
        conn.execute(sa.text("UPDATE room SET col=:c, row=:r, col_span=:cs, row_span=:rs WHERE id=:id"),
                     {"c": col, "r": row, "cs": cs, "rs": rs, "id": rid})
    op.drop_column("room", "layout")
    op.drop_column("room", "position")
    # One hallway per organization, where the quiet room's neighbour used to be.
    for (org_id,) in conn.execute(sa.text("SELECT id FROM organization")).all():
        conn.execute(sa.text(
            "INSERT INTO room (id, org_id, name, kind, floor_id, col, row, col_span, row_span, members_only) "
            "VALUES (gen_random_uuid(), :o, 'Hallway', 'hallway', 'main', 1, 2, 1, 1, false) ON CONFLICT DO NOTHING"
        ), {"o": org_id})


def downgrade() -> None:
    op.execute("DELETE FROM room WHERE kind = 'hallway'")
    op.add_column("room", sa.Column("layout", sa.String(30), nullable=False, server_default=""))
    op.add_column("room", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    for name in ("floor_id", "col", "row", "col_span", "row_span", "members_only"):
        op.drop_column("room", name)
    op.drop_column("organization", "floors")

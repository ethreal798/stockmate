"""merge_heads

Merge the three divergent heads back into a single tip.
No schema changes — this is purely a graph stitch.

Revision ID: fff0ff00ff00
Revises: (c4d5e6f7a8b9, e5f6a7b8c901, d7e8f9a0b1c2)
Create Date: 2026-10-03 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "fff0ff00ff00"
down_revision: Union[str, Sequence[str], None] = ("c4d5e6f7a8b9", "e5f6a7b8c901", "d7e8f9a0b1c2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge-only: no schema changes needed."""
    pass


def downgrade() -> None:
    """Merge-only: nothing to revert."""
    pass

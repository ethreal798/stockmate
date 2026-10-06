"""drop_rag_document_importance_score

Revision ID: e5f6a7b8c901
Revises: a3b5c7d9e1f2
Create Date: 2026-10-02 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c901"
down_revision: Union[str, None] = "a3b5c7d9e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("rag_documents", "importance_score")


def downgrade() -> None:
    op.add_column(
        "rag_documents",
        sa.Column(
            "importance_score",
            sa.Integer(),
            autoincrement=False,
            nullable=True,
            server_default=sa.text("0"),
            comment="重要性评分",
        ),
    )

"""drop_unused_rag_chunk_and_event_columns

Revision ID: c4d5e6f7a8b9
Revises: a3b5c7d9e1f2
Create Date: 2026-09-28 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "a3b5c7d9e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === rag_chunks: 先删索引，再删列 ===
    op.drop_index(op.f("ix_rag_chunks_chunk_hash"), table_name="rag_chunks")
    op.drop_index(op.f("ix_rag_chunks_category"), table_name="rag_chunks")
    op.drop_index(op.f("ix_rag_chunks_sentiment"), table_name="rag_chunks")

    op.drop_column("rag_chunks", "chunk_hash")
    op.drop_column("rag_chunks", "token_count")
    op.drop_column("rag_chunks", "start_offset")
    op.drop_column("rag_chunks", "end_offset")
    op.drop_column("rag_chunks", "category")
    op.drop_column("rag_chunks", "importance_score")
    op.drop_column("rag_chunks", "sentiment")

    # === rag_events: alias / weight / extra_metadata 无对应索引，直接删列 ===
    op.drop_index(op.f("ix_rag_events_chunk_id"), table_name="rag_events")
    op.drop_column("rag_events", "chunk_id")
    op.drop_column("rag_events", "alias")
    op.drop_column("rag_events", "weight")
    op.drop_column("rag_events", "extra_metadata")


def downgrade() -> None:
    # === rag_chunks ===
    op.add_column(
        "rag_chunks",
        sa.Column("chunk_hash", sa.String(length=64), autoincrement=False, nullable=False, comment="分块哈希"),
    )
    op.add_column(
        "rag_chunks",
        sa.Column(
            "token_count",
            sa.Integer(),
            autoincrement=False,
            nullable=True,
            server_default=sa.text("0"),
            comment="估算 token 数",
        ),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("start_offset", sa.Integer(), autoincrement=False, nullable=True, server_default=sa.text("0")),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("end_offset", sa.Integer(), autoincrement=False, nullable=True, server_default=sa.text("0")),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("category", sa.String(length=50), autoincrement=False, nullable=True),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("importance_score", sa.Integer(), autoincrement=False, nullable=True, server_default=sa.text("0")),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("sentiment", sa.String(length=50), autoincrement=False, nullable=True),
    )

    op.create_index(op.f("ix_rag_chunks_chunk_hash"), "rag_chunks", ["chunk_hash"], unique=False)
    op.create_index(op.f("ix_rag_chunks_category"), "rag_chunks", ["category"], unique=False)
    op.create_index(op.f("ix_rag_chunks_sentiment"), "rag_chunks", ["sentiment"], unique=False)

    # === rag_events ===
    op.add_column(
        "rag_events",
        sa.Column("chunk_id", sa.BigInteger(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "rag_events",
        sa.Column("alias", sa.String(length=200), autoincrement=False, nullable=True),
    )
    op.add_column(
        "rag_events",
        sa.Column(
            "weight", sa.Float(), autoincrement=False, nullable=True, server_default=sa.text("0"), comment="实体权重"
        ),
    )
    op.add_column(
        "rag_events",
        sa.Column("extra_metadata", sa.JSON(), autoincrement=False, nullable=True),
    )
    op.create_index(op.f("ix_rag_events_chunk_id"), "rag_events", ["chunk_id"], unique=False)

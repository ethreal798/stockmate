"""drop_unused_rag_document_columns

Revision ID: a3b5c7d9e1f2
Revises: bm25_zh_cn
Create Date: 2026-09-28 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a3b5c7d9e1f2"
down_revision: Union[str, None] = "bm25_zh_cn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先删索引（PG 不允许直接 DROP 有索引依赖的列）
    op.drop_index(op.f("ix_rag_documents_category"), table_name="rag_documents")
    op.drop_index(op.f("ix_rag_documents_sentiment"), table_name="rag_documents")
    op.drop_index(op.f("ix_rag_documents_content_hash"), table_name="rag_documents")

    # 再删列：6 个未使用的字段
    op.drop_column("rag_documents", "content_hash")
    op.drop_column("rag_documents", "summary")
    op.drop_column("rag_documents", "url")
    op.drop_column("rag_documents", "category")
    op.drop_column("rag_documents", "sentiment")
    op.drop_column("rag_documents", "language")


def downgrade() -> None:
    # 先加回列
    op.add_column(
        "rag_documents",
        sa.Column("content_hash", sa.String(length=64), autoincrement=False, nullable=False, comment="正文哈希"),
    )
    op.add_column(
        "rag_documents",
        sa.Column("summary", sa.Text(), autoincrement=False, nullable=True, comment="预生成摘要"),
    )
    op.add_column(
        "rag_documents",
        sa.Column("url", sa.String(length=500), autoincrement=False, nullable=True, comment="原文链接"),
    )
    op.add_column(
        "rag_documents",
        sa.Column("category", sa.String(length=50), autoincrement=False, nullable=True, comment="新闻分类"),
    )
    op.add_column(
        "rag_documents",
        sa.Column("sentiment", sa.String(length=50), autoincrement=False, nullable=True, comment="情绪标签"),
    )
    op.add_column(
        "rag_documents",
        sa.Column(
            "language",
            sa.String(length=20),
            autoincrement=False,
            nullable=True,
            server_default=sa.text("zh"),
            comment="语言",
        ),
    )

    # 再加回索引
    op.create_index(
        op.f("ix_rag_documents_category"), "rag_documents", ["category"], unique=False
    )
    op.create_index(
        op.f("ix_rag_documents_sentiment"), "rag_documents", ["sentiment"], unique=False
    )
    op.create_index(
        op.f("ix_rag_documents_content_hash"), "rag_documents", ["content_hash"], unique=False
    )

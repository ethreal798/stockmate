"""删除未使用的旧 AI 数据表。

Revision ID: e1f7c9a4b203
Revises: d6a4b8c2e105
Create Date: 2026-07-30 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1f7c9a4b203"
down_revision: Union[str, None] = "d6a4b8c2e105"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除没有业务引用的旧 AI 响应、推荐和聊天记忆表。"""
    op.execute("DROP TABLE IF EXISTS chat_memory")
    op.execute("DROP TABLE IF EXISTS ai_recommend_stocks")
    op.execute("DROP TABLE IF EXISTS ai_response_result")


def downgrade() -> None:
    """按删除前的结构恢复三张旧表。"""
    op.create_table(
        "ai_response_result",
        sa.Column("chat_id", sa.String(length=100), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("stock_code", sa.String(length=20), nullable=True),
        sa.Column("stock_name", sa.String(length=50), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("is_del", sa.DateTime(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_response_result_deleted_at", "ai_response_result", ["deleted_at"])
    op.create_index("ix_ai_response_result_is_del", "ai_response_result", ["is_del"])

    op.create_table(
        "ai_recommend_stocks",
        sa.Column("data_time", sa.DateTime(), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("rating", sa.String(length=20), nullable=True),
        sa.Column("stock_code", sa.String(length=20), nullable=True),
        sa.Column("stock_name", sa.String(length=50), nullable=True),
        sa.Column("bk_code", sa.String(length=50), nullable=True),
        sa.Column("bk_name", sa.String(length=100), nullable=True),
        sa.Column("stock_price", sa.String(length=20), nullable=True),
        sa.Column("stock_current_price", sa.String(length=20), nullable=True),
        sa.Column("stock_current_price_time", sa.String(length=50), nullable=True),
        sa.Column("stock_close_price", sa.String(length=20), nullable=True),
        sa.Column("stock_pre_price", sa.String(length=20), nullable=True),
        sa.Column("recommend_reason", sa.Text(), nullable=True),
        sa.Column("recommend_buy_price", sa.String(length=50), nullable=True),
        sa.Column("recommend_buy_price_min", sa.Float(), nullable=True),
        sa.Column("recommend_buy_price_max", sa.Float(), nullable=True),
        sa.Column("recommend_stop_profit_price", sa.String(length=50), nullable=True),
        sa.Column("recommend_stop_profit_price_min", sa.Float(), nullable=True),
        sa.Column("recommend_stop_profit_price_max", sa.Float(), nullable=True),
        sa.Column("recommend_stop_loss_price", sa.String(length=50), nullable=True),
        sa.Column("risk_remarks", sa.Text(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("enable_alert", sa.Boolean(), server_default="false", nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_recommend_stocks_data_time", "ai_recommend_stocks", ["data_time"])
    op.create_index("ix_ai_recommend_stocks_deleted_at", "ai_recommend_stocks", ["deleted_at"])

    op.create_table(
        "chat_memory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_memory_session_id", "chat_memory", ["session_id"])

"""add_users_table

Revision ID: d7e8f9a0b1c2
Revises: bm25_zh_cn
Create Date: 2026-10-03 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "bm25_zh_cn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 users 表（User 模型 + GormBaseModel 基类）。"""
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("username", sa.String(length=100), nullable=False, comment="用户名"),
        sa.Column("hashed_password", sa.String(length=255), nullable=False, comment="哈希密码"),
        sa.Column("email", sa.String(length=100), nullable=True, comment="电子邮箱"),
        sa.Column("full_name", sa.String(length=100), nullable=True, comment="姓名"),
        sa.Column("is_active", sa.Boolean(), nullable=True, comment="是否激活"),
        sa.Column("is_superuser", sa.Boolean(), nullable=True, comment="是否为超级管理员"),
        sa.Column("last_login", sa.DateTime(), nullable=True, comment="最后登录时间"),
    )
    op.create_index(op.f("ix_users_deleted_at"), "users", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)


def downgrade() -> None:
    """删除 users 表。"""
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_deleted_at"), table_name="users")
    op.drop_table("users")

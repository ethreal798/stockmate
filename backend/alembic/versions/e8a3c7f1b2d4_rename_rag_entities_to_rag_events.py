"""rename rag_entities to rag_events and add rag v1 fields

阶段 1 数据模型迁移（rag_foundation_v1）：
- rag_entities 重命名为 rag_events
- rag_events 新增事件字段（event_time / industry_category / industry_tag /
  event_action / sentiment / confidence），extra_metadata 旧表已存在跳过
- entity_name 放开 NOT NULL（macro/industry 事件无公司名，LLM 输出允许 null）
- 旧索引统一重命名：entity_code → idx_rag_events_entity_code（计划规范名），
  其余 ix_rag_entities_* 重命名为 ix_rag_events_*（与 SQLAlchemy 默认命名一致，
  避免 autogenerate 永久漂移，mixin 的 deleted_at 索引名无法在子类覆盖）
- 新建索引 idx_rag_events_category_time / idx_rag_events_confidence
- rag_documents 新增 processing_stage / processing_error
- rag_chunks 新增 chunking_version / embedding_text
- 新建 rag_weekly_reports 表

Revision ID: e8a3c7f1b2d4
Revises: c3d4e5f6a7b8
Create Date: 2026-08-29

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e8a3c7f1b2d4"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 表重命名（索引名不受影响，单独处理）
    op.rename_table("rag_entities", "rag_events")

    # 2. 旧索引统一重命名（entity_code 用计划规范名，其余对齐 SQLAlchemy 默认命名）
    op.execute("ALTER INDEX ix_rag_entities_entity_code RENAME TO idx_rag_events_entity_code")
    op.execute("ALTER INDEX ix_rag_entities_document_id RENAME TO ix_rag_events_document_id")
    op.execute("ALTER INDEX ix_rag_entities_chunk_id RENAME TO ix_rag_events_chunk_id")
    op.execute("ALTER INDEX ix_rag_entities_entity_name RENAME TO ix_rag_events_entity_name")
    op.execute("ALTER INDEX ix_rag_entities_entity_type RENAME TO ix_rag_events_entity_type")
    op.execute("ALTER INDEX ix_rag_entities_deleted_at RENAME TO ix_rag_events_deleted_at")
    op.execute("ALTER INDEX idx_rag_entities_type_name RENAME TO idx_rag_events_type_name")

    # 3. entity_name 放开 NOT NULL（macro/industry 事件无公司名）
    op.alter_column(
        "rag_events",
        "entity_name",
        existing_type=sa.String(length=200),
        nullable=True,
    )

    # 4. rag_events 新增事件字段（extra_metadata 旧表已存在，跳过）
    op.add_column("rag_events", sa.Column("event_time", sa.DateTime(), nullable=True, comment="事件发生时间"))
    op.add_column(
        "rag_events",
        sa.Column("industry_category", sa.String(length=50), nullable=True, comment="一级行业（聚合用，固定枚举）"),
    )
    op.add_column(
        "rag_events",
        sa.Column("industry_tag", sa.String(length=100), nullable=True, comment="二级行业（细粒度标注）"),
    )
    op.add_column("rag_events", sa.Column("event_action", sa.String(length=200), nullable=True, comment="事件动作描述"))
    op.add_column(
        "rag_events",
        sa.Column("sentiment", sa.String(length=20), nullable=True, comment="情绪: positive/negative/mixed/neutral"),
    )
    op.add_column("rag_events", sa.Column("confidence", sa.Float(), nullable=True, comment="LLM 自评置信度 0.0-1.0"))

    # 5. 核心索引（按一级行业 + 时间聚合）
    op.create_index("idx_rag_events_category_time", "rag_events", ["industry_category", "event_time"], unique=False)
    op.create_index("idx_rag_events_confidence", "rag_events", ["confidence"], unique=False)

    # 6. rag_documents 新增流水线状态字段（存量行默认 pending）
    op.add_column(
        "rag_documents",
        sa.Column(
            "processing_stage",
            sa.String(length=30),
            nullable=True,
            server_default="pending",
            comment="处理阶段: pending/embedded/events_done/chunk_failed/embedding_failed/event_failed",
        ),
    )
    op.add_column(
        "rag_documents",
        sa.Column("processing_error", sa.Text(), nullable=True, comment="处理失败错误信息"),
    )

    # 7. rag_chunks 新增 FlashV1 切片字段
    op.add_column(
        "rag_chunks",
        sa.Column("chunking_version", sa.String(length=30), nullable=True, comment="切片策略版本: flash-v1"),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("embedding_text", sa.Text(), nullable=True, comment="向量化输入文本（标题+正文模板）"),
    )

    # 8. 新建 rag_weekly_reports 表（Stage 4 周报）
    op.create_table(
        "rag_weekly_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("week_start", sa.DateTime(), nullable=False, comment="周起始时间（周一 00:00）"),
        sa.Column("week_end", sa.DateTime(), nullable=False, comment="周结束时间（周日 23:59:59）"),
        sa.Column("top_events", sa.JSON(), nullable=True, comment="TOP 10 事件列表"),
        sa.Column("industry_heat", sa.JSON(), nullable=True, comment="行业热度排行"),
        sa.Column("sentiment_distribution", sa.JSON(), nullable=True, comment="情绪分布"),
        sa.Column("trend_analysis", sa.Text(), nullable=True, comment="LLM 生成的行业趋势分析"),
        sa.Column("risk_warnings", sa.Text(), nullable=True, comment="LLM 生成的下周风险提示"),
        sa.Column("model_name", sa.String(length=100), nullable=True, comment="生成周报使用的模型"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_rag_weekly_reports_week_start", "rag_weekly_reports", ["week_start"], unique=False)


def downgrade() -> None:
    # 注意：entity_name 恢复 NOT NULL 的前提是 rag_events 中无 entity_name 为 NULL 的数据
    op.drop_index("idx_rag_weekly_reports_week_start", table_name="rag_weekly_reports")
    op.drop_table("rag_weekly_reports")

    op.drop_column("rag_chunks", "chunking_version")
    op.drop_column("rag_chunks", "embedding_text")

    op.drop_column("rag_documents", "processing_error")
    op.drop_column("rag_documents", "processing_stage")

    op.drop_index("idx_rag_events_confidence", table_name="rag_events")
    op.drop_index("idx_rag_events_category_time", table_name="rag_events")

    op.drop_column("rag_events", "confidence")
    op.drop_column("rag_events", "sentiment")
    op.drop_column("rag_events", "event_action")
    op.drop_column("rag_events", "industry_tag")
    op.drop_column("rag_events", "industry_category")
    op.drop_column("rag_events", "event_time")

    op.alter_column(
        "rag_events",
        "entity_name",
        existing_type=sa.String(length=200),
        nullable=False,
    )

    op.execute("ALTER INDEX idx_rag_events_entity_code RENAME TO ix_rag_entities_entity_code")
    op.execute("ALTER INDEX ix_rag_events_document_id RENAME TO ix_rag_entities_document_id")
    op.execute("ALTER INDEX ix_rag_events_chunk_id RENAME TO ix_rag_entities_chunk_id")
    op.execute("ALTER INDEX ix_rag_events_entity_name RENAME TO ix_rag_entities_entity_name")
    op.execute("ALTER INDEX ix_rag_events_entity_type RENAME TO ix_rag_entities_entity_type")
    op.execute("ALTER INDEX ix_rag_events_deleted_at RENAME TO ix_rag_entities_deleted_at")
    op.execute("ALTER INDEX idx_rag_events_type_name RENAME TO idx_rag_entities_type_name")

    op.rename_table("rag_events", "rag_entities")

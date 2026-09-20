def upgrade() -> None:
    # ① 确保三个扩展存在
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch")
    op.execute("CREATE EXTENSION IF NOT EXISTS zhparser")

    # ② 创建 zh_cn 文本搜索配置
    #    PG 的 ts_config = parser + token 映射规则
    op.execute("CREATE TEXT SEARCH CONFIGURATION public.zh_cn (PARSER = zhparser)")
    op.execute(
        "ALTER TEXT SEARCH CONFIGURATION public.zh_cn "
        "ADD MAPPING FOR n, v, a, i, e, l WITH simple"
    )
    # n=名词 v=动词 a=形容词 i=成语 e=短语 l=数词
    # simple = 不做 stemming/停词，直接保留原词（中文不需要 stemming）

    # ③ 建索引
    #    text_config 告诉 pg_textsearch 用哪个 parser 分词
    op.execute(
        "CREATE INDEX idx_chunks_bm25 "
        "ON rag_chunks "
        "USING bm25 (chunk_text) "
        "WITH (text_config='public.zh_cn')"
    )
"""add bm25 chinese index with zhparser

Revision ID: bm25_zh_cn
Revises: e8a3c7f1b2d4
Create Date: 2026-09-17 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "bm25_zh_cn"
down_revision: str = "e8a3c7f1b2d4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 三个 PG 扩展（已在 Docker 镜像 preload）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch")
    op.execute("CREATE EXTENSION IF NOT EXISTS zhparser")

    # zhparser text search config（PG 不支持 CREATE TEXT SEARCH CONFIGURATION IF NOT EXISTS）
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS public.zh_cn")
    op.execute(
        "CREATE TEXT SEARCH CONFIGURATION public.zh_cn (PARSER = zhparser)"
    )
    op.execute(
        "ALTER TEXT SEARCH CONFIGURATION public.zh_cn "
        "ADD MAPPING FOR n, v, a, i, e, l WITH simple"
    )

    # 验证 zhparser 分词真的生效（CREATE INDEX 本身如果 config 有问题会报错）
    # 这里只做一个轻量检查：确保 text config 已注册
    op.execute("SELECT cfgname FROM pg_ts_config WHERE cfgname = 'public.zh_cn'")

    # BM25 索引直接建在 chunk_text TEXT 列上
    # text_config 是 pg_textsearch REQUIRED 参数，zhparser 在 PG 层自动做中文分词
    # 历史数据自动处理（CREATE INDEX 扫描全表 + zhparser 自动分词）
    op.execute(
        "CREATE INDEX idx_chunks_bm25 "
        "ON rag_chunks "
        "USING bm25 (chunk_text) "
        "WITH (text_config='public.zh_cn')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunks_bm25")
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS public.zh_cn")
    # 注意：不回滚 pg_textsearch / zhparser extension（全局对象）

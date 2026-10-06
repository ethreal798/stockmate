"""异步 SQLAlchemy 数据库配置。"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 创建异步引擎
engine = create_async_engine(
    url=settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    future=True,
    # PostgreSQL数据库连接池配置
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,  # 自动检测并回收断开的连接
    pool_recycle=3600,  # 每小时回收连接，防止连接被数据库强制断开
)

# 异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy 声明基类，所有 ORM 模型需继承此类。"""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：获取异步数据库会话。

    使用方式::
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session  # ① 把 session 交给路由/Service 使用
            await session.commit()  # ② yield 返回后执行 commit（正常结束）
        except Exception:
            await session.rollback()  # ③ 路由抛异常则回滚
            raise
        finally:
            await session.close()  # ④ 无论如何关闭 session


async def init_db() -> None:
    """初始化数据库：创建所有表（开发阶段使用，生产用 Alembic 迁移）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """关闭数据库连接池。"""
    await engine.dispose()

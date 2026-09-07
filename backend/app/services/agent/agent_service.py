"""Agent 会话、运行任务和消息的数据库编排服务。"""

import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent import AgentMessage, AgentRun, AgentThread
from app.schemas.agent import (
    AgentMessageResponse,
    AgentModelOption,
    AgentRunCreate,
    AgentRunResponse,
    AgentRunSubmit,
    AgentThreadCreate,
    AgentThreadResponse,
)
from app.services.agent.runtime_model_config_service import RuntimeModelConfigService

ACTIVE_RUN_STATUSES = ("pending", "running", "cancel_requested")
TERMINAL_RUN_STATUSES = ("completed", "canceled", "failed", "interrupted")


class AgentService:
    """维护 LangGraph Agent 控制面的持久化状态与事务规则。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.model_configs = RuntimeModelConfigService(db)

    async def create_thread(self, user_id: int, request: AgentThreadCreate) -> AgentThreadResponse:
        """校验模型配置并创建用户会话。"""
        model_config = await self.model_configs.resolve(user_id, request.model_config_id)
        thread = AgentThread(
            user_id=user_id,
            title=(request.title or "New conversation").strip() or "New conversation",
            capability=request.capability,
            model_config_id=model_config.id,
        )
        self.db.add(thread)
        await self.db.flush()
        return self.to_thread_response(thread)

    async def list_available_models(self, user_id: int) -> list[AgentModelOption]:
        """返回当前用户可用于 Agent 对话的模型配置。"""
        return await self.model_configs.list_available_models(user_id)

    async def list_threads(self, user_id: int, *, limit: int = 20, offset: int = 0) -> list[AgentThreadResponse]:
        """分页查询用户未删除的会话。"""
        stmt = (
            select(AgentThread)
            .where(AgentThread.user_id == user_id, AgentThread.deleted_at.is_(None))
            .order_by(AgentThread.last_message_at.desc().nullslast(), AgentThread.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return [self.to_thread_response(item) for item in result.scalars().all()]

    async def get_thread(self, user_id: int, thread_id: uuid.UUID, *, for_update: bool = False) -> AgentThread:
        """按用户和会话 ID 查询会话，可选择加行锁。"""
        stmt = select(AgentThread).where(
            AgentThread.id == thread_id,
            AgentThread.user_id == user_id,
            AgentThread.deleted_at.is_(None),
        )
        if for_update:
            stmt = stmt.with_for_update()
        thread = (await self.db.execute(stmt)).scalar_one_or_none()
        if thread is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent 会话不存在")
        return thread

    async def get_thread_response(self, user_id: int, thread_id: uuid.UUID) -> AgentThreadResponse:
        """查询会话并转换为接口响应。"""
        return self.to_thread_response(await self.get_thread(user_id, thread_id))

    async def list_messages(self, user_id: int, thread_id: uuid.UUID) -> list[AgentMessageResponse]:
        """按顺序返回会话中对用户可见的消息。"""
        await self.get_thread(user_id, thread_id)
        stmt = (
            select(AgentMessage)
            .where(AgentMessage.thread_id == thread_id, AgentMessage.visible.is_(True))
            .order_by(AgentMessage.sequence.asc())
        )
        result = await self.db.execute(stmt)
        return [self.to_message_response(item) for item in result.scalars().all()]

    async def delete_thread(self, user_id: int, thread_id: uuid.UUID) -> AgentRun | None:
        """软删除会话，并取消该会话中可能存在的活动任务。"""
        thread = await self.get_thread(user_id, thread_id, for_update=True)
        active_run = await self.get_active_run(user_id, thread_id, for_update=True)

        if active_run is not None:
            if active_run.status == "pending":
                active_run.status = "canceled"
                active_run.finish_reason = "abort"
                active_run.finished_at = datetime.now()
                await self._update_assistant(active_run, status="canceled", finish_reason="abort")
            elif active_run.status == "running":
                active_run.status = "cancel_requested"

        thread.status = "deleted"
        thread.deleted_at = datetime.now()
        await self.db.flush()
        return active_run

    async def create_run(self, user_id: int, thread_id: uuid.UUID, request: AgentRunCreate) -> AgentRunResponse:
        """在指定会话内原子创建 Run、用户消息和助手占位消息。"""
        # 1. 从 agent_runs 表中查询是否已存在相同 client_request_id 的任务
        existing = await self._get_by_client_request(user_id, request.client_request_id)
        if existing is not None:
            # 如果存在相同 client_request_id 的任务，且指定的会话 ID 与该任务所属的会话 ID 不同，则抛出冲突异常（会话归属校验）
            if existing.thread_id != thread_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="client_request_id 已被其他会话使用")
            return self.to_run_response(existing)
        # 2. 校验本次任务使用的模型配置（存在、属于当前用户且未禁用）
        model_config = await self.model_configs.resolve(user_id, request.model_config_id)
        # 3. 设置会话行锁，确保并发情况下 对于同一会话只能有一个事务进行操作 因为接下来会进行Check-Then-Act 操作
        thread = await self.get_thread(user_id, thread_id, for_update=True)
        # TODO: 存在幂等检查时序缝隙——若重试请求的幂等预查发生在原请求 commit 之前，
        #  走到此处活动检查时会误判为"当前会话已有活动任务"(409)，而非幂等复用。
        #  建议：拿到行锁后重查一次 client_request_id，让重试复用优先于活动检查。
        # 4. 检测当前会话是否已存在活动任务
        active = await self.get_active_run(user_id, thread_id)
        if active is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前会话已有活动任务")
        
        # 5. 序号分配：sequence 是会话内消息的显示顺序
        max_sequence = (
            await self.db.execute(select(func.max(AgentMessage.sequence)).where(AgentMessage.thread_id == thread_id))
        ).scalar_one_or_none()
        user_sequence = 0 if max_sequence is None else max_sequence + 1
 
        # 6. 在应用代码中预生成 UUID（而非依赖数据库生成），因为三个对象互相引用，需在 flush 前于内存中组成完整对象图
        run_id = uuid.uuid4()
        user_message_id = uuid.uuid4()
        assistant_message_id = uuid.uuid4()
        now = datetime.now()

        run = AgentRun(
            id=run_id,
            thread_id=thread_id,
            user_id=user_id,
            client_request_id=request.client_request_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            model_config_id=model_config.id,
            capability=request.capability,
            status="pending",
            model_name=model_config.model,
        )
        user_message = AgentMessage(
            id=user_message_id,
            thread_id=thread_id,
            run_id=run_id,
            role="user",
            content=request.message,
            sequence=user_sequence,
            status="completed",
            model_config_id=model_config.id,
            model_name=model_config.model,
        )
        assistant_message = AgentMessage(
            id=assistant_message_id,
            thread_id=thread_id,
            run_id=run_id,
            role="assistant",
            content="",
            sequence=user_sequence + 1,
            status="streaming",
            model_config_id=model_config.id,
            model_name=model_config.model,
        )
        # 7. Run 和两条消息在同一事务中创建，避免接口返回后出现不完整记录。
        self.db.add_all([run, user_message, assistant_message])
        # 8. 同步更新会话信息（当前模型配置、能力、消息数、最近活跃时间）
        thread.model_config_id = model_config.id
        thread.capability = request.capability
        thread.message_count = (thread.message_count or 0) + 2
        thread.last_message_at = now
        # 9. 如果会话标题仍是默认占位 "New conversation"（即尚未命名的新会话），用首条用户消息生成标题
        if thread.title == "New conversation":
            thread.title = self._initial_title(request.message)
        
        # 10. 防止同用户、同 client_request_id、但落在不同 thread 的并发提交问题
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            existing = await self._get_by_client_request(user_id, request.client_request_id)
            if existing is not None:
                return self.to_run_response(existing)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="无法并发创建 Agent 任务") from exc
        return self.to_run_response(run)

    async def submit_run(self, user_id: int, request: AgentRunSubmit) -> AgentRunResponse:
        """按需创建会话，并以幂等方式提交一个后台任务。"""
        # 1. 从 agent_runs 表中查询是否已存在相同 client_request_id 的任务
        existing = await self._get_by_client_request(user_id, request.client_request_id)
        if existing is not None:
            # 如果存在相同 client_request_id 的任务，且指定的会话 ID 与该任务所属的会话 ID 不同，则抛出冲突异常（会话归属校验）
            if request.thread_id is not None and existing.thread_id != request.thread_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="client_request_id 已被其他会话使用")
            return self.to_run_response(existing)

        # 2. 按需创建会话（未传 thread_id 时自动创建）
        thread_id = request.thread_id
        if thread_id is None:
            thread = await self.create_thread(
                user_id,
                AgentThreadCreate(
                    model_config_id=request.model_config_id,
                    capability=request.capability,
                ),
            )
            thread_id = thread.thread_id

        # 3. 创建对话任务
        run_request = AgentRunCreate(
            message=request.message,
            model_config_id=request.model_config_id,
            capability=request.capability,
            client_request_id=request.client_request_id,
        )
        return await self.create_run(user_id, thread_id, run_request)

    async def get_run(self, user_id: int, run_id: uuid.UUID, *, for_update: bool = False) -> AgentRun:
        """按用户和任务 ID 查询 Run，可选择加行锁。"""
        stmt = select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
        if for_update:
            stmt = stmt.with_for_update()
        run = (await self.db.execute(stmt)).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent 任务不存在")
        return run

    async def get_run_response(self, user_id: int, run_id: uuid.UUID) -> AgentRunResponse:
        """查询 Run 并转换为接口响应。"""
        return self.to_run_response(await self.get_run(user_id, run_id))

    async def get_active_run(
        self,
        user_id: int,
        thread_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgentRun | None:
        """查询会话中唯一的非终态 Run，可选择加行锁。"""
        stmt = select(AgentRun).where(
            AgentRun.thread_id == thread_id,
            AgentRun.user_id == user_id,
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def request_abort(self, user_id: int, run_id: uuid.UUID) -> AgentRun:
        """请求中断任务；pending 立即取消，running 标记为等待中断。"""
        run = await self.get_run(user_id, run_id, for_update=True)
        if run.status == "pending":
            run.status = "canceled"
            run.finish_reason = "abort"
            run.finished_at = datetime.now()
            await self._update_assistant(run, status="canceled", finish_reason="abort")
        elif run.status == "running":
            run.status = "cancel_requested"
        await self.db.flush()
        return run

    async def _get_by_client_request(self, user_id: int, client_request_id: str) -> AgentRun | None:
        """通过客户端幂等键查询已创建的 Run。"""
        stmt = select(AgentRun).where(
            AgentRun.user_id == user_id,
            AgentRun.client_request_id == client_request_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _update_assistant(self, run: AgentRun, *, status: str, finish_reason: str | None = None) -> None:
        """同步更新 Run 对应的助手消息状态。"""
        message = (
            await self.db.execute(select(AgentMessage).where(AgentMessage.id == run.assistant_message_id))
        ).scalar_one()
        message.content = run.content_snapshot
        message.status = status
        message.finish_reason = finish_reason

    @staticmethod
    def _initial_title(message: str) -> str:
        """从首条用户消息生成最多 40 个字符的初始标题。"""
        title = " ".join(message.strip().split())
        return title[:40] or "New conversation"

    @staticmethod
    def to_thread_response(thread: AgentThread) -> AgentThreadResponse:
        """把会话 ORM 模型转换为接口模型。"""
        return AgentThreadResponse(
            thread_id=thread.id,
            title=thread.title,
            capability=thread.capability,
            model_config_id=thread.model_config_id,
            status=thread.status,
            message_count=thread.message_count,
            last_message_at=thread.last_message_at,
            created_at=thread.created_at,
        )

    @staticmethod
    def to_run_response(run: AgentRun) -> AgentRunResponse:
        """把 Run ORM 模型转换为接口模型。"""
        usage = None
        if run.input_tokens is not None or run.output_tokens is not None or run.total_tokens is not None:
            usage = {
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "total_tokens": run.total_tokens,
            }
        return AgentRunResponse(
            run_id=run.id,
            thread_id=run.thread_id,
            user_message_id=run.user_message_id,
            assistant_message_id=run.assistant_message_id,
            status=run.status,
            content=run.content_snapshot,
            last_event_id=run.last_event_id,
            model_name=run.model_name,
            usage=usage,
            error_message=run.error_message,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )

    @staticmethod
    def to_message_response(message: AgentMessage) -> AgentMessageResponse:
        """把消息 ORM 模型转换为接口模型。"""
        return AgentMessageResponse(
            message_id=message.id,
            run_id=message.run_id,
            role=message.role,
            content=message.content,
            sequence=message.sequence,
            status=message.status,
            model_config_id=message.model_config_id,
            model_name=message.model_name,
            citations=message.citations or [],
            tool_calls=message.tool_calls or [],
            created_at=message.created_at,
        )


async def claim_next_run(db: AsyncSession, worker_id: str) -> AgentRun | None:
    """使用 SKIP LOCKED 原子领取最早的 pending Run。"""
    stmt = (
        select(AgentRun)
        .where(AgentRun.status == "pending")
        .order_by(AgentRun.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        return None
    now = datetime.now()
    run.status = "running"
    run.worker_id = worker_id
    run.started_at = run.started_at or now
    run.lease_expires_at = now + timedelta(seconds=settings.AGENT_RUN_LEASE_SECONDS)
    run.attempt_count = (run.attempt_count or 0) + 1
    await db.flush()
    return run

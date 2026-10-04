FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先安装依赖，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install -r requirements.txt

# 再复制业务代码，避免代码变更导致依赖层失效
COPY alembic ./alembic
COPY app ./app
COPY alembic.ini .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

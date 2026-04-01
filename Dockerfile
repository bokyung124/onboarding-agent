FROM python:3.12-slim

WORKDIR /app

# 의존성 설치 (pipeline/dev extras 제외)
COPY pyproject.toml uv.lock ./
RUN pip install uv --quiet --root-user-action=ignore && uv sync --no-dev --no-install-project \
    --no-extra pipeline

# 서빙 소스 + 드립 캠페인 파이프라인 복사
COPY app/ ./app/
COPY pipeline/ ./pipeline/

ENV PORT=8080

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

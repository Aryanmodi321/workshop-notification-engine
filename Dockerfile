FROM python:3.12-slim
WORKDIR /service
COPY pyproject.toml README.md ./
COPY app ./app
COPY mock_service ./mock_service
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1

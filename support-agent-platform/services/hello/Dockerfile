# Multi-stage, non-root, slim. Enterprise container hygiene from the first image.
FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
# Non-root user.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
COPY --from=build /install /usr/local
WORKDIR /app
COPY app.py .

USER 10001
EXPOSE 8080
# Single worker is plenty for hello-world; HPA scales pods, not workers.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]

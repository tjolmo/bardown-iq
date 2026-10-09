FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# the commit a frozen image was built from (the forward service in docker-compose.yml), printed at startup
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=$GIT_COMMIT
# print() lines (pipeline steps, prediction log summaries) reach docker logs as they happen
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

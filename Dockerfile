FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
# Persist search history on a local volume. No paid database.
ENV HISTORY_DB=/data/search_history.db
VOLUME ["/data"]

EXPOSE 8080

CMD gunicorn --bind 0.0.0.0:$PORT app:app 
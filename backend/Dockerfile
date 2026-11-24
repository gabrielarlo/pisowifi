FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PISO_DB_PATH=/data/pisowifi.db
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

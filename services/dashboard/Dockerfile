FROM python:3.11-slim
WORKDIR /app
COPY services/dashboard/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/shared /shared
COPY services/dashboard/ .
EXPOSE 8020
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8020"]

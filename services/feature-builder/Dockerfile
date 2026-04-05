FROM python:3.11-slim
WORKDIR /app
COPY services/feature-builder/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/shared /shared
COPY services/feature-builder/ .
EXPOSE 8002
CMD ["python", "main.py"]

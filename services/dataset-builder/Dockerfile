FROM python:3.11-slim
WORKDIR /app
COPY services/dataset-builder/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/shared /shared
COPY services/dataset-builder/ .
EXPOSE 8003
CMD ["python", "main.py"]

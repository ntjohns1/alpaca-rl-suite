FROM python:3.11-slim

WORKDIR /app

# Install Kaggle CLI and dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY services/kaggle-orchestrator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/shared /shared
COPY services/kaggle-orchestrator/ .

EXPOSE 8011

CMD ["python", "main.py"]

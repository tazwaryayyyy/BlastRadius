FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cache layer)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ .

# Copy demo assets
COPY demo_repo/ /app/demo_repo/
COPY demo_prs/ /app/demo_prs/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

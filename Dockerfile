FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Remove bytecodes incompatíveis
RUN find . -name "*.pyc" -delete 2>/dev/null || true

CMD ["python", "main.py"]

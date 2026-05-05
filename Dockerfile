FROM python:3.11-slim

WORKDIR /app

# Copia requirements primeiro (melhor uso de cache do Docker)
COPY requirements.txt .

# Instala dependências com versões fixadas
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do projeto
COPY . .

# Remove bytecode incompatível se existir
RUN find . -name "*.pyc" -delete && find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

CMD ["python", "main.py"]

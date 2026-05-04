FROM python:3.11-slim

WORKDIR /app

# Instalando as ferramentas necessárias
RUN pip install --no-cache-dir python-telegram-bot google-generativeai

COPY . .

# No Railway não precisa de EXPOSE, mas não faz mal deixar
CMD ["python", "main.py"]

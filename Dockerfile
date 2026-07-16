FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8080"]
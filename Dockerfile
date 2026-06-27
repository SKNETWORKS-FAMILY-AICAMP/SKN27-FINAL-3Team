FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=1 \
    DJANGO_ALLOWED_HOSTS=*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY backend ./backend

RUN python backend/manage.py check

EXPOSE 8000

CMD ["python", "backend/manage.py", "runserver", "0.0.0.0:8000", "--noreload"]

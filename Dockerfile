FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ./*.py ./
COPY routers ./routers
COPY pipeline ./pipeline
COPY pa_tools ./pa_tools
COPY services ./services
COPY static ./static
COPY public ./public
COPY dashboard_app ./dashboard_app
COPY templates ./templates
COPY config.json ./config.json
COPY CLAUDE.md ./CLAUDE.md

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "gateway.py"]

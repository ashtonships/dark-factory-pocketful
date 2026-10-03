FROM python:3.12-slim

WORKDIR /app
COPY core.py server.py ./
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "server.py"]

FROM python:3.12-slim

WORKDIR /app
COPY core.py server.py state.py holds.py history.py history_store.py corrections.py ./
COPY ui/ ./ui/
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "server.py"]

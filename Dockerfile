FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY sample_docs sample_docs
RUN useradd -r -u 10001 app && mkdir -p /data && chown app /data
ENV DB_PATH=/data/docs.db UPLOAD_DIR=/data/uploads
VOLUME /data
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

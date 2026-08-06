FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY data_digger.py ./
COPY digital_detective ./digital_detective

RUN useradd --create-home detective && mkdir /reports && chown detective:detective /reports
USER detective
ENTRYPOINT ["python", "data_digger.py"]
CMD ["--help"]

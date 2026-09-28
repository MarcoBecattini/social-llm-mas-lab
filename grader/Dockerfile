# Slim grader for the paper's task pools: same Python and evaluation code as the official BigCodeBench image,
# without the heavy runtimes the pools exclude. Built for linux/amd64 (Render).
FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 MPLBACKEND=Agg
RUN apt-get update && apt-get install -y --no-install-recommends g++ python3-tk libfreetype6-dev libpng-dev pkg-config python3-dev procps \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /grader
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY bigcodebench_eval ./bigcodebench_eval
COPY server.py ./
RUN useradd --create-home --uid 10002 grader && chown -R grader:grader /grader && chmod 1777 /tmp
USER grader
ENV PORT=10000 GRADER_WORKERS=2
EXPOSE 10000
CMD ["python", "server.py"]

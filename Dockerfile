FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
WORKDIR /srv
COPY requirements.txt pyproject.toml README.md ./
COPY socialmas ./socialmas
RUN pip install -r requirements.txt && pip install --no-deps .
COPY app ./app
COPY .streamlit ./.streamlit
RUN useradd --create-home --uid 10001 app && chown -R app:app /srv
USER app
EXPOSE 8501
CMD ["sh", "-c", "streamlit run app/streamlit_app.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]

FROM python:3.13-slim
WORKDIR /app

COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY ui ./ui
COPY .streamlit/config.toml ./.streamlit/config.toml
RUN python -m pip install --no-cache-dir --no-deps . \
    && useradd --create-home --uid 10001 neurocoach \
    && install -d -o neurocoach -g neurocoach /app/data

ENV NEUROCOACH_DATA_DIR=/app/data
USER neurocoach
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "ui/app.py", "--server.address=0.0.0.0", "--server.headless=true"]

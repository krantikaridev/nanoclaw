FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Minimal runtime dependencies used by clean_swap.py.
RUN pip install --no-cache-dir web3 python-dotenv

COPY . /app

CMD ["python", "clean_swap.py"]

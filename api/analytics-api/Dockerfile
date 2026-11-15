FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The analytics-api code imports itself as `projection_api`, so stage the source
# under that package name at runtime.
COPY . /app/projection_api/

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "projection_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

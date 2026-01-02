FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY dental_requirements.txt .
RUN pip install --no-cache-dir -r dental_requirements.txt

# Copy application
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "-m", "app.main"]

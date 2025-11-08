FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "tools/evaluate.py", "--queries", "data/prefix_queries.csv", "--output", "reports/evaluation_template.csv"]
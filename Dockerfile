FROM python:3.12-slim

# Instala dependências de sistema necessárias para compilação e manipuladores de PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Configura timezone
ENV TZ=America/Araguaina
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Copia requirements e instala dependências
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia código-fonte
COPY src/ ./src
COPY .env.example .

# Volume de dados persistente
VOLUME ["/app/data"]

CMD ["python", "-m", "src.main"]

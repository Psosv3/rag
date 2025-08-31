FROM python:3.11-slim

# Définir le répertoire de travail
WORKDIR /app

# Installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libopenblas-dev \
    libomp-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copier les fichiers de requirements
COPY requirements.txt .

RUN pip install uv

# Installer les dépendances Python avec environnement virtuel
RUN uv venv /app/.venv && \
    uv pip install --no-cache-dir -r requirements.txt

# Vérifier la version de pip et tester l'installation de numpy
RUN /app/.venv/bin/pip --version
RUN /app/.venv/bin/python -c "import numpy; print('Numpy version:', numpy.__version__)"

# Copier le code de l'application
COPY . .

# Créer le dossier data s'il n'existe pas
RUN mkdir -p /app/data

# Exposer le port
EXPOSE 8000

# Variables d'environnement
ENV PYTHONPATH=/app:/app/dev/src
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Commande pour démarrer l'application
CMD ["/app/.venv/bin/uvicorn", "dev.src.app.app:app", "--host", "0.0.0.0", "--port", "8000"] 
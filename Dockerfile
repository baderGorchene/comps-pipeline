FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

# HF Spaces runs containers as non-root user with UID 1000
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Install project and production WSGI dependencies
COPY --chown=user pyproject.toml README.md $HOME/app/
COPY --chown=user src $HOME/app/src
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir gunicorn whitenoise .

# Copy the rest of the application
COPY --chown=user . $HOME/app

# Ensure writable directories exist for runtime output/input
RUN mkdir -p data/input data/output data/cache && \
    chown -R user:user $HOME/app

USER user

EXPOSE 7860

CMD ["gunicorn", "web.wsgi:application", "--bind", "0.0.0.0:7860", "--workers", "2", "--timeout", "120"]


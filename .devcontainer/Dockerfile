FROM mcr.microsoft.com/devcontainers/python:3.12

# Install system dependencies
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        portaudio19-dev \
        tesseract-ocr \
        ffmpeg \
        xvfb \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# Install PowerShell
RUN pwsh -Command "Set-PSRepository -Name PSGallery -InstallationPolicy Trusted" 2>/dev/null || true

# Pre-create venv (will be populated by postCreateCommand)
RUN python -m venv /workspaces/J.A.R.V.I.S/venv

# Set environment
ENV PATH="/workspaces/J.A.R.V.I.S/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

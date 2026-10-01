
FROM python:3.11-slim
WORKDIR /app

# Create a non-root user
RUN adduser --disabled-password --gecos "" myuser

# Switch to the non-root user
USER myuser

# Set up environment variables - Start
ENV PATH="/home/myuser/.local/bin:$PATH"

ENV GOOGLE_GENAI_USE_ENTERPRISE=1
ENV GOOGLE_CLOUD_PROJECT=crp-pro-cx-orquestacion
ENV GOOGLE_CLOUD_LOCATION=us-central1

# Set up environment variables - End

# Install ADK - Start
RUN ["pip", "install", "google-adk[a2a]==2.10.0"]
# Remove dev_server.py to ensure production-safe endpoints only (disabling dev endpoints in production)
# Shell form on purpose: this instruction interpolates nothing, and `|| true`
# is shell syntax. Do not add a `{...}` placeholder to it without moving it to
# exec form first.
RUN python -c "import os, glob, google.adk.cli as cli; d = os.path.dirname(cli.__file__); [os.remove(f) for f in glob.glob(os.path.join(d, 'dev_server*'))]; [os.remove(f) for f in glob.glob(os.path.join(d, '__pycache__', 'dev_server*'))]" || true
# Install ADK - End

# Copy agent - Start

# Set permission
COPY --chown=myuser:myuser "agents/agente_3/" "/app/agents/agente_3/"

# Copy agent - End

# Install Agent Deps - Start
RUN ["pip", "install", "-r", "/app/agents/agente_3/requirements.txt"]
# Install Agent Deps - End

EXPOSE 8080

CMD ["adk", "api_server", "--port=8080", "--host=0.0.0.0", "--session_service_uri=agentengine://projects/365635075676/locations/us-central1/reasoningEngines/1855385739697586176", "--memory_service_uri=agentengine://projects/365635075676/locations/us-central1/reasoningEngines/1855385739697586176", "--a2a", "--gemini_enterprise_app_name=agente_3", "/app/agents"]

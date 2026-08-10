# Packages the Omnigent orchestrator (router + CrewAI Flow + CLI).
#
# IMPORTANT: the harness CLIs (claude, grok, codex) are NOT in this image.
# They hold YOUR logged-in subscriptions on the host. Two ways to use Docker:
#
#   1) Orchestrator-only (recommended): run natively on the host where the CLIs
#      live. This image is for packaging/CI of the omnigent code itself.
#   2) Full container: install the agent CLIs into the image and provide their
#      credentials (API keys via env, e.g. ANTHROPIC_API_KEY / OPENAI_API_KEY /
#      XAI_API_KEY, or mounted CLI config dirs). Subscription logins don't
#      transfer automatically — this is the honest catch the design doc skipped.
FROM python:3.11-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .

# Mount your projects here: docker run -v /path/to/projects:/projects ...
VOLUME ["/projects"]

ENTRYPOINT ["omnigent"]
CMD ["list"]

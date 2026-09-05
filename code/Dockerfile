# Orbit API — container image.
# Pure standard-library app: no pip install needed. Runs anywhere Docker runs,
# on any cloud or a plain VPS. Fully provider-neutral.

FROM python:3.12-slim

# Non-root user for safety.
RUN useradd --create-home --uid 10001 orbit
WORKDIR /app

# Copy the package and entrypoints.
COPY orbit/ ./orbit/
COPY pyproject.toml README.md ./

# Persist the JSON store in a mounted volume so data survives restarts.
# Set DATABASE_URL instead to use PostgreSQL (the SQL plan). Set ORBIT_TOKEN
# to require a token on write endpoints.
ENV ORBIT_HOST=0.0.0.0 \
    ORBIT_PORT=8080 \
    ORBIT_DB=/data/orbit.json
VOLUME ["/data"]
RUN mkdir -p /data && chown orbit:orbit /data

USER orbit
EXPOSE 8080

# Simple healthcheck hitting the /health endpoint via stdlib urllib.
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
url='http://127.0.0.1:'+os.environ.get('ORBIT_PORT','8080')+'/health'; \
sys.exit(0) if urllib.request.urlopen(url, timeout=2).status==200 else sys.exit(1)"

CMD ["python", "-m", "orbit.api"]

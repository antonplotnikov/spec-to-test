# Spec-to-Test with the Automation tab: the Streamlit app, the pinned Node
# toolchain (Playwright test runner + Playwright MCP server) and Chromium.
#
#   docker compose up --build        then open http://localhost:8501
#
# The base image ships Node and the Chromium build that @playwright/test 1.63.0
# expects (revision 1243), so no browser is downloaded at build time.
FROM mcr.microsoft.com/playwright:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-ai.txt requirements-automation.txt ./
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install -r requirements-automation.txt
ENV PATH=/opt/venv/bin:$PATH

COPY automation/runner/package.json automation/runner/package-lock.json automation/runner/
RUN cd automation/runner && npm ci --ignore-scripts --no-audit --no-fund

COPY . .

# Shared server defaults: work stays in each browser session; job files go to a
# private temp folder. The container is the sandbox for Chromium (non-root,
# no capabilities, read-only root file system, resource limits in compose), so
# Chromium's own sandbox, which needs extra kernel privileges here, is off.
ENV SPEC_TO_TEST_STORAGE=session \
    AUTOMATION_CHROMIUM_SANDBOX=false

USER pwuser
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python3 -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status != 200)"
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]

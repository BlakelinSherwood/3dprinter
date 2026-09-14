# Part Studio, cloud edition: the same studio (viewer/server.py) run with
# STUDIO_MODE=cloud for designing from a phone. Design tools only - CadQuery,
# the mesh stack and the Claude CLI. No slicer, no Blender, no printer access.
FROM python:3.13-slim-bookworm

# OpenCASCADE/VTK wheels link these even though nothing is ever drawn.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git \
      libgl1 libegl1 libglib2.0-0 libx11-6 libxext6 libxrender1 libxt6 libxi6 \
      libgomp1 libfontconfig1 libfreetype6 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app

# --no-deps is deliberate: every real dependency is pinned (see setup-cad.sh)
COPY scripts/requirements-cad.txt scripts/requirements-cad.txt
RUN pip install --no-cache-dir --no-deps -r scripts/requirements-cad.txt \
 && python -c "import cadquery as cq, trimesh, manifold3d, rtree, matplotlib, segno, lxml; \
from tweaker3.MeshTweaker import Tweak; \
cq.exporters.export(cq.Workplane().box(10, 10, 10), '/tmp/smoke.stl'); \
print('cad stack ok')" \
 && rm -f /tmp/smoke.stl

# Claude Code CLI for describe-to-build, installed for the app user and pinned.
# Its sign-in arrives at runtime as CLAUDE_CODE_OAUTH_TOKEN (a Railway variable).
ARG CLAUDE_CODE_VERSION=2.1.266
USER app
RUN curl -fsSL https://claude.ai/install.sh | bash -s "$CLAUDE_CODE_VERSION" \
 && /home/app/.local/bin/claude --version
USER root

COPY viewer viewer
COPY models models
COPY scripts/cloud-entrypoint.sh scripts/cloud-entrypoint.sh

ENV STUDIO_MODE=cloud \
    STUDIO_DATA=/data \
    PATH="/home/app/.local/bin:${PATH}" \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    MPLBACKEND=Agg \
    PYTHONUNBUFFERED=1

# Starts as root only long enough to hand the mounted volume to the app user.
CMD ["sh", "/app/scripts/cloud-entrypoint.sh"]

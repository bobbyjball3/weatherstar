# Weather Star — Jellyfin streamer image (software encoding).
#
# This image runs `weatherstar-stream` headless: it renders the show offscreen
# with SDL's dummy drivers and broadcasts H.264 (libx264) + AAC as HLS. It works
# on any CPU and is the right image for development/CI.
#
# For the RK1/RK3588 (hardware h264_rkmpp encode) build the rk1 variant instead:
#
#     docker build -f Dockerfile.rk1 -t weatherstar-stream:rk1 .
#
# The only runtime requirement beyond Python + pygame is an ffmpeg on PATH. The
# image ships the Python package plus static_assets (fonts/backgrounds/logos/
# icons/music); bake a config.toml into a derived image (default CMD path:
# /etc/weatherstar/config.toml) and no runtime mounts are needed.

FROM python:3.10-slim

# ffmpeg (Debian ships libx264 builds) + SDL + fonts so pygame works headless.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      libsdl2-2.0-0 \
      libsdl2-ttf-2.0-0 \
      fonts-dejavu-core \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install the project into a venv. The repo is copied so `uv sync` is not
# needed at runtime; pip is sufficient for the stream image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /srv/weatherstar
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY static_assets ./static_assets

# Bake the Weather Star config where the default CMD looks for it. Swap in a
# different file (same path) via a derived image when your config differs.
RUN mkdir -p /etc/weatherstar
COPY deploy/weatherstar-config.toml /etc/weatherstar/config.toml

RUN pip install --no-cache-dir .

# Headless render + no audio device access.
ENV SDL_VIDEODRIVER=dummy \
    SDL_AUDIODRIVER=dummy \
    PYGAME_HIDE_SUPPORT_PROMPT=1

# Runtime mounts: none are required — bake your config/assets/music into a
# derived image (e.g. `FROM weatherstar-stream` + `COPY config.toml
# /etc/weatherstar/config.toml`). HLS segments go to the container's own
# writable filesystem.

EXPOSE 8080
ENTRYPOINT ["weatherstar-stream"]
CMD ["--config", "/etc/weatherstar/config.toml"]

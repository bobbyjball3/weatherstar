# Weather Star streamer — Nomad job (Docker driver)
#
# Runs `weatherstar-stream` on the RK1 with hardware h264_rkmpp encoding and
# publishes the channel through Consul + Traefik at:
#
#     http://weatherstar.nomad/channel.m3u
#
# Everything the app needs (config.toml, assets, music) is baked into the image;
# this job mounts nothing and passes nothing through besides VPU access. Traefik
# (with the consul-catalog provider enabled) picks the service up from the
# `traefik.*` tags below, so no extra Traefik config is needed. Jellyfin uses the
# same hostname for the M3U tuner.
#
# Apply with:
#     nomad job run deploy/weatherstar-stream.nomad.hcl
#
# Prereqs on the Nomad client (the RK1):
#   * /dev/mpp_service and /dev/dri present on the host (VPU access for rkmpp)
#   * Consul agent reachable so the service + health check register
#
# VPU access: the task runs `privileged = true` rather than the docker driver's
# `devices` passthrough. Nomad/Docker device forwarding has been unreliable
# (the container would fail to see the nodes), while privileged mode reliably
# exposes all host devices — the RK1's /dev/mpp_service and /dev/dri included.

job "weatherstar-stream" {
  datacenters = ["dc1"]
  type        = "service"

  group "stream" {
    # A single, always-on channel. Do NOT scale this group: each alloc would
    # run its own show + HLS window behind the same hostname.
    count = 1

    network {
      port "http" {
        static = 8080
      }
    }

    # Consul service + Traefik routing. Traefik's consul-catalog provider reads
    # the `traefik.*` tags: route Host `weatherstar.nomad` on the `web`
    # entrypoint to this task's http port.
    service {
      name = "weatherstar-stream"
      port = "http"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.weatherstar.rule=Host(`weatherstar.nomad`)",
        "traefik.http.routers.weatherstar.entrypoints=web",
        "traefik.http.routers.weatherstar.service=weatherstar",
        "traefik.http.services.weatherstar.loadbalancer.server.port=8080",
        # Optional HTTPS: uncomment and point at your ACME certresolver.
        # "traefik.http.routers.weatherstar.entrypoints=websecure",
        # "traefik.http.routers.weatherstar.tls.certresolver=letsencrypt",
        # "traefik.http.routers.weatherstar.tls=true",
      ]

      # Liveness: the M3U endpoint answers as soon as the HTTP server is up.
      check {
        type     = "http"
        path     = "/channel.m3u"
        interval = "15s"
        timeout  = "3s"
      }
    }

    task "stream" {
      driver = "docker"

      # Graceful shutdown: our SIGTERM handler stops the render loop and lets
      # ffmpeg finalize the HLS playlist.
      kill_signal  = "SIGTERM"
      kill_timeout = "15s"

      config {
        # Local image cache: the image is exported on the build machine and
        # `docker load`ed into each Nomad client's local Docker daemon BEFORE
        # this job runs (commands in docs/STREAMING.md). `force_pull = false`
        # (the default) means Nomad uses the local copy and never reaches for a
        # registry while it is present.
        image       = "weatherstar-stream:rk1"
        force_pull  = false
        # VPU access for h264_rkmpp: Nomad's docker `devices` passthrough proved
        # unreliable here, so run privileged (host /dev/mpp_service + /dev/dri
        # are then visible to the container).
        privileged  = true

        ports = ["http"]

        # Point at the config baked into your image. Omit `args` entirely if
        # your image's default CMD already names it.
        # args = ["--config", "/etc/weatherstar/config.toml"]
      }

      env {
        SDL_VIDEODRIVER = "dummy"
        SDL_AUDIODRIVER = "dummy"

        # Routing + encoder. The stream advertises THIS URL in its M3U so
        # Jellyfin reaches it through Traefik (same hostname it uses to fetch
        # /channel.m3u). Matches the Host(...) rule above.
        WEATHERSTAR_STREAM_PUBLIC_URL    = "http://weatherstar.nomad"
        WEATHERSTAR_STREAM_VIDEO_ENCODER = "h264_rkmpp"
      }

      resources {
        cpu    = 1500    # MHz (RK1: shared with VPU encode offload)
        memory = 512
      }

      logs {
        max_files     = 3
        max_file_size = 10
      }
    }
  }
}


# Weather Star streamer — Nomad job (Docker driver)
#
# Runs `weatherstar-stream` on the RK1 with hardware h264_rkmpp encoding and
# publishes the HLS/HTTP port for Jellyfin Live TV.
#
# Apply with:
#     nomad job run deploy/weatherstar-stream.nomad.hcl
#
# Then add an M3U Tuner in Jellyfin pointing at:
#     http://<weatherstar-host>:8080/channel.m3u

job "weatherstar-stream" {
  datacenters = ["dc1"]
  type        = "service"

  group "stream" {
    count = 1

    network {
      port "http" {
        static = 8080
      }
    }

    # Bind-mount the simulator's data. The music directory is optional but the
    # config + writable HLS dir are required.
    volume "config" {
      type      = "host"
      source    = "weatherstar-config"   # a host volume in your cluster
      read_only = true
    }
    volume "assets" {
      type      = "host"
      source    = "weatherstar-assets"
      read_only = true
    }
    volume "music" {
      type      = "host"
      source    = "weatherstar-music"
      read_only = true
    }
    volume "hls" {
      type   = "host"
      source = "weatherstar-hls"
    }

    task "stream" {
      driver = "docker"

      config {
        image = "registry.example.com/weatherstar-stream:rk1"

        # Rockchip VPU access for h264_rkmpp.
        devices = [
          {
            host_path = "/dev/mpp_service"     # RK3588 MPP service node
          },
          {
            host_path = "/dev/dri"             # DRM render nodes (rkmpp/DRM)
          },
        ]

        mounts = [
          {
            type     = "volume"
            target   = "/config"
            source   = "config"
            readonly = true
          },
          {
            type     = "volume"
            target   = "/assets"
            source   = "assets"
            readonly = true
          },
          {
            type     = "volume"
            target   = "/music"
            source   = "music"
            readonly = true
          },
          {
            type     = "volume"
            target   = "/data/hls"
            source   = "hls"
          },
        ]

        ports = ["http"]

        # Graceful shutdown: our SIGTERM handler stops the render loop and lets
        # ffmpeg finalize the HLS playlist.
        kill_signal = "SIGTERM"
        kill_timeout = "15s"
      }

      env {
        SDL_VIDEODRIVER              = "dummy"
        SDL_AUDIODRIVER              = "dummy"
        WEATHERSTAR_STREAM_HLS_DIR   = "/data/hls"
        # The URL Jellyfin reaches this box at. If Jellyfin resolves the host by
        # the same name it uses to fetch /channel.m3u you can omit this; setting
        # it explicitly is the most reliable.
        WEATHERSTAR_STREAM_PUBLIC_URL = "http://weatherstar.lan:8080"
        # Hardware encode on the RK1:
        WEATHERSTAR_STREAM_VIDEO_ENCODER = "h264_rkmpp"
      }

      resources {
        cpu    = 1500    # MHz
        memory = 512
      }

      logs {
        max_files     = 3
        max_file_size = 10
      }
    }
  }
}

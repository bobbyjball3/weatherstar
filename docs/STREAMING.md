# Streaming Weather Star to Jellyfin as a live TV channel

The Weather Star simulator renders to a window on your desktop. This add-on runs
the **same show headless** and broadcasts it as an always-on H.264 + AAC HLS
stream that Jellyfin's **Live TV** consumes through a plain M3U tuner — the goal
being to watch the channel on CRT displays fed by your Jellyfin instance.

Everything described here lives in `src/weatherstar/streaming/` plus its tests, a
console script, `Dockerfile`/`Dockerfile.rk1`, a Nomad job spec, and this page.
It is a **fully optional, self-contained add-on**: the core engine never imports
it, and deleting it leaves the simulator untouched (see
["Removing it"](#removing-it)).

## How it works

```
                     weatherstar.streaming (headless, SDL dummy drivers)
        ┌─────────────────────────────────────────────────────────────┐
        │  Builder.build_runtime()  (public core API, no core changes) │
        │        │ renders to an offscreen pygame.Surface             │
        │  SequenceRunner.step() → BottomTicker/3000Scroll.render()    │
        │        │                                          (loop.py) │
        │  pygame.image.tobytes(surface, "RGB")                       │
        └───────────────┬─────────────────────────────────────────────┘
                        │ one frame per 1/fps sec  (real-time pacing)
                        ▼
                  .video.fifo ─┐                     ffmpeg (encoder.py)
                        ┌──────┴──────────────────────────────► ─c:v h264 | libx264
   music files          │                                           + aac
        │ decode to PCM (audio.py)                                  │
        │ paced at rate·ch·2 bytes/s  ──► .audio.fifo ──►          │
        │ (or anullsrc silence when no music)                       │
        ▼                                                            ▼
                                                        HLS: index.m3u8 + *.ts
                                                                   │
                        ThreadingHTTPServer (server.py)  ◄──────────┘
                        GET /channel.m3u  ── M3U for Jellyfin Live TV
                        GET /guide.xml    ── XMLTV EPG (generated per request)
                        GET /stream/…     ── the HLS window
```

**No core-engine changes.** The streamer drives the exact public APIs the app
already uses for `--validate`: it builds the runtime with `Builder`, steps the
slides with `SequenceRunner`, and draws the same ticker. The only differences
are that it never calls `pygame.display.flip()` (there is no window — SDL runs
under the dummy drivers, exactly like CI) and it *captures* each finished frame
instead.

**Two feeds, both paced in Python.** ffmpeg's HLS muxer is **not** wall-clock
paced — left to its own devices it drains its inputs as fast as it can. Video is
therefore fed one frame per `1/fps` second by the render loop, and the audio
feeder is paced in pure Python at `sample_rate × channels × 2` bytes per second
(ffmpeg stamps PCM by sample count, so feeding at the real-time byte rate keeps
audio glued to video). Because music is *ambient* the encoder only needs A/V
timelines that move together, not sample-perfect lip sync. This is also why
tracks are decoded to temporary raw-PCM files ahead of time rather than pointed
at ffmpeg `-re` decode processes: `-re` does not reliably throttle when the sink
is a fast-draining FIFO.

**One muxing ffmpeg, three native pieces.** Everything else is Python; the only
native binaries are the ffmpeg processes (encode + per-track decode). ffmpeg and
the render loop talk over POSIX FIFOs, which give natural backpressure — a slow
encoder stalls the writer, never drops frames.

**Audio is always present.** If music is enabled and files exist, the shuffled
playlist is streamed (honouring `[media.music] volume`); otherwise the encoder
is fed digital silence (`anullsrc`) so Jellyfin always sees an audio track.

## Prerequisites

- Python 3.10 + `uv` (this repo), and **ffmpeg on PATH**.
  - Development: any ffmpeg with `libx264` (macOS Homebrew, Debian/Ubuntu, …).
  - RK1/RK3588 hardware encode: a Rockchip ffmpeg with `h264_rkmpp` (below).
- A Weather Star config file (the usual `config.toml`).

## Quick start (local)

```sh
uv run weatherstar-stream --config ~/.config/weatherstar/config.toml
```

Without a config file you can pass the essentials (note `channel_number` is
**required** — no baked-in default — so supply it on the CLI or via the
`WEATHERSTAR_STREAM_CHANNEL_NUMBER` env var):

```sh
uv run weatherstar-stream --sequence main --lat 28.54 --lon -81.38 --channel-number 5.1
# or: WEATHERSTAR_STREAM_CHANNEL_NUMBER=5.1 uv run weatherstar-stream --sequence main --lat 28.54 --lon -81.38
```

Check it is live:

```sh
curl -s http://localhost:8080/channel.m3u        # the Jellyfin playlist
curl -s http://localhost:8080/guide.xml          # the XMLTV program guide
curl -s http://localhost:8080/stream/index.m3u8  # the HLS master playlist
```

`ffprobe http://localhost:8080/stream/index.m3u8` (or `mpv` that URL) should
show `h264` + `aac`.

### Configuring music

Add to your `config.toml` (this is the normal Weather Star music config — the
streamer reuses it):

```toml
[media.music]
enabled = true
asset_dir = "static_assets/weatherstar_4000"   # files are read from <asset_dir>/music
volume = 0.6
```

Supported extensions are `mp3`, `ogg`, `wav` (same set the simulator plays).
`asset_dir` may be absolute — handy in a container where music lives on a volume.

## Configuration reference

The streamer reads the optional `[stream]` table of the same `config.toml`,
overridable by `WEATHERSTAR_STREAM_*` environment variables, then by CLI flags
(highest precedence). Resolution and frame rate come from the existing `[video]`
section (`640 × 480 @ 30` by default).

| Field | Env var | CLI | Default | Meaning |
| --- | --- | --- | --- | --- |
| `host` | `WEATHERSTAR_STREAM_HOST` | `--host` | `0.0.0.0` | Interface for the HLS/HTTP server |
| `port` | `WEATHERSTAR_STREAM_PORT` | `--port` | `8080` | TCP port |
| `public_url` | `WEATHERSTAR_STREAM_PUBLIC_URL` | `--public-url` | *(from Host header)* | Externally reachable `scheme://host[:port]` used in the M3U. Set this when Jellyfin reaches the box by a different name than the one it used to fetch `/channel.m3u`. |
| `hls_dir` | `WEATHERSTAR_STREAM_HLS_DIR` | `--hls-dir` | temp `weatherstar-hls` | Where ffmpeg writes `index.m3u8` + segments |
| `hls_time` | `WEATHERSTAR_STREAM_HLS_TIME` | `--hls-time` | `4.0` | Target segment seconds |
| `hls_list_size` | `WEATHERSTAR_STREAM_HLS_LIST_SIZE` | `--hls-list-size` | `6` | Segments in the rolling window |
| `video_encoder` | `WEATHERSTAR_STREAM_VIDEO_ENCODER` | `--video-encoder` | `libx264` | `-c:v`. Use `h264_rkmpp` on the RK1 |
| `preset` | `WEATHERSTAR_STREAM_PRESET` | `--preset` | `veryfast` | Software-encoder preset (ignored for rkmpp) |
| `audio_encoder` | `WEATHERSTAR_STREAM_AUDIO_ENCODER` | `--audio-encoder` | `aac` | `-c:a` (RK3588 has no HW AAC encoder; AAC is cheap in software) |
| `audio_bitrate` | `WEATHERSTAR_STREAM_AUDIO_BITRATE` | — | `128k` | `-b:a` |
| `audio_rate` | `WEATHERSTAR_STREAM_AUDIO_RATE` | — | `48000` | Sample rate fed to the encoder |
| `audio_channels` | `WEATHERSTAR_STREAM_AUDIO_CHANNELS` | — | `2` | Interleaved channels (2 = stereo) |
| `channel_name` | `WEATHERSTAR_STREAM_CHANNEL_NAME` | — | `Weather Star 4000` | Name in the M3U and XMLTV guide |
| `channel_id` | `WEATHERSTAR_STREAM_CHANNEL_ID` | — | `weatherstar-4000` | M3U `tvg-id` / XMLTV channel id |
| `channel_number` | `WEATHERSTAR_STREAM_CHANNEL_NUMBER` | `--channel-number` | *(required)* | Channel number (M3U `tvg-chno` / XMLTV display-name). No default — pick your own so it is never baked into the repo. Any string works; use a decimal for sub-channels (`5.1`/`5.2`). A bare hyphen (`5-1`) is dropped by Jellyfin's M3U tuner, which only keeps numbers it can parse. |
| `channel_logo` | `WEATHERSTAR_STREAM_CHANNEL_LOGO` | — | *(none)* | M3U `tvg-logo` URL |
| `guide_days` | `WEATHERSTAR_STREAM_GUIDE_DAYS` | — | `7` | Days of hourly XMLTV guide generated ahead of "now" |

Other flags: `--music-dir DIR` (stream music from `DIR`, overriding config),
`--no-music` (force silence), `--frames N` (smoke test: stop after N frames),
plus the usual `--config/--sequence/--theme/--lat/--lon/--log-level/--log-file`.

Example `[stream]` block (`channel_number` is required — substitute your own):

```toml
[stream]
host = "0.0.0.0"
port = 8080
public_url = "http://weatherstar.lan:8080"
video_encoder = "libx264"
hls_time = 4.0
hls_list_size = 6
channel_name = "Weather Star 4000"
channel_number = "5.1"
guide_days = 7
```

Running a second instance (e.g. the Weather Star 3000 theme)? Point each at its
own `channel_id` and give them distinct numbers, e.g. `5.1` for the 4000 and
`5.2` for the 3000, so both can appear in one Jellyfin channel list.

## Adding the channel to Jellyfin

1. In Jellyfin go to **Dashboard → Live TV → Tuner Devices → Add**.
2. Choose **M3U Tuner**, and set the file/URL to
   `http://<weatherstar-host>:8080/channel.m3u`.
3. Save and run a scan; a channel named after your `channel_name` should appear
   under Live TV.
4. So clients can show a guide ("on now", etc.), add the EPG in
   **Dashboard → Live TV → Guide Data Providers → Add → XMLTV**, set the file/URL
   to `http://<weatherstar-host>:8080/guide.xml`, and save.
5. Run another scan so Jellyfin matches the guide's channel (`tvg-id`) to the
   tuner channel and fills the listing.

The `/channel.m3u` response is generated **per request**: its stream URL is built
from the `Host` header Jellyfin used (so it always points somewhere reachable),
unless `[stream] public_url` is set, which wins. When deployed with the
Nomad/Traefik job below, `public_url` is `http://weatherstar.nomad`, so the
tuner URL is simply `http://weatherstar.nomad/channel.m3u`.

The `/guide.xml` response is also generated **per request**, anchored to the
moment it is fetched. The channel is 24/7, so no periodic regeneration is
needed: the first hourly programme always opens at the current hour (that block
is "on now") and hourly blocks roll forward for `guide_days`, so clients always
see `Weather Star 4000` as playing now and into the future. The M3U advertises
the guide on its `#EXTM3U` line (`url-tvg=…`), built from the same
`public_url`/`Host` base as the stream URL, so IPTV apps that read the M3U
directly (MisterFin, InFuse, Neptune, …) can auto-discover the EPG without a
separate guide URL — both point at the same host you configured.

Notes:
- Jellyfin treats the channel as a live IPTV source; clients receive the HLS
  directly (or Jellyfin transcodes if needed). Because segments open on
  keyframes (`-g` aligned to `hls_time` + `independent_segments`), clients can
  tune in mid-show and start decoding immediately.
- The stream has no `#EXT-X-ENDLIST` while it runs; it is a rolling window
  (`hls_list_size` segments), so the channel is effectively infinite.
- Only one tuner needs the M3U — every Jellyfin client can then watch.

## Hardware encoding on the RK1 / RK3588 (rkmpp)

`[stream] video_encoder = "h264_rkmpp"` turns on VPU encoding. Debian's ffmpeg
has no rkmpp, so `Dockerfile.rk1` **builds ffmpeg + Rockchip MPP from source**
inside a builder stage and ships the result in `/opt/rockchip`. This is an
arm64 build — run it on the RK1 itself (or an arm64 builder), never on x86:

```sh
docker build -f Dockerfile.rk1 -t weatherstar-stream:rk1 .
```

The build compiles [rockchip-linux/mpp](https://github.com/rockchip-linux/mpp)
(providing `librockchip_mpp`), then ffmpeg `8.1` configured with
`--enable-libdrm --enable-rkmpp`; it takes several minutes. ffmpeg must be
`>= 8.1` — upstream only added the rkmpp *encoders* (`h264_rkmpp`/`hevc_rkmpp`)
in 8.1; 7.1 and earlier ship rkmpp decoders only. `rkmpp` needs the MPP runtime
plus a DRM build dependency, which is why the image also installs `libdrm2` and
why `ffmpeg`/its libs live under `/opt/rockchip`
(`LD_LIBRARY_PATH` is set for you).

At runtime the VPU device nodes must be visible to the container — under Nomad
that's handled by running the task privileged (see below); under plain Docker
you pass them with `--device`. The image already ships
`static_assets` (fonts/backgrounds/logos/icons **and** the built-in smooth-jazz
music) and `deploy/weatherstar-config.toml`, baked to
`/etc/weatherstar/config.toml` (the default `CMD` path). To use a different
config or add extra music, build a small derived image:

```dockerfile
FROM weatherstar-stream:rk1          # or weatherstar-stream (software encode)
COPY my-config.toml /etc/weatherstar/config.toml
COPY extra_music/ /srv/weatherstar/static_assets/weatherstar_4000/music/  # optional extras
```

Under plain Docker the runtime command is then just:

```sh
docker run --rm --device /dev/mpp_service --device /dev/dri \
  -e WEATHERSTAR_STREAM_PUBLIC_URL=http://weatherstar.nomad \
  -p 8080:8080 \
  weatherstar-stream:rk1
```

Verify with `ffmpeg -encoders | grep rkmpp` (inside the container) and watch the
startup log for `encoder_start … -c:v h264_rkmpp`. RK1 caveat: AAC has no
Rockchip hardware encoder, so `audio_encoder = "aac"` runs in software — audio
is tiny compared with video and is not a bottleneck.

## Running on Nomad (Docker)

`deploy/weatherstar-stream.nomad.hcl` is a complete, commented job. It runs the
container **privileged** for VPU access (Nomad/Docker `devices` passthrough
proved unreliable for exposing `/dev/mpp_service` and `/dev/dri`, so the task
uses `privileged = true`, which reliably exposes the host's device nodes to the
container) — config, assets and music are baked into your image. It sets the
rkmpp encoder and registers a **Consul service** whose `traefik.*` tags route
`http://weatherstar.nomad` through Traefik (consul-catalog provider) to the
stream. SIGTERM is honoured (the render loop stops and the HLS window is
finalised) with a 15s kill timeout.

```sh
nomad job run deploy/weatherstar-stream.nomad.hcl
```

The job's `image` is `weatherstar-stream:rk1` with `force_pull = false`, i.e. it
runs from each client's **local Docker image cache** and never touches a
registry. Get the image onto your nodes once (see below), then the job uses it
directly.

**Build → export → import onto the RK1 nodes** (do this from your build machine,
e.g. an Apple Silicon Mac so the arm64 build is native):

```sh
# 1. Build the rk1 image (compiles ffmpeg + Rockchip MPP; takes a few minutes).
docker build -f Dockerfile.rk1 -t weatherstar-stream:rk1 .

# 2. Export it to a tarball (gzip to make the transfer small).
docker save weatherstar-stream:rk1 | gzip > weatherstar-stream-rk1.tar.gz

# 3. Copy it to each Nomad client node that might run the job (the RK1s).
scp weatherstar-stream-rk1.tar.gz <user>@<rk1-node>:/tmp/

# 4. Import (load) it into that node's local Docker daemon.
ssh <user>@<rk1-node> 'gzip -dc /tmp/weatherstar-stream-rk1.tar.gz | docker load'

# 5. Sanity check on the node, then run the job.
ssh <user>@<rk1-node> 'docker images weatherstar-stream:rk1'
nomad job run deploy/weatherstar-stream.nomad.hcl
```

Repeat steps 3–4 for every client in the job's datacenter. If a node's daemon
already has the image, Nomad uses it as-is (no pull); only when it is missing
will Nomad attempt a pull, so import before running. Building directly on an
RK1 node works too and skips the export/import entirely.

No per-route Traefik config is needed: the job's service tags declare the
`Host(weatherstar.nomad)` rule, entrypoint, and backend port, and Traefik
discovers them from Consul (make sure Traefik runs with the
`providers.consulCatalog` provider enabled and a `web` entrypoint). The
streamer listens on **8081** inside the alloc — Traefik already occupies 8080 on
the nodes — and Traefik routes `weatherstar.nomad` to it. The
`WEATHERSTAR_STREAM_PUBLIC_URL` env is set to `http://weatherstar.nomad`, so the
M3U the streamer publishes points back at the Traefik hostname (never a
per-alloc port) — that same hostname is what you give Jellyfin as the M3U tuner
URL:

```
http://weatherstar.nomad/channel.m3u
http://weatherstar.nomad/guide.xml
```

Prereq on the Nomad client (the RK1): `/dev/mpp_service` and `/dev/dri` exist on
the host (privileged mode exposes them to the container). The job makes no other
mounts; make sure your image's default `--config` path matches
where you baked the config, or set it with `args = ["--config", "…"]` in the
job. HLS segments are written to the container's own writable filesystem. If you
use a Traefik `websecure` entrypoint with ACME instead of plain HTTP, flip the
commented TLS tags in the job and change `public_url` to `https://…`.

## Design notes

- **Separate, rippable package.** `src/weatherstar/streaming/` never imports the
  plugin machinery and nothing in `weatherstar` imports it. It talks to the core
  only through public runtime APIs (`Builder`, `SequenceRunner`, the ticker
  classes, `AppConfig`).
- **Python-first.** Orchestration, pacing, the HTTP server and the M3U are pure
  Python (stdlib + pydantic). The only native code is ffmpeg, invoked as a
  subprocess, which the brief explicitly allows.
- **Deterministic pacing.** Both A/V feeds are paced in Python; the encoder and
  per-track decoders never need `-re`/wall-clock modes and a slow encoder
  backpressures rather than corrupting the timeline.
- **Defensive like the app.** One slide throwing renders a placeholder frame and
  the channel continues (logged); only encoder failures stop the stream.
- **Secrets safe.** No credentials are involved; logs go through the engine's
  structlog redactor when `weatherstar` logging is configured.

## Testing

The stream has its own suite (`tests/test_stream_*.py`), fully headless and
offline. ffmpeg-gated tests (`encoder` lifecycle, the end-to-end HLS test)
skip when `ffmpeg` is not on PATH:

```sh
uv run pytest tests/test_stream_*.py -q
```

Run everything (core + stream) with coverage as usual:

```sh
task check && task coverage
```

## Troubleshooting

- **`ffmpeg executable not found`** — install ffmpeg or make sure it is on PATH
  in the container.
- **`ffmpeg exited during stream with code …`** — ffmpeg printed an error to
  stderr (visible in the logs); the most common causes are an unknown encoder
  name and a full disk (HLS segments).
- **No channel appears in Jellyfin** — fetch `/channel.m3u` from the Jellyfin
  host and check the stream URL inside is reachable from Jellyfin; if not, set
  `[stream] public_url`. Also confirm the tuner scan ran.
- **Picture is hidden behind the ticker band / band looks wrong** — the theme's
  bottom band is drawn exactly as in the desktop app; nothing about streaming
  changes screen layout.
- **Music sounds wrong / too fast** — the audio feeder paces in Python; if the
  channel is sped up the encoder is being fed faster than real time, which
  normally only happens if `--frames` (test mode) is left on, or wall-clock
  pacing was disabled in a custom loop.
- **rkmpp: `Cannot load librockchip_mpp` / encoder unavailable** — the Rockchip
  runtime is missing or not on the library path (`ldconfig` in
  `Dockerfile.rk1` handles it); verify the device nodes are mounted and
  `ffmpeg -encoders | grep rkmpp` lists it inside the container.

## Removing it

The streamer is deliberately deletable. The engine never imports it, so the
simulator keeps working unchanged:

- `rm -r src/weatherstar/streaming tests/test_stream_*.py`
- `deploy/` (the Nomad job + baked config), `Dockerfile`, `Dockerfile.rk1`,
  `.dockerignore`
- `docs/STREAMING.md`
- In `pyproject.toml`: remove the `weatherstar-stream` console script.
- In `README.md`: drop the STREAMING doc row.

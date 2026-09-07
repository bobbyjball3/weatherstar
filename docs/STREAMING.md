# Streaming Weather Star to Jellyfin as a live TV channel

The Weather Star simulator renders to a window on your desktop. This add-on runs
the **same show headless** and broadcasts it as an always-on H.264 + AAC HLS
stream that Jellyfin's **Live TV** consumes through a plain M3U tuner — the goal
being to watch the channel on CRT displays fed by your Jellyfin instance.

Everything described here lives in `src/weatherstar_stream/` plus its tests, a
console script, `Dockerfile`/`Dockerfile.rk1`, a Nomad job spec, and this page.
It is a **fully optional, self-contained add-on**: the core engine never imports
it, and deleting it leaves the simulator untouched (see
["Removing it"](#removing-it)).

## How it works

```
                     weatherstar_stream (headless, SDL dummy drivers)
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

Without a config file you can pass the essentials:

```sh
uv run weatherstar-stream --sequence main --lat 28.54 --lon -81.38
```

Check it is live:

```sh
curl -s http://localhost:8080/channel.m3u        # the Jellyfin playlist
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
| `channel_name` | `WEATHERSTAR_STREAM_CHANNEL_NAME` | — | `Weather Star` | Name in the M3U |
| `channel_id` | `WEATHERSTAR_STREAM_CHANNEL_ID` | — | `weatherstar-4000` | M3U `tvg-id` |
| `channel_logo` | `WEATHERSTAR_STREAM_CHANNEL_LOGO` | — | *(none)* | M3U `tvg-logo` URL |

Other flags: `--music-dir DIR` (stream music from `DIR`, overriding config),
`--no-music` (force silence), `--frames N` (smoke test: stop after N frames),
plus the usual `--config/--sequence/--theme/--lat/--lon/--log-level/--log-file`.

Example `[stream]` block:

```toml
[stream]
host = "0.0.0.0"
port = 8080
public_url = "http://weatherstar.lan:8080"
video_encoder = "libx264"
hls_time = 4.0
hls_list_size = 6
channel_name = "Weather Star"
```

## Adding the channel to Jellyfin

1. In Jellyfin go to **Dashboard → Live TV → Tuner Devices → Add**.
2. Choose **M3U Tuner**, and set the file/URL to
   `http://<weatherstar-host>:8080/channel.m3u`.
3. Save and run a scan; a channel named after your `channel_name` should appear
   under Live TV.

The `/channel.m3u` response is generated **per request**: its stream URL is built
from the `Host` header Jellyfin used (so it always points somewhere reachable),
unless `[stream] public_url` is set, which wins.

Notes:
- Jellyfin treats the channel as a live IPTV source; clients receive the HLS
  directly (or Jellyfin transcodes if needed). Because segments open on
  keyframes (`-g` aligned to `hls_time` + `independent_segments`), clients can
  tune in mid-show and start decoding immediately.
- The stream has no `#EXT-X-ENDLIST` while it runs; it is a rolling window
  (`hls_list_size` segments), so the channel is effectively infinite.
- Only one tuner needs the M3U — every Jellyfin client can then watch.

## Hardware encoding on the RK1 / RK3588 (rkmpp)

`[stream] video_encoder = "h264_rkmpp"` turns on VPU encoding. That requires:

1. **A Rockchip ffmpeg.** Debian's ffmpeg has no rkmpp. Get one that was built
   with `--enable-rkmpp` (Rockchip publishes these for their boards / Turing
   Pi RK1 images, or build ffmpeg against `rockchip-mpp`). Keep it on PATH in
   the container.
2. **The MPP runtime** (`librockchip_mpp*`) loadable by that ffmpeg.
3. **The VPU device nodes** exposed to the container.

`Dockerfile.rk1` packages steps 1–2 for you (drop the `ffmpeg` binary and
`librockchip_mpp*.so*` from an RK1 into `vendor/rk1/`, then build):

```sh
docker build -f Dockerfile.rk1 -t weatherstar-stream:rk1 .
```

Step 3 is a container/scheduler concern — the Nomad spec in
[`deploy/weatherstar-stream.nomad.hcl`](../deploy/weatherstar-stream.nomad.hcl)
mounts `/dev/mpp_service` and `/dev/dri`. Under plain Docker the equivalent is:

```sh
docker run --rm \
  --device /dev/mpp_service --device /dev/dri \
  -v /path/config:/config:ro -v /path/music:/music:ro \
  -v /path/hls:/data/hls \
  -e WEATHERSTAR_STREAM_VIDEO_ENCODER=h264_rkmpp \
  -e WEATHERSTAR_STREAM_PUBLIC_URL=http://weatherstar.lan:8080 \
  -p 8080:8080 \
  weatherstar-stream:rk1 --config /config/config.toml
```

Verify with `ffmpeg -encoders | grep rkmpp` and watch the startup log for
`encoder_start … -c:v h264_rkmpp`. RK1 caveat: AAC has no Rockchip hardware
encoder, so `audio_encoder = "aac"` runs in software — audio is tiny compared
with video and is not a bottleneck.

## Running on Nomad (Docker)

`deploy/weatherstar-stream.nomad.hcl` is a complete, commented job: it mounts
the VPU devices, bind-mounts your config/assets/music and a writable HLS volume,
sets the rkmpp encoder + `public_url` env, and forwards port 8080. SIGTERM is
honoured (the render loop stops and the HLS window is finalised) with a 15s
kill timeout.

```sh
nomad job run deploy/weatherstar-stream.nomad.hcl
```

The image expects four mounts:

| Mount | Purpose |
| --- | --- |
| `/config/config.toml` | Weather Star config (the usual one, plus `[stream]`/`[media.music]`) |
| `/assets` | `static_assets` tree (fonts, backgrounds, logos, icons) — `asset_dir` must point here if you override it |
| `/music` | Ambient music files (`asset_dir` → `<dir>/music`) |
| `/data/hls` | Writable rolling HLS window |

Point `[media.music] asset_dir` at the absolute mount path, e.g.
`asset_dir = "/assets/weatherstar_4000"`, or `--music-dir /music`.

## Design notes

- **Separate, rippable package.** `src/weatherstar_stream/` never imports the
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

The streamer is deliberately deletable:

- `rm -r src/weatherstar_stream tests/test_stream_*.py`
- `deploy/` (the Nomad job), `Dockerfile`, `Dockerfile.rk1`, `.dockerignore`
- `docs/STREAMING.md`
- In `pyproject.toml`: remove the `weatherstar-stream` console script,
  `weatherstar_stream` from `[tool.ruff.lint.isort] known-first-party`, and the
  `"src/weatherstar_stream"` entry in `[tool.coverage.run] source`.
- In `README.md`: drop the STREAMING doc row.

None of these are imported by the Weather Star engine, so the simulator keeps
working unchanged.

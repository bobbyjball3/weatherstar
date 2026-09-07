"""Tiny HTTP server publishing the HLS stream + the Jellyfin M3U playlist.

Serving is deliberately dependency-free (stdlib ``http.server``): the whole
point of the streamer is that it must be trivial to rip out, and it runs inside
a container where a hand-rolled static server is more than enough.

Routes:

- ``/``                — tiny HTML index with links (handy for debugging),
- ``/channel.m3u``     — M3U playlist for Jellyfin Live TV (generated per
  request so the stream URL is derived from the Host header Jellyfin used),
- ``/guide.xml``       — XMLTV electronic program guide (generated per request,
  anchored to now so the always-on channel always shows as playing),
- ``/stream/index.m3u8`` and ``/stream/segment_*.ts`` — the HLS output ffmpeg
  writes into ``hls_dir``.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from weatherstar.logging_setup import get_logger
from weatherstar.streaming.m3u import Channel, channel_m3u
from weatherstar.streaming.xmltv import guide_xml

log = get_logger("weatherstar.stream.server")

_SERVED_SUFFIXES = (".m3u8", ".ts", ".vtt")

_INDEX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Weather Star stream</title></head>
<body style="font-family: monospace">
<h1>Weather Star stream</h1>
<ul>
<li><a href="/channel.m3u">Jellyfin M3U playlist</a></li>
<li><a href="/guide.xml">XMLTV program guide</a></li>
<li><a href="/stream/index.m3u8">HLS master playlist</a></li>
</ul>
<p>Add the M3U URL above as a Jellyfin Live TV &rarr; M3U tuner, and the
guide URL above as a Live TV &rarr; guide data provider (XMLTV).</p>
</body></html>
"""


def _base_url(handler: BaseHTTPRequestHandler, public_url: str | None) -> str:
    """Resolve the externally reachable base URL for this stream."""
    if public_url:
        return public_url.rstrip("/")
    host = handler.headers.get("Host")
    if host:
        return f"http://{host}"
    return "http://localhost"


def make_handler(
    hls_dir: Path,
    *,
    channel: Channel,
    public_url: str | None = None,
    guide_days: int = 7,
) -> type[BaseHTTPRequestHandler]:
    """Build a request-handler class serving the HLS directory + channel M3U."""

    root = Path(hls_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "WeatherStarStream/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib hook
            self._dispatch()

        def do_HEAD(self) -> None:  # noqa: N802 - stdlib hook
            self._dispatch(head_only=True)

        def log_message(self, fmt: str, *args: object) -> None:
            log.debug("http_request", message=fmt % args)

        # -- routing -----------------------------------------------------

        def _dispatch(self, head_only: bool = False) -> None:
            path = urlsplit(self.path).path
            if path == "/":
                self._send_bytes(
                    200, _INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8", head_only
                )
            elif path == "/channel.m3u":
                base = _base_url(self, public_url)
                stream_url = f"{base}/stream/index.m3u8"
                guide_url = f"{base}/guide.xml"
                body = channel_m3u(stream_url, channel, guide_url=guide_url).encode("utf-8")
                self._send_bytes(200, body, "application/x-mpegurl", head_only)
            elif path == "/guide.xml":
                body = guide_xml(channel, days=guide_days).encode("utf-8")
                self._send_bytes(200, body, "application/xml", head_only)
            elif path.startswith("/stream/"):
                self._serve_hls(path, head_only)
            else:
                self._send_bytes(404, b"not found", "text/plain", head_only)

        def _serve_hls(self, path: str, head_only: bool) -> None:
            rel = path[len("/stream/") :]
            if "/" in rel or rel in {".", ".."} or not rel.endswith(_SERVED_SUFFIXES):
                self._send_bytes(404, b"not found", "text/plain", head_only)
                return
            candidate = (root / rel).resolve()
            if not str(candidate).startswith(str(root) + "/") or not candidate.is_file():
                self._send_bytes(404, b"not found", "text/plain", head_only)
                return
            content_type = (
                "application/vnd.apple.mpegurl" if rel.endswith(".m3u8") else "video/mp2t"
            )
            with candidate.open("rb") as handle:
                data = handle.read()
            self._send_bytes(200, data, content_type, head_only)

        def _send_bytes(self, status: int, body: bytes, content_type: str, head_only: bool) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

    return Handler


def start_server(
    *,
    host: str,
    port: int,
    hls_dir: Path,
    channel: Channel,
    public_url: str | None = None,
    guide_days: int = 7,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the HTTP server on a background thread; return (server, thread)."""
    handler = make_handler(
        hls_dir,
        channel=channel,
        public_url=public_url,
        guide_days=guide_days,
    )
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, name="hls-http", daemon=True)
    thread.start()
    log.info("http_server_started", host=host, port=port, hls_dir=str(hls_dir))
    return server, thread

"""Tests for the HLS HTTP server and its route handling."""

import http.client
import urllib.parse

import pytest

from weatherstar.streaming.m3u import Channel
from weatherstar.streaming.server import start_server


@pytest.fixture()
def running_server(tmp_path):
    (tmp_path / "index.m3u8").write_text("#EXTM3U\n#EXT-X-VERSION:3\n")
    (tmp_path / "segment_00000.ts").write_bytes(b"\x00\x01\x02segment")
    (tmp_path / "secret.txt").write_text("do not serve")
    server, _thread = start_server(
        host="127.0.0.1",
        port=0,
        hls_dir=tmp_path,
        channel=Channel(name="Weather Star", channel_id="weatherstar-4000"),
        public_url=None,
    )
    port = server.server_address[1]
    yield f"http://127.0.0.1:{port}", tmp_path
    server.shutdown()
    server.server_close()


def _get(base, path):
    parsed = urllib.parse.urlsplit(base)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, resp.getheader("Content-Type"), body


def test_index_page(running_server):
    base, _ = running_server
    status, content_type, body = _get(base, "/")
    assert status == 200
    assert "text/html" in content_type
    assert b"channel.m3u" in body


def test_channel_m3u_uses_host_header(running_server):
    base, _ = running_server
    host = urllib.parse.urlsplit(base).netloc
    status, content_type, body = _get(base, "/channel.m3u")
    assert status == 200
    assert "mpegurl" in content_type
    text = body.decode()
    assert text.startswith("#EXTM3U")
    assert f"http://{host}/stream/index.m3u8" in text
    assert 'tvg-name="Weather Star"' in text


def test_channel_m3u_public_url_override(tmp_path):
    (tmp_path / "index.m3u8").write_text("x")
    server, _thread = start_server(
        host="127.0.0.1",
        port=0,
        hls_dir=tmp_path,
        channel=Channel(),
        public_url="http://rk1:9090",
    )
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    status, _ct, body = _get(base, "/channel.m3u")
    assert status == 200
    # public_url wins over whatever Host the request carried.
    assert b"http://rk1:9090/stream/index.m3u8" in body
    assert b"http://127.0.0.1" not in body
    server.shutdown()
    server.server_close()


def test_serve_segment_and_playlist(running_server):
    base, hls_dir = running_server
    status, content_type, body = _get(base, "/stream/index.m3u8")
    assert status == 200
    assert "apple.mpegurl" in content_type
    assert b"#EXTM3U" in body

    status, content_type, body = _get(base, "/stream/segment_00000.ts")
    assert status == 200
    assert "video/mp2t" in content_type
    assert body == b"\x00\x01\x02segment"


def test_traversal_and_unknown_paths_rejected(running_server):
    base, hls_dir = running_server
    status, _ct, _body = _get(base, "/stream/../secret.txt")
    assert status == 404
    status, _ct, body = _get(base, "/stream/secret.txt")
    assert status == 404
    assert b"do not serve" not in body
    status, _ct, _body = _get(base, "/nope")
    assert status == 404
    status, _ct, _body = _get(base, "/stream/segment_00000.ts/extra")
    assert status == 404


def test_head_request(running_server):
    base, _ = running_server
    parsed = urllib.parse.urlsplit(base)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    conn.request("HEAD", "/stream/index.m3u8")
    resp = conn.getresponse()
    resp.read()
    conn.close()
    assert resp.status == 200
    assert int(resp.getheader("Content-Length")) > 0

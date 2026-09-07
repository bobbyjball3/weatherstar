"""Tests for the streaming render loop (no real encoder/ffmpeg required)."""

import threading
import types

import pygame

from weatherstar.sequence import Sequence
from weatherstar_stream.loop import choose_ticker, run_stream


class _FakeScreen:
    """Minimal stand-in for a Screen: records steps/draws."""

    def __init__(self, name):
        self.name = name
        self.steps = 0
        self.draws = 0

    def step(self, ctx, dt):
        self.steps += 1

    def draw(self, surface, ctx, dt):
        self.draws += 1
        surface.fill((0, 0, 0))


class _FakeTicker:
    def __init__(self):
        self.renders = 0

    def render(self, surface, ctx, dt):
        self.renders += 1
        surface.fill((10, 10, 10))


class _FakeEncoder:
    def __init__(self):
        self.frames = []

    def write_frame(self, data):
        self.frames.append(data)


def _sequence(names=("alpha", "beta")):
    raw = {"pause": 0.001, "slides": [{"screen": n} for n in names]}
    return Sequence.from_config("mini", raw)


def _make_ctx(surface):
    return types.SimpleNamespace(surface=surface)


def test_run_stream_renders_frames_into_encoder(pygame_env):
    surface = pygame.Surface((64, 48))
    screens = [_FakeScreen("alpha"), _FakeScreen("beta")]
    sequence = _sequence()
    encoder = _FakeEncoder()
    ticker = _FakeTicker()
    frames = run_stream(
        types.SimpleNamespace(surface=surface),
        screens,
        sequence,
        encoder=encoder,
        fps=30,
        ticker=ticker,
        max_frames=10,
        wall_clock=False,
    )
    assert frames == 10
    assert len(encoder.frames) == 10
    for frame in encoder.frames:
        assert len(frame) == 64 * 48 * 3
    assert ticker.renders == 10
    # Slides wrapped: every screen drew at least once.
    assert all(s.draws >= 1 for s in screens)


def test_run_stream_stops_on_stop_event(pygame_env):
    surface = pygame.Surface((32, 32))
    screens = [_FakeScreen("alpha")]
    sequence = _sequence(("alpha",))
    encoder = _FakeEncoder()
    stop_event = threading.Event()

    def _set():
        import time

        time.sleep(0.05)
        stop_event.set()

    threading.Thread(target=_set, daemon=True).start()
    frames = run_stream(
        _make_ctx(surface),
        screens,
        sequence,
        encoder=encoder,
        fps=30,
        ticker=_FakeTicker(),
        stop_event=stop_event,
        wall_clock=False,
    )
    assert frames >= 1


def test_run_stream_tolerates_slide_exceptions(pygame_env):
    from weatherstar.context import AppContext

    surface = pygame.Surface((64, 48))

    class _Boom(_FakeScreen):
        def draw(self, surface, ctx, dt):
            raise RuntimeError("boom")

    encoder = _FakeEncoder()
    frames = run_stream(
        AppContext(surface=surface),
        [_Boom("alpha")],
        _sequence(("alpha",)),
        encoder=encoder,
        fps=30,
        ticker=_FakeTicker(),
        max_frames=5,
        wall_clock=False,
    )
    assert frames == 5
    assert len(encoder.frames) == 5


def test_choose_ticker_defaults_to_navy(pygame_env):
    from weatherstar.themes import FALLBACK_THEME

    ctx = types.SimpleNamespace(theme=FALLBACK_THEME)
    ticker = choose_ticker(ctx)
    assert type(ticker).__name__ == "BottomTicker"

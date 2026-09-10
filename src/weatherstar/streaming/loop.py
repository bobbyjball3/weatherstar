"""Headless render loop that streams every frame to an encoder.

This mirrors ``weatherstar.engine.run_sequence``'s non-interactive mode (auto
advance per slide pause, wrap around forever, bottom ticker on every slide) but
is *infinite* and, instead of flipping a display, hands each finished frame to
an encoder object with a ``write_frame(bytes)`` method.

The loop never opens a window: the caller builds an offscreen
``pygame.Surface`` (exactly like ``--validate`` does) and the engine draws onto
it. pygame is imported lazily so importing this module has no side effects.
"""

from __future__ import annotations

from typing import Any

from weatherstar.logging_setup import get_logger
from weatherstar.streaming.encoder import EncoderError

log = get_logger("weatherstar.stream.loop")


def choose_ticker(ctx: Any) -> Any:
    """Return the bottom-band renderer the active theme asks for."""
    from weatherstar.ticker import BottomTicker, WeatherStar3000Scroll

    theme = getattr(ctx, "theme", None)
    from weatherstar.themes import LayoutVariant

    if getattr(theme, "bottom_band", LayoutVariant.WS4000) == LayoutVariant.WS3000:
        return WeatherStar3000Scroll()
    return BottomTicker()


def run_stream(
    ctx: Any,
    screens: list[Any],
    sequence: Any,
    *,
    encoder: Any,
    fps: int = 30,
    stop_event: Any = None,
    ticker: Any = None,
    max_frames: int | None = None,
    wall_clock: bool = True,
) -> int:
    """Draw the sequence forever, feeding each frame to ``encoder``.

    Returns the number of frames drawn. The loop stops when ``max_frames`` is
    reached or ``stop_event.is_set()`` becomes true. ``wall_clock`` paces output
    to real time (always true in production; disable in tests to render as fast
    as possible).
    """
    import pygame

    from weatherstar import render
    from weatherstar.engine import SequenceRunner

    runner = SequenceRunner(ctx, screens, sequence)

    if ticker is None:
        ticker = choose_ticker(ctx)
    clock = pygame.time.Clock()
    slide_index = 0
    slide_elapsed = 0.0
    frames = 0
    running = True

    def _should_stop() -> bool:
        if stop_event is not None and stop_event.is_set():
            return True
        return False

    while running:
        dt_ms = clock.tick(fps) if wall_clock else 1000 // fps
        dt = dt_ms / 1000.0
        frames += 1

        # Advance slides by their configured pause, wrapping forever.
        slide_elapsed += dt_ms
        pause_ms = int(sequence.pause_for(slide_index) * 1000)
        if pause_ms > 0:
            while slide_elapsed >= pause_ms:
                slide_elapsed -= pause_ms
                slide_index = (slide_index + 1) % len(sequence.slides)
                pause_ms = int(sequence.pause_for(slide_index) * 1000)
                if pause_ms <= 0:
                    break
        else:
            slide_index = (slide_index + 1) % len(sequence.slides)
            slide_elapsed = 0.0

        try:
            runner.step(slide_index, dt)
        except Exception as exc:  # noqa: BLE001 - one bad slide must not kill the channel
            log.warning(
                "slide_render_failed",
                screen=sequence.slides[slide_index].screen,
                error=repr(exc),
            )
            render.draw_centered_text(
                ctx.surface,
                ctx,
                "RENDER ERROR",
                240,
                font_name="large",
                color_key="yellow",
            )

        ticker.render(ctx.surface, ctx, dt)

        data = pygame.image.tobytes(ctx.surface, "RGB")
        try:
            encoder.write_frame(data)
        except EncoderError:
            # If we are already stopping (SIGTERM/SIGINT raced a dying ffmpeg),
            # a dead encoder is expected — bow out cleanly instead of surfacing
            # an error on shutdown.
            if _should_stop():
                running = False
                break
            raise

        if max_frames is not None and frames >= max_frames:
            running = False
        if _should_stop():
            running = False

    return frames

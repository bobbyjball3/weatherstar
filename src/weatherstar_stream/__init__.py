"""Weather Star streaming output: broadcast the show to a Jellyfin TV channel.

This package is a fully self-contained, optional add-on. It reuses the core
engine's *public* building blocks (``Builder``, ``SequenceRunner``, the ticker
classes) to render the show offscreen and hands the resulting frames to an
``ffmpeg`` subprocess for H.264/AAC encoding into a rolling HLS window, which a
small HTTP server publishes for Jellyfin's Live TV (M3U tuner).

Nothing in ``weatherstar`` imports this package. Deleting ``weatherstar_stream``
(plus its tests, the ``weatherstar-stream`` console script and the packaging
entries) has no effect on the simulator itself.
"""

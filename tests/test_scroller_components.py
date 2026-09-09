"""Unit tests for the HeadlineScroller and DataTable components."""

import pytest
from pydantic import ValidationError

from weatherstar.context import AppContext, DataRegistry, Location


def _ctx(screen, fonts, *, data=None, location=None):
    return AppContext(
        surface=screen,
        fonts=fonts,
        data=data or DataRegistry(),
        location=location or Location(lat=28.0, lon=-81.0),
    )


def _nonblank(screen, x0, x1, y0, y1):
    return any(
        screen.get_at((x, y))[:3] != (0, 0, 0) for x in range(x0, x1, 4) for y in range(y0, y1, 4)
    )


class _History:
    def __init__(self, rows=None):
        self._rows = rows or [("2026-08-27", 95, 70), ("2026-08-26", 90, 65)]

    def temperature(self, lat, lon):
        return list(self._rows)

    def scroll(self, current_time):
        pass

    @property
    def scroll_offsets(self):
        return (30.0, 0.0)


class _NoNews:
    def headlines(self, lat, lon):
        raise RuntimeError("offline")


def test_headline_scroller_draws_and_steps(screen, fonts):
    from weatherstar.components.headline_scroller import HeadlineScroller

    scroller = HeadlineScroller.model_validate({"numbered": True})
    scroller.set_headlines([("BREAKING: Storm tonight", "u"), "plain headline"])
    ctx = _ctx(screen, fonts)
    before = scroller._scroll
    scroller.step(ctx, dt=1 / 30)
    assert scroller._scroll < before
    scroller.render(screen, ctx)
    assert _nonblank(screen, 55, 585, 100, 398)


def test_headline_scroller_empty_message(screen, fonts):
    from weatherstar.components.headline_scroller import HeadlineScroller

    scroller = HeadlineScroller.model_validate({"empty_text": "No headlines"})
    scroller.render(screen, _ctx(screen, fonts))
    assert _nonblank(screen, 0, 640, 220, 260)


def test_headline_scroller_fetches_from_datasource_and_swallows_errors(screen, fonts):
    from weatherstar.components.headline_scroller import HeadlineScroller

    data = DataRegistry()
    data.register("local_news", _NoNews())
    scroller = HeadlineScroller.model_validate({"datasource_name": "local_news"})
    ctx = _ctx(screen, fonts, data=data)
    scroller.step(ctx, dt=1 / 30)  # datasource raises -> treated as empty, no crash
    scroller.render(screen, ctx)
    assert _nonblank(screen, 0, 640, 220, 260)


def test_data_table_renders_history_rows(screen, fonts):
    from weatherstar.components.data_table import Column, DataTable

    data = DataRegistry()
    data.register("history", _History())
    table = DataTable.model_validate(
        {
            "datasource_name": "history",
            "rows_method": "temperature",
            "columns": [
                Column(header="DATE", header_x=60, x=60, format="date", index=0),
                Column(header="HIGH", header_x=320, x=330, format="degrees", index=1),
                Column(header="LOW", header_x=480, x=490, format="degrees", index=2),
            ],
        }
    )
    ctx = _ctx(screen, fonts, data=data)
    table.step(ctx, dt=1 / 30)
    table.render(screen, ctx)
    # Header text (yellow) present; at least one data row drawn beneath it.
    assert _nonblank(screen, 60, 500, 120, 160)
    assert _nonblank(screen, 60, 500, 160, 320)


def test_data_table_skips_invalid_rows(screen, fonts):
    from weatherstar.components.data_table import Column, DataTable

    data = DataRegistry()
    data.register(
        "history",
        _History(rows=[("2026-08-27", "nope", 70), ("2026-08-26", 90, "bad")]),
    )
    table = DataTable.model_validate(
        {
            "datasource_name": "history",
            "rows_method": "temperature",
            "max_rows": 8,
            "columns": [Column(header="DATE", header_x=60, x=60, format="date", index=0)],
        }
    )
    ctx = _ctx(screen, fonts, data=data)
    table.render(screen, ctx)
    assert _nonblank(screen, 60, 200, 120, 320)


def test_data_table_empty_when_datasource_has_no_rows(screen, fonts):
    from weatherstar.components.data_table import DataTable

    class _Empty:
        def temperature(self, lat, lon):
            return []

        def scroll(self, current_time):
            pass

        @property
        def scroll_offsets(self):
            return (0.0, 0.0)

    data = DataRegistry()
    data.register("history", _Empty())
    table = DataTable.model_validate(
        {
            "datasource_name": "history",
            "rows_method": "temperature",
            "empty_text": "No data",
            "columns": [],
        }
    )
    table.render(screen, _ctx(screen, fonts, data=data))
    assert _nonblank(screen, 0, 640, 220, 260)


def test_data_table_no_scroll_with_static_rows(screen, fonts):
    from weatherstar.components.data_table import Column, DataTable

    data = DataRegistry()
    data.register("history", _History())
    table = DataTable.model_validate(
        {
            "datasource_name": "history",
            "rows_method": "temperature",
            "scroll": False,
            "max_rows": 1,
            "columns": [Column(header="DATE", header_x=60, x=60, format="date", index=0)],
        }
    )
    table.render(screen, _ctx(screen, fonts, data=data))  # static -> first-row window
    assert _nonblank(screen, 60, 200, 120, 320)


def test_data_table_uv_protection_fallback(screen, fonts):
    from weatherstar.components.data_table import Column, DataTable

    data = DataRegistry()
    data.register("uv_index", object())  # no protection_level() -> fallback thresholds
    table = DataTable.model_validate(
        {
            "datasource_name": "uv_index",
            "rows_method": "daily",
            "scroll": False,
            "columns": [
                Column(header="UV", header_x=60, x=60, format="protection", key="uv_index")
            ],
        }
    )
    ctx = _ctx(screen, fonts, data=data)
    assert table._protection(ctx, 11.0) == "Extreme"
    assert table._protection(ctx, 1.0) == "Low"


def test_data_table_column_requires_one_accessor():
    from weatherstar.components.data_table import Column

    with pytest.raises(ValidationError):
        Column(header="X", header_x=0, x=0, format="text", index=None, key=None)
    with pytest.raises(ValidationError):
        Column(header="X", header_x=0, x=0, format="text", index=0, key="date")


def test_data_table_money_and_signed_formats():
    from weatherstar.components.data_table import Column, DataTable

    table = DataTable.model_validate(
        {
            "datasource_name": "stocks",
            "rows_method": "quotes",
            "scroll": False,
            "columns": [
                Column(header="P", header_x=0, x=0, format="money", attr="price"),
                Column(header="C", header_x=0, x=0, format="signed", attr="change"),
            ],
        }
    )
    ctx = _ctx(None, {})
    assert table._format_cell(412.50, table.columns[0], ctx) == "412.50"
    assert table._format_cell(1234.5, table.columns[0], ctx) == "1,234.50"
    assert table._format_cell(-2.0, table.columns[1], ctx) == "-2.00"
    assert table._format_cell(1.25, table.columns[1], ctx) == "+1.25"
    assert table._format_cell(None, table.columns[0], ctx) is None


def test_data_table_sign_color_uses_up_down(screen, fonts):
    from weatherstar.components.data_table import Column, DataTable

    table = DataTable.model_validate(
        {
            "datasource_name": "stocks",
            "rows_method": "quotes",
            "scroll": False,
            "columns": [
                Column(header="C", header_x=0, x=0, format="signed", attr="change", sign_color=True)
            ],
        }
    )
    ctx = _ctx(screen, fonts)
    assert table._cell_color(table.columns[0], 1.0, ctx) == (0, 255, 0)
    assert table._cell_color(table.columns[0], -1.0, ctx) == (255, 0, 0)
    assert table._cell_color(table.columns[0], "bad", ctx) == (0, 255, 0)

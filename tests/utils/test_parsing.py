"""Tests for src.utils.parsing — AC-0307"""
import pytest

from src.utils.parsing import parse_hedge_fund_response


class TestParseHedgeFundResponse:
    # AC-0307: valid JSON string returns a dict
    def test_valid_json_returns_dict(self):
        result = parse_hedge_fund_response('{"AAPL": {"action": "buy", "quantity": 10}}')
        assert result == {"AAPL": {"action": "buy", "quantity": 10}}

    # AC-0307: invalid JSON string returns None (no exception raised)
    def test_invalid_json_returns_none(self, capsys):
        result = parse_hedge_fund_response("not-json{{{")
        assert result is None
        captured = capsys.readouterr()
        assert "JSON decoding error" in captured.out

    # AC-0307: wrong type (e.g. dict instead of str) returns None
    def test_wrong_type_returns_none(self, capsys):
        result = parse_hedge_fund_response({"already": "a dict"})
        assert result is None
        captured = capsys.readouterr()
        assert "Invalid response type" in captured.out

    # AC-0307: None input returns None
    def test_none_input_returns_none(self, capsys):
        result = parse_hedge_fund_response(None)
        assert result is None

    # AC-0307: empty JSON object is valid
    def test_empty_json_object(self):
        result = parse_hedge_fund_response("{}")
        assert result == {}

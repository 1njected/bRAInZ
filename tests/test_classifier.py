"""Tests for the classifier — LLM response parsing (no network calls)."""

import pytest


VALID_CATEGORIES = {
    "ai", "appsec", "blueteam", "cloud", "crypto", "devops",
    "forensics", "fuzzing", "hw", "ics", "malware", "mobile",
    "netsec", "os", "osint", "redteam", "reversing", "rf", "web3", "misc",
}


class TestParseClassification:
    def _parse(self, raw, valid_tags=None):
        from classifier.classify import _parse_classification
        return _parse_classification(raw, VALID_CATEGORIES, valid_tags or set())

    def test_clean_json(self):
        raw = '{"category": "appsec", "tags": ["xss", "csrf"], "summary": "Web vulns."}'
        result = self._parse(raw)
        assert result["category"] == "appsec"
        assert "xss" in result["tags"]
        assert result["summary"] == "Web vulns."

    def test_json_in_markdown_code_block(self):
        raw = '```json\n{"category": "netsec", "tags": ["mitm"], "summary": "Net attack."}\n```'
        result = self._parse(raw)
        assert result["category"] == "netsec"

    def test_json_embedded_in_prose(self):
        raw = 'Sure! Here is the result:\n{"category": "malware", "tags": ["c2"], "summary": "Malware."}\nDone.'
        result = self._parse(raw)
        assert result["category"] == "malware"

    def test_unknown_category_falls_back_to_misc(self):
        raw = '{"category": "definitely-not-valid", "tags": [], "summary": "?"}'
        result = self._parse(raw)
        assert result["category"] == "misc"

    def test_tags_capped_at_seven(self):
        tags = ["a", "b", "c", "d", "e", "f", "g", "h", "i"]
        raw = f'{{"category": "misc", "tags": {tags}, "summary": "x"}}'
        result = self._parse(raw)
        assert len(result["tags"]) <= 7

    def test_tags_lowercased(self):
        raw = '{"category": "appsec", "tags": ["XSS", "CSRF"], "summary": "."}'
        result = self._parse(raw)
        assert all(t == t.lower() for t in result["tags"])

    def test_invalid_json_returns_fallback(self):
        result = self._parse("this is not json at all")
        assert result["category"] == "misc"
        assert result["tags"] == []
        assert result["summary"] == ""

    def test_empty_string_returns_fallback(self):
        result = self._parse("")
        assert result["category"] == "misc"

    def test_missing_tags_key(self):
        raw = '{"category": "appsec", "summary": "No tags here."}'
        result = self._parse(raw)
        assert result["tags"] == []

    def test_tags_as_non_list_returns_empty(self):
        raw = '{"category": "appsec", "tags": "xss,csrf", "summary": "."}'
        result = self._parse(raw)
        assert result["tags"] == []


class TestClassifyContent:
    @pytest.mark.asyncio
    async def test_calls_llm_and_returns_expected_keys(self, mock_llm):
        from classifier.classify import classify_content
        result = await classify_content("Test Title", "Some security content about networks.", mock_llm)
        assert "category" in result
        assert "tags" in result
        assert "summary" in result
        assert "classified_by" in result

    @pytest.mark.asyncio
    async def test_classified_by_uses_provider_name(self, mock_llm):
        from classifier.classify import classify_content
        result = await classify_content("Title", "Content", mock_llm)
        assert result["classified_by"] == "mock/test"

    @pytest.mark.asyncio
    async def test_category_is_valid(self, mock_llm):
        from classifier.classify import classify_content
        result = await classify_content("Title", "Content", mock_llm)
        assert result["category"] in VALID_CATEGORIES

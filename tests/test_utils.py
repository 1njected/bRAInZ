"""Tests for backend/utils.py — slug, content_hash, validate_url_no_ssrf, now_iso."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from utils import slug, content_hash, validate_url_no_ssrf, now_iso


# ---------------------------------------------------------------------------
# slug()
# ---------------------------------------------------------------------------

class TestSlug:
    def test_basic_lowercase(self):
        assert slug("Hello World") == "hello-world"

    def test_special_chars_removed(self):
        assert slug("My Post!!!") == "my-post"

    def test_spaces_become_hyphens(self):
        assert slug("a b c") == "a-b-c"

    def test_underscores_become_hyphens(self):
        assert slug("hello_world") == "hello-world"

    def test_multiple_spaces_collapsed(self):
        assert slug("a   b") == "a-b"

    def test_leading_trailing_hyphens_stripped(self):
        result = slug("  hello  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_truncated_to_max_len(self):
        long = "a" * 100
        assert len(slug(long)) <= 40

    def test_custom_max_len(self):
        assert len(slug("hello world", max_len=5)) <= 5

    def test_numbers_preserved(self):
        assert "2024" in slug("post 2024")

    def test_already_lowercase(self):
        assert slug("hello") == "hello"

    def test_unicode_letters_preserved(self):
        # \w matches unicode word chars — letters remain
        result = slug("café")
        assert len(result) > 0

    def test_empty_string(self):
        assert slug("") == ""

    def test_only_special_chars(self):
        assert slug("!!!") == ""

    def test_hyphen_not_doubled(self):
        result = slug("hello--world")
        assert "--" not in result


# ---------------------------------------------------------------------------
# content_hash()
# ---------------------------------------------------------------------------

class TestContentHash:
    def test_returns_sha256_prefix(self):
        assert content_hash("hello").startswith("sha256:")

    def test_deterministic(self):
        assert content_hash("hello world") == content_hash("hello world")

    def test_different_inputs_differ(self):
        assert content_hash("hello") != content_hash("world")

    def test_empty_string(self):
        h = content_hash("")
        assert h.startswith("sha256:")
        assert len(h) > 10

    def test_hash_length(self):
        # sha256 hex is 64 chars; with prefix total is 71
        assert len(content_hash("test")) == len("sha256:") + 64

    def test_whitespace_matters(self):
        assert content_hash("hello") != content_hash("hello ")

    def test_case_sensitive(self):
        assert content_hash("Hello") != content_hash("hello")


# ---------------------------------------------------------------------------
# validate_url_no_ssrf()
# ---------------------------------------------------------------------------

class TestValidateUrlNoSsrf:
    def test_public_url_passes(self):
        # Should not raise for a real public hostname
        # Using a domain that reliably resolves to a public IP
        validate_url_no_ssrf("https://example.com/path")

    def test_localhost_rejected(self):
        with pytest.raises(ValueError, match="private|internal|loopback"):
            validate_url_no_ssrf("http://localhost/page")

    def test_127_0_0_1_rejected(self):
        with pytest.raises(ValueError, match="private|internal|loopback"):
            validate_url_no_ssrf("http://127.0.0.1/page")

    def test_private_10_range_rejected(self):
        with pytest.raises(ValueError):
            validate_url_no_ssrf("http://10.0.0.1/page")

    def test_private_192_168_rejected(self):
        with pytest.raises(ValueError):
            validate_url_no_ssrf("http://192.168.1.1/page")

    def test_private_172_16_rejected(self):
        with pytest.raises(ValueError):
            validate_url_no_ssrf("http://172.16.0.1/page")

    def test_link_local_rejected(self):
        with pytest.raises(ValueError):
            validate_url_no_ssrf("http://169.254.169.254/")  # AWS metadata

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError, match="scheme"):
            validate_url_no_ssrf("ftp://example.com/file")

    def test_file_scheme_rejected(self):
        with pytest.raises(ValueError, match="scheme"):
            validate_url_no_ssrf("file:///etc/passwd")

    def test_no_hostname_rejected(self):
        with pytest.raises(ValueError, match="hostname"):
            validate_url_no_ssrf("http:///path")

    def test_custom_allowed_schemes(self):
        # ftp allowed when explicitly passed
        # (will still fail on private IP, but scheme check passes for public)
        with pytest.raises(ValueError):
            # loopback still fails
            validate_url_no_ssrf("ftp://localhost/", allowed_schemes=("ftp",))

    def test_https_allowed_by_default(self):
        validate_url_no_ssrf("https://example.com/")

    def test_http_allowed_by_default(self):
        validate_url_no_ssrf("http://example.com/")


# ---------------------------------------------------------------------------
# now_iso()
# ---------------------------------------------------------------------------

class TestNowIso:
    def test_ends_with_z(self):
        assert now_iso().endswith("Z")

    def test_is_iso_format(self):
        ts = now_iso()
        # Basic structure: YYYY-MM-DDTHH:MM:SSZ
        assert "T" in ts
        assert len(ts) == 20  # seconds precision + Z

    def test_returns_string(self):
        assert isinstance(now_iso(), str)

"""Tests for credential/token redaction and env sanitisation."""
from __future__ import annotations

import os

import pytest

from agent.security.redaction import redact_sensitive_text
from agent.security.execution_policy import sanitise_env, DEFAULT_POLICY


class TestCredentialRedaction:
    def test_redacts_bearer_token(self):
        text = "Authorization: Bearer sk-abc123def456ghij789klm"
        result = redact_sensitive_text(text)
        assert "sk-abc123" not in result
        assert "sk-" not in result or "<redacted-secret>" in result

    def test_redacts_url_with_token(self):
        text = "request to https://api.example.com/v1/chat?key=secret123"
        result = redact_sensitive_text(text)
        assert "https://api.example.com" not in result
        assert "<redacted-endpoint>" in result

    def test_redacts_env_var_style_leak(self):
        text = "FPT26_LLM_API_KEY=sk-mysecretkey12345"
        result = redact_sensitive_text(text)
        assert "sk-mysecretkey12345" not in result

    def test_redacts_api_key_assignment(self):
        text = "apikey=abc123def456"
        result = redact_sensitive_text(text)
        assert "abc123def456" not in result

    def test_preserves_safe_text(self):
        text = "csim passed with 0 errors"
        result = redact_sensitive_text(text)
        assert "csim passed" in result
        assert "0 errors" in result

    def test_handles_non_string_input(self):
        result = redact_sensitive_text(42)
        assert "42" in result


class TestEnvSanitisation:
    def test_strips_secret_variables(self):
        env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "FPT26_LLM_API_KEY": "sk-secret",
            "OPENROUTER_API_KEY": "sk-router-secret",
            "FPT26_LLM_BASE_URL": "https://api.example.com",
            "FPT26_LLM_MODEL": "qwen3-coder-plus",
            "VITIS": "/tools/Xilinx/Vitis/2025.2",
        }
        clean = sanitise_env(env)
        assert "PATH" in clean
        assert "HOME" in clean
        assert "VITIS" in clean
        assert "FPT26_LLM_API_KEY" not in clean
        assert "OPENROUTER_API_KEY" not in clean
        assert "FPT26_LLM_BASE_URL" not in clean
        assert "FPT26_LLM_MODEL" not in clean

    def test_keeps_allowlisted_xilinx_vars(self):
        env = {
            "XILINX_VITIS": "/tools/Xilinx/Vitis/2025.2",
            "LM_LICENSE_FILE": "2100@server",
            "PATH": "/usr/bin",
            "FPT26_LLM_SECRET": "sk-abc",
        }
        clean = sanitise_env(env)
        assert "XILINX_VITIS" in clean
        assert "LM_LICENSE_FILE" in clean
        assert "PATH" in clean
        assert "FPT26_LLM_SECRET" not in clean

    def test_keeps_locale_path_without_secret_vars(self):
        env = {
            "LOCPATH": "/tmp/fpt26_locale_dirs/usr/lib/locale",
            "LC_ALL": "en_US.UTF-8",
            "PATH": "/usr/bin",
            "FPT26_LLM_API_KEY": "sk-secret",
        }
        clean = sanitise_env(env)
        assert clean["LOCPATH"] == "/tmp/fpt26_locale_dirs/usr/lib/locale"
        assert clean["LC_ALL"] == "en_US.UTF-8"
        assert "FPT26_LLM_API_KEY" not in clean

    def test_extra_allowlist(self):
        env = {
            "PATH": "/usr/bin",
            "MY_CUSTOM_VAR": "hello",
            "FPT26_LLM_API_KEY": "sk-secret",
        }
        clean = sanitise_env(env, extra_allow=frozenset({"MY_CUSTOM_VAR"}))
        assert "MY_CUSTOM_VAR" in clean
        assert "FPT26_LLM_API_KEY" not in clean

    def test_default_policy_has_sanitised_env(self):
        env = DEFAULT_POLICY.sanitised_env()
        assert isinstance(env, dict)
        # Real env may have PATH etc. but should never have LLM secrets
        for key in env:
            assert not key.upper().startswith("FPT26_LLM_")
            assert not key.upper().startswith("OPENROUTER_")

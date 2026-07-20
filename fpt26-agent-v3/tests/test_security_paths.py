"""Tests for security path validation and identifier checks."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.errors import (
    InvalidIdentifierError,
    PathEscapesWorkspaceError,
    SymlinkNotAllowedError,
)
from agent.security.paths import (
    resolve_safe_path,
    validate_hls_identifier,
    validate_task_id,
    validate_tcl_token,
    validate_workspace_path,
)


class TestTaskIdValidation:
    def test_accepts_valid_ids(self):
        assert validate_task_id("polybench__gemm") == "polybench__gemm"
        assert validate_task_id("chstone__df_add128") == "chstone__df_add128"
        assert validate_task_id("machsuite__aes_aes") == "machsuite__aes_aes"
        assert validate_task_id("dotProduct_optimize") == "dotProduct_optimize"

    @pytest.mark.parametrize(
        "bad_id",
        [
            "",
            "   ",
            "../escape",
            "task/../../etc",
            "a b",
            ";rm -rf /",
            "a|b",
        ],
    )
    def test_rejects_dangerous_ids(self, bad_id):
        with pytest.raises(InvalidIdentifierError):
            validate_task_id(bad_id)


class TestHlsIdentifierValidation:
    def test_accepts_valid_identifiers(self):
        assert validate_hls_identifier("kernel") == "kernel"
        assert validate_hls_identifier("top_function") == "top_function"
        assert validate_hls_identifier("my_func_2") == "my_func_2"

    @pytest.mark.parametrize(
        "bad_name",
        [
            "",
            "   ",
            "a; rm -rf /",
            "a$(whoami)",
            "a`ls`",
            "a|b",
        ],
    )
    def test_rejects_dangerous_identifiers(self, bad_name):
        with pytest.raises(InvalidIdentifierError):
            validate_hls_identifier(bad_name)

    def test_rejects_overlong(self):
        with pytest.raises(InvalidIdentifierError):
            validate_hls_identifier("a" * 300)


class TestTclTokenValidation:
    def test_accepts_safe_tokens(self):
        assert validate_tcl_token("xcu55c-fsvh2892-2L-e") == "xcu55c-fsvh2892-2L-e"
        assert validate_tcl_token("top.cpp") == "top.cpp"

    @pytest.mark.parametrize(
        "bad_token",
        [
            "a; rm -rf /",
            "a$(whoami)",
            "a`ls`",
            "a[expr 1+1]",
            "a{b}c",
        ],
    )
    def test_rejects_tcl_unsafe(self, bad_token):
        with pytest.raises(InvalidIdentifierError):
            validate_tcl_token(bad_token)


class TestPathValidation:
    def test_resolves_safe_path_inside_root(self, tmp_path: Path):
        (tmp_path / "allowed.txt").write_text("ok")
        result = resolve_safe_path("allowed.txt", root=tmp_path)
        assert result.is_file()

    def test_absolute_path_inside_root(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file.txt").write_text("ok")
        result = resolve_safe_path(tmp_path / "sub" / "file.txt", root=tmp_path)
        assert result.is_file()

    def test_rejects_path_outside_root(self, tmp_path: Path):
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("bad")
        with pytest.raises(PathEscapesWorkspaceError):
            resolve_safe_path(outside, root=tmp_path)

    def test_rejects_relative_escape(self, tmp_path: Path):
        (tmp_path / "ok.txt").write_text("ok")
        with pytest.raises(PathEscapesWorkspaceError):
            resolve_safe_path("../outside.txt", root=tmp_path)

    def test_rejects_symlink_to_outside_target(self, tmp_path: Path):
        """Symlink pointing outside root fails."""
        (tmp_path / "real.txt").write_text("real")
        outside = tmp_path.parent / "outside_target.txt"
        outside.write_text("outside")
        link_path = tmp_path / "link.txt"
        os.symlink(str(outside), str(link_path))
        # Either SymlinkNotAllowedError or PathEscapesWorkspaceError is correct
        with pytest.raises((SymlinkNotAllowedError, PathEscapesWorkspaceError)):
            resolve_safe_path("link.txt", root=tmp_path)

    def test_rejects_internal_symlink_by_default(self, tmp_path: Path):
        """Even internal symlinks are rejected when allow_symlink=False."""
        (tmp_path / "real.txt").write_text("real")
        os.symlink(str(tmp_path / "real.txt"), str(tmp_path / "link.txt"))
        with pytest.raises(SymlinkNotAllowedError):
            resolve_safe_path("link.txt", root=tmp_path, allow_symlink=False)

    def test_allows_symlink_when_permitted(self, tmp_path: Path):
        (tmp_path / "real.txt").write_text("real")
        os.symlink(str(tmp_path / "real.txt"), str(tmp_path / "link.txt"))
        result = resolve_safe_path("link.txt", root=tmp_path, allow_symlink=True)
        assert result.is_file()

    def test_raises_for_missing_when_required(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            resolve_safe_path("missing.txt", root=tmp_path, must_exist=True)

    def test_skips_existence_check(self, tmp_path: Path):
        result = resolve_safe_path("future.txt", root=tmp_path, must_exist=False)
        assert result.name == "future.txt"


class TestWorkspacePathValidation:
    def test_path_inside_workspace_passes(self, tmp_path: Path):
        (tmp_path / "out").mkdir()
        result = validate_workspace_path(str(tmp_path / "out" / "file.txt"),
                                         workspace_root=tmp_path)
        assert result.parent == tmp_path / "out"

    def test_path_inside_artifact_root_passes(self, tmp_path: Path):
        art = tmp_path / "artifacts"
        art.mkdir()
        result = validate_workspace_path(str(art / "out.txt"),
                                         workspace_root=tmp_path / "ws",
                                         artifact_root=art)
        assert result.parent == art

    def test_path_outside_all_roots_fails(self, tmp_path: Path):
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("bad")
        with pytest.raises(PathEscapesWorkspaceError):
            validate_workspace_path(str(outside), workspace_root=tmp_path)

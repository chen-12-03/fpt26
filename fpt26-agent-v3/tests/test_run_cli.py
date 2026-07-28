from __future__ import annotations

import io
from pathlib import Path

import pytest

from agent.run_cli import (
    CliError,
    RunSpec,
    TaskInfo,
    _parse_args,
    build_agent_command,
    build_launch_command,
    build_run_spec,
    execute,
    main,
    resolve_task,
)


def _write_task(
    root: Path,
    relative: str,
    *,
    task_id: str,
    task_type: str = "repair",
) -> Path:
    path = root / relative
    path.mkdir(parents=True)
    (path / "task.toml").write_text(
        "\n".join(
            [
                f'task_id = "{task_id}"',
                f'task_type = "{task_type}"',
                'top = "top"',
                "budget = 60",
                "requires_cosim = false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_task_id_resolves_across_task_collections(tmp_path: Path) -> None:
    expected = _write_task(
        tmp_path,
        "track_a_150/compile_repair__16",
        task_id="compile_repair__16",
    )

    task = resolve_task(
        task_root=tmp_path,
        task_id="compile_repair__16",
        task_path=None,
    )

    assert task.path == expected.resolve()
    assert task.task_type == "repair"
    assert task.top == "top"
    assert task.budget == 60


def test_duplicate_task_id_fails_with_paths(tmp_path: Path) -> None:
    _write_task(tmp_path, "official/duplicate", task_id="duplicate")
    _write_task(tmp_path, "generated/duplicate", task_id="duplicate")

    with pytest.raises(CliError, match="ambiguous"):
        resolve_task(
            task_root=tmp_path,
            task_id="duplicate",
            task_path=None,
        )


def test_run_spec_uses_env_model_and_builds_agent_command(
    tmp_path: Path,
) -> None:
    task_path = _write_task(
        tmp_path, "track/task", task_id="task_from_cli", task_type="optimize"
    )
    env_file = tmp_path / "agent.env"
    env_file.write_text(
        "OPENROUTER_API_KEY=secret-not-for-display\n"
        "LLM4HLS_MODEL=test/model\n",
        encoding="utf-8",
    )
    output = tmp_path / "runs" / "demo"
    log = tmp_path / "runs" / "demo.log"
    args = _parse_args(
        [
            "--task-path",
            str(task_path),
            "--mode",
            "auto",
            "--backend",
            "openrouter",
            "--env-file",
            str(env_file),
            "--output-root",
            str(output),
            "--log-file",
            str(log),
            "--max-optimization-rounds",
            "2",
        ]
    )

    spec = build_run_spec(args)
    command = build_agent_command(spec)

    assert spec.model == "test/model"
    assert spec.runtime == "docker"
    assert spec.image == "fpt26-agent-v3:latest"
    assert spec.output_root == output.resolve()
    assert spec.log_file == log.resolve()
    assert command[0:3] == [
        "python3",
        "-m",
        "agent.main",
    ]
    assert command[command.index("--task") + 1] == "/fpt26-task"
    assert command[command.index("--max-optimization-rounds") + 1] == "2"

    launch = build_launch_command(spec)
    assert launch[:3] == ["docker", "run", "--rm"]
    assert "fpt26-agent-v3:latest" in launch
    assert "--env-file" in launch
    assert str(env_file.resolve()) in launch
    assert "secret-not-for-display" not in " ".join(launch)
    assert f"{task_path.resolve()}:/fpt26-task:ro" in launch


def test_dry_run_previews_configuration_without_creating_files(
    tmp_path: Path, capsys
) -> None:
    task_path = _write_task(tmp_path, "tasks/demo", task_id="dry_demo")
    output = tmp_path / "runs" / "dry"
    log = tmp_path / "runs" / "dry.log"

    rc = main(
        [
            "--task-id",
            "dry_demo",
            "--task-root",
            str(tmp_path / "tasks"),
            "--model",
            "demo/model",
            "--output-root",
            str(output),
            "--log-file",
            str(log),
            "--no-env-file",
            "--dry-run",
            "--color",
            "never",
        ]
    )

    rendered = capsys.readouterr().out
    assert rc == 0
    assert "FPT26 · TASK RUNNER" in rendered
    assert "dry_demo" in rendered
    assert str(task_path.resolve()) in rendered
    assert "demo/model" in rendered
    assert "docker · image=fpt26-agent-v3:latest" in rendered
    assert "docker run --rm" in rendered
    assert "DRY RUN" in rendered
    assert not output.exists()
    assert not log.exists()


def test_wrapper_container_mode_does_not_start_nested_docker(
    tmp_path: Path, monkeypatch
) -> None:
    task_path = _write_task(tmp_path, "tasks/demo", task_id="container_demo")
    monkeypatch.setenv("FPT26_CLI_IN_CONTAINER", "1")
    args = _parse_args(
        [
            "--task-path",
            str(task_path),
            "--output-root",
            str(tmp_path / "runs" / "container"),
            "--log-file",
            str(tmp_path / "runs" / "container.log"),
            "--no-env-file",
        ]
    )

    spec = build_run_spec(args)
    launch = build_launch_command(spec)

    assert spec.runtime == "container"
    assert launch[0] != "docker"
    assert "python3" in launch
    assert str(task_path.resolve()) in launch


def test_vitis_preamble_does_not_enable_nounset(
    tmp_path: Path, monkeypatch
) -> None:
    task_path = _write_task(tmp_path, "tasks/demo", task_id="vitis_demo")
    monkeypatch.setenv("FPT26_CLI_IN_CONTAINER", "1")
    args = _parse_args(
        [
            "--task-path",
            str(task_path),
            "--output-root",
            str(tmp_path / "runs" / "vitis"),
            "--log-file",
            str(tmp_path / "runs" / "vitis.log"),
            "--no-env-file",
        ]
    )

    launch = build_launch_command(build_run_spec(args))

    assert any("set -eo pipefail" in argument for argument in launch)
    assert all("set -euo pipefail" not in argument for argument in launch)


def test_custom_vitis_install_is_mounted_as_a_complete_tree(
    tmp_path: Path, monkeypatch
) -> None:
    task_path = _write_task(tmp_path, "tasks/demo", task_id="custom_vitis")
    settings = tmp_path / "Xilinx" / "2025.2" / "Vitis" / "settings64.sh"
    settings.parent.mkdir(parents=True)
    settings.write_text("# test settings\n", encoding="utf-8")
    monkeypatch.setenv("FPT26_VITIS_SETTINGS", str(settings))
    monkeypatch.delenv("VITIS_MOUNT_ROOT", raising=False)
    args = _parse_args(
        [
            "--task-path",
            str(task_path),
            "--output-root",
            str(tmp_path / "runs" / "custom-vitis"),
            "--log-file",
            str(tmp_path / "runs" / "custom-vitis.log"),
            "--no-env-file",
        ]
    )

    spec = build_run_spec(args)
    launch = build_launch_command(spec)

    install_root = tmp_path / "Xilinx"
    assert spec.vitis_settings == settings.resolve()
    assert f"{install_root}:{install_root}:ro" in launch
    assert str(settings.resolve()) in launch


def test_execute_tees_output_and_strips_ansi_from_log(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    task_path = _write_task(tmp_path, "tasks/demo", task_id="tee_demo")
    spec = RunSpec(
        task=TaskInfo(
            path=task_path.resolve(),
            task_id="tee_demo",
            task_type="repair",
            top="top",
            budget=60,
            requires_cosim=False,
        ),
        runtime="docker",
        image="fpt26-agent-v3:latest",
        mode="auto",
        backend="scripted",
        model="scripted",
        budget=None,
        output_root=tmp_path / "runs" / "tee",
        log_file=tmp_path / "runs" / "tee.log",
        env_file=None,
        vitis_settings=None,
        max_repair_attempts=None,
        max_optimization_rounds=1,
        max_structural_attempts=None,
        scoring_profile="balanced",
        competition=False,
        quiet=False,
        color="never",
    )

    class FakeProcess:
        stdout = io.StringIO("\x1b[32mPASS\x1b[0m child output\n")

        def wait(self) -> int:
            return 0

        def terminate(self) -> None:
            return None

    monkeypatch.setattr(
        "agent.run_cli.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    rc = execute(spec, show_summary=False)

    assert rc == 0
    terminal = capsys.readouterr().out
    assert "PASS" in terminal
    assert "child output" in terminal
    logged = spec.log_file.read_text(encoding="utf-8")
    assert "PASS child output" in logged
    assert "\x1b[" not in logged

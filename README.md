# FPT'26 Track-A: Verified-Candidate Loop for Budgeted LLM-Assisted HLS

An autonomous LLM agent for High-Level Synthesis (HLS) that uses a
Verified-Candidate Loop (VCL) to repair and optimise FPGA kernels under
explicit model and tool budgets.  The agent runs inside Docker with
Vitis 2025.2 and targets the Alveo U55C platform.

## Quick Start

```bash
# 0. REQUIRED — set your local Vitis 2025.2 installation path.
#    Verify it exists:  ls "$VITIS_SDK/settings64.sh"
#    The container hard-codes /tools/Xilinx/2025.2/Vitis/settings64.sh.
#    Examples:
#      export VITIS_SDK=/tools/Xilinx/2025.2/Vitis          # AMD default (Linux/WSL)
#      export VITIS_SDK=/mnt/c/Xilinx/Vitis/2025.2/Vitis    # Windows (may fail with Docker Desktop)
#
export VITIS_SDK=/tools/Xilinx/2025.2/Vitis   # <-- EDIT THIS LINE
ls "$VITIS_SDK/settings64.sh"                 # verify the path exists

# 1. Build the Docker image (base image: public ubuntu:22.04)
export FPT26_REPO_ROOT=$(pwd) HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose -f fpt26-agent-v3/docker-compose.yml build

# 2. Create an environment file with your API key (input hidden, not saved to history)
read -s -p "Paste your OpenRouter API key: " KEY && echo
cat > /tmp/fpt26.env << EOF
OPENROUTER_API_KEY=${KEY}
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM4HLS_MODEL=qwen/qwen3.6-27b
EOF
# 3. Run a single task (mounts Vitis parent directory at /tools/Xilinx)
VITIS_PARENT=$(dirname $(dirname "$VITIS_SDK"))   # e.g. /tools/Xilinx
docker run --rm \
  -v $(pwd):/workspace \
  -v "${VITIS_PARENT}:/tools/Xilinx:ro" \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -e FPT26_CLI_IN_CONTAINER=1 \
  -w /workspace/fpt26-agent-v3 \
  fpt26-agent-v3:latest \
  bash -c "source /tools/Xilinx/2025.2/Vitis/settings64.sh && \
    python3 -m agent.run_cli \
      --task-root /workspace/tasks/track_a_150 \
      --task-id code_generation__01__amd_accel__performance_axi_burst_performance_src_test_kernel_maxi_256bit_1 \
      --mode auto \
      --backend openrouter \
      --output-root /workspace/runs/demo"
```

## Prerequisites

| Component | Version / Detail |
|-----------|-----------------|
| Docker | 24+ with `docker compose` |
| Vitis HLx | 2025.2 — **not bundled; you must provide your own installation** |
| Alveo U55C | `xcu55c-fsvh2892-2L-e` |
| Python | 3.10+ (inside Docker) |
| LLM API | Any OpenRouter-compatible endpoint |

> **Vitis SDK path:** Set `VITIS_SDK` to your local Vitis installation
> (e.g. `/tools/Xilinx/2025.2/Vitis`). The parent directory
> (`/tools/Xilinx`) is bind-mounted read-only into the container.
> The Docker image contains only runtime libraries; the full Vitis
> toolchain is mounted from the host.

### API Configuration

The agent supports any OpenAI-compatible API via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | API key (**required**) |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | API base URL |
| `LLM4HLS_MODEL` | — | Model ID, e.g. `qwen/qwen3.6-27b` |

For the recommended three-model evaluation (see paper), use:

```bash
# DeepSeek V4 Pro (1.6T MoE)
LLM4HLS_MODEL=deepseek/deepseek-v4-pro

# Qwen3.5 122B A10B (MoE, AWQ-4bit)
LLM4HLS_MODEL=qwen/qwen3.5-122b-a10b

# Qwen3.6 27B (Dense, FP8)
LLM4HLS_MODEL=qwen/qwen3.6-27b
```

## Directory Structure

```
.
├── fpt26-agent-v3/          # Agent source code
│   ├── agent/               #   Core agent (CLI, pipeline, optimisation)
│   ├── scoring/             #   Scoring & batch-run infrastructure
│   ├── Dockerfile           #   Docker image definition
│   ├── docker-compose.yml   #   Build & runtime orchestration
│   ├── requirements.txt     #   Python dependencies (tomli, pytest)
│   └── run-agent.sh         #   Convenience launcher
├── fpt26-harness/           # Vitis tool-call harness
│   ├── run-vitis.sh         #   csim / synth / cosim wrapper
│   └── vitis.dockerfile     #   Reference Vitis image
├── tasks/track_a_150/       # 150-task balanced benchmark
│   ├── candidate_manifest.json
│   ├── code_generation/     #   25 tasks: stub → kernel
│   ├── compile_repair/      #   25 tasks: fix compile errors
│   ├── synthesis_repair/    #   25 tasks: fix synthesis failures
│   ├── functional_repair/   #   25 tasks: fix CSim failures
│   ├── structural_cosim_repair/  # 25 tasks: fix CoSim deadlocks
│   └── qor_optimization/    #   25 tasks: improve PPA
├── tools/                   # Audit, validation & summarisation scripts
├── runs/150_ultimate/       # Raw results (submission evidence)
│   ├── CROSS_MODEL_REPORT.md
│   ├── deepseek/
│   ├── qwen3.5-122b-a10b/
│   └── qwen3.6-27b/
├── technical-paper/         # IEEE double-column paper + LaTeX source
│   ├── main.pdf
│   ├── main.tex
│   └── sections/
└── README.md
```

## Task Modes

The `--mode` flag selects the agent's repair pipeline:

| Mode | Description |
|------|-------------|
| `auto` | Auto-detect category from `task.toml` (recommended) |
| `generate` | Code generation from stub |
| `repair` | Compile / synthesis / functional repair |
| `structural` | C/RTL co-simulation deadlock repair |
| `optimize` | QoR optimisation |
| `full` | Full pipeline: repair → structural → optimise |

## Batch Evaluation (150 Tasks)

The scoring infrastructure runs each task in its own isolated Docker
container.  The launcher therefore needs the Docker socket mounted:

```bash
# Three-way shard launch — copy & paste for each shard index
SHARD=0  # or 1, 2
MODEL=qwen/qwen3.6-27b
OUTPUT=runs/my_run_shard${SHARD}

VITIS_PARENT=$(dirname $(dirname "$VITIS_SDK"))
docker run -d --name fpt26-s${SHARD} \
  -v $(pwd):/workspace \
  -v "${VITIS_PARENT}:/tools/Xilinx:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -w /workspace/fpt26-agent-v3 \
  fpt26-agent-v3:latest \
  bash -c "source /tools/Xilinx/2025.2/Vitis/settings64.sh && \
    python3 -m scoring.run_p0_real_api_shard \
      --task-root /workspace/tasks/track_a_150 \
      --output-root /workspace/${OUTPUT} \
      --shard-index ${SHARD} --shard-count 3 \
      --task-timeout-s 7200 \
      --backend openrouter --model ${MODEL}"
```

After all shards finish, generate the cross-model report:

```bash
python3 tools/write_track_a_final_summary.py \
  --run-root runs/my_run_shard0 \
  runs/my_run_shard1 \
  runs/my_run_shard2 \
  --output runs/my_run/CROSS_MODEL_REPORT.md
```

## Reproducing Paper Results

1. Place the three model outputs under `runs/150_ultimate/` (already provided
   with submission evidence).
2. Refresh generated macros:
   ```bash
   python3 technical-paper/scripts/update_results.py
   ```
3. Compile the paper:
   ```bash
   cd technical-paper
   pdflatex main && bibtex main && pdflatex main && pdflatex main
   ```

## Submission Checklist (Track-A)

- [x] Technical paper (IEEE double-column, ≤ 2 pages + appendices)
- [x] Dockerfile with reproducible build
- [x] Agent source code
- [x] Task corpus (150 balanced tasks)
- [x] Per-task submission evidence (`submission_evidence.json`)
- [x] Cross-model evaluation report
- [x] Token & credit accounting
- [x] Three recommended open-weight model comparisons
- [ ] Demo video (≤ 5 min, record separately)

## License

Agent code: MIT.  Task corpus kernels derived from AMD/Xilinx
`Vitis-HLS-Introductory-Examples` (Apache-2.0) and `Vitis_Accel_Examples`
(MIT).  See `tasks/track_a_150/candidate_manifest.json` for per-task
provenance.

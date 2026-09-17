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

# 1. Build the Docker image (base image: Xilinx Alveo runtime on Ubuntu 22.04)
export FPT26_REPO_ROOT=$(pwd) HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose -f fpt26-agent-v3/docker-compose.yml build

# 2. Create an environment file with your API key (input hidden, not saved to history)
read -s -p "Paste your OpenRouter API key: " KEY && echo
cat > /tmp/fpt26.env << EOF
OPENROUTER_API_KEY=${KEY}
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM4HLS_MODEL=qwen/qwen3.6-27b
FPT26_LLM_TEMPERATURE=0
FPT26_LLM_MAX_TOKENS=8192
FPT26_LLM_MAX_RETRIES=0
FPT26_LLM_OPEN_SOURCE=true
FPT26_LLM_LICENSE=apache-2.0
FPT26_LLM_SOURCE=https://huggingface.co/Qwen/Qwen3.6-27B-FP8
EOF
# 3. Run one public task, then grade it in a separate offline container.
RUN_LABEL=demo_qwen36 \
MODEL_ID=qwen/qwen3.6-27b \
ENV_FILE=/tmp/fpt26.env BACKEND=openrouter \
SHARD_COUNT=1 SHARD_INDEX=0 TASK_IDS=ta2_qo_001 \
./run_track_a_v4_split.sh
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
| `FPT26_LLM_TEMPERATURE` | backend default | Set `0` for the paper campaign contract |
| `FPT26_LLM_MAX_TOKENS` | backend default | Set `8192` for the paper campaign contract |
| `FPT26_LLM_MAX_RETRIES` | backend default | Set `0` for the paper campaign contract |
| `FPT26_LLM_OPEN_SOURCE` | — | Set `true` only for a model with public weights |
| `FPT26_LLM_LICENSE` | — | SPDX-style model license evidence, e.g. `apache-2.0` |
| `FPT26_LLM_SOURCE` | — | Public model-card URL or repository identifier |

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
├── releases/track_a_150_v4_20260911/
│   ├── public_agent/        # Public-only 150-task bundle
│   └── evaluator_private/   # Runtime-private: mounted only into Evaluator
├── tools/                   # Audit, validation & summarisation scripts
├── runs/                    # Ignored runtime evidence and summaries
├── run_track_a_v4_split.sh  # Physically isolated campaign entry point
├── docs/experiment-results.md  # Detailed paper experiment tables
├── technical-paper/         # IEEE double-column paper + LaTeX source
│   ├── main.tex
│   ├── output/pdf/FPT26_46474_NULL.pdf
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

The campaign uses distinct Submission and Evaluator containers. The
Submission container never mounts the repository root or evaluator bundle;
the Evaluator has no API environment and runs with `--network none`:

`evaluator_private` describes the runtime trust boundary, not repository
confidentiality. The bundle is published for reproducibility, but it is never
mounted into the Submission container.

```bash
RUN_LABEL=my_qwen36_full150 \
MODEL_ID=qwen/qwen3.6-27b \
ENV_FILE=/tmp/fpt26.env BACKEND=openrouter \
SHARD_COUNT=3 SHARD_INDEX=all \
./run_track_a_v4_split.sh
```

See [`docs/track-a-v4-isolated-reproduction.md`](docs/track-a-v4-isolated-reproduction.md)
for mount guarantees, external private-bundle placement, resume behavior,
output layout, and three-model commands.

## Reproducing Paper Results

The detailed tables omitted from the two-page paper are collected in
[`docs/experiment-results.md`](docs/experiment-results.md).
The independent full-DeepSeek rerun comparison is available as a
[human-readable report](technical-paper/evidence/track_a_v4_deepseek_reproduction_validation_20260917.md)
and [machine-readable JSON](technical-paper/evidence/track_a_v4_deepseek_reproduction_validation_20260917.json).

The repository supports two reproduction levels. Evidence reproduction is
deterministic and requires no API key or Vitis license. A new three-endpoint
campaign uses hosted models and may produce different candidate text.

Verify that the committed LaTeX macros match the canonical v4 dataset:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace \
  fpt26-agent-v3:latest \
  python3 technical-paper/scripts/update_results.py --check
```

Regenerate both macro files after changing the canonical dataset:

```bash
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" -w /workspace \
  fpt26-agent-v3:latest \
  python3 technical-paper/scripts/update_results.py
```

The generator reads only the committed canonical dataset and the frozen v4
evaluator mapping. It does not read `runs/` or any retired construction-time
task tree. The exact data source is
[`technical-paper/evidence/track_a_v4_three_model_paper_data_20260913.json`](technical-paper/evidence/track_a_v4_three_model_paper_data_20260913.json).

Compile the paper with an IEEEtran-capable TeX installation:

```bash
cd technical-paper
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

See [`docs/track-a-v4-isolated-reproduction.md`](docs/track-a-v4-isolated-reproduction.md)
for corpus-integrity checks and full campaign commands.

## Submission Checklist (Track-A)

- [x] Technical paper (IEEE double-column, ≤ 2 pages including figures and references)
- [x] Dockerfile with reproducible build
- [x] Agent source code
- [x] Task corpus (150 balanced tasks)
- [x] Per-task submission evidence (`submission_evidence.json`)
- [x] Cross-model evaluation report
- [x] Token & credit accounting
- [x] Three recommended open-weight model comparisons
- [ ] Demo video (≤ 5 min, record separately)

## License

Original repository code is available under the [MIT License](LICENSE). The
frozen corpus retains the licenses of its ten upstream source suites. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [`LICENSES/`](LICENSES/),
and the evaluator-side `EVALUATOR_MAPPING.json` for task-level provenance.

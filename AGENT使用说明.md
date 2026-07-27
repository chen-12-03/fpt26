# FPT26 Agent 使用说明

本文档说明如何在 Ubuntu 22.04 / WSL 终端中运行本工作区的 Agent，并在终端实时查看日志。

## 1. 进入工作区

```bash
cd /home/chen1/projects/fpt26_new
```

## 2. 完整运行指令

将下面整段内容复制到同一个 Bash 终端中执行：

```bash
cd /home/chen1/projects/fpt26_new

RUN_LABEL="demo_c2hlsc_des_$(date +%Y%m%d_%H%M%S)"
RUN_ROOT="runs/${RUN_LABEL}"
LOG_FILE="runs/${RUN_LABEL}.terminal.log"

mkdir -p runs

export LOCPATH=/tmp/fpt26_locale_dirs/usr/lib/locale
source /tools/Xilinx/Vitis/2025.2/settings64.sh

export LD_LIBRARY_PATH="/tmp/fpt26_vitis_tinfo5_qemu:/tools/Xilinx/2025.2/Vitis/lib/lnx64.o/Ubuntu/22:${LD_LIBRARY_PATH:-}"

set -a
source /tmp/fpt26.env
set +a

set -o pipefail

PYTHONPATH=fpt26-agent-v3:. python3 -m agent.main \
  --task tasks/generated/c2hlsc__des \
  --mode auto \
  --backend custom \
  --output-root "$RUN_ROOT" \
  --scoring-profile balanced \
  --color always \
  2>&1 | tee "$LOG_FILE"

RUN_EXIT=${PIPESTATUS[0]}

echo
echo "run_root=$RUN_ROOT"
echo "terminal_log=$LOG_FILE"
echo "exit_code=$RUN_EXIT"

exit "$RUN_EXIT"
```

运行时，日志会同时：

- 实时显示在当前终端中；
- 保存到 `runs/<运行名称>.terminal.log`；
- 将 Agent 生成的文件保存到 `runs/<运行名称>/`。

命令最后会打印：

- `run_root`：本次运行的输出目录；
- `terminal_log`：完整终端日志的位置；
- `exit_code`：Agent 的退出码，`0` 通常表示成功。

最后一行 `exit "$RUN_EXIT"` 会把 Agent 的真实退出状态传递给终端或上层脚本。如果需要在运行结束后继续使用同一个交互式终端，可以删除这一行；此前打印的 `exit_code` 不受影响。

## 3. 查看运行中的日志

上述命令已经通过 `tee` 边运行边输出日志，不需要另外执行命令。

如果需要在另一个终端中跟踪同一日志，可先根据主终端打印的 `terminal_log` 找到日志路径，然后运行：

```bash
tail -f runs/<运行名称>.terminal.log
```

按 `Ctrl+C` 可停止跟踪日志，但不会停止另一个终端中正在运行的 Agent。

## 4. 中止 Agent

在运行 Agent 的终端中按：

```text
Ctrl+C
```

中止后仍可在对应的 `terminal_log` 文件中查看已经产生的日志。

## 5. 关于“实际提交版本”

这条命令运行的是当前工作区中检出的代码：

- Agent 模块入口：`agent.main`
- Agent Python 路径：`fpt26-agent-v3`
- 任务：`tasks/generated/c2hlsc__des`
- 模式：`auto`
- 后端：`custom`
- 评分配置：`balanced`

`RUN_LABEL` 中的 `demo_` 只用于命名运行目录和日志文件，不会启用“演示代码”，也不会改变 Agent 的执行逻辑。若希望输出名称体现正式提交，可将：

```bash
RUN_LABEL="demo_c2hlsc_des_$(date +%Y%m%d_%H%M%S)"
```

改为：

```bash
RUN_LABEL="submission_c2hlsc_des_$(date +%Y%m%d_%H%M%S)"
```

是否属于最终提交版本，取决于当前 Git 分支和提交号，而不是 `RUN_LABEL`。正式提交前建议记录：

```bash
git branch --show-current
git rev-parse HEAD
git status --short
```

其中 `git status --short` 没有输出，表示当前已跟踪文件没有未提交修改；分支名和提交号应与计划提交的版本一致。

## 6. 运行前检查

运行前应确认以下文件或目录存在：

```bash
test -f /tools/Xilinx/Vitis/2025.2/settings64.sh
test -f /tmp/fpt26.env
test -d fpt26-agent-v3
test -e tasks/generated/c2hlsc__des
```

以上命令均无输出且退出码为 `0` 时，表示对应路径存在。

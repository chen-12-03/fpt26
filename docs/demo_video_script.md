# FPT'26 Track-A 演示视频详细录制方案

## Context
录制一段 5 分钟以内的演示视频，满足 Submission Guidelines 第 10 条要求：
"Demonstration Video (max 5 min): must show project running on target platform with clear explanation."

## 录制环境准备

- **终端模拟器**：推荐 Windows Terminal 或 VS Code 内置终端
- **录屏工具**：OBS Studio（免费）或 Xbox Game Bar (Win+G)
- **终端配色**：深色背景 + 浅色文字，字体 14-16pt
- **工作目录**：`/home/chen1/projects/fpt26`
- **Docker 镜像**：提前 `docker compose build` 完成
- **API Key**：提前写入 `/tmp/fpt26.env`
- **演示 Task**：`qor_optimization__13__amd_intro__interface_streaming_axi_stream_to_master`
  - 内核：`example` — demux→双路proc→mux 的 dataflow 结构，使用 AXI stream（无 m_axi 干扰）
  - 故障：`removed_performance_pragmas:5` — DATAFLOW 等 5 个 pragma 被移除
  - 难度：3，无 CoSim，预算 60 credits
  - 修复：`#pragma HLS DATAFLOW` — 使 demux、proc、mux 三级流水并行执行
  - QoR Score：85.17/100，10 credits，~53s 完成，1 次 API 请求
  - 演示亮点：agent 诊断 `serial_loop_latency` 瓶颈，识别 `source_connected_task_pipeline`，精确插入单行 DATAFLOW 实现任务级流水，latency 136→54 cyc

## 录制方式

**先录屏，后配旁白**。这样终端输出和旁白完全同步，避免实时口误。

## 视频分段时间线

| 时间段 | 时长 | 主题 | 屏幕内容 |
|--------|------|------|----------|
| 0:00-0:25 | 25s | 项目概述 | 目录结构 |
| 0:25-0:55 | 30s | 环境就绪 | Docker 镜像 + Vitis 路径 |
| 0:55-1:20 | 25s | Task 说明 | task.toml + example.cpp（demux-proc-mux dataflow 结构） |
| 1:20-3:20 | 120s | 核心演示 | Agent 优化运行全流程 |
| 3:20-4:05 | 45s | 结果分析 | diff 展示 DATAFLOW + 合成前后对比 + QoR score |
| 4:05-4:40 | 35s | 多模型对比 | CROSS_MODEL_REPORT.md |
| 4:40-5:00 | 20s | 总结 | 回归目录结构 |

---

## 详细分镜与英文旁白稿

### 第一段 | 0:00-0:25 | 项目概述

**屏幕操作**：
```bash
cd /home/chen1/projects/fpt26
ls
tree -L 2 fpt26-agent-v3/agent/
```

**旁白**：
> This is our FPT'26 Track-A submission — an autonomous LLM agent for High-Level Synthesis using a Verified-Candidate Loop. The agent lives in `fpt26-agent-v3` — core pipeline, LLM backends, tool harness, and scoring. The balanced 150-task benchmark is under `tasks/track_a_150`. Pre-computed results for three models are in `runs/150_ultimate`, and the IEEE paper source in `technical-paper`.

---

### 第二段 | 0:25-0:55 | 环境就绪

**屏幕操作**：
```bash
docker images fpt26-agent-v3:latest
echo "Vitis: $VITIS"
ls "$VITIS/settings64.sh"
cat /tmp/fpt26.env  # 展示 API 配置（隐藏 key 值）
```

**旁白**：
> The agent runs inside Docker with Vitis 2025.2 bind-mounted from the host. The pre-built image contains all system dependencies, Python packages, and agent source. We target the Alveo U55C platform at 200 MHz. API credentials are passed via an environment file. For this demo we use Qwen3.6-27B, the smallest and best-performing model in our evaluation.

---

### 第三段 | 0:55-1:20 | 演示 Task 说明

**屏幕操作**：
```bash
cat tasks/track_a_150/qor_optimization__13__amd_intro__interface_streaming_axi_stream_to_master/task.toml
head -40 tasks/track_a_150/qor_optimization__13__amd_intro__interface_streaming_axi_stream_to_master/example.cpp
```

**旁白**：
> The demo is a QoR optimization — a kernel from AMD's Vitis-HLS examples. The top function `example` implements a demux–process–mux dataflow pattern: input is demultiplexed into two parallel streams, processed by two identical compute units, then multiplexed back.  Five performance pragmas are removed. The starter code is functionally correct but the three stages execute sequentially。

---

### 第四段 | 1:20-3:20 | 核心演示：Agent 运行

**屏幕操作**：
```bash
./fpt26-agent-v3/run-task-cli \
  --env-file /tmp/fpt26.env \
  --vitis-settings "$VITIS/settings64.sh" \
  --task-path tasks/track_a_150/qor_optimization__13__amd_intro__interface_streaming_axi_stream_to_master \
  --mode auto \
  --backend openrouter \
  --output-root runs/demo
```

**旁白（穿插在终端输出之间）**：

*（Agent 面板出现时）*
> The CLI wrapper displays a configuration panel summarizing the task, mode, model — Qwen3.6-27B — and budget of 60 credits. It then launches the agent inside Docker.

*（Agent 开始读取 task 时）*
> The agent reads the task specification. Target: Alveo U55C at 5 nanoseconds. Top function: `example`. Task type: `optimize`.

*（Agent 运行 baseline CSim 和 Synth 时）*
> The agent runs C simulation — passes immediately. Then synthesis for a baseline. The starter achieves latency of 136 cycles with an initiation interval of 137 — the three stages execute sequentially at 707 LUTs and 141 FFs.

*（Agent 分析报告，生成修复）*
> The agent analyzes the synthesis report. It identifies diagnoses the bottleneck: the three stages run sequentially. It proposes a single fix — #pragma HLS DATAFLOW — enabling task-level pipelining so all stages overlap.

*（Agent 通过所有 gates）*
> The candidate passes every gate — Interface, CSim, Synthesis, Frequency, Capacity. With DATAFLOW, the three stages overlap: demux processes the next batch while proc computes and mux writes the previous result. The candidate becomes the new verified fallback.

*（Agent 结束时）*
> The run completes in one iteration, consuming 10 of 60 credits with a single API request. The agent writes the final kernel, run report, and submission evidence.

---

### 第五段 | 3:20-4:05 | 结果分析

**屏幕操作**：
```bash
# 展示 agent 添加的 DATAFLOW pragma
diff tasks/track_a_150/qor_optimization__13__amd_intro__interface_streaming_axi_stream_to_master/example.cpp \
     runs/demo/*/final_example.cpp
cat runs/demo/*/submission_evidence.json | python3 -m json.tool | head -50
cat runs/demo/*/resource_usage.md
```

**旁白**：
> Let's examine what the agent delivered. The diff shows one line added: `#pragma HLS DATAFLOW`. After adding DATAFLOW, latency drops to 54 cycles — a 60% reduction. The three stages now overlap as a task-level pipeline: demux processes the next batch while proc computes the current one and mux writes the previous result.

> The resource usage report shows QoR metrics. Q_HW combines performance and area ratios — score 85.17 out of 100. Latency dropped from 136 to 54 cycles while resource usage stayed within U55C limits.

> The evidence records the full verification chain: CSim pass, Synthesis pass, all gates green. Every decision grounded in tool evidence — that's the VCL.

---

### 第六段 | 4:05-4:40 | 多模型对比

**屏幕操作**：
```bash
sed -n '1,14p;18,25p;39,48p;99,105p;130,136p' runs/150_ultimate/CROSS_MODEL_REPORT.md
```

**旁白**：
> We evaluated three open-weight models. The smallest model achieves the highest completion rate and best optimization quality. On structural co-simulation repair, it scores 100% versus 80% for Qwen3.5. We believe architecture matters more than parameter count for HLS repair.

---

### 第七段 | 4:40-5:00 | 总结

**屏幕操作**：
```bash
ls
```

**旁白**：
> To summarize: a self-contained Docker agent; a balanced 150-task benchmark; a Verified-Candidate Loop; pre-computed results across three open-weight models; and an IEEE paper. We believe architecture matters more than parameter count. Thank you for reviewing our submission.

---

## 录制后处理

1. **剪辑加速**：合成（synth）等待阶段可 1.5x-2x 加速，旁白在加速后重新对齐
2. **音量平衡**：确保旁白清晰，终端滚动声消除
3. **字幕**：可选添加英文字幕（SRT 格式），便于非英语母语审稿人
4. **输出格式**：MP4, 1080p, H.264

## 验证

录制完成后，检查：
- [ ] 视频时长 ≤ 5 分钟
- [ ] 终端输出清晰可读（字体大小足够）
- [ ] 旁白与画面同步
- [ ] Docker 镜像、Vitis 路径、API 配置均已展示
- [ ] Agent 完整运行流程可见：read task → csim pass → synth baseline → diagnose → insert DATAFLOW → synth improvement → verify → evidence
- [ ] submission_evidence.json 和 resource_usage.md 中 QoR 评分可见
- [ ] CROSS_MODEL_REPORT 关键数据可见

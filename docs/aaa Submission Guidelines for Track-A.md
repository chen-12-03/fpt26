Track A: Budgeted End-to-End LLM4HLS Agent
轨道 A：预算中的端到端 LLM4HLS 代理程序

This track requires participants to develop an autonomous agent capable of addressing a range of HLS tasks under constrained tool invocation budgets. Each task is provided as a problem statement that may contain at least one of several initial conditions:
这条任务要求参与者开发一个自主代理程序，能够在有限的工具调用预算下完成各种高性能学习任务。每个任务都会以问题的形式提供，这些问题可能包含至少一种初始条件。

A functionally correct but unoptimized baseline C/C++ implementation.
一个功能上正确但未经优化的 C/C++实现版本。
An HLS design that fails compilation or synthesis.
一个在编译或合成过程中出现问题的 HLS 设计。
An HLS design that compiles successfully but fails C simulation, co-simulation, or hidden functional tests.
一个 HLS 设计在编译时能够成功运行，但在 C 语言仿真、联合仿真或隐藏功能测试时会出现失败。
An HLS design that exhibits structural issues such as deadlock, invalid streaming behavior, or severe resource inefficiency.
一个存在结构性问题的 HLS 设计，例如死锁、无效的流媒体播放行为，或者严重的资源利用效率低下等问题。
Other problems related to HLS compilation.
其他与 HLS 编译相关的问题。
The agent must iteratively generate, repair, or optimize candidate HLS code by calling the provided evaluation interfaces. A successful submission should demonstrate the following complete workflow:
该代理必须通过调用提供的评估接口，来逐步生成、修复或优化候选的 HLS 代码。成功的提交应该能够展示出完整的工作流程：

Interpretation of the task specification and initial code.
对任务规范以及初始代码的解释。
Generation or modification of HLS C/C++ code (including pragmas).
生成或修改 HLS 的 C/C++ 代码（包括相关配置文件）。
Invocation of tool feedback interfaces.
调用工具反馈接口。
Parsing of logs and reports for issue diagnosis.
对日志和报告进行解析，以诊断问题。
Prioritization of correctness issue resolution before PPA optimization.
在 PPA 优化之前，应优先解决 correctness 问题的相关事宜。
Termination within the assigned budget constraints.
在规定的预算范围内完成项目。
Each task will include the following artifacts:
每个任务都将包含以下成果：

Source files: Baseline C/C++, with several problems indicated as above.
源文件：基线版本的 C/C++代码，其中包含了上述提到的几个问题。
Testbench: Public correctness tests, building scripts (e.g. Makefile).
测试平台：进行公共正确性测试，编写构建脚本（例如 Makefile）。
Specification: Interface contract, data types, numerical tolerance, and design constraints.
规格说明：接口协议、数据类型、数值公差以及设计约束条件。
Target constraints: FPGA platform, HLS tool version, clock target, and optional resource limits.
目标限制：FPGA 平台、HLS 工具版本、时钟目标，以及可选的资源限制。
Budget configuration: Maximum iterations allowed calls to csim, cosim, and synth, or an equivalent unified credit budget.
预算配置：允许对 csim、cosim 和 synth 等工具进行的最大迭代次数，或者相当于一个统一的信用额度。
Submitted entries will be evaluated based on the following primary dimensions: correctness, PPA metrics, and problem difficulties.
提交的参赛作品将依据以下主要标准进行评估：正确性、PPA 指标以及问题的难度。

Submission Guidelines for Track-A
1. FPGA platform is targeted at the Alveo U55C for Co-simulation
2. Software version is targeted at Vitis 2025.2
3. Please pass csim, cosim and synth, and provide experimental report
4. HLS generated hardware with at least 100Mhz
5. Token consumption is an important factor for final evaluation
6. Only open-source LLM is permitted in this competition
7. Hidden test benchmarks exist for final evaluation
8. Submissions are expected to be built and run within a Docker environment. A Dockerfile is recommended to be included with the submission; a reference example is provided below:
https://anonymous.4open.science/r/fpt26-harness
9. Source codes, testbenches and other supplementary materials that will be helpful for the reproduction, should be submitted for final evaluation (e.g., .Zip file)
10. Demonstration Video (max 5 min): must show project running on target platform with clear explanation

翻译：1. FPGA 平台目标为 `Alveo U55C`，用于协同仿真（`Co-simulation`）。 
2. 软件版本目标为 `Vitis 2025.2`。 
3. 请通过 `csim`、`cosim` 和 `synth`，并提供实验报告。 
4. HLS 生成的硬件频率至少应达到 `100 MHz`。 
5. `Token` 消耗是最终评测中的一个重要因素。 
6. 本次比赛仅允许使用开源大语言模型（`open-source LLM`）。 
7. 最终评测中存在隐藏测试基准（`hidden test benchmarks`）。 
8. 提交作品应能够在 `Docker` 环境中构建并运行。建议随提交材料附带 `Dockerfile`；下面提供了一个参考示例： [https://anonymous.4open.science/r/fpt26-harness](https://anonymous.4open.science/r/fpt26-harness) 
9. 为了便于复现，源代码、测试平台（`testbenches`）以及其他有帮助的补充材料都应一并提交用于最终评测（例如 `.zip` 文件）。 
10. 演示视频（最长 `5` 分钟）：必须清楚展示项目如何在目标平台上运行，并附有明确说明。 

Submission Requirement  提交要求
Project Description: Participants are required to submit a technical paper electronically in PDF format, following the IEEE conference double-column format. The main content should not exceed two pages, with optional unlimited appendices as additional materials.
项目说明：参与者需要以 PDF 格式电子提交技术论文，并按照 IEEE 会议的双栏排版格式进行编写。论文正文长度不得超过两页，可以附加不限数量的附录作为补充材料。
Demonstration Video (max 5 min): must show project running on target platform with clear explanation.
演示视频（时长最多 5 分钟）：必须展示该项目在目标平台上的运行情况，并附带清晰的说明。
For recommended submission guidelines for Track A and Track B, please visit https://github.com/FPT26/Design-Competition-Submission-Guidelines.
关于 A 轨道和 B 轨道的提交指南，请访问 https://github.com/FPT26/Design-Competition-Submission-Guidelines。
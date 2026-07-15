.PHONY: iter2-pj iter2-rs iter3-dp iter3-pj iter3-rs iter1-all iter2-all iter3-all all

REPO_ROOT := $(shell realpath $(CURDIR)/..)
TASKS := /workspace/fpt26-harness/tasks

DOCKER=docker run --rm \
  -v $(REPO_ROOT):/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -w /workspace fpt26-agent-v3:latest

VITIS=source /tools/Xilinx/Vitis/2025.2/settings64.sh

FILTER=grep -E "step|csim|synth|cosim|opt r|repair|ACCEPTED|Pipeline|final|budget|Gates|success|fail|Done|latency|no improv|Tools:|Repair:|knowledge"

# --- Iter 2 dotProduct already done above. Run the rest ---

iter2-pj:
	cp /tmp/iter2_prompts.py $(CURDIR)/agent/prompts.py
	cp /tmp/iter2_optimize.py $(CURDIR)/agent/agents/optimize.py
	rm -f $(CURDIR)/agent/knowledge.py
	$(DOCKER) bash -c "$(VITIS) && python3 -m agent.main --task $(TASKS)/projection_bugfix --mode repair --output-root runs/v3_iter2 --backend custom --no-score --max-repair-attempts 2" 2>&1 | $(FILTER)

iter2-rs:
	cp /tmp/iter2_prompts.py $(CURDIR)/agent/prompts.py
	cp /tmp/iter2_optimize.py $(CURDIR)/agent/agents/optimize.py
	rm -f $(CURDIR)/agent/knowledge.py
	$(DOCKER) bash -c "$(VITIS) && python3 -m agent.main --task $(TASKS)/residual_stream_deadlock --mode structural --output-root runs/v3_iter2 --backend custom --no-score --max-structural-attempts 2" 2>&1 | $(FILTER)

iter3-dp:
	cp /tmp/iter3_prompts.py $(CURDIR)/agent/prompts.py
	cp /tmp/iter3_optimize.py $(CURDIR)/agent/agents/optimize.py
	cp /tmp/iter3_knowledge.py $(CURDIR)/agent/knowledge.py
	$(DOCKER) bash -c "$(VITIS) && python3 -m agent.main --task $(TASKS)/dotProduct_optimize --mode optimize --output-root runs/v3_iter3 --backend custom --no-score --max-optimization-rounds 1" 2>&1 | $(FILTER)

iter3-pj:
	cp /tmp/iter3_prompts.py $(CURDIR)/agent/prompts.py
	cp /tmp/iter3_optimize.py $(CURDIR)/agent/agents/optimize.py
	cp /tmp/iter3_knowledge.py $(CURDIR)/agent/knowledge.py
	$(DOCKER) bash -c "$(VITIS) && python3 -m agent.main --task $(TASKS)/projection_bugfix --mode repair --output-root runs/v3_iter3 --backend custom --no-score --max-repair-attempts 2" 2>&1 | $(FILTER)

iter3-rs:
	cp /tmp/iter3_prompts.py $(CURDIR)/agent/prompts.py
	cp /tmp/iter3_optimize.py $(CURDIR)/agent/agents/optimize.py
	cp /tmp/iter3_knowledge.py $(CURDIR)/agent/knowledge.py
	$(DOCKER) bash -c "$(VITIS) && python3 -m agent.main --task $(TASKS)/residual_stream_deadlock --mode structural --output-root runs/v3_iter3 --backend custom --no-score --max-structural-attempts 2" 2>&1 | $(FILTER)

iter2-all: iter2-dp iter2-pj iter2-rs
iter3-all: iter3-dp iter3-pj iter3-rs
all: iter2-all iter3-all

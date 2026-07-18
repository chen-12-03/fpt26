ARG BASE_IMAGE=vitis_runtime:2025.2
FROM ${BASE_IMAGE}

RUN apt-get update \
    && apt-get install -y --no-install-recommends zip unzip python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir tomli pytest

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WORKSPACE=/workspace
ENV PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness

WORKDIR /workspace

CMD ["bash"]

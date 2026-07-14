ARG BASE_IMAGE=vitis_runtime:2025.2
FROM ${BASE_IMAGE}

RUN apt-get update \
    && apt-get install -y --no-install-recommends zip unzip \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WORKSPACE=/workspace
ENV PYTHONPATH=/workspace/fpt26-agent:/workspace/fpt26-harness:/workspace/third_party/fpt26_harness

WORKDIR /workspace

CMD ["bash"]

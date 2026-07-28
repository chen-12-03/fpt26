ARG BASE_IMAGE=xilinx/xilinx_runtime_base:alveo-2023.2-ubuntu-22.04
FROM ${BASE_IMAGE}

ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Vitis 2025.2 is mounted from the host at runtime.  This image contains the
# Linux runtime/build dependencies required by HLS plus the agent's Python
# dependencies, so it no longer depends on a locally prebuilt vitis_runtime
# image.
RUN if [ -n "${TARGETARCH}" ] && [ "${TARGETARCH}" != "amd64" ]; then \
      echo "FPT26/Vitis 2025.2 requires an amd64 image (got ${TARGETARCH})" >&2; \
      exit 2; \
    fi \
    && dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      autoconf \
      automake \
      bison \
      build-essential \
      ca-certificates \
      chrpath \
      cmake \
      cpio \
      curl \
      debianutils \
      diffstat \
      flex \
      g++ \
      gawk \
      gcc \
      gcc-multilib \
      git \
      gnupg \
      gzip \
      iproute2 \
      iputils-ping \
      lib32stdc++6 \
      libegl1-mesa \
      liberror-perl \
      libfontconfig1:i386 \
      libftdi1 \
      libftdi1-2 \
      libgtk2.0-0:i386 \
      libncurses5 \
      libncurses5:i386 \
      libncurses5-dev \
      libncurses-dev \
      libncursesw5 \
      libncursesw5-dev \
      libselinux1 \
      libsdl1.2-dev \
      libsm6:i386 \
      libssl-dev \
      libstdc++6:i386 \
      libtinfo5 \
      libtool \
      libx11-6:i386 \
      libxcb-randr0-dev \
      libxcb-shape0-dev \
      libxcb-xinerama0-dev \
      libxcb-xkb-dev \
      libxcb-xtest0-dev \
      libxext6:i386 \
      libxrender1:i386 \
      locales \
      lsb-release \
      make \
      net-tools \
      ocl-icd-libopencl1 \
      ocl-icd-opencl-dev \
      opencl-headers \
      openssh-client \
      openssl \
      perl \
      python3 \
      python3-git \
      python3-jinja2 \
      python3-pexpect \
      python3-pip \
      socat \
      tar \
      texinfo \
      tofrodos \
      unzip \
      util-linux \
      wget \
      xtrans-dev \
      xvfb \
      xz-utils \
      zip \
      zlib1g:i386 \
      zlib1g-dev \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

COPY fpt26-agent-v3/requirements.txt /tmp/fpt26-requirements.txt
RUN python3 -m pip install --no-cache-dir \
      -r /tmp/fpt26-requirements.txt \
    && rm -f /tmp/fpt26-requirements.txt

ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WORKSPACE=/workspace
ENV PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness

WORKDIR /workspace

CMD ["bash"]

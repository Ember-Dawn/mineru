# Use the official vllm image for gpu with Volta、Turing、Ampere、Ada Lovelace、Hopper、Blackwell architecture (7.0 <= Compute Capability <= 12.1)
# The default base image uses vLLM 0.21.0 with CUDA 13.0. For CUDA 12.9 environments, switch to the commented cu129 image below.
# Compute Capability version query (https://developer.nvidia.com/cuda-gpus)
# support x86_64 architecture and ARM(AArch64) architecture
FROM vllm/vllm-openai:v0.21.0
# FROM vllm/vllm-openai:v0.21.0-cu129

# Install libgl for opencv support
RUN apt-get update && \
    apt-get install -y \
        libgl1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install the local MinerU source with Torch; reuse vLLM from the base image.
WORKDIR /opt/mineru-source
COPY . /opt/mineru-source/
RUN python3 -m pip install -U '.[torch]' --break-system-packages && \
    python3 -m pip cache purge

# Keep build-time model downloads and runtime selection aligned, including builds without a GPU.
ENV MINERU_MODEL_SMALL_BACKEND=torch \
    MINERU_MODEL_VLM_ENGINE=vllm

# Download the Torch bundle and original VLM weights.
# Persistent BuildKit cache preserves completed and partial downloads on later builds.
# Copy from the cache into the image: cache mount contents are not automatically exported.
RUN --mount=type=cache,id=mineru-standard-models,target=/root/.mineru/models,sharing=locked \
    --mount=type=cache,id=mineru-hf-xet,target=/root/.cache/huggingface,sharing=locked \
    /bin/bash -c 'set -e; \
      mineru-kit models download --tier standard --small-backend torch --vlm-engine vllm -s huggingface; \
      mkdir -p /opt/mineru-bundled-models; \
      cp -a /root/.mineru/models/. /opt/mineru-bundled-models/'

# Restore normal model location in the runtime image after the cache mount is gone.
RUN mkdir -p /root/.mineru && mv /opt/mineru-bundled-models /root/.mineru/models

# Set the entry point to activate the virtual environment and run the command line tool
ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]

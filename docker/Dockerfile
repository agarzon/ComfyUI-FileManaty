# CPU-only image; the file manager doesn't touch inference, so no CUDA.
FROM python:3.11-slim

ARG COMFYUI_REF=master

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 --branch ${COMFYUI_REF} \
        https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI

WORKDIR /opt/ComfyUI

# Install ComfyUI's requirements. Prefer CPU torch wheels from the PyTorch
# index; requirements.txt already lists torch/torchvision/torchaudio plus
# the dependencies we need (Pillow, aiohttp), so a single install is enough.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt

EXPOSE 8188

CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--cpu"]

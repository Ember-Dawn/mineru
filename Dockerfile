# Fast application image. Build or tag mineru:model-base once before using this Dockerfile.
# Model weights and third-party dependencies are inherited from the prepared base image.
FROM mineru:model-base

WORKDIR /opt/mineru-source
COPY . /opt/mineru-source/

# Install only the changed local package. Third-party libraries and models
# are prepared separately by Dockerfile.models.
RUN python3 -m pip install --no-deps --no-cache-dir . --break-system-packages

# Retain the mineru:model-base ENTRYPOINT and MINERU_MODEL_* settings.

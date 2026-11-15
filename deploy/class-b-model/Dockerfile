FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

# The pinned llama.cpp CPU binary needs the OpenMP and C++ runtime libraries.
# Network is available only while building this image; the worker container is
# run with --network=none and sees no credentials.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

USER 65534:65534

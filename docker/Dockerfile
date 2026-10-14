FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install Blender + Python
RUN apt-get update && apt-get install -y \
    blender \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Python packages used by the geometry kernel
RUN pip3 install numpy pillow

WORKDIR /workspace

ENTRYPOINT ["blender"]

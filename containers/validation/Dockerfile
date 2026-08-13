# syntax=docker/dockerfile:1
# The base and validation toolchain are pinned in image.lock.json. Provisioning
# is explicit; it produces the derived immutable digest recorded in the lock.
FROM docker.io/library/python@sha256:9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r /tmp/requirements.txt \
    && uv --version

USER 65532:65532
WORKDIR /workspace

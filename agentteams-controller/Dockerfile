# ============================================================
# agentteams-controller - Standalone build for Go binaries
# ============================================================
# Produces: /agentteams-controller, /agt, /kube-apiserver, /opt/agentteams/config/crd/
# Manager Dockerfile copies these artifacts via: COPY --from=agentteams-controller ...
#
# Since v0.2: includes merged worker lifecycle, auth, credentials, and proxy.

ARG HIGRESS_REGISTRY=higress-registry.cn-hangzhou.cr.aliyuncs.com

# ============ Stage 1: Build Go binaries ============
FROM ${HIGRESS_REGISTRY}/higress/golang:1.25-alpine AS builder

ARG GOPROXY=https://goproxy.cn,direct
ENV GOPROXY=${GOPROXY}
RUN apk add --no-cache gcc musl-dev

WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download || true

COPY . .
RUN CGO_ENABLED=1 go build -ldflags '-extldflags "-static"' -o /agentteams-controller ./cmd/controller/
RUN CGO_ENABLED=0 go build -o /agt ./cmd/agt/

# ============ Stage 2: mc (MinIO Client) ============
FROM ${HIGRESS_REGISTRY}/higress/mc:20260216@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727 AS mc
# mc is pinned to RELEASE.2025-08-13T08-35-41Z by image digest and by binary
# checksum. It is baked into the image and never downloaded at runtime.
# Bump all Dockerfiles together; shared/tests/test-mc-pin.sh enforces this.
ARG TARGETARCH
RUN set -eu; \
    arch="${TARGETARCH:-$(uname -m)}"; \
    case "${arch}" in \
        amd64|x86_64) sum=01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891 ;; \
        arm64|aarch64) sum=14c8c9616cfce4636add161304353244e8de383b2e2752c0e9dad01d4c27c12c ;; \
        *) echo "mc: no pinned checksum for ${arch}" >&2; exit 1 ;; \
    esac; \
    echo "${sum}  /usr/bin/mc" | sha256sum -c -

# ============ Stage 3: Download kube-apiserver (native arch to avoid QEMU TLS bugs) ============
FROM --platform=$BUILDPLATFORM ${HIGRESS_REGISTRY}/higress/alpine:3.20 AS kube-bin
ARG KUBE_VERSION=v1.31.3
# TARGETARCH is auto-injected by buildx for multi-arch builds. For plain
# `docker build` (no buildx) it is unset, so fall back to `uname -m` —
# safe here because the stage is pinned to BUILDPLATFORM and a non-buildx
# build is always single-arch == host arch.
ARG TARGETARCH
RUN apk add --no-cache curl && \
    ARCH="${TARGETARCH:-$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')}" && \
    curl -fSL -o /kube-apiserver \
      "https://dl.k8s.io/release/${KUBE_VERSION}/bin/linux/${ARCH}/kube-apiserver" && \
    chmod +x /kube-apiserver

# ============ Final: Minimal image with all artifacts ============
FROM ${HIGRESS_REGISTRY}/higress/alpine:3.20

RUN apk add --no-cache bash jq curl unzip kubectl

COPY --from=mc /usr/bin/mc /usr/local/bin/mc
COPY --from=builder /agentteams-controller /usr/local/bin/agentteams-controller
COPY --from=builder /agt /usr/local/bin/agt
COPY --from=kube-bin /kube-apiserver /usr/local/bin/kube-apiserver
COPY config/crd/ /opt/agentteams/config/crd/
COPY agent/ /opt/agentteams/agent/

# Default endpoint + token-file for the bundled `agt` CLI. The controller process mints a
# long-lived admin SA token at startup (see internal/app.bootstrapAdminCLIToken)
# and writes it to AGENTTEAMS_AUTH_TOKEN_FILE; the CLI's discoverToken() then
# auto-loads it so operators don't need to pass `-e AGENTTEAMS_AUTH_TOKEN=…` on
# every exec. Both vars are container-local defaults — `docker exec -e` still
# overrides them, and the controller binary itself does not read them.
ENV AGENTTEAMS_CONTROLLER_URL=http://127.0.0.1:8090 \
    AGENTTEAMS_AUTH_TOKEN_FILE=/var/run/agentteams/cli-token

ENTRYPOINT ["agentteams-controller"]

ARG HIGRESS_REGISTRY=higress-registry.cn-hangzhou.cr.aliyuncs.com

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

FROM node:22.22-bookworm-slim

ARG DSH_VERSION=0.1.1-rc.2

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        jq \
        python3 \
        tini \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=mc /usr/bin/mc /usr/local/bin/mc.bin
COPY shared/lib/ /opt/agentteams/scripts/lib/

RUN npm install --global "pnpm@11.7.0" "@deepseek-ai/dsh@${DSH_VERSION}" \
    && npm cache clean --force

COPY plugins/teamharness/ /opt/agentteams/plugins/teamharness/
RUN mkdir -p /opt/agentteams/dsh-template /tmp/adapter-pack \
    && DSH_HOME=/opt/agentteams/dsh-template pnpm --dir /opt/agentteams/plugins/teamharness/adapters/deepseek-harness pack --pack-destination /tmp/adapter-pack \
    && DSH_HOME=/opt/agentteams/dsh-template dsh plugin --profile headless add /tmp/adapter-pack/*.tgz \
    && rm -rf /tmp/adapter-pack

COPY deepseek-harness/scripts/deepseek-harness-worker-entrypoint.sh /opt/agentteams/scripts/deepseek-harness-worker-entrypoint.sh
COPY deepseek-harness/scripts/agentteams-dsh /usr/local/bin/agentteams-dsh
COPY deepseek-harness/scripts/bridge_state.py /opt/agentteams/scripts/bridge_state.py
COPY deepseek-harness/scripts/matrix_channel.py /opt/agentteams/scripts/matrix_channel.py
COPY deepseek-harness/scripts/matrix_bridge.py /opt/agentteams/scripts/matrix_bridge.py
COPY deepseek-harness/scripts/runtime_env.py /opt/agentteams/scripts/runtime_env.py

RUN chmod +x /opt/agentteams/scripts/lib/mc-wrapper.sh \
        /opt/agentteams/scripts/deepseek-harness-worker-entrypoint.sh \
        /opt/agentteams/scripts/matrix_bridge.py \
        /opt/agentteams/scripts/runtime_env.py \
        /usr/local/bin/agentteams-dsh \
    && ln -sf /opt/agentteams/scripts/lib/mc-wrapper.sh /usr/local/bin/mc \
    && mkdir -p /root/agentteams-fs/agents

WORKDIR /root/agentteams-fs/agents
EXPOSE 8088
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/agentteams/scripts/deepseek-harness-worker-entrypoint.sh"]

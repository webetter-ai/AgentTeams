#!/bin/bash
# Every image that bakes in mc must use the same pinned mc stage: an image
# digest plus a per-architecture binary checksum, and no build/runtime download.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MC_STAGE_RE='^FROM .*/mc[:@].* AS mc$'

fail() {
    echo "FAIL: $1" >&2
    exit 1
}

mapfile -t dockerfiles < <(
    cd "${REPO_ROOT}" &&
        git ls-files -- '*Dockerfile*' | while IFS= read -r file; do
            if tr -d '\r' < "${file}" | grep -Eq "${MC_STAGE_RE}"; then
                printf '%s\n' "${file}"
            fi
        done
)
[ "${#dockerfiles[@]}" -gt 0 ] || fail "no Dockerfile with an mc stage found"

reference=""
reference_file=""
for file in "${dockerfiles[@]}"; do
    content="$(tr -d '\r' < "${REPO_ROOT}/${file}")"
    from_line="$(grep -E "${MC_STAGE_RE}" <<< "${content}")"
    case "${from_line}" in
        *@sha256:*) ;;
        *) fail "${file}: mc stage is not pinned by digest: ${from_line}" ;;
    esac
    # The pinned block: FROM line through the sha256sum check.
    block="$(sed -n '/^FROM .*\/mc[:@].* AS mc$/,/sha256sum -c -$/p' <<< "${content}")"
    grep -q 'sha256sum -c -$' <<< "${block}" || fail "${file}: mc binary checksum is not verified"
    grep -Eq 'amd64[|]x86_64[)] sum=[0-9a-f]{64} ;;' <<< "${block}" || fail "${file}: missing amd64 mc checksum"
    grep -Eq 'arm64[|]aarch64[)] sum=[0-9a-f]{64} ;;' <<< "${block}" || fail "${file}: missing arm64 mc checksum"
    if [ -z "${reference}" ]; then
        reference="${block}"
        reference_file="${file}"
    elif [ "${block}" != "${reference}" ]; then
        fail "${file}: mc pin differs from ${reference_file}; bump all Dockerfiles together"
    fi
    if grep -Ev '^[[:space:]]*#' <<< "${content}" | grep -Eq 'dl[.]min[.]io|minio-releases'; then
        fail "${file}: downloads mc instead of using the pinned stage"
    fi
done

echo "PASS: mc pin (${#dockerfiles[@]} Dockerfiles)"

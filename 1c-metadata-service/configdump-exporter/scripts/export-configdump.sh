#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'USAGE'
Usage:
  export-configdump
  export-configdump --help

Required connection settings, choose one:
  ONEC_IB_CONNECTION  Full 1C connection string, for example Srvr="1c-host";Ref="1c-test";
  ONEC_SERVER + ONEC_INFOBASE
  ONEC_FILE_DB

Optional:
  ONEC_USERNAME       Infobase user. Alias: ONEC_USER.
  ONEC_PASSWORD       Infobase password. Alias: ONEC_PASS. Empty value is allowed.
  ONEC_EXECUTABLE     Path to 1cv8. Auto-detected by default.
  ONEC_OUTPUT_DIR     Output directory. Default: /out.
  ONEC_RESULT_FILE    Result file. Default: /out/ConfigDumpInfo.xml.
  ONEC_WORK_DIR       Working directory. Default: /work.
  ONEC_DUMP_DIR       Temporary dump directory. Default: /work/config-dump.
  ONEC_LOG_FILE       1C batch log file. Default: /out/configdump-export.log.
  ONEC_FORMAT         Dump format. Default: Hierarchical.
  ONEC_USE_XVFB       auto | always | never. Default: auto.
USAGE
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

log() {
    printf '[configdump-exporter] %s\n' "$*" >&2
}

fail() {
    printf '[configdump-exporter] ERROR: %s\n' "$*" >&2
    exit 1
}

find_1cv8() {
    if [[ -n "${ONEC_EXECUTABLE:-}" ]]; then
        [[ -x "${ONEC_EXECUTABLE}" ]] || fail "ONEC_EXECUTABLE is not executable: ${ONEC_EXECUTABLE}"
        printf '%s\n' "${ONEC_EXECUTABLE}"
        return
    fi

    if command -v 1cv8 >/dev/null 2>&1; then
        command -v 1cv8
        return
    fi

    local candidate
    candidate="$(find /opt -type f -name 1cv8 -perm -111 2>/dev/null | sort -V | tail -n 1 || true)"
    [[ -n "${candidate}" ]] || fail "1cv8 executable was not found"
    printf '%s\n' "${candidate}"
}

append_auth_args() {
    local username="${ONEC_USERNAME:-${ONEC_USER:-}}"
    if [[ -n "${username}" ]]; then
        cmd+=(/N "${username}")
    fi

    if [[ -n "${ONEC_PASSWORD+x}" ]]; then
        cmd+=(/P "${ONEC_PASSWORD}")
    elif [[ -n "${ONEC_PASS+x}" ]]; then
        cmd+=(/P "${ONEC_PASS}")
    fi
}

append_connection_args() {
    if [[ -n "${ONEC_IB_CONNECTION:-}" ]]; then
        cmd+=(/IBConnectionString "${ONEC_IB_CONNECTION}")
        return
    fi

    if [[ -n "${ONEC_SERVER:-}" && -n "${ONEC_INFOBASE:-}" ]]; then
        cmd+=(/S "${ONEC_SERVER}\\${ONEC_INFOBASE}")
        return
    fi

    if [[ -n "${ONEC_FILE_DB:-}" ]]; then
        cmd+=(/F "${ONEC_FILE_DB}")
        return
    fi

    fail "No infobase connection configured. Set ONEC_IB_CONNECTION, ONEC_SERVER+ONEC_INFOBASE, or ONEC_FILE_DB."
}

print_log_tail() {
    local file="$1"
    if [[ -s "${file}" ]]; then
        log "1C log tail (${file}):"
        tail -n 80 "${file}" \
            | sed -E \
                -e 's/([Pp][Ww][Dd]=)"[^"]*"/\1"<redacted>"/g' \
                -e 's/([Pp][Ww][Dd]=)[^;[:space:]]+/\1<redacted>/g' \
                -e 's/([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]=)"[^"]*"/\1"<redacted>"/g' \
                -e 's/([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]=)[^;[:space:]]+/\1<redacted>/g' \
            >&2 || true
    fi
}

output_dir="${ONEC_OUTPUT_DIR:-/out}"
result_file="${ONEC_RESULT_FILE:-${output_dir}/ConfigDumpInfo.xml}"
work_dir="${ONEC_WORK_DIR:-/work}"
dump_dir="${ONEC_DUMP_DIR:-${work_dir}/config-dump}"
log_file="${ONEC_LOG_FILE:-${output_dir}/configdump-export.log}"
format="${ONEC_FORMAT:-Hierarchical}"
use_xvfb="${ONEC_USE_XVFB:-auto}"

case "${format}" in
    Plain|Hierarchical) ;;
    *) fail "ONEC_FORMAT must be Plain or Hierarchical, got: ${format}" ;;
esac

case "${use_xvfb}" in
    auto|always|never) ;;
    *) fail "ONEC_USE_XVFB must be auto, always, or never, got: ${use_xvfb}" ;;
esac

mkdir -p "${output_dir}" "${work_dir}" "$(dirname "${result_file}")" "$(dirname "${log_file}")"
rm -rf "${dump_dir}"
mkdir -p "${dump_dir}"
rm -f "${log_file}"

onec_executable="$(find_1cv8)"

cmd=("${onec_executable}" DESIGNER /DisableStartupDialogs /DisableStartupMessages /AppAutoCheckMode /WA-)
append_connection_args
append_auth_args
cmd+=(/DumpConfigToFiles "${dump_dir}" -Format "${format}" -configDumpInfoOnly /Out "${log_file}")

runner=()
if [[ "${use_xvfb}" == "always" || ( "${use_xvfb}" == "auto" && -z "${DISPLAY:-}" ) ]]; then
    command -v xvfb-run >/dev/null 2>&1 || fail "xvfb-run is required but not installed"
    runner=(xvfb-run -a --server-args="-screen 0 1280x768x24")
fi

log "Starting ConfigDumpInfo.xml export"
log "Using 1cv8: ${onec_executable}"
log "Dump dir: ${dump_dir}"
log "Result file: ${result_file}"

export_status=0
if (( ${#runner[@]} > 0 )); then
    "${runner[@]}" "${cmd[@]}" || export_status=$?
else
    "${cmd[@]}" || export_status=$?
fi

if [[ "${export_status}" -ne 0 ]]; then
    print_log_tail "${log_file}"
    fail "1cv8 DESIGNER export failed"
fi

dump_file="${dump_dir}/ConfigDumpInfo.xml"
[[ -s "${dump_file}" ]] || {
    print_log_tail "${log_file}"
    fail "ConfigDumpInfo.xml was not created in ${dump_dir}"
}

tmp_result="${result_file}.tmp"
cp "${dump_file}" "${tmp_result}"
mv "${tmp_result}" "${result_file}"

log "ConfigDumpInfo.xml exported successfully"

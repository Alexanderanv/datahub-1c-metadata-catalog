#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPORTER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPORTER="${EXPORTER_DIR}/scripts/export-configdump.sh"

fail() {
    printf '[smoke] ERROR: %s\n' "$*" >&2
    exit 1
}

assert_arg() {
    local file="$1"
    local expected="$2"
    grep -Fxq -- "${expected}" "${file}" || {
        printf '[smoke] args were:\n' >&2
        sed 's/^/[smoke]   /' "${file}" >&2
        fail "expected arg not found: ${expected}"
    }
}

run_case() {
    local name="$1"
    shift
    local expected_file_db=""
    local assignment
    for assignment in "$@"; do
        case "${assignment}" in
            ONEC_FILE_DB=*) expected_file_db="${assignment#ONEC_FILE_DB=}" ;;
        esac
    done

    local tmpdir
    tmpdir="$(mktemp -d)"
    local fake="${tmpdir}/1cv8"
    local args_file="${tmpdir}/args.txt"

    cat > "${fake}" <<'FAKE_1CV8'
#!/usr/bin/env bash
set -Eeuo pipefail

printf '%s\n' "$@" > "${ONEC_FAKE_ARGS_FILE}"

dump_dir=""
log_file=""
previous=""
for arg in "$@"; do
    if [[ "${previous}" == "/DumpConfigToFiles" ]]; then
        dump_dir="${arg}"
    fi
    if [[ "${previous}" == "/Out" ]]; then
        log_file="${arg}"
    fi
    previous="${arg}"
done

mkdir -p "${dump_dir}" "$(dirname "${log_file}")"
printf '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo" format="Hierarchical" version="smoke"/>\n' > "${dump_dir}/ConfigDumpInfo.xml"
printf 'fake 1cv8 ok\n' > "${log_file}"
FAKE_1CV8
    chmod +x "${fake}"

    env \
        ONEC_EXECUTABLE="${fake}" \
        ONEC_FAKE_ARGS_FILE="${args_file}" \
        ONEC_USE_XVFB=never \
        ONEC_OUTPUT_DIR="${tmpdir}/out" \
        ONEC_WORK_DIR="${tmpdir}/work" \
        ONEC_USERNAME=Администратор \
        ONEC_PASSWORD= \
        "$@" \
        "${EXPORTER}" >/dev/null

    [[ -s "${tmpdir}/out/ConfigDumpInfo.xml" ]] || fail "${name}: result file was not created"
    assert_arg "${args_file}" DESIGNER
    assert_arg "${args_file}" /DumpConfigToFiles
    assert_arg "${args_file}" -configDumpInfoOnly
    assert_arg "${args_file}" /Out

    case "${name}" in
        server)
            assert_arg "${args_file}" /S
            assert_arg "${args_file}" 'srv\base'
            ;;
        file)
            assert_arg "${args_file}" /F
            assert_arg "${args_file}" "${expected_file_db}"
            ;;
        ibstring)
            assert_arg "${args_file}" /IBConnectionString
            assert_arg "${args_file}" 'Srvr="srv";Ref="base";'
            ;;
        *)
            fail "unknown test case: ${name}"
            ;;
    esac

    rm -rf "${tmpdir}"
}

run_case server ONEC_SERVER=srv ONEC_INFOBASE=base

file_tmpdir="$(mktemp -d)"
run_case file ONEC_FILE_DB="${file_tmpdir}/ib"
rm -rf "${file_tmpdir}"

run_case ibstring 'ONEC_IB_CONNECTION=Srvr="srv";Ref="base";'

printf '[smoke] ok\n'

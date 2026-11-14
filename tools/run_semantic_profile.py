"""Project07-only fixed Linux admission/cgroup/semantic integration entry point.
No SDK/build, arbitrary command, shared policy change, or unbounded retry.
--probe is for the manager's reviewed kernel admission; it runs no target app.
Local --run requires an exact file/hash-bound manager handoff. CI use requires
the separately authorized exact source event; no CI/public authority is granted here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SELF = ROOT / "tools/run_semantic_profile.py"
CONFIG = ROOT / "tools/semantic-profile.inputs.json"
PREFIX = "contract-evolution-07-"
PUBLIC_LIMIT = 262144


def require(ok, cause):
    if not ok:
        raise ValueError(cause)


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def read_json(path, limit=65536):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit, "Bounded regular JSON required")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_pairs)


def sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Regular hash input required")
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_new(path, value, limit=PUBLIC_LIMIT):
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    require(len(data) <= limit, "Receipt size cap")
    with Path(path).open("xb") as output:
        output.write(data)


def checked_path(value):
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts, "Absolute bounded path required")
    for candidate in (path, *path.parents):
        require(not candidate.is_symlink(), "Symlink input/output not admitted")
    return path.resolve()


def fixed_config():
    value = read_json(CONFIG)
    require(value["schema"] == "contract-evolution/fixed-profile/v1" and value["projectId"] == "07", "Wrong fixed profile")
    require(value["caps"] == {"cpuQuota": 200, "memoryMax": 4294967296, "memorySwapMax": 0, "tasksMax": 128, "runtimeMaxSec": 900, "timeoutStopSec": 15}, "Fixed kernel caps changed")
    require(value["baseline"] == "ce9c2916e591dbe647e50d0990c4af4ba4a2ae88", "Frozen runtime source changed")
    require(value["executionReceiptSha256"] == "45c67dcd400c6444b8b353b71e922e2e69ab7afa9b5ee1297ae73ec54e21081f", "Wrong execution scope")
    return value


def local_env():
    value = os.environ.copy()
    value.update({"XDG_RUNTIME_DIR": "/run/user/1000", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"})
    return value


def command(args, timeout=30, cwd=ROOT, env=None):
    if env is None and "--user" in list(map(str, args))[:3]:
        env = local_env()
    result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, capture_output=True, timeout=timeout)
    require(len(result.stdout) <= 262144 and len(result.stderr) <= 262144, "Helper output bound")
    require(result.returncode == 0, "Owned fixed command failed: " + Path(str(args[0])).name)
    return result.stdout.decode("utf-8").strip()


def own_group(pid):
    lines = (Path("/proc") / str(pid) / "cgroup").read_text().splitlines()
    matches = [line[3:] for line in lines if line.startswith("0::")]
    require(len(matches) == 1 and ".." not in Path(matches[0]).parts, "Unified cgroup required")
    return matches[0]


def systemctl(route, *args):
    prefix = ["systemctl", "--user"] if route == "local-user" else ["systemctl", "--system"]
    return command([*prefix, *args], timeout=10)


def duration_seconds(text):
    # systemctl's standard human-readable USec property, never infinity/default.
    matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)(us|ms|min|h|s)", text)
    require(matches and re.sub(r"([0-9]+(?:\.[0-9]+)?)(us|ms|min|h|s)|\s+", "", text) == "", "Unobserved RuntimeMaxUSec")
    return sum(float(n) * {"us": .000001, "ms": .001, "s": 1, "min": 60, "h": 3600}[unit] for n, unit in matches)


def kernel_guard(request, role):
    group = own_group(os.getpid())
    require(group.endswith("/" + request["unit"]), "Wrong owned unit membership")
    root = Path("/sys/fs/cgroup") / group.lstrip("/")
    quota, period = (root / "cpu.max").read_text().split()
    require(quota != "max" and int(quota) == 2 * int(period), "Real 2CPU quota missing")
    for name, expected in (("memory.max", 4294967296), ("memory.swap.max", 0), ("pids.max", 128)):
        require((root / name).read_text().strip() == str(expected), "Real " + name + " cap missing")
    runtime = duration_seconds(systemctl(request["route"], "show", request["unit"], "--property=RuntimeMaxUSec", "--value"))
    require(0 < runtime <= request["budget"] <= 900, "Real kernel lifetime missing")
    return {"role": role, "pid": os.getpid(), "controlGroup": group, "effectiveCaps": {"cpuQuotaPercent": 200, "memoryMaxBytes": 4294967296, "memorySwapMaxBytes": 0, "tasksMax": 128, "runtimeMaxSeconds": runtime}}


def identities():
    return {"launcherSha256": sha(SELF), "profileSha256": sha(CONFIG), "harnessSha256": sha(ROOT / "tools/integration.py")}


def verify_tools(config):
    for row in config["trustedTools"]:
        require(sha(ROOT / row["path"]) == row["sha256"], "Trusted source tool changed: " + row["path"])


def unit_state(route, unit):
    prefix = ["systemctl", "--user"] if route == "local-user" else ["systemctl", "--system"]
    result = subprocess.run([*prefix, "show", unit, "--property=LoadState,ActiveState,MainPID,ControlGroup"], capture_output=True, timeout=10, env=local_env() if route == "local-user" else None)
    require(len(result.stdout) <= 4096 and len(result.stderr) <= 4096, "Bounded own-unit observation")
    value = dict(line.split("=", 1) for line in result.stdout.decode().splitlines() if "=" in line)
    require(value.get("LoadState") in ("loaded", "not-found"), "Owned unit state unobserved")
    return value


def unit_terminal(state):
    return state["LoadState"] == "not-found" or (state.get("ActiveState") in ("inactive", "failed") and state.get("MainPID") == "0")


def linux_e(value):
    value = str(value).replace("\\", "/")
    if value.startswith("E:/"):
        value = "/mnt/e/" + value[3:]
    return checked_path(value)


def bound_shared_inputs(config):
    binding = config["sharedInputBinding"]
    require(sha(binding["path"]) == binding["sha256"], "Shared input binding identity mismatch")
    value = read_json(binding["path"])
    require(value["schema"] == "wave3-manager-input-binding/v1" and value["approvalSha256"] == config["executionReceiptSha256"], "Different shared input scope")
    require(value["canonicalProtocolSha256"] == config["canonicalProtocolSha256"] == sha(config["leaseProtocol"]), "Protocol binding changed")
    selected = value["project07"]
    require(selected["pgFiveRawFilesFreshBytesAndSha256Verified"] is True and selected["pgFiles"] == config["pg"], "Wrong five-file PG cache")
    require(linux_e(selected["pgArchiveRoot"]) == checked_path(config["localPgArchiveRoot"]), "Different named PG cache not allowed")
    require(linux_e(selected["publicPreviewCache"]) == checked_path(config["localReleaseRoot"]), "Different public preview cache")
    require(selected["priorPublicReceiptSha256"] == config["priorPublicReceipt"]["sha256"] == sha(config["priorPublicReceipt"]["path"]), "Historical provenance receipt changed")
    require(selected["knownFingerprint"] == config["fingerprint"], "Different known key")
    return selected


def manager_handoff(args, config):
    require(args.admission and re.fullmatch("[0-9a-f]{64}", args.admission_sha256 or ""), "Manager file-bound input/profile admission required")
    path = checked_path(args.admission)
    require(sha(path) == args.admission_sha256, "Manager admission file identity mismatch")
    value = read_json(path)
    require(value["schema"] == "contract-evolution/manager-admission/v1" and value["status"] == "PROJECT07_INPUT_PROFILE_KERNEL_ADMITTED" and value["projectId"] == "07", "Manager admission not ready")
    require(value["executionReceiptSha256"] == config["executionReceiptSha256"], "Different technical contract")
    require(checked_path(value["checkout"]) == ROOT and value["identities"] == identities(), "Admission source identity mismatch")
    require(checked_path(value["inputRoot"]) == checked_path(args.inputs), "Admission input path mismatch")
    require(checked_path(value["outputRoot"]) == checked_path(config["localOutputRoot"]), "Admission output root mismatch")
    proof_path = checked_path(value["kernelProof"]["path"])
    require(sha(proof_path) == value["kernelProof"]["sha256"], "Kernel proof file mismatch")
    proof = read_json(proof_path, 262144)
    require(proof["schema"] == "contract-evolution/kernel-probe/v1" and proof["status"] == "CAPS_PROBE_COMPLETE" and proof["identities"] == identities(), "Reviewed kernel proof mismatch")
    require(proof["resource"]["terminalUnit"] and proof["resource"]["cgroupEmpty"], "Admitted probe not terminated")
    require(proof["resource"]["effectiveCaps"]["memoryMaxBytes"] == 4294967296 and proof["resource"]["effectiveCaps"]["tasksMax"] == 128 and proof["resource"]["effectiveCaps"]["cpuQuotaPercent"] == 200 and proof["resource"]["effectiveCaps"]["memorySwapMaxBytes"] == 0 and 0 < proof["resource"]["effectiveCaps"]["runtimeMaxSeconds"] <= 900, "Wrong probe caps")
    require(len(proof["witnesses"]) == 2, "Parent/child inheritance proof required")
    for witness in proof["witnesses"]:
        require(witness["controlGroup"] == proof["resource"]["controlGroup"] and witness["effectiveCaps"] == proof["resource"]["effectiveCaps"], "Kernel witness mismatch")
    require(value["lane"]["project07Approved"] is True, "Local lane does not admit07")
    require(sha(config["leaseProtocol"]) == value["lane"]["protocolSha256"], "Lane protocol identity mismatch")
    require("07" in read_json(config["leaseProtocol"])["participants"], "07 absent from canonical lane")
    bound_shared_inputs(config)
    return value


def claim_lease(config, out):
    token = os.urandom(16).hex()
    path = Path(config["canonicalLease"])
    value = {"projectId": "07", "randomToken": token, "ownerOS": "Linux", "ownerPID": os.getpid(), "ownerProcessStartIdentity": (Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]), "phase": "semantic-matrix", "startedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "receiptDirectory": str(out)}
    write_new(path, value, 4096)  # atomic O_EXCL; existing/ambiguous means HOLD
    return path, value


def release_lease(lease):
    path, expected = lease
    require(read_json(path, 4096) == expected, "Canonical lease owner/token changed; preserve")
    path.unlink()


def download(config, root, started, pg=False):
    # Only fixed public URLs/identities. No latest lookup, retry or arbitrary URL.
    root.mkdir(parents=True, exist_ok=True)
    rows = config["pg"] if pg else config["releaseAssets"]
    for row in rows:
        target = root / row["name"]
        if target.exists():
            require(target.stat().st_size == row["bytes"] and sha(target) == row["sha256"], "Existing pinned cache mismatch; never overwrite")
            continue
        require(time.monotonic() - started < 180, "Aggregate download deadline")
        url = row["url"] if pg else config["releaseBase"] + row["name"]
        request = urllib.request.Request(url, headers={"User-Agent": "contract-evolution-07-fixed-profile"})
        transfer_start = time.monotonic()
        with urllib.request.urlopen(request, timeout=min(90, 180 - (time.monotonic() - started))) as response, target.open("xb") as output:
            total = 0
            digest = hashlib.sha256()
            while True:
                require(time.monotonic() - started < 180 and time.monotonic() - transfer_start < 90, "Bounded transfer deadline")
                block = response.read(min(1024 * 1024, row["bytes"] - total + 1))
                if not block:
                    break
                total += len(block)
                require(total <= row["bytes"], "Download byte cap")
                digest.update(block)
                output.write(block)
            require(total == row["bytes"] and digest.hexdigest() == row["sha256"], "Pinned download mismatch")


def prepare_inputs(request, config, private):
    inputs = checked_path(request["inputs"])
    require(inputs.is_dir(), "Bound input directory missing")
    if request["route"] == "ci-system":
        started = time.monotonic()
        download(config, inputs / "release", started)
        download(config, inputs / "pg-archives", started, pg=True)
        release = inputs / "release"
    else:
        bound_shared_inputs(config)
        release = checked_path(config["localReleaseRoot"])
    for row in config["releaseAssets"]:
        file = release / row["name"]
        require(file.stat().st_size == row["bytes"] and sha(file) == row["sha256"], "Frozen release file mismatch")
    verify_tools(config)
    archive = next(row["name"] for row in config["releaseAssets"] if row["name"].endswith(".tar.gz"))
    command([sys.executable, ROOT / "tools/verify_downloads.py", "--directory", release, "--work", private / "signature", "--trusted-fingerprint", config["fingerprint"], "--archive", archive], timeout=90)
    extracted = private / "frozen-runtime"
    command([sys.executable, ROOT / "tools/extract_package.py", "--archive", release / archive, "--out", extracted], timeout=60)
    packages = list(extracted.iterdir())
    require(len(packages) == 1 and packages[0].is_dir(), "One frozen package required")
    package = packages[0]
    manifest_path = package / "BUILD-MANIFEST.json"
    require(sha(manifest_path) == config["manifestSha256"], "Frozen manifest changed")
    manifest = read_json(manifest_path, 2 * 1024 * 1024)
    require(manifest["sourceCommit"] == config["baseline"] and manifest["sourceTree"] == config["tree"] and manifest["localCandidate"] is False and manifest["rid"] == "linux-x64", "Wrong frozen runtime source/RID")
    expected = set()
    for row in manifest["files"]:
        name = row["path"]
        require(not Path(name).is_absolute() and ".." not in Path(name).parts and "\\" not in name and name not in expected, "Unsafe/duplicate manifest member")
        expected.add(name)
        file = package / name
        require(file.is_file() and not file.is_symlink() and file.stat().st_size == row["bytes"] and sha(file) == row["sha256"], "Frozen member changed")
    require({p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()} == expected | {"BUILD-MANIFEST.json"}, "Frozen file set changed")
    for row in config["appMembers"]:
        require(sha(package / row["path"]) == row["sha256"], "Pinned app identity mismatch")
    archives = inputs / "pg-archives" if request["route"] == "ci-system" else checked_path(config["localPgArchiveRoot"])
    for row in config["pg"]:
        file = archives / row["name"]
        require(file.stat().st_size == row["bytes"] and sha(file) == row["sha256"], "Bound PG input changed")
    # Only this fresh private extraction after manager/kernel admission.
    pg = private / "pg-fixtures"
    command([sys.executable, ROOT / "tools/prepare_linux.py", "--archives", archives, "--out", pg], timeout=180)
    return package, pg


def worker(request_path):
    request = read_json(checked_path(request_path))
    config = fixed_config()
    require(sys.version_info >= (3, 12), "Existing Python3.12+ required; never bootstrap")
    require(request["identities"] == identities(), "Source changed after launch")
    require(request["unit"] == PREFIX + request["runId"][5:] + ".service", "Unit identity mismatch")
    private = checked_path(request["out"]) / "private"
    witness = kernel_guard(request, "launcher")
    # Fixed self-witness, not an arbitrary command runner.
    raw = command([sys.executable, SELF, "--_witness", request_path], timeout=10)
    inherited = json.loads(raw, object_pairs_hook=strict_pairs)
    require(inherited["controlGroup"] == witness["controlGroup"], "Child cgroup inheritance failed")
    write_new(private / "kernel-witnesses.json", [witness, inherited])
    if request["probe"]:
        write_new(private / "resource.inner.json", witness)
        return
    package, pg = prepare_inputs(request, config, private)
    context = {"projectId": "07", "profile": config["profile"], "runId": request["runId"], "controlGroup": witness["controlGroup"], "harnessCommit": request["harnessCommit"], "harnessSha256": sha(ROOT / "tools/integration.py"), "profileSha256": sha(CONFIG), "runtimeCommit": config["baseline"], "runtimeTag": config["releaseTag"], "archiveSha256": next(r["sha256"] for r in config["releaseAssets"] if r["name"].endswith(".tar.gz"))}
    write_new(private / "context.json", context)
    env = os.environ.copy()
    env.update({"CE07_PROFILE_CONTEXT": str(private / "context.json"), "DOTNET_PROCESSOR_COUNT": "2", "PYTHONDONTWRITEBYTECODE": "1"})
    scratch = Path("/tmp") / request["runId"]
    scratch.mkdir(mode=0o700, exist_ok=False)
    require(scratch.stat().st_uid == os.getuid() and scratch.stat().st_mode & 0o777 == 0o700, "Private E-backed Linux scratch required")
    env["TMPDIR"] = str(scratch)
    target = [sys.executable, ROOT / "tools/integration.py", "--apps", package / "apps", "--fixtures", pg, "--out", private / "integration", "--semantic-matrix"]
    remaining = request["deadline"] - time.time() - 15
    require(remaining > 0, "Integration budget exhausted before target")
    command(target, timeout=remaining, env=env)
    # No remaining helper/server is permitted to become a clean-stop proof.
    group_root = Path("/sys/fs/cgroup") / witness["controlGroup"].lstrip("/")
    require(set((group_root / "cgroup.procs").read_text().split()) == {str(os.getpid())}, "Owned descendants not terminal")
    for name in ("memory.peak", "pids.peak"):
        path = group_root / name
        witness[name] = int(path.read_text()) if path.exists() else None
    write_new(private / "resource.inner.json", witness)
    admission = {"schema": "contract-evolution/admission/v1", "status": "ADMITTED", "projectId": "07", "runId": request["runId"], **{k:context[k] for k in ("harnessCommit","harnessSha256","profileSha256","runtimeCommit","runtimeTag","archiveSha256")}, "manifestSha256": config["manifestSha256"], "sourceArchiveSha256": "c632bf60c1a15fdadbc82fd4848c9526660ae830f33bac297fed29b9aa7a99cd", "verifierSha256": sha(ROOT / "tools/verify_downloads.py"), "fingerprint": config["fingerprint"], "pgInputSha256s": {row["name"]: row["sha256"] for row in config["pg"]}, "runtimeMemberSha256s": {row["path"]: row["sha256"] for row in config["appMembers"]}, "historicalReceiptSha256": config["priorPublicReceipt"]["sha256"] if request["route"] == "local-user" else None}
    write_new(Path(request["out"]) / "admission.sanitized.json", admission)


def local_readiness():
    require(os.getuid() == 1000, "Local UID1000 required")
    until = time.monotonic() + 15
    while time.monotonic() < until:
        if Path("/run/user/1000/bus").exists():
            result = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True, timeout=3, env=local_env())
            if result.returncode == 0 and result.stdout.strip() == b"running":
                return
        time.sleep(.25)
    raise ValueError("User bus/manager not ready within bounded wait; no restart/fallback")


def run_parent(args):
    config = fixed_config()
    require(sys.platform == "linux" and os.getuid() != 0, "Non-root Linux only")
    require(re.fullmatch(r"ce07-[0-9a-f]{32}", args.run_id or ""), "Fixed run identity")
    route = "ci-system" if args.ci else "local-user"
    if args.ci:
        require(os.environ.get("GITHUB_ACTIONS") == "true", "Authorized hosted CI context required")
        require(checked_path(os.environ["GITHUB_WORKSPACE"]) == ROOT, "Wrong CI source root")
        output_root = ROOT / "artifacts/ce07-profile"
        started = int(os.environ["CE07_JOB_START_EPOCH"])
        budget = min(900, 1200 - int(time.time() - started) - 60)
        require(budget >= 90, "Insufficient remaining20m job budget")
        command(["sudo", "-n", "true"], timeout=5)
    else:
        require(ROOT == checked_path(config["localCheckout"]), "Wrong allocated local checkout")
        local_readiness()
        output_root = checked_path(config["localOutputRoot"])
        budget = 900  # probe observes the actual fixed lifetime; its parent wall is30s
    out = checked_path(args.out)
    require(out.parent == output_root and out.name == args.run_id and not out.exists(), "Fresh fixed output path required")
    inputs = checked_path(args.inputs) if args.inputs else None
    handoff = None
    if not args.probe:
        require(inputs is not None, "Bound inputs required")
        if not args.ci:
            require(inputs == checked_path(config["localInputRoot"]), "Wrong fixed local admission root")
            handoff = manager_handoff(args, config)
    if args.ci:
        require(inputs == ROOT / "artifacts/ce07-profile/inputs" if not args.probe else True, "Fixed CI input root")
    if inputs is not None:
        inputs.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    out.mkdir(mode=0o700)
    (out / "private").mkdir(mode=0o700)
    # No new evidence overwrites, no manager acknowledgment per child command.
    request = {"runId": args.run_id, "unit": PREFIX + args.run_id[5:] + ".service", "route": route, "out": str(out), "inputs": str(inputs) if inputs else None, "probe": args.probe, "budget": budget, "deadline": time.time() + budget, "identities": identities(), "handoff": handoff, "harnessCommit": command(["git", "rev-parse", "HEAD"], timeout=10)}
    write_new(out / "private/request.json", request)
    lease = None
    if not args.probe and not args.ci:
        lease = claim_lease(config, out)
    properties = [f"CPUQuota=200%", "MemoryMax=4294967296", "MemorySwapMax=0", "TasksMax=128", f"RuntimeMaxSec={budget}s", "TimeoutStopSec=15s", "KillMode=control-group"]
    launch = ["systemd-run", "--wait", "--pipe", "--quiet", "--unit=" + request["unit"], "--working-directory=" + str(ROOT)]
    if args.ci:
        launch = ["sudo", "-n", *launch, "--uid=" + str(os.getuid()), "--gid=" + str(os.getgid())]
    else:
        launch.insert(1, "--user")
    for prop in properties:
        launch.extend(["--property", prop])
    if not args.ci:
        launch.extend(["--setenv=XDG_RUNTIME_DIR=/run/user/1000", "--setenv=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"])
    launch.extend(["--setenv=PYTHONDONTWRITEBYTECODE=1", "--setenv=PATH=/usr/bin:/bin", "--", "/usr/bin/python3", str(SELF), "--_worker", str(out / "private/request.json")])
    process = None
    group = None
    terminal = False
    complete = False
    failure_type = None
    start = time.monotonic()
    try:
        with (out / "private/unit-console.log").open("xb") as log:
            process = subprocess.Popen(launch, stdout=log, stderr=subprocess.STDOUT, env=local_env() if not args.ci else None)
            until = time.monotonic() + (30 if args.probe else budget) + 15
            while process.poll() is None:
                require(time.monotonic() < until, "Owned unit lifetime exceeded")
                require(log.tell() <= config["bounds"]["logsBytes"], "Console log cap")
                size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file() and not p.is_symlink())
                require(size <= config["bounds"]["workspaceBytes"], "Workspace byte budget")
                scratch = Path("/tmp") / args.run_id
                if scratch.exists():
                    size += sum(p.stat().st_size for p in scratch.rglob("*") if p.is_file() and not p.is_symlink())
                    require(size <= config["bounds"]["workspaceBytes"], "PG scratch workspace budget")
                time.sleep(.5)
            require(process.returncode == 0, "Owned fixed profile failed; retain private cause")
        inner = read_json(out / "private/resource.inner.json", 262144)
        group = inner["controlGroup"]
        group_path = Path("/sys/fs/cgroup") / group.lstrip("/")
        require(not group_path.exists() or not (group_path / "cgroup.procs").read_text().strip(), "Cgroup not empty after fixed command")
        # systemd-run --wait success plus actual empty owned group; never cleanup kill == pass.
        require(unit_terminal(unit_state(route, request["unit"])), "Owned unit terminal state unobserved")
        terminal = True
        members = read_json(out / "private/kernel-witnesses.json", 262144)
        by_role = {row["role"]: [row["pid"]] for row in members}
        if not args.probe:
            evidence = read_json(out / "private/integration/membership.private.json", 262144)
            for row in evidence:
                require(row["controlGroup"] == group, "Actual worker membership mismatch")
                by_role.setdefault(row["role"], []).append(row["pid"])
        resource = {"schema": "contract-evolution/resources/v1", "status": "CAPS_PROBE_COMPLETE" if args.probe else "OBSERVED_EFFECTIVE_CAPS_AND_TERMINAL", "projectId": "07", "runId": args.run_id, "unit": request["unit"], "controlGroup": group, "effectiveCaps": inner["effectiveCaps"], "parentPid": members[0]["pid"], "membershipByRole": by_role, "elapsedSeconds": round(time.monotonic() - start, 3), "peakMemoryBytes": inner.get("memory.peak"), "peakTasks": inner.get("pids.peak"), "terminalUnit": terminal, "cgroupEmpty": True}
        write_new(out / "resource.sanitized.json", resource)
        if args.probe:
            write_new(out / "kernel-probe.private.json", {"schema": "contract-evolution/kernel-probe/v1", "status": "CAPS_PROBE_COMPLETE", "identities": identities(), "witnesses": members, "resource": resource})
        else:
            publish_summary(out, request, config)
        complete = True
    except BaseException as error:
        failure_type = type(error).__name__
        raise
    finally:
        if process is not None:
            try:
                state = unit_state(route, request["unit"])
                if process.poll() is None or not unit_terminal(state):
                    stop = ["systemctl", "--user", "stop", request["unit"]] if not args.ci else ["sudo", "-n", "systemctl", "stop", request["unit"]]
                    command(stop, timeout=15)
                    process.wait(timeout=15)
                    state = unit_state(route, request["unit"])
                group = group or state.get("ControlGroup")
                if not group and (out / "private/kernel-witnesses.json").exists():
                    group = read_json(out / "private/kernel-witnesses.json", 262144)[0]["controlGroup"]
                empty = not group or not (Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs").exists() or not (Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs").read_text().strip()
                terminal = unit_terminal(state) and process.poll() is not None and empty
            except Exception:
                terminal = False
        if not complete:
            write_new(out / "incomplete.private.json", {"status": "INCOMPLETE_NOT_A_PASS", "errorType": failure_type or "UNOBSERVED", "terminalUnit": terminal, "scope": "No semantic or clean-completion inference; retain private diagnostics"})
        # Fair release on a proven-terminal failure; cleanup kill never becomes PASS.
        if lease is not None and terminal:
            release_lease(lease)



def publish_summary(out, request, config):
    private = out / "private/integration"
    receipt = read_json(private / "receipt.json", 262144)
    matrix_path = private / "semantic-matrix.json"
    matrix = read_json(matrix_path, 262144)
    require(receipt["status"] == matrix["status"] == "PASS", "Incomplete profile not publishable")
    require((receipt["caseCount"], receipt["effectCount"], receipt["total"], receipt["finalStage"]) == (15, 52, 3556, 2), "Full conservation differs")
    require(matrix["rollback"]["status"] == "ROLLBACK_BLOCKED" and matrix["rollback"]["sqlUnchanged"], "Explicit blocked rollback missing")
    require(matrix["caseCounts"] == {"frames": 8, "parserObservations": 16, "rpcCalls": 16}, "Incomplete matrix")
    require(len(matrix["cases"]) == 8 and len({c["id"] for c in matrix["cases"]}) == 8, "Missing/duplicate cases")
    # Known schema only; do not upload raw private history or environment/config.
    require(set(matrix) == {"schema","status","projectId","runId","harnessCommit","harnessSha256","profileSha256","runtimeCommit","runtimeTag","archiveSha256","cases","caseCounts","binaryIdentityBefore","binaryIdentityAfter","rollback"}, "Unexpected matrix fields")
    write_new(out / "semantic-matrix.json", matrix)
    summary = {"schema": "contract-evolution/profile-summary/v1", "status": "PASS", "projectId": "07", "runId": request["runId"], "harnessCommit": request["harnessCommit"], "runtimeCommit": config["baseline"], "profileSha256": sha(CONFIG), "caseCount": 15, "effectCount": 52, "total": 3556, "finalStage": 2, "rollbackStatus": "ROLLBACK_BLOCKED", "inputReceiptSha256": sha(out / "admission.sanitized.json"), "resourceReceiptSha256": sha(out / "resource.sanitized.json"), "matrixReceiptSha256": sha(out / "semantic-matrix.json"), "legacyReproductionBoundary": config["runtimeBoundary"], "elapsedSeconds": read_json(out / "resource.sanitized.json")["elapsedSeconds"]}
    write_new(out / "receipt.sanitized.json", summary)
    require(sum((out / name).stat().st_size for name in config["publicFiles"]) <= 1048576, "Total sanitized output cap")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs")
    p.add_argument("--out")
    p.add_argument("--run-id")
    p.add_argument("--admission")
    p.add_argument("--admission-sha256")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--ci", action="store_true")
    p.add_argument("--_worker", help=argparse.SUPPRESS)
    p.add_argument("--_witness", help=argparse.SUPPRESS)
    a = p.parse_args()
    if a._worker:
        worker(a._worker)
    elif a._witness:
        request = read_json(checked_path(a._witness))
        require(request["identities"] == identities(), "Witness source changed")
        print(json.dumps(kernel_guard(request, "inheritance-witness")))
    else:
        require(a.out and a.run_id, "Fixed output/run identity required")
        run_parent(a)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "INCOMPLETE_NOT_A_PASS", "errorType": type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)

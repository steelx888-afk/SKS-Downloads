import hashlib
import json
import os
import pathlib
import plistlib
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "ci/mac-release-019.json").read_text(encoding="utf-8-sig"))
TEMP = pathlib.Path(os.environ["RUNNER_TEMP"])
REPO = "steelx888-afk/SKS-Downloads"
TAG = os.environ["CACHE_TAG"]
RUN_ID = os.environ["GITHUB_RUN_ID"]
ARCH = os.environ["BUILD_ARCH"]
EXPECTED_MACHINE = "arm64" if ARCH == "arm64" else "x86_64"
APPS = ("designz", "proz")
PORTS = {"designz": range(8851, 8861), "proz": range(8861, 8871)}
LOG = TEMP / f"mac-final-startup-{ARCH}.log"
CLOCK_NAME = f"final-startup-clock-{RUN_ID}.json"


def command(args, capture=False, check=True):
    with LOG.open("a", encoding="utf-8") as log:
        result = subprocess.run(
            [str(value) for value in args],
            stdout=subprocess.PIPE if capture else log,
            stderr=log,
            text=True,
        )
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {pathlib.Path(str(args[0])).name}")
    return result.stdout.strip() if capture else result.returncode


def upload(*files):
    command(["gh", "release", "upload", TAG, "-R", REPO, "--clobber", *files])


def download(pattern, destination, check=True):
    destination.mkdir(parents=True, exist_ok=True)
    return command(
        ["gh", "release", "download", TAG, "-R", REPO, "--pattern", pattern, "--dir", destination, "--clobber"],
        check=check,
    )


def file_sha256(file):
    with pathlib.Path(file).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def release_assets():
    value = command(["gh", "release", "view", TAG, "-R", REPO, "--json", "assets"], capture=True)
    return {asset["name"] for asset in json.loads(value)["assets"] if asset["state"] == "uploaded"}


def http(url, body=None):
    payload = json.dumps(body).encode() if body else None
    request = urllib.request.Request(url, data=payload, headers={"content-type": "application/json"})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else {}


def prepare():
    if os.uname().machine != EXPECTED_MACHINE:
        raise RuntimeError(f"Expected {EXPECTED_MACHINE}, got {os.uname().machine}")
    cache = TEMP / "final-startup"
    prepared = {}
    for app in APPS:
        archive = cache / f"SKS-{app.upper()}-0.1.19-universal.zip"
        download(archive.name, cache)
        unpacked = TEMP / f"prepared-{app}"
        unpacked.mkdir(parents=True, exist_ok=True)
        command(["ditto", "-x", "-k", archive, unpacked])
        bundle = next(unpacked.glob("*.app"))
        info = plistlib.load((bundle / "Contents/Info.plist").open("rb"))
        if info["CFBundleShortVersionString"] != "0.1.19":
            raise RuntimeError(f"Unexpected {app} package version")
        prepared[app] = {
            "archive": archive,
            "archiveSha256": file_sha256(archive),
            "bundle": bundle,
            "binary": bundle / "Contents/MacOS" / info["CFBundleExecutable"],
        }
    marker = cache / f"final-ready-{RUN_ID}-{ARCH}.json"
    marker.write_text(
        json.dumps(
            {
                "runId": RUN_ID,
                "arch": ARCH,
                "machine": os.uname().machine,
                "preparedAtMs": int(time.time() * 1000),
                "archives": {app: prepared[app]["archiveSha256"] for app in APPS},
            },
            indent=2,
        )
    )
    upload(marker)
    print(f"Prepared DESIGNZ and PROZ on {ARCH}; waiting for the other native runner.", flush=True)
    required = {f"final-ready-{RUN_ID}-arm64.json", f"final-ready-{RUN_ID}-x64.json"}
    end = time.time() + 600
    while time.time() < end:
        if required <= release_assets():
            return cache, prepared
        time.sleep(5)
    raise RuntimeError("The other native runner did not finish preparation; no test clock was started.")


def shared_clock(cache):
    clock = cache / CLOCK_NAME
    if ARCH == "arm64":
        now = int(time.time() * 1000)
        clock.write_text(
            json.dumps(
                {
                    "runId": RUN_ID,
                    "startedAtMs": now,
                    "deadlineMs": now + 120_000,
                    "limitSeconds": 120,
                    "authorization": "Finish remaining checks (2-minute cap)",
                    "scope": ["designz-arm64", "designz-x64", "proz-arm64", "proz-x64"],
                },
                indent=2,
            )
        )
        upload(clock)
    else:
        end = time.time() + 30
        while time.time() < end and CLOCK_NAME not in release_assets():
            time.sleep(1)
        if CLOCK_NAME not in release_assets():
            raise RuntimeError("The shared two-minute clock was not created.")
        download(CLOCK_NAME, cache)
    value = json.loads(clock.read_text())
    if value["runId"] != RUN_ID or value["limitSeconds"] != 120:
        raise RuntimeError("Invalid shared test clock")
    return value


def stop_process(child):
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def verify_app(app, prepared, clock, cache):
    deadline = clock["deadlineMs"] / 1000
    if time.time() >= deadline - 8:
        raise RuntimeError("Shared two-minute cap reached before the next startup case.")
    state = TEMP / f"isolated-final-{app}"
    state.mkdir(exist_ok=True)
    debug_port = 19301 if app == "designz" else 19302
    env = {
        **os.environ,
        "HOME": str(state),
        "SKS_HOME": str(state / "agent-home"),
        "SKS_APP_ID": app,
    }
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env.pop("NODE_OPTIONS", None)
    started = time.time()
    with LOG.open("a", encoding="utf-8") as log:
        child = subprocess.Popen(
            [
                str(prepared["binary"]),
                "--no-first-run",
                f"--remote-debugging-port={debug_port}",
                "--enable-logging=stderr",
            ],
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    try:
        ready = None
        case_end = min(deadline - 3, started + 35)
        while time.time() < case_end:
            if child.poll() is not None:
                raise RuntimeError(f"{app} exited before startup")
            for port in PORTS[app]:
                try:
                    status, health = http(f"http://127.0.0.1:{port}/health")
                    if status == 200 and health.get("ok") and health.get("appId") == app:
                        ready = (port, health)
                        break
                except Exception:
                    pass
            if ready:
                break
            time.sleep(0.25)
        if not ready:
            raise RuntimeError(f"{app} did not become ready within its focused startup case")
        port, health = ready
        if health.get("authRequired") is not True:
            raise RuntimeError(f"{app} did not preserve required sign-in")
        status, denied = http(f"http://127.0.0.1:{port}/desk", {"action": "state"})
        if status != 401 or denied.get("code") != "signin_required":
            raise RuntimeError(f"{app} did not protect unsigned desk access")
        status, identity = http(f"http://127.0.0.1:{port}/desk", {"action": "account.auth.status"})
        if status != 200 or identity["centralAccount"]["app"]["id"] != app:
            raise RuntimeError(f"{app} returned the wrong product identity")
        renderer_loaded = False
        while time.time() < case_end:
            try:
                status, pages = http(f"http://127.0.0.1:{debug_port}/json/list")
                renderer_loaded = status == 200 and any(
                    page.get("type") == "page"
                    and (
                        page.get("url", "").startswith("app://sks/index.html")
                        or ("/renderer/" in page.get("url", "") and "index.html" in page.get("url", ""))
                    )
                    for page in pages
                )
            except Exception:
                renderer_loaded = False
            if renderer_loaded:
                break
            time.sleep(0.25)
        if not renderer_loaded or time.time() > deadline:
            raise RuntimeError(f"{app} renderer did not load before the shared deadline")
        proof = {
            "ok": True,
            "scope": "remaining-native-startup-only",
            "app": app,
            "arch": ARCH,
            "machine": os.uname().machine,
            "macOS": command(["sw_vers", "-productVersion"], capture=True),
            "sourceCommit": CONFIG["products"][app]["commit"],
            "version": "0.1.19",
            "archiveSha256": prepared["archiveSha256"],
            "packagedAppStarted": True,
            "rendererLoaded": True,
            "nativeAgentReady": True,
            "productIdentity": app,
            "protectedDeskDeniedUnsigned": True,
            "signedOutAdapterReady": True,
            "testedAtMs": int(time.time() * 1000),
            "deadlineMs": clock["deadlineMs"],
            "clockAsset": CLOCK_NAME,
            "screenControlUsed": False,
        }
        proof_file = cache / f"proof-{app}-{ARCH}.json"
        proof_file.write_text(json.dumps(proof, indent=2))
        print(f"Passed focused native Mac startup: {app} {ARCH}", flush=True)
        return proof_file
    finally:
        stop_process(child)


def main():
    cache, prepared = prepare()
    clock = shared_clock(cache)
    print("Shared two-minute startup clock started.", flush=True)
    proofs = [verify_app(app, prepared[app], clock, cache) for app in APPS]
    upload(*proofs)
    print(f"All remaining native startup cases passed on {ARCH}.", flush=True)


try:
    main()
except Exception as error:
    print(str(error) or type(error).__name__, file=sys.stderr, flush=True)
    if LOG.exists():
        try:
            upload(LOG)
        except Exception:
            pass
    sys.exit(1)

#!/usr/bin/env python3
"""The measurement session, natively on Windows (i7-13700F), Next.js vs SvelteKit vs Nuxt.

Per round, each framework (order rotates every round) runs four cells, one after another:

  build    a clean production build (`next build`, `vite build`, `nuxt build`), wall time, pinned to the 16 P-core threads
  ssr      the production server (one Node process, as each framework's start command runs it) pinned to four
           P-cores, oha on four other P-cores: 8 s warm-up, then 20 s at full speed with 64 connections on GET /
           (100 products rendered on the server); req/s, latency, server memory
  browser  real Chrome (headless, CPU slowed 4x) on the same server, 10 fresh page loads: time until the page's
           code has run, then "Show 1,000" (create 1,000 cards) and "10% off" (update all 1,000 prices)
  sizes    (round 1 and the plain round) every script the page and /hello load, compressed by us at fixed settings

Rounds 1..N record oha's live screen as an asciinema cast (and round 1 films one extra, unmeasured browser run);
one final round runs oha with --no-tui, to check that recording didn't move the numbers. Every server's HTML is
checked to carry the same 100 products (ids, names, prices) before it is measured.

usage (from the repo root):  python tools/session.py RESULTS_DIR [ROUNDS=5]
env:  BENCH_SECONDS_SCALE (pilot: 0.25), BENCH_BROWSER_RUNS (default 10), BENCH_NO_GATE=1 (pilot only),
      BENCH_SIDES=next,svelte,nuxt
"""
import hashlib
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

BUILD_CPUS = list(range(16))  # all P-core threads; E-cores 16-23 untouched
SERVER_CPUS = [0, 2, 4, 6]  # one logical CPU per physical P-core
OHA_CPUS = [8, 9, 10, 11, 12, 13, 14, 15]  # four other physical P-cores; Chrome runs here too (never beside oha)
QUIET_CPUS = SERVER_CPUS + [c + 1 for c in SERVER_CPUS] + OHA_CPUS
PORT = int(os.environ.get("BENCH_PORT", "8133"))
BASE = f"http://127.0.0.1:{PORT}"
CONNECTIONS = 64
SCALE = float(os.environ.get("BENCH_SECONDS_SCALE", "1"))
BROWSER_RUNS = int(os.environ.get("BENCH_BROWSER_RUNS", "10"))
# Quiet gate: our cores' mean and max CPU % over 5 s. BENCH_GATE_MAX can raise the max when one Windows service thread
# (WmiPrvSE on 2026-11-09) keeps hopping across idle cores; every reading is kept in busy_before either way.
GATE_MEAN = float(os.environ.get("BENCH_GATE_MEAN", "5"))
GATE_MAX = float(os.environ.get("BENCH_GATE_MAX", "15"))
COLS, ROWS = 64, 14  # oha's live screen at a size that stays readable on a phone (100, 110)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PY = str(Path(sys.executable).with_name("python.exe")) if os.name == "nt" else sys.executable
TOOLS = Path(__file__).parent
ROOT = TOOLS.parent
OHA = os.environ.get("OHA") or shutil.which("oha") or "oha"
NODE = shutil.which("node") or "node"

SIDES = {
    "next": {"dir": "next", "clean": [".next"],
             "build": ["node_modules/next/dist/bin/next", "build"],
             "start": ["node_modules/next/dist/bin/next", "start", "-H", "127.0.0.1", "-p", str(PORT)],
             "packages": ["next", "react", "react-dom"]},
    "svelte": {"dir": "svelte", "clean": [".svelte-kit", "build"],
               "build": ["node_modules/vite/bin/vite.js", "build"],
               "start": ["build/index.js"],
               "packages": ["@sveltejs/kit", "svelte", "vite", "@sveltejs/adapter-node"]},
    "nuxt": {"dir": "nuxt", "clean": [".nuxt", ".output", "node_modules/.cache"],
             "build": ["node_modules/nuxt/bin/nuxt.mjs", "build"],
             "start": [".output/server/index.mjs"],
             "packages": ["nuxt", "vue", "nitropack", "vite"]},
}
ENV = {"PORT": str(PORT), "HOST": "127.0.0.1", "NITRO_HOST": "127.0.0.1", "NODE_ENV": "production",
       "NEXT_TELEMETRY_DISABLED": "1", "NUXT_TELEMETRY_DISABLED": "1"}
CARD = re.compile(r'data-id="(\d+)".*?<h2>(.*?)</h2>.*?class="price">(.*?)</span>', re.DOTALL)


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def secs(s: float) -> int:
    return max(2, round(s * SCALE))


def quiet_gate(max_wait: int = 1800) -> dict:
    """Waits until the benchmark's cores are idle (mean under 5%, none over 15% across 5 s) and the whole machine
    under 15%; returns that reading. Gives up after max_wait: a busy machine (a game, a video render) voids the
    numbers."""
    if os.environ.get("BENCH_NO_GATE") == "1":
        return {"gate": "skipped"}
    waited = 0
    while True:
        per = psutil.cpu_percent(interval=5, percpu=True)
        ours = [per[c] for c in QUIET_CPUS]
        reading = {"cores_mean": round(sum(ours) / len(ours), 1), "cores_max": max(ours), "total": round(sum(per) / len(per), 1)}
        if reading["cores_mean"] < GATE_MEAN and reading["cores_max"] < GATE_MAX and reading["total"] < 15:
            return reading
        if waited >= max_wait:
            raise RuntimeError(f"machine stayed busy for {max_wait} s: {reading}")
        if waited % 300 == 0:
            log(f"machine busy {reading}, waiting")
        waited += 5


def pinned(cpus: list[int], argv: list[str]) -> list[str]:
    return [PY, str(TOOLS / "pin.py"), ",".join(map(str, cpus)), *argv]


def get(path: str, timeout: float = 10) -> tuple[int, bytes]:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
        return resp.status, resp.read()


def cards(page: bytes) -> list[tuple[str, str, str]]:
    """(id, name, price) of every product card in a server-rendered page, as text."""
    text = page.decode("utf-8")
    return [(i, html.unescape(re.sub(r"<!--.*?-->", "", n)), html.unescape(re.sub(r"<!--.*?-->", "", p))) for i, n, p in CARD.findall(text)]


def build(side: str) -> dict:
    spec = SIDES[side]
    app = ROOT / spec["dir"]
    for d in spec["clean"]:
        shutil.rmtree(app / d, ignore_errors=True)
    busy = quiet_gate()
    t0 = time.perf_counter()
    proc = subprocess.run(pinned(BUILD_CPUS, [NODE, *spec["build"]]), check=False, cwd=app, env=dict(os.environ, **ENV),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    seconds = time.perf_counter() - t0
    if proc.returncode != 0:
        raise RuntimeError(f"{side} build failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
    return {"build_s": round(seconds, 3), "busy_before": busy}


class Server:
    """One framework's production server, pinned to SERVER_CPUS from its first instruction (pin.py sets the mask,
    node and anything it starts inherit it)."""

    def __init__(self, side: str):
        spec = SIDES[side]
        t0 = time.time()
        self.wrapper = subprocess.Popen(pinned(SERVER_CPUS, [NODE, *spec["start"]]), cwd=ROOT / spec["dir"],
                                        env=dict(os.environ, **ENV), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=NO_WINDOW)
        self.ready_s = self._wait_ready(t0)

    def _wait_ready(self, t0: float) -> float:
        deadline = t0 + 120
        while time.time() < deadline:
            if self.wrapper.poll() is not None:
                raise RuntimeError(f"server exited with {self.wrapper.returncode}")
            try:
                status, _ = get("/", 2)
                if status == 200:
                    return round(time.time() - t0, 2)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                pass
            time.sleep(0.1)
        raise RuntimeError("server not ready after 120 s")

    def tree(self) -> list[psutil.Process]:
        try:
            kids = psutil.Process(self.wrapper.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            return []
        return [k for k in kids if k.name().lower().startswith("node")]

    def memory_mb(self) -> float:
        """Working set of every node process the server runs (Next.js may start more than one)."""
        total = 0
        for p in self.tree():
            try:
                total += p.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        return round(total / 2**20, 1)

    def stop(self) -> None:
        procs = self.tree()
        try:
            procs += psutil.Process(self.wrapper.pid).children(recursive=True) + [psutil.Process(self.wrapper.pid)]
        except psutil.NoSuchProcess:
            pass
        for p in procs:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(procs, timeout=30)
        self.wrapper.wait(timeout=30)
        for _ in range(100):  # the port must be free, or the next server's checks would reach this one
            try:
                get("/", 0.5)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                return
            time.sleep(0.1)
        raise RuntimeError("old server still answers after stop")


def oha_argv(seconds: int, export: Path | None, tui: bool) -> list[str]:
    argv = [OHA, "-z", f"{seconds}s", "-c", str(CONNECTIONS), BASE + "/"]
    argv += ["--output-format", "json", "-o", str(export)] if export else ["--output-format", "quiet"]
    if not tui:
        argv.append("--no-tui")
    return pinned(OHA_CPUS, argv)


def ssr(server: Server, side: str, rdir: Path, record: bool) -> dict:
    subprocess.check_call(oha_argv(secs(8), None, False), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=NO_WINDOW)
    export = rdir / f"{side}-ssr.json"
    argv = oha_argv(secs(20), export, record)
    mem: list[float] = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(0.5):
            mem.append(server.memory_mb())

    sampler = threading.Thread(target=sample)
    busy = quiet_gate()
    sampler.start()
    t0 = time.time()
    try:
        if record:
            rc = subprocess.call([PY, str(TOOLS / "cast.py"), str(rdir / f"{side}-ssr.cast"), str(COLS), str(ROWS), "--", *argv],
                                 creationflags=NO_WINDOW)
        else:
            rc = subprocess.call(argv, stdout=subprocess.DEVNULL, creationflags=NO_WINDOW)
    finally:
        stop.set()
        sampler.join()
    cpu_during = psutil.cpu_percent(percpu=True)
    if rc != 0 or not export.exists():
        raise RuntimeError(f"{side} ssr: oha failed ({rc})")
    report = json.loads(export.read_text(encoding="utf-8"))
    codes = report.get("statusCodeDistribution", {})
    if set(codes) != {"200"}:
        raise RuntimeError(f"{side} ssr: non-200 responses {codes} {report.get('errorDistribution')}")
    pct = report["latencyPercentiles"]
    ws = sorted(mem) or [0.0]
    return {"started": t0, "seconds": secs(20), "busy_before": busy, "rps": report["summary"]["requestsPerSec"],
            "requests": sum(codes.values()), "p50_ms": pct["p50"] * 1000, "p99_ms": pct["p99"] * 1000,
            "max_ms": report["summary"]["slowest"] * 1000, "errors": report.get("errorDistribution", {}),
            "mem_mb_median": ws[len(ws) // 2], "mem_mb_max": ws[-1], "cpu_percpu_during": cpu_during}


def browser(side: str, rdir: Path, sizes: bool, film: bool) -> dict:
    out = rdir / f"{side}-browser.json"
    argv = [NODE, str(TOOLS / "browser.mjs"), "--url", BASE, "--runs", str(BROWSER_RUNS), "--out", str(out)]
    if sizes:
        argv += ["--sizes", str(rdir / f"{side}-sizes.json")]
    if film:
        argv += ["--film", str(rdir / f"{side}-film")]
    busy = quiet_gate()
    proc = subprocess.run(pinned(OHA_CPUS, argv), check=False, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"{side} browser failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    report = json.loads(out.read_text(encoding="utf-8"))
    res = {"busy_before": busy, "chrome": report["chrome"], "cpu_slowdown": report["cpu_slowdown"], "browser_runs": report["runs"]}
    if sizes:
        res["sizes"] = json.loads((rdir / f"{side}-sizes.json").read_text(encoding="utf-8"))
    return res


def run_side(side: str, r: int, rdir: Path, record: bool) -> dict:
    row = {"side": side, "round": r if record else "plain"}
    row.update(build(side))
    log(f"  {side:6s} build {row['build_s']:6.1f} s")
    server = Server(side)
    try:
        status, page = get("/")
        found = cards(page)
        if status != 200 or len(found) != 100:
            raise RuntimeError(f"{side}: GET / gave {status} with {len(found)} product cards")
        row.update(ready_s=server.ready_s, idle_mem_mb=server.memory_mb(), html_bytes=len(page),
                   cards_sha256=hashlib.sha256(json.dumps(found).encode()).hexdigest(), first_card=list(found[0]))
        row.update(ssr(server, side, rdir, record))
        log(f"  {side:6s} ssr {row['rps']:8,.0f} req/s  p99 {row['p99_ms']:7.1f} ms  mem {row['mem_mb_median']:6.1f} MB")
        row.update(browser(side, rdir, sizes=r == 1 or not record, film=record and r == 1))
        runs = row["browser_runs"]
        med = lambda k: sorted(x[k] for x in runs)[len(runs) // 2]
        log(f"  {side:6s} browser ready {med('ready_ms'):6.0f} ms  create {med('create_ms'):6.0f} ms  update {med('update_ms'):6.0f} ms")
    finally:
        server.stop()
    return row


def order_for(round_no: int, sides: list[str]) -> list[str]:
    k = (round_no - 1) % len(sides)
    return sides[k:] + sides[:k]


def versions(sides: list[str]) -> dict:
    def cmd(*a: str) -> str:
        try:
            return subprocess.run(a, check=False, capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
        except OSError as e:
            return f"unavailable: {e}"
    pkgs = {}
    for side in sides:
        app = ROOT / SIDES[side]["dir"]
        for name in SIDES[side]["packages"]:
            pj = app / "node_modules" / name / "package.json"
            pkgs[f"{side}:{name}"] = json.loads(pj.read_text())["version"] if pj.exists() else None
    return {"node": cmd(NODE, "-v"), "oha": cmd(OHA, "--version"), "packages": pkgs, "os": platform.platform(),
            "cpu": platform.processor(), "power_plan": cmd("powercfg", "/getactivescheme") if os.name == "nt" else ""}


def main() -> int:
    results = Path(sys.argv[1]).resolve()
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    sides = os.environ.get("BENCH_SIDES", "next,svelte,nuxt").split(",")
    results.mkdir(parents=True, exist_ok=False)
    (results / "meta.json").write_text(json.dumps(
        {"versions": versions(sides), "rounds": rounds, "sides": sides, "build_cpus": BUILD_CPUS,
         "server_cpus": SERVER_CPUS, "oha_cpus": OHA_CPUS, "connections": CONNECTIONS, "seconds_scale": SCALE,
         "browser_runs": BROWSER_RUNS, "gate": {"mean": GATE_MEAN, "max": GATE_MAX}, "started": time.ctime()}, indent=2))
    log("waiting for a quiet machine (up to 4 h)")
    quiet_gate(max_wait=4 * 3600)
    shas = set()
    for r in range(1, rounds + 2):
        record = r <= rounds
        rdir = results / (f"round{r}" if record else "plain")
        rdir.mkdir()
        log(f"round {r} ({'recorded' if record else 'plain'})")
        for side in order_for(r, sides):
            row = run_side(side, r, rdir, record)
            shas.add(row["cards_sha256"])
            if len(shas) != 1:
                raise RuntimeError(f"{side}: its 100 product cards differ from the other frameworks'")
            with open(results / "runs.jsonl", "a") as f:
                f.write(json.dumps(row) + "\n")
    (results / "meta.json").write_text(json.dumps(
        {**json.loads((results / "meta.json").read_text()), "finished": time.ctime()}, indent=2))
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

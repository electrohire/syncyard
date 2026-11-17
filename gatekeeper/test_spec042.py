#!/usr/bin/env python3
"""Scenario battery for spec 042 slice 1: the `gk power`
verb family (FR-001..FR-007) and the downtime record
module (FR-011..FR-013, FR-016).

Golden style (as test_spec011.py): temp dir, copied
gk.py + config.py, a written test config (SYNCYARD_CONFIG)
with a Linux fleet shape, subprocess drivers, stubs at the
module seams (ledger, gh_json, fetch_backchannel_heartbeat,
_power_host_back, _power_signal where ordering matters).
NO LIVE FIRE: every signal path runs against stubs or the
real submit machinery pointed at the temp queue only.

Covers:
  - config: power/downtime validation fail-closed, the
    ratified defaults (900 / 180), host exception flags;
  - poweroff's confirm gate, and DOWN-BY-ACTION recorded
    in the host's power section BEFORE the signal seam
    runs (ordering asserted at the seam);
  - drain refusal naming active jobs; the --drain path
    (clean drain proceeds, an uncheckpointed job refuses
    by name); the --force override gate and its record;
  - cancel: scheduled withdrawal, in-grace abort with
    verdicts from observed state (CANCELLED-CONFIRMED /
    CANCEL-FAILED), immediate signal NOT-CANCELLABLE;
  - boot-back: VERIFIED only after observed silence,
    RETURN-MISSED opening a BY-ACTION downtime record,
    VERIFIED-LATE amendment; CONFIRMED-DOWN after the
    full silence window; UNREACHABLE with no live route;
  - the macOS and off-fleet gates (FR-016);
  - downtime: dedupe (a second detection adds no record
    and no push), class from evidence only, the ruling-D4
    push set (no push on open, no push on close, exactly
    one push on escalate, main chat only), the FR-016
    hard exceptions, sweep detection open/close, and the
    outbox rendering of the escalation push.

Run: python3 gatekeeper/test_spec042.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


TEST_CONFIG = r"""
version: 1
workflows:
  - run.yml
  - wsl.yml
  - grab.yml
  - linux.yml
hosts:
  win:
    type: windows
    workflows:
      run.yml: execute
      wsl.yml: execute
      grab.yml: grab
    identity: [LID_HOST, LID_WINUSER, LID_OS]
    cwd:
      run.yml: "C:\\Users\\you"
      grab.yml: null
  win-wsl:
    type: wsl2
    via: win
    distro: Ubuntu-24.04
    workflows:
      wsl.yml: execute
      grab.yml: grab
    identity: [LID_HOST, LID_WSLUSER, LID_OS]
    cwd:
      wsl.yml: /home/you
  tower:
    type: linux
    workflows:
      linux.yml: execute
      grab.yml: grab
    identity: [LID_HOST, LID_USER, LID_OS]
    cwd:
      linux.yml: /var/lib/runner
      grab.yml: null
    wol:
      mac: "00:11:22:33:44:55"
      via: roam
      enabled: true
  roam:
    type: linux
    roaming: true
    workflows:
      linux.yml: execute
      grab.yml: grab
    identity: [LID_HOST, LID_USER, LID_OS]
    wol:
      mac: "00:11:22:33:44:66"
      via: tower
      enabled: true
  airmac:
    type: macos
    roaming: true
    workflows:
      grab.yml: grab
    identity: [LID_HOST, LID_USER, LID_OS]
  offfleet:
    type: linux
    off_fleet: true
    physical_owner: Ryan Anderson
    workflows:
      linux.yml: execute
      grab.yml: grab
    identity: [LID_HOST, LID_USER, LID_OS]
lanes:
  active_profile: fleet
  profiles:
    fleet:
      quick:
        host: win
        runner_label: lane-quick
        queued: [10, 30]
        executing:
          mode: fixed
          values: [5, 15]
      tower-quick:
        host: tower
        runner_label: lane-tower-quick
        queued: [10, 30]
        executing:
          mode: fixed
          values: [5, 15]
      tower-long:
        host: tower
        runner_label: lane-tower-long
        queued: [45, 120]
        executing:
          mode: expectation
          floor: [90, 180]
      roam-quick:
        host: roam
        runner_label: lane-roam-quick
        queued: [10, 30]
        executing:
          mode: fixed
          values: [5, 15]
checkpoint:
  holds_dir:
    linux.yml: /home/you/.syncyard/holds
downtime:
  escalation_chats:
    - main-chat
"""

PRELUDE = r"""
import importlib.util, io, json, os, sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
spec = importlib.util.spec_from_file_location(
    "gk_under_test", os.path.join(BASE_DIR, "gk.py"))
gk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gk)
NOW = [datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)]
gk.now_dt = lambda: NOW[0]
gk.DRAIN_POLL_S = 0
os.makedirs(gk.QUEUE_DIR, exist_ok=True)
open(gk.LANES_LIVE_FILE, "w").close()
EV = []
gk.ledger = lambda event, **kw: EV.append(dict(event=event, **kw))
BACK = [False]
gk._power_host_back = lambda host, since: (
    BACK[0], "stub-evidence" if BACK[0] else "silent")
gk.fetch_backchannel_heartbeat = lambda: (None, "no backchannel")
RUNNERS = [True]
def fake_gh(args, timeout=120):
    a = " ".join(args)
    if "actions/runners" in a:
        st = "online" if RUNNERS[0] else "offline"
        return {"total_count": 1, "runners": [
            {"name": "tower-runner", "status": st,
             "busy": False}]}, None
    return {"status": "in_progress", "conclusion": None,
            "createdAt": "2026-11-17T11:30:00Z"}, None
gk.gh_json = fake_gh

def advance(s):
    NOW[0] = NOW[0] + timedelta(seconds=s)

def job(jid, lane, key=None, state="submitted", workflow="linux.yml",
        run_id=None, run_status=None):
    j = {"id": jid, "key": key or jid, "program": "prog",
         "workflow": workflow, "lane": lane, "state": state,
         "created_at": "2026-11-17T11:00:00Z",
         "script_sha256": "sha-" + jid, "maintenance": False,
         "notify_chat": None, "run_id": run_id,
         "run_status": run_status, "run_conclusion": None,
         "flags": [], "watermarks": {}, "expected_min": None,
         "cwd": "/var/lib/runner"}
    with open(os.path.join(gk.QUEUE_DIR, jid + ".json"), "w") as f:
        json.dump(j, f)
    return j

def hosts_state():
    if not os.path.isfile(gk.HOSTS_FILE):
        return {}
    with open(gk.HOSTS_FILE) as f:
        return json.load(f)

def actions():
    return gk.load_power_actions()

def signal_jobs():
    return [j for j in gk.load_jobs()
            if str(j.get("key") or "").startswith("gk-power-")]

def script_of(j):
    with open(j["script_path"]) as f:
        return f.read()

def events(name=None):
    return [e for e in EV if name is None or e["event"] == name]

def call(fn, args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = fn(args)
    return rc, buf.getvalue()

def power(**kw):
    base = dict(host="tower", action="reboot", id=None, delay=None,
                at=None, confirm=None, drain=False, force=False,
                override_reason=None, requested_by="test-chat")
    base.update(kw)
    return call(gk.cmd_power, NS(**base))
"""


def run_driver(body, config=TEST_CONFIG, real_ledger=False):
    d = tempfile.mkdtemp(prefix="gk-spec042-")
    try:
        shutil.copy(os.path.join(HERE, "gk.py"), d)
        shutil.copy(os.path.join(HERE, "config.py"), d)
        env = {k: v for k, v in os.environ.items()
               if k not in ("SYNCYARD_CONFIG", "SYNCARD_CONFIG")}
        if config is not None:
            cfg_path = os.path.join(d, "test-config.yaml")
            with open(cfg_path, "w") as f:
                f.write(config)
            env["SYNCYARD_CONFIG"] = cfg_path
        pre = PRELUDE
        if real_ledger:
            pre = pre.replace(
                'gk.ledger = lambda event, **kw: '
                'EV.append(dict(event=event, **kw))',
                'pass  # real ledger')
        driver = "BASE_DIR = %r\n%s\n%s" % (d, pre, body)
        r = subprocess.run([sys.executable, "-c", driver],
                           capture_output=True, text=True, env=env,
                           cwd=d)
        if r.returncode != 0:
            raise RuntimeError("driver failed: " + r.stderr[-1200:])
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- Config: validation + ratified defaults ------------------------------
res = run_driver(r"""
import importlib.util
cspec = importlib.util.spec_from_file_location(
    "cfg_under_test", os.path.join(BASE_DIR, "config.py"))
cfg = importlib.util.module_from_spec(cspec)
cspec.loader.exec_module(cfg)
ok = cfg.load_config(os.environ["SYNCYARD_CONFIG"])
def bad(mutate):
    import copy
    c = copy.deepcopy(cfg.load_config(os.environ["SYNCYARD_CONFIG"]))
    mutate(c)
    try:
        cfg.validate(c)
        return False
    except cfg.ConfigError:
        return True
print(json.dumps({
    "return_window": ok["power"]["return_window_s"],
    "confirm_down": ok["power"]["confirm_down_s"],
    "esc": ok["downtime"]["escalation_chats"],
    "roaming": ok["hosts"]["roam"].get("roaming"),
    "bad_window": bad(lambda c: c["power"].update(
        return_window_s=0)),
    "bad_roaming": bad(lambda c: c["hosts"]["roam"].update(
        roaming="yes")),
    "bad_esc": bad(lambda c: c["downtime"].update(
        escalation_chats="main-chat")),
}))
""")
check("config: ratified defaults load (return 900, confirm 180), "
      "escalation registration + roaming flag ride the config",
      res["return_window"] == 900 and res["confirm_down"] == 180
      and res["esc"] == ["main-chat"] and res["roaming"] is True,
      str(res))
check("config: bad power window, non-bool roaming, and a "
      "non-list escalation registration all fail closed",
      res["bad_window"] and res["bad_roaming"] and res["bad_esc"],
      str(res))

# --- Poweroff: the confirm gate -------------------------------------------
res = run_driver(r"""
rc1, out1 = power(action="poweroff")
a1 = actions()[-1]
rc2, _ = power(action="poweroff", confirm="other-host")
a2 = actions()[-1]
print(json.dumps({
    "rc1": rc1, "v1": a1["verdict"],
    "rc2": rc2, "v2": a2["verdict"],
    "signals": len(signal_jobs()),
    "gd": bool((hosts_state().get("tower") or {}).get("going_down")),
    "refused_events": len(events("host_power_refused")),
}))
""")
check("poweroff confirm gate: no --confirm and a wrong "
      "--confirm both refuse (rc 3, record REFUSED), no signal "
      "job, no going-down record",
      res["rc1"] == 3 and res["v1"] == "REFUSED"
      and res["rc2"] == 3 and res["v2"] == "REFUSED"
      and res["signals"] == 0 and res["gd"] is False
      and res["refused_events"] == 2, str(res))

# --- Poweroff: DOWN-BY-ACTION before signal; CONFIRMED-DOWN ---------------
res = run_driver(r"""
seen = {}
real_signal = gk._power_signal
def spy(host, rec, route):
    st = hosts_state().get("tower") or {}
    seen["power_state"] = (st.get("power") or {}).get("power_state")
    seen["gd_trigger"] = (st.get("going_down") or {}).get("trigger")
    return real_signal(host, rec, route)
gk._power_signal = spy
rc, out = power(action="poweroff", confirm="tower", delay=120)
a = actions()[-1]
body = script_of(signal_jobs()[-1]) if signal_jobs() else ""
BACK[0] = False
advance(120)
gk.power_pass()
mid = actions()[-1]
advance(180)
gk.power_pass()
done = actions()[-1]
print(json.dumps({
    "rc": rc, "seen": seen, "body": body, "state": a["state"],
    "mid_verdict": mid["verdict"],
    "mid_down_since": bool(mid.get("down_since")),
    "verdict": done["verdict"],
    "confirmed_events": len(events("host_power_confirmed_down")),
    "power_state": (hosts_state()["tower"].get("power") or {})
                   .get("power_state"),
}))
""")
check("poweroff: DOWN-BY-ACTION and the remote-poweroff "
      "going-down record are in the host state BEFORE the "
      "signal seam runs",
      res["seen"] == {"power_state": "DOWN-BY-ACTION",
                      "gd_trigger": "remote-poweroff"}, str(res))
check("poweroff: the Linux signal body is the cancellable "
      "shutdown -h +2 form for a 120 s grace",
      "shutdown -h +2" in res["body"], str(res))
check("poweroff: silence inside the window sets down_since "
      "with no verdict; a full 180 s of silence closes "
      "CONFIRMED-DOWN and the host stays DOWN-BY-ACTION",
      res["mid_verdict"] is None and res["mid_down_since"]
      and res["verdict"] == "CONFIRMED-DOWN"
      and res["confirmed_events"] == 1
      and res["power_state"] == "DOWN-BY-ACTION", str(res))

# --- Reboot: refusal names active jobs -------------------------------------
res = run_driver(r"""
job("act1", "tower-quick", state="dispatched", run_id=7,
    run_status="in_progress")
rc, out = power()
a = actions()[-1]
print(json.dumps({
    "rc": rc, "verdict": a["verdict"],
    "named_out": "act1" in out,
    "named_rec": "act1" in (a.get("verdict_detail") or ""),
    "signals": len(signal_jobs()),
    "refused": [e.get("verdict") for e in
                events("host_power_refused")],
}))
""")
check("drain refusal: an active job refuses the reboot "
      "(rc 3) and is named in the output and the record; "
      "nothing is signaled",
      res["rc"] == 3 and res["verdict"] == "REFUSED"
      and res["named_out"] and res["named_rec"]
      and res["signals"] == 0
      and res["refused"] == ["REFUSED"], str(res))

# --- The override gate ------------------------------------------------------
res = run_driver(r"""
job("act1", "tower-quick", state="dispatched", run_id=7,
    run_status="in_progress")
rc1, _ = power(force=True)
a1 = [a for a in actions() if a["verdict"] == "REFUSED"][-1]
rc2, _ = power(force=True, override_reason="window approved")
a2 = [a for a in actions() if a["state"] == "SIGNALED"][-1]
req = [e for e in events("host_power_requested") if e.get("override")]
print(json.dumps({
    "rc1": rc1, "v1": a1["verdict"], "rc2": rc2,
    "state2": a2["state"],
    "ovr": a2.get("override"),
    "uncp": (hosts_state()["tower"].get("going_down") or {})
            .get("uncheckpointed"),
    "req_override": len(req),
}))
""")
check("override: --force without --override-reason refuses; "
      "with a reason it proceeds, the record carries the "
      "override, the going-down names the job uncheckpointed, "
      "and the ledger request carries the override flag",
      res["rc1"] == 3 and res["v1"] == "REFUSED"
      and res["rc2"] == 0 and res["state2"] == "SIGNALED"
      and res["ovr"] == {"force": True,
                         "reason": "window approved"}
      and res["uncp"] == ["act1"] and res["req_override"] == 1,
      str(res))

# --- The --drain path --------------------------------------------------------
res = run_driver(r"""
job("w", "tower-quick", state="dispatched", run_id=9,
    run_status="in_progress")
def gh2(args, timeout=120):
    a = " ".join(args)
    if "actions/runners" in a:
        return {"total_count": 1, "runners": [
            {"name": "tower-runner", "status": "online",
             "busy": False}]}, None
    return {"status": "completed", "conclusion": "failure",
            "createdAt": "2026-11-17T11:30:00Z"}, None
gk.gh_json = gh2
def fetch(j):
    j["markers"] = ["CHECKPOINT_PAUSED at unit 3"]
    j["log_fetched_at"] = "x"
    return True
gk.fetch_log_once = fetch
rc, out = power(drain=True)
a = actions()[-1]
print(json.dumps({
    "rc": rc, "state": a["state"],
    "drain": a.get("drain"),
    "signals": len(signal_jobs()),
}))
""")
check("--drain: a job that checkpoints lets the action "
      "proceed, and the drain verdict rides the record",
      res["rc"] == 0 and res["state"] == "SIGNALED"
      and res["drain"]["verdict"] == "clean"
      and res["drain"]["checkpointed"] == ["w"]
      and res["signals"] == 1, str(res))

# The ignoring job's drain window is the config default (120 s
# per lane); the driver cannot wait it out in real time, so this
# scenario runs the drain with a shrunken per-lane window via
# the module constant instead.
res = run_driver(r"""
gk.DRAIN_PER_LANE_WINDOW_S = {"tower-quick": 1}
job("i", "tower-quick", state="dispatched", run_id=11,
    run_status="in_progress")
rc, out = power(drain=True)
a = actions()[-1]
print(json.dumps({
    "rc": rc, "verdict": a["verdict"],
    "uncp": (a.get("drain") or {}).get("uncheckpointed"),
    "named": "i" in out, "signals": len(signal_jobs()),
}))
""")
check("--drain: a job the drain leaves UNCHECKPOINTED "
      "refuses the action by name; nothing is signaled",
      res["rc"] == 3 and res["verdict"] == "REFUSED"
      and res["uncp"] == ["i"] and res["named"]
      and res["signals"] == 0, str(res))

# --- Reboot: VERIFIED only after observed silence ---------------------------
res = run_driver(r"""
rc, _ = power(delay=0)
a = actions()[-1]
body = script_of(signal_jobs()[-1]) if signal_jobs() else ""
BACK[0] = True
gk.power_pass()
early = actions()[-1]
BACK[0] = False
gk.power_pass()
mid = actions()[-1]
BACK[0] = True
gk.power_pass()
done = actions()[-1]
print(json.dumps({
    "rc": rc, "body": body,
    "early_verdict": early["verdict"],
    "mid_verdict": mid["verdict"],
    "mid_down": bool(mid.get("observed_down_at")),
    "verdict": done["verdict"],
    "identity": "interim identity" in (done.get("identity") or ""),
    "power_state": (hosts_state()["tower"].get("power") or {})
                   .get("power_state"),
    "issues_open": len(gk._open_power_actions()),
}))
""")
check("reboot: a delay-0 Linux signal is systemctl reboot; "
      "a host merely up does NOT verify (no down observed), "
      "silence arms the return, and the next proof closes "
      "VERIFIED on the interim identity, named as such",
      res["rc"] == 0 and "systemctl reboot" in res["body"]
      and res["early_verdict"] is None
      and res["mid_verdict"] is None and res["mid_down"]
      and res["verdict"] == "VERIFIED" and res["identity"]
      and res["power_state"] == "UP"
      and res["issues_open"] == 0, str(res))

# --- Reboot: RETURN-MISSED opens a record; VERIFIED-LATE amends -------------
res = run_driver(r"""
rc, _ = power(delay=0)
aid = actions()[-1]["id"]
BACK[0] = False
advance(901)
gk.power_pass()
missed = actions()[-1]
dt = gk.downtime_open_record("tower")
BACK[0] = True
gk.power_pass()
late = actions()[-1]
print(json.dumps({
    "aid": aid,
    "verdict1": missed["verdict"], "dt_class": dt["class"],
    "dt_detector": dt["detectors"],
    "dt_notify": len(events("downtime_notify")),
    "verdict2": late["verdict"],
    "verified_events": len(events("host_power_verified")),
}))
""")
check("reboot: an expired return window closes "
      "RETURN-MISSED and opens a BY-ACTION downtime record "
      "with the action as detector — and opening pushes "
      "nothing (ruling D4)",
      res["verdict1"] == "RETURN-MISSED"
      and res["dt_class"] == "BY-ACTION"
      and res["dt_detector"] == ["power-action:%s" % res["aid"]]
      and res["dt_notify"] == 0, str(res))
check("reboot: a late return amends the record to "
      "VERIFIED-LATE with the verified event ledgered",
      res["verdict2"] == "VERIFIED-LATE"
      and res["verified_events"] == 1, str(res))

# --- Cancel: scheduled withdrawal -------------------------------------------
res = run_driver(r"""
rc1, _ = power(at="2026-11-17T13:00:00Z")
a = actions()[-1]
rc2, out2 = power(action="cancel")
done = actions()[-1]
print(json.dumps({
    "rc1": rc1, "state": a["state"], "rc2": rc2,
    "verdict": done["verdict"], "signals": len(signal_jobs()),
    "cancelled_events": len(events("host_power_cancelled")),
}))
""")
check("cancel: a scheduled (unsignaled) action is withdrawn "
      "outright — CANCELLED-CONFIRMED, no signal ever sent",
      res["rc1"] == 0 and res["state"] == "SCHEDULED"
      and res["rc2"] == 0
      and res["verdict"] == "CANCELLED-CONFIRMED"
      and res["signals"] == 0 and res["cancelled_events"] == 1,
      str(res))

# --- Cancel: in-grace abort, verdicts from observed state -------------------
res = run_driver(r"""
rc1, _ = power(delay=300)
rc2, _ = power(action="cancel")
a = actions()[-1]
abort_body = ""
for j in signal_jobs():
    if "abort" in str(j.get("key")):
        abort_body = script_of(j)
BACK[0] = True
advance(300)
gk.power_pass()
done = actions()[-1]
print(json.dumps({
    "rc2": rc2, "state": a["state"],
    "abort_body": abort_body, "verdict": done["verdict"],
}))
""")
check("cancel: an in-grace action takes the OS abort "
      "(shutdown -c on Linux) and settles CANCELLING; a host "
      "observed up past the fire time closes "
      "CANCELLED-CONFIRMED",
      res["rc2"] == 0 and res["state"] == "CANCELLING"
      and "shutdown -c" in res["abort_body"]
      and res["verdict"] == "CANCELLED-CONFIRMED", str(res))

res = run_driver(r"""
power(delay=300)
power(action="cancel")
BACK[0] = False
advance(300)
gk.power_pass()
done = actions()[-1]
print(json.dumps({"verdict": done["verdict"]}))
""")
check("cancel: a host that went down anyway closes "
      "CANCEL-FAILED — the verdict is the observed state, "
      "never the abort's exit code",
      res["verdict"] == "CANCEL-FAILED", str(res))

# --- Cancel: immediate signal has no abort handle ---------------------------
res = run_driver(r"""
power(delay=0)
rc, out = power(action="cancel")
a = actions()[-1]
print(json.dumps({
    "rc": rc, "words": "NOT-CANCELLABLE" in out,
    "state": a["state"],
    "attempts": len(a.get("cancel_attempts") or []),
}))
""")
check("cancel: an immediate (delay 0) signal is "
      "NOT-CANCELLABLE in those words, the attempt is "
      "recorded, and the action itself stands open",
      res["rc"] == 1 and res["words"]
      and res["state"] == "SIGNALED" and res["attempts"] == 1,
      str(res))

# --- Unreachable --------------------------------------------------------------
res = run_driver(r"""
RUNNERS[0] = False
rc, out = power()
a = actions()[-1]
print(json.dumps({
    "rc": rc, "verdict": a["verdict"],
    "words": "POWER UNREACHABLE" in out,
    "events": len(events("host_power_unreachable")),
}))
""")
check("unreachable: no heartbeat and no online runner "
      "closes the record UNREACHABLE (rc 4), ledgered",
      res["rc"] == 4 and res["verdict"] == "UNREACHABLE"
      and res["words"] and res["events"] == 1, str(res))

# --- The OS / fleet gates -----------------------------------------------------
res = run_driver(r"""
rc1, _ = power(host="airmac")
a1 = [a for a in actions() if a["host"] == "airmac"][-1]
rc2, _ = power(host="offfleet")
a2 = [a for a in actions() if a["host"] == "offfleet"][-1]
print(json.dumps({
    "rc1": rc1, "v1": a1["verdict"],
    "d1": a1.get("verdict_detail") or "",
    "rc2": rc2, "v2": a2["verdict"],
    "d2": a2.get("verdict_detail") or "",
    "signals": len(signal_jobs()),
}))
""")
check("gates: macOS takes no initiated power action and an "
      "off-fleet host takes no power verbs — both REFUSED "
      "on the record, nothing signaled",
      res["rc1"] == 3 and res["v1"] == "REFUSED"
      and "macOS" in res["d1"]
      and res["rc2"] == 3 and res["v2"] == "REFUSED"
      and "off-fleet" in res["d2"] and res["signals"] == 0,
      str(res))

# --- Downtime: dedupe + the ruling-D4 push set --------------------------------
res = run_driver(r"""
r1 = gk.open_downtime("tower", "sweep-liveness",
                      evidence={"mid_job": True}, jobs=[])
r2 = gk.open_downtime("tower", "operator", note="hand check",
                      jobs=[])
same = r1["id"] == r2["id"]
n_open = len(events("downtime_notify"))
esc = gk.escalate_downtime("tower")
esc2 = gk.escalate_downtime("tower")
notifies = events("downtime_notify")
closed = gk.close_downtime("tower", "RECOVERED-UNASSISTED",
                           account="back on its own")
after = events("downtime_notify")
store = gk.load_downtime()
print(json.dumps({
    "same": same, "detectors": r2["detectors"],
    "cls": r1["class"], "push_open": n_open,
    "push_esc": len(notifies),
    "esc_chats": [e.get("notify_chat") for e in notifies],
    "esc_transition": [e.get("transition") for e in notifies],
    "push_after_close": len(after),
    "pushes": esc["pushes"],
    "owner": esc["physical_owner"],
    "checklist": len((esc.get("physical") or {})
                     .get("checklist") or []),
    "closed_state": closed["state"],
    "open_left": list(store["open"].keys()),
    "closed_n": len(store["closed"]),
}))
""")
check("downtime dedupe: a second detection of the same "
      "incident appends its detector to the SAME record — "
      "no second record",
      res["same"] and res["detectors"] == ["sweep-liveness",
                                           "operator"]
      and res["open_left"] == [] and res["closed_n"] == 1,
      str(res))
check("downtime pushes (ruling D4): open pushes nothing, "
      "close pushes nothing, escalate pushes exactly once "
      "to the main chat only",
      res["push_open"] == 0 and res["push_esc"] == 1
      and res["esc_chats"] == ["main-chat"]
      and res["esc_transition"] == ["NEEDS-PHYSICAL"]
      and res["push_after_close"] == 1
      and res["pushes"] == ["NEEDS-PHYSICAL"], str(res))
check("downtime escalate: the NEEDS-PHYSICAL flip carries "
      "the named owner and a non-empty on-site checklist; "
      "the close lands RECOVERED-UNASSISTED",
      res["owner"] == "Tristen Pierson" and res["checklist"] >= 3
      and res["closed_state"] == "RECOVERED-UNASSISTED",
      str(res))

# --- Downtime: class from evidence only ---------------------------------------
res = run_driver(r"""
gd = {"host": "tower", "ts": "2026-11-17T11:58:00Z",
      "trigger": "shutdown"}
c1 = gk.downtime_classify({"going_down": gd})
c2 = gk.downtime_classify(
    {"open_action": {"id": "a1", "action": "reboot",
                     "requested_by": "chat-x"}})
c3 = gk.downtime_classify({"lan_reachable": True})
c4 = gk.downtime_classify({"mid_job": True})
c5 = gk.downtime_classify({})
print(json.dumps({"c": [c1[0], c2[0], c3[0], c4[0], c5[0]],
                  "lines": all(len(x[1]) >= 1
                               for x in (c1, c2, c3, c4, c5))}))
""")
check("downtime class: ORDERLY from a going-down record, "
      "BY-ACTION from an open action, NETWORK from a LAN "
      "prober still reaching the host, UNKNOWN otherwise — "
      "each with its evidence lines",
      res["c"] == ["ORDERLY", "BY-ACTION", "NETWORK",
                   "UNKNOWN", "UNKNOWN"] and res["lines"],
      str(res))

# --- FR-016: the hard exceptions ------------------------------------------------
res = run_driver(r"""
a = gk.open_downtime("roam", "sweep-liveness", jobs=[])
b = gk.open_downtime("roam", "operator", jobs=[])
c = gk.open_downtime("airmac", "operator", jobs=[])
d = gk.open_downtime("offfleet", "sweep-liveness", jobs=[])
e = gk.open_downtime("offfleet", "operator",
                     note="hand-filed by the owner", jobs=[])
store = gk.load_downtime()
print(json.dumps({
    "roam_sweep": a is None, "roam_op": b is None,
    "air_op": c is None, "off_sweep": d is None,
    "off_op": e is not None,
    "off_owner": (e or {}).get("physical_owner"),
    "open_hosts": sorted(store["open"].keys()),
    "notify": len(events("downtime_notify")),
    "opened_events": len(events("downtime_opened")),
}))
""")
check("FR-016: roaming hosts (roam, airmac) never open a "
      "record under any detector; the off-fleet host opens "
      "by hand filing only, with its named owner (Ryan "
      "Anderson) on the record",
      res["roam_sweep"] and res["roam_op"] and res["air_op"]
      and res["off_sweep"] and res["off_op"]
      and res["off_owner"] == "Ryan Anderson"
      and res["open_hosts"] == ["offfleet"]
      and res["notify"] == 0 and res["opened_events"] == 1,
      str(res))

# --- Sweep detection: open on down-transition, close on return -----------------
res = run_driver(r"""
HB = {"ts": "2026-11-17T11:00:00Z", "host": "EXAMPLE",
      "stopped": False}
gk.fetch_backchannel_heartbeat = lambda: (HB, None)
gk.sweep_liveness([])
opened = gk.downtime_open_record("desktop-wsl")
HB2 = {"ts": "2026-11-17T12:00:00Z", "host": "EXAMPLE",
       "stopped": False}
gk.fetch_backchannel_heartbeat = lambda: (HB2, None)
gk.sweep_liveness([])
store = gk.load_downtime()
mine = [c for c in store["closed"] if c["host"] == "desktop-wsl"]
print(json.dumps({
    "opened": opened is not None,
    "detector": (opened or {}).get("detectors"),
    "cls": (opened or {}).get("class"),
    "open_left": [h for h in store["open"]
                  if h == "desktop-wsl"],
    "closed": [c["closing"] for c in mine],
}))
""", config=None)
check("sweep detection: a stale heartbeat opens the "
      "record (detector sweep-liveness) and the host's "
      "return closes it RECOVERED-UNASSISTED",
      res["opened"] and res["detector"] == ["sweep-liveness"]
      and res["open_left"] == []
      and res["closed"] == ["RECOVERED-UNASSISTED"], str(res))

# --- Sweep detection: DOWN-BY-ACTION is not an incident -------------------------
res = run_driver(r"""
HB = {"ts": "2026-11-17T11:00:00Z", "host": "EXAMPLE",
      "stopped": False}
gk.fetch_backchannel_heartbeat = lambda: (HB, None)
gk._set_host_power("desktop-wsl", power_state="DOWN-BY-ACTION")
gk.sweep_liveness([])
rec = gk.downtime_open_record("desktop-wsl")
print(json.dumps({"opened": rec is not None}))
""", config=None)
check("sweep detection: a host under a DOWN-BY-ACTION "
      "expected state opens no downtime record",
      res["opened"] is False, str(res))

# --- The outbox renders the escalation push --------------------------------------
res = run_driver(r"""
r = gk.open_downtime("tower", "operator",
                     note="hand-filed for the outbox test",
                     jobs=[])
# The first outbox read initializes the cursor at the
# ledger's end (history is never replayed), so the
# escalation must land after it to be owed.
call(gk.cmd_outbox, NS(ack=False, force_ack=False))
gk.escalate_downtime("tower")
rc, out = call(gk.cmd_outbox, NS(ack=False, force_ack=False))
print(json.dumps({"rc": rc, "out": out}))
""", real_ledger=True)
check("outbox: the escalation push renders once, addressed "
      "to the main chat, with the FR-013 body fields",
      res["rc"] == 0 and "NOTIFY main-chat" in res["out"]
      and "[downtime] tower NEEDS-PHYSICAL" in res["out"]
      and "class=UNKNOWN" in res["out"]
      and "record " in res["out"], str(res))

# --- FR-008: the power section renders (status + snapshot) ----------------------
res = run_driver(r"""
power(action="poweroff", confirm="tower", delay=120)
lines = gk.host_status_lines()
tower_line = [ln for ln in lines if ln.startswith("host tower:")]
snap = gk.build_snapshot()
hp = snap.get("hosts_power") or {}
print(json.dumps({
    "line": tower_line[0] if tower_line else "",
    "snap_state": (hp.get("tower") or {}).get("power_state"),
    "snap_action": ((hp.get("tower") or {}).get("last_action")
                    or {}).get("action"),
    "roam_absent": "roam" not in hp,
}))
""")
check("FR-008 rendering: a planned-down host renders "
      "DOWN-BY-ACTION in the status lines (never identical "
      "to a crashed host's plain DOWN) and the snapshot "
      "carries the power section for that host only",
      "power DOWN-BY-ACTION" in res["line"]
      and "last action poweroff" in res["line"]
      and res["snap_state"] == "DOWN-BY-ACTION"
      and res["snap_action"] == "poweroff"
      and res["roam_absent"], str(res))

# =========================================================================
# Slice 2 — Wake-on-LAN (FR-010) and the recovery ladder (FR-014/015)
# =========================================================================

# --- WoL: config validation + standing + the roaming refusal ------------------
res = run_driver(r"""
import importlib.util, copy
cspec = importlib.util.spec_from_file_location(
    "cfg2", os.path.join(BASE_DIR, "config.py"))
cfg = importlib.util.module_from_spec(cspec)
cspec.loader.exec_module(cfg)
def bad(mutate):
    c = copy.deepcopy(cfg.load_config(
        os.environ["SYNCYARD_CONFIG"]))
    mutate(c)
    try:
        cfg.validate(c)
        return False
    except cfg.ConfigError:
        return True
o1, d1 = gk.wol_attempt("roam")
o2, d2 = gk.wol_attempt("win")
rc3, out3 = call(gk.cmd_wol, NS(host="tower"))
senders = [j for j in gk.load_jobs()
           if str(j.get("key") or "").startswith("gk-wol-")]
script = script_of(senders[0]) if senders else ""
w = (hosts_state().get("tower") or {}).get("wol") or {}
print(json.dumps({
    "bad_mac": bad(lambda c: c["hosts"]["tower"]["wol"]
                   .update(mac="00:11:22:33:44")),
    "bad_via": bad(lambda c: c["hosts"]["tower"]["wol"]
                   .update(via="nowhere")),
    "bad_enabled": bad(lambda c: c["hosts"]["tower"]["wol"]
                       .update(enabled="yes")),
    "roam": o1, "win": o2, "rc3": rc3,
    "senders": len(senders), "script": script,
    "attempts": len(w.get("attempts") or []),
    "sender": (w.get("attempts") or [{}])[0].get("sender"),
    "standing": gk.wol_standing("tower"),
}))
""")
check("WoL config: a malformed MAC, an unknown via host, "
      "and a non-bool enabled all fail closed",
      res["bad_mac"] and res["bad_via"] and res["bad_enabled"],
      str(res))
check("WoL: a roaming host is wake-free even with a block "
      "written for it (ruling D2), an unconfigured host "
      "reports NOT-CONFIGURED, and a configured attempt "
      "queues the sender job on the via host with the MAC "
      "in it — standing CONFIGURED, attempt logged with "
      "its sender",
      res["roam"] == "WOL-NOT-CONFIGURED"
      and res["win"] == "WOL-NOT-CONFIGURED"
      and res["rc3"] == 0 and res["senders"] == 1
      and "00:11:22:33:44:55" in res["script"]
      and res["attempts"] == 1 and res["sender"] == "roam"
      and res["standing"] == "CONFIGURED", str(res))

LADDER_PRELUDE = r"""
PROBE = {"heartbeat_age_s": None, "runners_online": 0,
         "agent": None, "lan_reachable": None}
gk._ladder_probe = lambda host: dict(PROBE)
def ladder_steps(host="tower"):
    rec = gk.downtime_open_record(host)
    if rec is None:
        store = gk.load_downtime()
        rec = [c for c in store["closed"]
               if c["host"] == host][-1]
    return [(e["step"], e["outcome"]) for e in rec["ladder"]]
"""

# --- Ladder: the host answers at step 1 ---------------------------------------
res = run_driver(LADDER_PRELUDE + r"""
gk.open_downtime("tower", "operator", jobs=[])
st = gk.load_hosts_state()
r = gk._host_record(st, "tower")
r["last_heartbeat_ts"] = "2026-11-17T12:00:30Z"
gk.save_hosts_state(st)
gk.ladder_pass([])
store = gk.load_downtime()
mine = [c for c in store["closed"] if c["host"] == "tower"]
print(json.dumps({
    "closed": [c["closing"] for c in mine],
    "account": mine[0]["closing_account"] if mine else "",
    "steps": ladder_steps(),
}))
""")
check("ladder: a host that answers the step-1 re-probe on "
      "its own identity closes RECOVERED-UNASSISTED — the "
      "ladder took no active step and claims none",
      res["closed"] == ["RECOVERED-UNASSISTED"]
      and "heartbeat" in res["account"] and res["steps"] == [],
      str(res))

# --- Ladder: wakes at step 2, wake PROVEN by the return -------------------------
res = run_driver(LADDER_PRELUDE + r"""
gk.open_downtime("tower", "operator", jobs=[])
gk.ladder_pass([])
mid = gk.downtime_open_record("tower")
senders = [j for j in gk.load_jobs()
           if str(j.get("key") or "").startswith("gk-wol-")]
PROBE["runners_online"] = 1
gk.ladder_pass([])
store = gk.load_downtime()
mine = [c for c in store["closed"] if c["host"] == "tower"]
w = (hosts_state().get("tower") or {}).get("wol") or {}
print(json.dumps({
    "mid_state": mid["state"], "senders": len(senders),
    "closed": [c["closing"] for c in mine],
    "account": mine[0]["closing_account"] if mine else "",
    "steps": ladder_steps(),
    "wol_state": w.get("state"),
}))
""")
check("ladder: step 1 re-probes, step 2 sends the wake "
      "(sender job queued), and the host's return closes "
      "RECOVERED-BY-LADDER at step 2 — and the wake "
      "standing becomes PROVEN, by the return, not the "
      "send",
      res["mid_state"] == "LADDER" and res["senders"] == 1
      and res["closed"] == ["RECOVERED-BY-LADDER"]
      and "step 2 (wake)" in res["account"]
      and res["steps"] == [[1, "re-probed"], [2, "WOL-SENT"]]
      and res["wol_state"] == "PROVEN", str(res))

# --- Ladder: returns during backoff ----------------------------------------------
res = run_driver(LADDER_PRELUDE + r"""
gk.open_downtime("win", "operator", jobs=[])
gk.ladder_pass([])
advance(120)
gk.ladder_pass([])
PROBE["runners_online"] = 1
gk.ladder_pass([])
store = gk.load_downtime()
mine = [c for c in store["closed"] if c["host"] == "win"]
print(json.dumps({
    "closed": [c["closing"] for c in mine],
    "steps": ladder_steps("win"),
}))
""")
check("ladder: a host with no wake step logs "
      "WOL-NOT-CONFIGURED at step 2, and a return during "
      "the backoff closes RECOVERED-UNASSISTED",
      res["closed"] == ["RECOVERED-UNASSISTED"]
      and res["steps"] == [[1, "re-probed"],
                           [2, "WOL-NOT-CONFIGURED"],
                           [3, "re-probed"]], str(res))

# --- Ladder: stack restart at step 4 ----------------------------------------------
res = run_driver(LADDER_PRELUDE + r"""
PROBE["lan_reachable"] = True
def restart(host):
    PROBE["runners_online"] = 1
    return True, "stub restart ok"
gk._ladder_stack_restart = restart
gk.open_downtime("win", "operator", jobs=[])
gk.ladder_pass([])
advance(120); gk.ladder_pass([])
advance(180); gk.ladder_pass([])
advance(300); gk.ladder_pass([])
gk.ladder_pass([])
store = gk.load_downtime()
mine = [c for c in store["closed"] if c["host"] == "win"]
print(json.dumps({
    "closed": [c["closing"] for c in mine],
    "account": mine[0]["closing_account"] if mine else "",
    "steps": ladder_steps("win"),
}))
""")
check("ladder: with a LAN channel proving the host alive "
      "but its stack down, step 4 restarts the stack and "
      "the return closes RECOVERED-BY-LADDER at step 4 — "
      "after the full backoff, in order",
      res["closed"] == ["RECOVERED-BY-LADDER"]
      and "step 4 (stack restart)" in res["account"]
      and [s for s, _ in res["steps"]] == [1, 2, 3, 3, 3, 4]
      and res["steps"][-1][1] == "restarted", str(res))

# --- Ladder: one controlled reboot at step 5 ---------------------------------------
res = run_driver(LADDER_PRELUDE + r"""
gk.open_downtime("win", "operator", jobs=[])
gk.ladder_pass([])
advance(120); gk.ladder_pass([])
advance(180); gk.ladder_pass([])
advance(300); gk.ladder_pass([])
gk.ladder_pass([])
gk.ladder_pass([])
acts = gk.load_power_actions()
mid = gk.downtime_open_record("win")
BACK[0] = False
advance(61); gk.power_pass()
BACK[0] = True
gk.power_pass()
PROBE["runners_online"] = 1
gk.ladder_pass([])
gk.ladder_pass([])
acts2 = gk.load_power_actions()
store = gk.load_downtime()
mine = [c for c in store["closed"] if c["host"] == "win"]
print(json.dumps({
    "n_actions": len(acts), "by": acts[0]["requested_by"]
    if acts else None,
    "mid_stage": (mid.get("ladder_state") or {}).get("stage"),
    "verdict": acts2[0]["verdict"] if acts2 else None,
    "n_actions_after": len(acts2),
    "closed": [c["closing"] for c in mine],
    "account": mine[0]["closing_account"] if mine else "",
    "steps": ladder_steps("win"),
}))
""")
check("ladder: with no channel alive, step 5 spends ONE "
      "controlled reboot (requested by the ladder, drain "
      "accounting in its record); the verified return "
      "closes RECOVERED-BY-LADDER at step 5, and no second "
      "reboot is ever spent",
      res["n_actions"] == 1 and res["by"] == "downtime-ladder"
      and res["mid_stage"] == "await-return"
      and res["verdict"] == "VERIFIED"
      and res["n_actions_after"] == 1
      and res["closed"] == ["RECOVERED-BY-LADDER"]
      and "step 5 (controlled reboot)" in res["account"]
      and res["steps"][-1] == [5, "signaled"], str(res))

# --- Ladder: never returns — budget flip, FAILED wake, slow re-probe ----------------
res = run_driver(LADDER_PRELUDE + r"""
gk.open_downtime("tower", "operator", jobs=[])
gk.ladder_pass([])
advance(120); gk.ladder_pass([])
advance(180); gk.ladder_pass([])
advance(300); gk.ladder_pass([])
gk.ladder_pass([])
gk.ladder_pass([])
BACK[0] = False
advance(61); gk.power_pass()
advance(900); gk.power_pass()
gk.ladder_pass([])
advance(300)
gk.ladder_pass([])
rec = gk.downtime_open_record("tower")
w = (hosts_state().get("tower") or {}).get("wol") or {}
print(json.dumps({
    "state": rec["state"],
    "steps": [(e["step"], e["outcome"]) for e in rec["ladder"]],
    "detectors": rec["detectors"],
    "wol_state": w.get("state"),
    "notify": len(events("downtime_notify")),
    "owner": rec["physical_owner"],
}))
""")
check("ladder: a host that never returns walks every step "
      "in order, the missed reboot appends its detector to "
      "the same record, and at budget expiry the record "
      "flips NEEDS-PHYSICAL — wake marked FAILED (attempted, "
      "never proven), exactly one escalation push",
      res["state"] == "NEEDS-PHYSICAL"
      and [s for s, _ in res["steps"]]
          == [1, 2, 3, 3, 3, 4, 5, 5, "flip"]
      and res["wol_state"] == "FAILED"
      and res["notify"] == 1
      and any(d.startswith("power-action:")
              for d in res["detectors"])
      and res["owner"] == "Tristen Pierson", str(res))

# --- After the flip: slow re-probe only ----------------------------------------------
res = run_driver(LADDER_PRELUDE + r"""
gk.open_downtime("tower", "operator", jobs=[])
gk.escalate_downtime("tower")
st = gk.load_hosts_state()
r = gk._host_record(st, "tower")
r["last_heartbeat_ts"] = "2026-11-17T12:00:30Z"
gk.save_hosts_state(st)
gk.ladder_pass([])
early = gk.downtime_open_record("tower")
advance(3601)
gk.ladder_pass([])
store = gk.load_downtime()
mine = [c for c in store["closed"] if c["host"] == "tower"]
print(json.dumps({
    "early_open": early is not None,
    "closed": [c["closing"] for c in mine],
    "account": mine[0]["closing_account"] if mine else "",
}))
""")
check("ladder: after NEEDS-PHYSICAL the only automated "
      "act is the slow re-probe — a return inside the "
      "interval is not acted on early, and the re-probe "
      "closes the record RECOVERED-UNASSISTED when it "
      "notices the return",
      res["early_open"] and res["closed"] == ["RECOVERED-UNASSISTED"]
      and "slow re-probe" in res["account"], str(res))

print()
if fails:
    print(f"TEST_SPEC042: FAIL ({len(fails)} failing)")
    sys.exit(1)
print("TEST_SPEC042: ALL PASS")

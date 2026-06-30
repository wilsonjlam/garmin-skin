#!/usr/bin/env python3
"""
push_to_garmin.py — push the NYC Marathon 2026 training plan into Garmin Connect
as structured, scheduled running workouts (they sync to the Forerunner 255 Music).

This script is UNTESTED against a live account by its author — YOU are the verifier.
It is therefore DRY-RUN BY DEFAULT (prints what it would do, writes nothing) and every
workout it creates is name-prefixed "NYC26 " so a bad run is fully recoverable via
--cleanup. Read plans/garmin/README.md for the staged rollout before using --push.

Data source: plan_weeks.json (generated from the Lavish plan's week-by-week calendar
by extract_plan.py — single source of truth, no hand transcription).

Usage:
    python push_to_garmin.py                 # dry run: list every workout, write nothing
    python push_to_garmin.py --push --only 1 # create+schedule ONLY the first running workout
    python push_to_garmin.py --push          # create+schedule the whole plan (idempotent)
    python push_to_garmin.py --cleanup       # delete every NYC26-prefixed workout (dry run)
    python push_to_garmin.py --cleanup --push# actually delete them

Auth: set env GARMIN_EMAIL / GARMIN_PASSWORD (or you'll be prompted). A token cache at
~/.garminconnect means MFA is entered only once. Requires:  pip install garminconnect
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN_JSON = HERE / "plan_weeks.json"
PREFIX = "NYC26"                       # every workout name starts with this — used by --cleanup
TOKENSTORE = os.path.expanduser(os.getenv("GARMINTOKENS", "~/.garminconnect"))
PLAN_YEAR = 2026
MI = 1609.344                          # meters per mile

RUN_SPORT = {"sportTypeId": 1, "sportTypeKey": "running"}
STEP = {"warmup": 1, "cooldown": 2, "interval": 3, "recovery": 4, "rest": 5, "repeat": 6}
COND = {"lap.button": 1, "time": 2, "distance": 3, "iterations": 7}
TGT  = {"no.target": 1, "pace.zone": 6}

MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], start=1)}
DOW_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── pace zones (min:sec per mile → speed range in m/s) ──────────────────────────
def _sec(pace: str) -> int:
    m, s = pace.split(":")
    return int(m) * 60 + int(s)

def _mps(pace: str) -> float:
    return MI / _sec(pace)

# (fast_pace, slow_pace) → fast pace is the HIGHER speed.
_ZONE_PACES = {
    "recovery": ("11:15", "11:45"),
    "easy":     ("10:45", "11:30"),
    "long":     ("10:45", "11:30"),
    "mp":       ("10:15", "10:45"),
    "tempo":    ("9:30",  "9:50"),
    "interval": ("8:45",  "9:15"),
}

def pace_target(zone: str) -> dict:
    """pace.zone target. targetValueOne = lower speed (slower pace), Two = higher speed."""
    fast, slow = _ZONE_PACES[zone]
    lo, hi = _mps(slow), _mps(fast)          # slow pace = lower m/s
    return {
        "targetType": {"workoutTargetTypeId": TGT["pace.zone"], "workoutTargetTypeKey": "pace.zone"},
        "targetValueOne": round(lo, 3),
        "targetValueTwo": round(hi, 3),
    }

NO_TARGET = {"targetType": {"workoutTargetTypeId": TGT["no.target"], "workoutTargetTypeKey": "no.target"}}


# ── step builders ───────────────────────────────────────────────────────────────
_ORDER = [0]
def _next_order():
    _ORDER[0] += 1
    return _ORDER[0]

def run_step(step_key: str, *, meters=None, seconds=None, zone=None, cue=""):
    s = {
        "type": "ExecutableStepDTO",
        "stepOrder": _next_order(),
        "stepType": {"stepTypeId": STEP[step_key], "stepTypeKey": step_key},
    }
    if cue:
        s["description"] = cue
    if meters is not None:
        s["endCondition"] = {"conditionTypeId": COND["distance"], "conditionTypeKey": "distance"}
        s["endConditionValue"] = round(meters, 1)
    elif seconds is not None:
        s["endCondition"] = {"conditionTypeId": COND["time"], "conditionTypeKey": "time"}
        s["endConditionValue"] = float(seconds)
    else:
        s["endCondition"] = {"conditionTypeId": COND["lap.button"], "conditionTypeKey": "lap.button"}
    s.update(pace_target(zone) if zone else NO_TARGET)
    return s

def repeat_group(reps: int, children: list):
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": _next_order(),
        "stepType": {"stepTypeId": STEP["repeat"], "stepTypeKey": "repeat"},
        "numberOfIterations": reps,
        "smartRepeat": False,
        "endCondition": {"conditionTypeId": COND["iterations"], "conditionTypeKey": "iterations"},
        "endConditionValue": float(reps),
        "workoutSteps": children,
    }

def finalize(steps: list) -> list:
    """Re-stamp stepOrder depth-first (repeat group before its children) and set
    childStepId on repeat children, matching Garmin's on-wire workout format."""
    order = [0]
    def walk(lst, parent_repeat_order=None):
        for st in lst:
            order[0] += 1
            st["stepOrder"] = order[0]
            if parent_repeat_order is not None:
                st["childStepId"] = parent_repeat_order
            if st.get("type") == "RepeatGroupDTO":
                walk(st["workoutSteps"], st["stepOrder"])
    walk(steps)
    return steps


# ── classify a calendar day → ordered list of steps ─────────────────────────────
def parse_miles(main: str):
    m = re.search(r"([\d.]+)\s*mi", main)
    return float(m.group(1)) if m else None

def build_steps(main: str, sub: str) -> list:
    """Return a list of workout steps for one running day. Falls back to a single
    easy/zone step when a structured pattern isn't recognised."""
    _ORDER[0] = 0
    text = f"{main} {sub}".lower()
    miles = parse_miles(main)

    # --- Half-marathon tune-up (Week 12): WU + 10mi @ MP + ~3.1mi build ---
    if "half" in text:
        return [
            run_step("warmup", meters=1.0 * MI, zone="easy", cue="ease in"),
            run_step("interval", meters=9.0 * MI, zone="mp", cue="settle at marathon goal pace"),
            run_step("cooldown", meters=3.1 * MI, zone="tempo", cue="last 5K — build by feel, strong finish"),
        ]

    # --- Hill reps:  "hills 6×60s" ---
    mh = re.search(r"hills?\s*(\d+)\s*[x×]\s*(\d+)\s*s", text)
    if mh and miles:
        reps, secs = int(mh.group(1)), int(mh.group(2))
        return [
            run_step("warmup", meters=1.5 * MI, zone="easy", cue="warm up before hills"),
            repeat_group(reps, [
                run_step("interval", seconds=secs, zone="interval", cue="hard uphill, drive arms"),
                run_step("recovery", seconds=90, zone="recovery", cue="jog/walk down to recover"),
            ]),
            run_step("cooldown", meters=max(0.5, miles - 1.5 - reps * (secs + 90) / 3600 * 7) * MI,
                     zone="easy", cue="easy cooldown"),
        ]

    # --- Tempo:  "tempo 2×8 min" / "tempo 20 min" ---
    mt = re.search(r"tempo\s*(?:(\d+)\s*[x×]\s*)?(\d+)\s*min", text)
    if mt and miles:
        reps = int(mt.group(1) or 1)
        block = int(mt.group(2))
        children = [run_step("interval", seconds=block * 60, zone="tempo", cue="comfortably hard, controlled")]
        if reps > 1:
            children.append(run_step("recovery", seconds=120, zone="recovery", cue="float recovery"))
        main_steps = [repeat_group(reps, children)] if reps > 1 else children
        return [run_step("warmup", meters=1.0 * MI, zone="easy", cue="ease in"),
                *main_steps,
                run_step("cooldown", meters=1.0 * MI, zone="easy", cue="easy cooldown")]

    # --- Marathon-pace block:  "4 mi @ MP" / "8 mi @ MP" inside a longer run ---
    mp = re.search(r"([\d.]+)\s*mi\s*@?\s*mp", text)
    if mp and miles:
        block = float(mp.group(1))
        wu = 1.0 if miles - block >= 1.5 else max(0.5, (miles - block) / 2)
        cd = max(0.5, miles - block - wu)
        return [
            run_step("warmup", meters=wu * MI, zone="easy", cue="ease in"),
            run_step("interval", meters=block * MI, zone="mp", cue="lock in marathon goal pace"),
            run_step("cooldown", meters=cd * MI, zone="easy", cue="easy to finish"),
        ]

    # --- Simple single-zone runs ---
    if miles:
        if "recovery" in text:
            zone, cue = "recovery", "absurdly easy — recovery only"
        elif "long" in text:
            zone, cue = "long", ("fuel every 30–40 min · practice race nutrition" if "fuel" in text else "relaxed, conversational")
        else:
            zone, cue = "easy", ("easy + finish with a few strides" if "stride" in text else "truly easy, full-sentence chat")
        return [run_step("interval", meters=miles * MI, zone=zone, cue=cue)]

    return []


# ── assemble full workout payload ───────────────────────────────────────────────
def short_label(main, sub):
    t = f"{main} {sub}".lower()
    if "half" in t: return "Half tune-up"
    if "long" in t: return "Long run"
    if re.search(r"hills?\s*\d+\s*[x×]\s*\d+\s*s", t): return "Hills"
    if "tempo" in t: return "Tempo"
    if "@ mp" in t or "@mp" in t: return "MP block"
    if "recovery" in t: return "Recovery"
    if "stride" in t: return "Easy + strides"
    return "Easy"

def make_workout(week, dow, main, sub):
    steps = finalize(build_steps(main, sub))
    if not steps:
        return None
    name = f"{PREFIX} W{week:02d} {dow} · {short_label(main, sub)}"
    desc = f"{main} — {sub}".strip(" —")
    return {
        "sportType": RUN_SPORT,
        "workoutName": name[:80],
        "description": desc[:1024],
        "workoutSegments": [{
            "segmentOrder": 1,
            "sportType": RUN_SPORT,
            "workoutSteps": steps,
        }],
    }


# ── dates ───────────────────────────────────────────────────────────────────────
def monday_of(week_dates: str) -> dt.date:
    # week_dates like "Jun 29 – Jul 5" — first token is the Monday
    mon, day = week_dates.split("–")[0].strip().split()[:2]
    return dt.date(PLAN_YEAR, MONTHS[mon], int(day))

def day_date(week_dates: str, dow: str) -> dt.date:
    return monday_of(week_dates) + dt.timedelta(days=DOW_ORDER.index(dow))


# ── plan → list of (date, workout) ──────────────────────────────────────────────
def enumerate_workouts():
    weeks = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    out = []
    for w in weeks:
        for c in w["cells"]:
            if c.get("rest") or c.get("race"):
                continue
            wk = make_workout(w["week"], c["dow"], c["main"], c["sub"])
            if wk is None:
                continue
            out.append((day_date(w["dates"], c["dow"]), wk, c))
    return out


# ── Garmin client ───────────────────────────────────────────────────────────────
def connect():
    try:
        from garminconnect import Garmin
        from garth.exc import GarthHTTPError
    except ImportError:
        sys.exit("Missing dependency. Run:  pip install garminconnect")
    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ").strip()
    pwd = os.getenv("GARMIN_PASSWORD")
    try:
        g = Garmin()
        g.login(TOKENSTORE)                       # reuse cached tokens (no MFA)
        print(f"  ✓ resumed Garmin session from token cache ({TOKENSTORE})")
        return g
    except Exception:
        pass
    import getpass
    if not pwd:
        pwd = getpass.getpass("Garmin password: ")
    g = Garmin(email=email, password=pwd, return_on_mfa=True)
    res = g.login()
    if isinstance(res, tuple) and res[0] == "needs_mfa":
        code = input("MFA code (from email/app): ").strip()
        g.resume_login(res[1], code)
    g.garth.dump(TOKENSTORE)
    print(f"  ✓ logged in; token cached to {TOKENSTORE}")
    return g

def api_post(g, path, payload):
    r = g.garth.post("connectapi", path, json=payload, api=True)
    return r.json() if hasattr(r, "json") else r

def list_existing(g):
    """All NYC26-prefixed workouts already on the account: name → id."""
    found = {}
    start = 0
    while True:
        batch = g.get_workouts(start, 100)
        if not batch:
            break
        for wk in batch:
            nm = wk.get("workoutName", "")
            if nm.startswith(PREFIX):
                found[nm] = wk.get("workoutId")
        if len(batch) < 100:
            break
        start += 100
    return found


# ── actions ─────────────────────────────────────────────────────────────────────
def do_cleanup(push, only):
    print(f"\n=== CLEANUP — delete all '{PREFIX}*' workouts {'(LIVE)' if push else '(dry run)'} ===")
    g = connect()
    existing = list_existing(g)
    if not existing:
        print("  nothing to delete.")
        return
    for i, (nm, wid) in enumerate(sorted(existing.items()), 1):
        if only and i != only:
            continue
        if push:
            g.garth.request("DELETE", "connectapi", f"/workout-service/workout/{wid}", api=True)
            print(f"  ✗ deleted  {nm}  (id {wid})")
        else:
            print(f"  would delete  {nm}  (id {wid})")
    if not push:
        print(f"\n{len(existing)} workouts would be deleted. Re-run with --push to apply.")

def do_push(push, only):
    items = enumerate_workouts()
    print(f"\n=== PUSH — {len(items)} running workouts {'(LIVE)' if push else '(dry run — writes nothing)'} ===")
    if not push:
        for i, (d, wk, c) in enumerate(items, 1):
            tag = f"[{i}]"
            print(f"  {tag:>5} {d.isoformat()} {d.strftime('%a')}  {wk['workoutName']}")
            print(f"          {len(wk['workoutSegments'][0]['workoutSteps'])} steps · {wk['description']}")
        print(f"\nDry run only. Verify the dates/names above, then:")
        print(f"  • one workout : python {Path(__file__).name} --push --only 1")
        print(f"  • full plan   : python {Path(__file__).name} --push")
        return

    g = connect()
    existing = list_existing(g)        # idempotency: skip/replace by name
    created = scheduled = skipped = 0
    for i, (d, wk, c) in enumerate(items, 1):
        if only and i != only:
            continue
        name = wk["workoutName"]
        if name in existing:
            print(f"  • skip (exists) {name}")
            skipped += 1
            continue
        resp = api_post(g, "/workout-service/workout", wk)
        wid = resp.get("workoutId")
        created += 1
        api_post(g, f"/workout-service/schedule/{wid}", {"date": d.isoformat()})
        scheduled += 1
        print(f"  ✓ {d.isoformat()} {name}  (id {wid})")
    print(f"\nDone. created={created} scheduled={scheduled} skipped={skipped}.")
    print("Check Garmin Connect → Calendar, and sync your Forerunner 255.")


def main():
    ap = argparse.ArgumentParser(description="Push NYC26 marathon plan to Garmin Connect.")
    ap.add_argument("--push", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--cleanup", action="store_true", help="delete all NYC26* workouts instead of creating")
    ap.add_argument("--only", type=int, metavar="N", help="act on only the Nth item (1-based)")
    a = ap.parse_args()
    if not PLAN_JSON.exists():
        sys.exit(f"Missing {PLAN_JSON}. Run extract_plan.py first.")
    if a.cleanup:
        do_cleanup(a.push, a.only)
    else:
        do_push(a.push, a.only)


if __name__ == "__main__":
    main()

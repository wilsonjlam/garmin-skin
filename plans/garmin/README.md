# Push the NYC 2026 plan into Garmin Connect

This turns the 18-week plan into **structured, scheduled running workouts** in Garmin
Connect. They land on your Connect **Calendar** and sync to your **Forerunner 255 Music**,
so each day the watch can guide you through warmup / intervals / pace targets / cooldown.

> ⚠️ **This script writes ~85 entries to your live Garmin account and was not tested by its
> author against a real account.** It is built to be safe and reversible: it does nothing
> until you pass `--push`, every workout is named `NYC26 …`, and `--cleanup` removes them
> all. **You are the verifier — follow the staged rollout below.**

## What gets pushed

- **85 running workouts** (Weeks 1–18, every run day). Each is a structured workout with
  pace targets drawn from your plan's pace zones (Recovery → Intervals).
  - Easy / recovery / long runs → one paced step.
  - Tempo (`tempo 2×10 min`), hills (`hills 6×60s`), MP blocks (`4 mi @ MP`),
    and the Week 12 half tune-up → warmup + structured main set + cooldown.
- **Rest days and race day** → nothing pushed (rest is rest; race day is yours).
- **Strength days** → intentionally **not** pushed as structured workouts. The 255's
  strength tracking is weak and the value is low; your gym sessions live in the plan doc
  and the `#strength` sheets. (The 💪 badges stay in the HTML plan as your reference.)

## One-time setup

```bash
pip install garminconnect
export GARMIN_EMAIL="wilson.j.lam@gmail.com"
export GARMIN_PASSWORD="…"        # or omit and you'll be prompted
```

First real run will prompt for an **MFA code** (email/app) once, then cache a token at
`~/.garminconnect` so later runs don't re-auth.

## Staged rollout (do these in order)

```bash
cd plans/garmin

# 1) DRY RUN — writes nothing. Read the list: dates, names, step counts.
python push_to_garmin.py

# 2) Push ONE workout, then open Garmin Connect → Calendar (and sync the 255).
#    Confirm it looks right on both before going further.
python push_to_garmin.py --push --only 1

# 3) Happy? Push the whole plan. Safe to re-run — it skips anything already there.
python push_to_garmin.py --push
```

## If something looks wrong

```bash
python push_to_garmin.py --cleanup          # dry run: list every NYC26* workout
python push_to_garmin.py --cleanup --push    # delete them all (Connect has no bulk undo)
```

Then fix and re-push. Because everything is `NYC26`-prefixed, cleanup never touches your
other Garmin workouts.

## Regenerating the plan data

`plan_weeks.json` is generated from the Lavish plan's week-by-week calendar — the single
source of truth. If you edit the calendar in `.lavish/marathon-plan.html`, regenerate:

```bash
python extract_plan.py     # rewrites plan_weeks.json
```

## Notes / limitations

- Pace targets are ranges in m/s derived from the plan's per-mile zones; the watch shows
  them as pace bands. Adjust zones in `_ZONE_PACES` in `push_to_garmin.py` if your fitness
  shifts.
- Interval/hill **distances** are approximate (those steps end on time, not distance), so a
  workout's total mileage may differ slightly from the plan's headline number — the
  structure and paces are what matter.
- Scheduling uses each week's Monday date from the calendar (Week 1 = Mon Jun 29 2026)
  through race day **Sun Nov 1 2026**.

import re, json, io

path = "/Users/wilsonlam/workspace/garmin-skin/.lavish/marathon-plan.html"
html = io.open(path, encoding="utf-8").read()
start = html.index('id="detailed"'); end = html.index('id="strength"')
section = html[start:end]
s = re.sub(r'\s+', ' ', section)
s = re.sub(r'\s*>', '>', s)
s = re.sub(r'>\s+<', '><', s)

hdr = re.compile(
    r'<span class="font-bold">Week (\d+)</span>'
    r'<span class="text-sm text-base-content/60 break-words">([^<]+)</span>'
    r'(?:<span class="badge[^"]*">([^<]*)</span>)?', re.S)
cell_open = re.compile(r'<div class="(bg-[^"]*?) p-2 min-w-0([^"]*?)">')

hdrs = list(hdr.finditer(s))
weeks = []
for i, m in enumerate(hdrs):
    wk = int(m.group(1)); dates = m.group(2).strip(); phase = (m.group(3) or "").strip()
    seg_end = hdrs[i+1].start() if i+1 < len(hdrs) else len(s)
    window = s[m.end():seg_end]
    tot = re.search(r'<span class="font-semibold">([^<]+)</span>', window)
    total = tot.group(1).strip() if tot else ""
    opens = list(cell_open.finditer(window))
    cells = []
    for j, cm in enumerate(opens[:7]):
        cstart = cm.start()
        cend = opens[j+1].start() if j+1 < len(opens) else len(window)
        chunk = window[cstart:cend]
        bg, extra = cm.group(1), cm.group(2)
        dow = re.search(r'text-\[10px\][^"]*">([A-Za-z]+)</div>', chunk)
        main = re.search(r'font-semibold break-words">(.*?)</div>', chunk)
        subs = re.findall(r'text-xs[^"]*">(.*?)</div>', chunk)
        sub = " · ".join(re.sub(r'<[^>]+>', '', x).strip() for x in subs)
        sm = re.search(r'badge-accent[^>]*>(💪[^<]*)</span>', chunk)
        cells.append({
            "dow": dow.group(1) if dow else "?",
            "main": re.sub(r'<[^>]+>', '', main.group(1)).strip() if main else "",
            "sub": sub.strip(),
            "strength": sm.group(1).strip() if sm else "",
            "long": "secondary" in bg,
            "quality": bg == "bg-primary/10",
            "race": ("🗽" in (main.group(1) if main else "")) or "NYC MARATHON" in chunk,
            "rest": (re.sub(r'<[^>]+>', '', main.group(1)).strip().lower() == "rest") if main else False,
        })
    weeks.append({"week": wk, "dates": dates, "phase": phase, "total": total, "cells": cells})

print("weeks:", len(weeks), "| not-7:", [w["week"] for w in weeks if len(w["cells"]) != 7])
for w in [weeks[0], weeks[6], weeks[11], weeks[-1]]:
    print(f"\nW{w['week']} {w['dates']} [{w['phase']}] tot={w['total']}")
    for c in w["cells"]:
        flag = 'L' if c['long'] else ('Q' if c['quality'] else ('R' if c['race'] else ' '))
        print(f"  {c['dow']:4}{flag} {c['main']:9}| {c['sub'][:46]:46}| {c['strength']}")
json.dump(weeks, io.open("/tmp/plan_weeks.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved /tmp/plan_weeks.json")

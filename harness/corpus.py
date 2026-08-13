"""Run a corpus of real descriptions through the whole app, over HTTP.

Answers every question with its first option (a real user would choose, but the
question set is the agent's own, so any consistent policy exercises the same
path). Reports what actually happens: how long, how many design rounds, whether it
released, and — when it did not — the exact reason, so failures can be counted by
kind rather than guessed at.
"""

import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8079"
PARALLEL = 3

CORPUS = [
    "a floating desk for a small bedroom, 48 inches wide and 22 deep",
    "a workbench for my garage, 6 feet long, with a lower shelf for tools",
    "a raised planter box for vegetables, 4 feet long and 2 feet tall",
    "a nightstand with one drawer and an open shelf below",
    "a wall-mounted coat rack with a shelf above the hooks",
    "a storage bench for the end of a bed, 5 feet long with a hinged lid",
    "a bookshelf for a child's room, 36 inches tall, four shelves",
    "a firewood rack for the porch, 4 feet wide",
    "a shoe cabinet with three tilting fronts",
    "a corner plant stand with two tiers",
    "a laundry hamper cabinet with a lift-out bin",
    "a simple side table with tapered legs, 22 inches tall",
]


def api(path, body=None, timeout=240):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run_one(desc):
    started = time.time()
    out = {"desc": desc, "released": False, "reason": "", "pages": 0,
           "turns": 0, "questions": 0, "rounds": [], "seconds": 0.0}
    try:
        pid = api("/api/projects/new", {"title": desc[:40]})["id"]
        out["pid"] = pid
        intake = api(f"/api/projects/{pid}/intake", {"text": desc})
        out["intake"] = intake["outcome"]
        if intake["outcome"] == "offer_template":
            # the corpus measures the agent path; a real user would be offered both
            pass
        api(f"/api/projects/{pid}/photos-done", {})
        plan = api(f"/api/projects/{pid}/plan", {})
        if not plan.get("planned"):
            out["reason"] = "question planning failed: " + str(plan.get("error"))[:120]
            return out
        out["turns"] = plan.get("turns", 0)
        while True:
            st = api(f"/api/projects/{pid}")
            turn = st.get("turn")
            if not turn:
                break
            ans = {}
            for q in turn["questions"]:
                ans[q["field"]] = (q["options"][0]["value"] if q["options"]
                                   else (q["numeric_presets"] or [24])[0])
                out["questions"] += 1
            api(f"/api/projects/{pid}/answer", {"answers": ans})
        api(f"/api/projects/{pid}/generate", {})
        seen = set()
        while True:
            time.sleep(6)
            job = api(f"/api/projects/{pid}/job")["job"]
            mark = f"{job.get('phase')}|{job.get('detail')}"
            if mark not in seen:
                seen.add(mark)
                out["rounds"].append(mark)
            if job.get("status") in ("done", "failed"):
                if job.get("status") == "failed":
                    out["reason"] = job.get("error", "")[:220]
                break
            if time.time() - started > 900:
                out["reason"] = "timed out after 15 minutes"
                break
        st = api(f"/api/projects/{pid}")
        if st.get("document"):
            out["released"] = True
            out["pages"] = st["document"]["pages"]
    except urllib.error.URLError as exc:
        out["reason"] = f"transport: {exc}"
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"{type(exc).__name__}: {exc}"[:200]
    out["seconds"] = time.time() - started
    return out


def main():
    work = queue.Queue()
    for d in CORPUS:
        work.put(d)
    results, lock = [], threading.Lock()

    def worker():
        while True:
            try:
                desc = work.get_nowait()
            except queue.Empty:
                return
            res = run_one(desc)
            with lock:
                results.append(res)
                status = "RELEASED" if res["released"] else "held"
                print(f"[{status:8s}] {res['seconds']:5.0f}s  {res['pages']:2d}pp  "
                      f"{res['desc'][:52]}", flush=True)
                if res["reason"]:
                    print(f"             reason: {res['reason'][:150]}", flush=True)

    threads = [threading.Thread(target=worker) for _ in range(PARALLEL)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    released = [r for r in results if r["released"]]
    print("\n" + "=" * 62)
    print(f"released {len(released)}/{len(results)}")
    if released:
        times = sorted(r["seconds"] for r in released)
        pages = sorted(r["pages"] for r in released)
        print(f"time    median {times[len(times)//2]:.0f}s   "
              f"range {times[0]:.0f}-{times[-1]:.0f}s")
        print(f"pages   median {pages[len(pages)//2]}   range {pages[0]}-{pages[-1]}")
        qs = [r["questions"] for r in released]
        print(f"asked   median {sorted(qs)[len(qs)//2]} questions")
    print("\nheld back:")
    for r in results:
        if not r["released"]:
            print(f"  {r['desc'][:46]:48s} {r['reason'][:110]}")
    json.dump(results, open("out/_corpus_results.json", "w"), indent=1)


if __name__ == "__main__":
    main()

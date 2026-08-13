"""Run the RH Mara sofa through the app, with its reference photos.

Different in kind from the corpus: an upholstered piece, where what is actually
buildable is the frame. Worth seeing what the app does with that — and it is the
first run where the photos carry information the text does not.
"""

import base64
import glob
import json
import os
import time
import urllib.request

BASE = "http://localhost:8079"
# Reference photos, if any: point this at a directory of images and every one is
# attached to the project before the questions are planned.
UPLOADS = os.environ.get("SOFA_PHOTOS", "")

DESC = (
    "A low, wide two-cushion sofa frame in the style of the RH Mara — clean lines "
    "and soft rectangular curves, Italian sensibility. Roughly 96 inches wide, 40 "
    "deep and 29 tall overall. Wide flat track arms the full depth of the piece, a "
    "solid recessed plinth base so it reads as floating, two seat cushions and two "
    "back cushions. I want the hardwood frame and its plinth base built to be "
    "upholstered afterwards in bouclé."
)


def api(path, body=None, timeout=240):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def photo_data_urls():
    """The four reference shots, downscaled enough to travel as data URLs."""
    urls = []
    if not UPLOADS:
        return urls
    for path in sorted(glob.glob(os.path.join(UPLOADS, "*.png"))
                       + glob.glob(os.path.join(UPLOADS, "*.jpg"))):
        raw = open(path, "rb").read()
        urls.append("data:image/png;base64," + base64.b64encode(raw).decode())
    return urls


def main():
    pid = api("/api/projects/new", {"title": "Mara-style sofa frame"})["id"]
    print("project", pid, flush=True)
    r = api(f"/api/projects/{pid}/intake", {"text": DESC})
    print("intake:", r["outcome"], flush=True)

    for i, url in enumerate(photo_data_urls()):
        api(f"/api/projects/{pid}/photos",
            {"mime": "image/png", "data_url": url, "caption": f"reference {i+1}"})
    st = api(f"/api/projects/{pid}")
    print(f"photos attached: {len(st['photos'])}", flush=True)

    api(f"/api/projects/{pid}/photos-done", {})
    t = time.time()
    plan = api(f"/api/projects/{pid}/plan", {})
    print(f"planned {plan.get('turns')} turns in {time.time()-t:.0f}s", flush=True)
    if not plan.get("planned"):
        print("PLANNING FAILED:", plan.get("error"), flush=True)
        return

    while True:
        st = api(f"/api/projects/{pid}")
        turn = st.get("turn")
        if not turn:
            break
        ans = {}
        for q in turn["questions"]:
            ans[q["field"]] = (q["options"][0]["value"] if q["options"]
                               else (q["numeric_presets"] or [24])[0])
            print(f"  Q: {q['prompt'][:72]} -> {ans[q['field']]}", flush=True)
        api(f"/api/projects/{pid}/answer", {"answers": ans})

    print("generating", flush=True)
    api(f"/api/projects/{pid}/generate", {})
    last = None
    while True:
        time.sleep(8)
        job = api(f"/api/projects/{pid}/job")["job"]
        line = f"  [{job['status']}] {job['phase']} — {job.get('detail','')[:88]}"
        if line != last:
            print(line, flush=True)
            last = line
        if job["status"] in ("done", "failed"):
            if job.get("error"):
                print("  ERROR:", job["error"][:400], flush=True)
            break

    st = api(f"/api/projects/{pid}")
    if st.get("document"):
        print("RELEASED:", st["document"]["pages"], "pages", flush=True)
        for g in st["document"]["gates"]:
            print("   ", g["name"].split("—")[0].strip(), g["passed"], flush=True)
    print("PID", pid, flush=True)


if __name__ == "__main__":
    main()

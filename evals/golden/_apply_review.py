import json, glob, os

# (expected_score, expected_tier, annotator) from human review
PATCH = {
    "golden_001": (84, "B", "human"),
    "golden_002": (92, "A", "human"),
    "golden_003": (70, "C", "human"),
    "golden_004": (58, "C", "human"),
    "golden_005": (80, "B", "human"),
    "golden_006": (78, "B", "human"),
    "golden_007": (77, "B", "human"),
    "golden_008": (82, "B", "human"),
    "golden_009": (68, "C", "human"),
    "golden_010": (85, "A", "human"),
}

base = os.path.dirname(os.path.abspath(__file__))
for f in sorted(glob.glob(os.path.join(base, "case_*.json"))):
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
    cid = data.get("id")
    if cid not in PATCH:
        print(f"SKIP {os.path.basename(f)} (id={cid}) not in PATCH")
        continue
    sc, tier, ann = PATCH[cid]
    old = (data.get("expected_score"), data.get("expected_tier"), data.get("annotator"))
    data["expected_score"] = sc
    data["expected_tier"] = tier
    data["annotator"] = ann
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"OK {os.path.basename(f)} {old} -> ({sc},{tier},{ann})")
print("DONE")

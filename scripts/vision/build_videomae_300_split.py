import csv
import random
from collections import Counter, defaultdict
from pathlib import Path


SOURCE = Path("/workspace/SKN27-FINAL-3Team/storage/vision/staging/per_label_300/unique_300_manifest.csv")
TARGET = SOURCE.with_name("videomae_300_split.csv")
SPLITS = (("train", 210), ("val", 45), ("test", 45))


with SOURCE.open(encoding="utf-8-sig", newline="") as file:
    reader = csv.DictReader(file)
    rows = list(reader)
    fields = reader.fieldnames

by_label = defaultdict(list)
for row in rows:
    by_label[row["coarse_label"]].append(row)

rng = random.Random(20260724)
for label, label_rows in by_label.items():
    groups = defaultdict(list)
    for row in label_rows:
        groups[row["incident_id"]].append(row)
    assert len(groups) == 300 and all(len(group) == 1 for group in groups.values()), label
    shuffled = list(groups.values())
    rng.shuffle(shuffled)
    offset = 0
    for split, count in SPLITS:
        for group in shuffled[offset : offset + count]:
            for row in group:
                row["split"] = split
        offset += count

with TARGET.open("w", encoding="utf-8-sig", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

counts = Counter((row["coarse_label"], row["split"]) for row in rows)
assert all(counts[label, split] == count for label in by_label for split, count in SPLITS)
assert all(len({row["split"] for row in rows if row["incident_id"] == incident}) == 1 for incident in {row["incident_id"] for row in rows})
print(TARGET)
print(Counter(row["split"] for row in rows))

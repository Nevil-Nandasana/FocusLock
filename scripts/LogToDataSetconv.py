import re
import pandas as pd

LOG_FILE = "../data/logs/focuslock.log"
OUTPUT_FILE = "../data/ml/parsed_dataset.csv"

# Regex for extracting useful lines
pattern = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?"
    r"\[(?P<mode>NORMAL|DRIFT)\]\s+"
    r"(?P<label>PRODUCTIVE|DISTRACTION|NEUTRAL)\s+"
    r"\(Conf:\s*(?P<conf>[\d\.]+)\s*\|\s*Sim:\s*(?P<sim>[\d\.]+)\s*\|\s*Heur:\s*(?P<heur>-?\d+)\)\s*->\s*"
    r"(?P<app>[\w\.]+):\s*(?P<title>.*)"
)

rows = []

with open(LOG_FILE, "r", encoding="utf-8") as f:
    for line in f:
        match = pattern.search(line)
        if match:
            rows.append(
                {
                    "timestamp": match.group("timestamp"),
                    "mode": match.group("mode"),
                    "label": match.group("label"),
                    "confidence": float(match.group("conf")),
                    "similarity": float(match.group("sim")),
                    "heuristic": int(match.group("heur")),
                    "app": match.group("app"),
                    "window_title": match.group("title").strip(),
                }
            )

df = pd.DataFrame(rows)

# Optional: clean titles
df["window_title"] = df["window_title"].str.replace(r"\s+", " ", regex=True)

# Shuffle
df = df.sample(frac=1).reset_index(drop=True)

df.to_csv(OUTPUT_FILE, index=False)

print(f"✅ Extracted {len(df)} rows → {OUTPUT_FILE}")
print(df.head())

import pandas as pd
import random
from datetime import datetime, timedelta

# -------- CONFIG --------
SAMPLES = {"PRODUCTIVE": 2000, "DISTRACTION": 8000, "NEUTRAL": 4000}

MODES = ["deep", "normal"]

NEUTRALS = [
    "File Explorer",
    "Settings",
    "Task Manager",
    "Calculator",
    "Notepad",
    "CMD",
    "Desktop",
]

GENERIC_DISTRACTIONS = list(
    set(
        [
            "YouTube - Funny Cat Compilation",
            "Netflix - Breaking Bad",
            "Instagram",
            "Twitter",
            "Reddit - r/memes",
            "Steam - Dota 2",
            "Twitch - Live Stream",
            "Disney+ - The Mandalorian",
            "Amazon Prime Video",
            "Facebook",
            "TikTok",
            "Whatsapp Web",
            "Discord - Chat",
            "Hulu",
            "HBO Max",
            "Gaming - Cyberpunk 2077",
            "Pinterest - Home Decor",
            "9GAG - Fun",
            "BuzzFeed - Quizzes",
            "YouTube - Standup Comedy",
            "Netflix - Dave Chappelle",
            "Comedy Central",
        ]
    )
)

GOALS = {
    "Learn Python": [
        "Python Documentation",
        "Real Python Tutorial",
        "VS Code - main.py",
        "Jupyter Notebook",
        "StackOverflow - Python Lists",
        "PyCharm Project",
    ],
    "Prepare Amazon SDE interview": [
        "LeetCode - Two Sum",
        "System Design Primer",
        "Mock Interview",
        "GeeksforGeeks - DP",
        "HackerRank Dashboard",
    ],
}


# -------- HELPERS --------
def random_time():
    now = datetime.now()
    delta = timedelta(minutes=random.randint(0, 600))
    return (now - delta).strftime("%H:%M")


def add_noise(title):
    noise_types = [
        lambda x: f"{x} - Chrome",
        lambda x: f"{x} | Tab 3",
        lambda x: f"{x} ({random_time()})",
        lambda x: f"Editing - {x}",
        lambda x: x,
    ]
    return random.choice(noise_types)(title)


def generate_samples(goal, label, count):
    samples = []

    if label == "PRODUCTIVE":
        base_list = GOALS[goal]
    elif label == "DISTRACTION":
        base_list = GENERIC_DISTRACTIONS
    else:
        base_list = NEUTRALS

    for _ in range(count):
        base = random.choice(base_list)
        title = add_noise(base)

        samples.append(
            {
                "goal": goal,
                "window_title": title,
                "mode": random.choice(MODES),
                "time": random_time(),
                "label": label,
            }
        )

    return samples


# -------- MAIN --------
def build_dataset():
    data = []

    for goal in GOALS.keys():
        for label, count in SAMPLES.items():
            data.extend(generate_samples(goal, label, count))

    df = pd.DataFrame(data)

    # Shuffle dataset
    df = df.sample(frac=1).reset_index(drop=True)

    return df


if __name__ == "__main__":
    df = build_dataset()
    df.to_csv("../data/ml/training_data.csv", index=False)

    print(f"✅ Generated {len(df)} samples")
    print(df.head())
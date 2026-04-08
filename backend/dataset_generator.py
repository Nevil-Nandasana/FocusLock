
import pandas as pd
import random

# -------- CONFIGURATION --------
GOALS = [
    "Prepare Amazon SDE interview",
    "Learn React",
    "Study for math exam",
    "Write research paper",
    "Learn Python",
    "Build a portfolio website",
    "Debug backend API",
    "Learn machine learning",
    "Write technical documentation",
    "Fix CSS bugs"
]

# Shared generic distractions (will be mixed with all goals)
GENERIC_DISTRACTIONS = [
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
    "Pinterest - Home Decor",
    "9GAG - Fun",
    "BuzzFeed - Quizzes",
    "YouTube - Standup Comedy",
    "Netflix - Dave Chappelle",
    "Comedy Central"
]

# Goal-specific productive titles
PRODUCTIVE_MAP = {
    "Prepare Amazon SDE interview": [
        "LeetCode - Two Sum", "Amazon Leadership Principles", "System Design Primer", "Cracking the Coding Interview PDF", 
        "HackerRank - Dashboard", "GeeksforGeeks - Dynamic Programming", "Mock Interview", "YouTube - Amazon SDE Interview Guide"
    ],
    "Learn React": [
        "React Official Documentation", "Redux Toolkit Guide", "StackOverflow - useEffect hook", "YouTube - React Crash Course",
        "Udemy - React - The Complete Guide", "VS Code - App.js", "Create React App", "Tailwind CSS Docs"
    ],
    "Study for math exam": [
        "Wolfram Alpha", "Khan Academy - Calculus", "Linear Algebra PDF", "Desmos Graphing Calculator", 
        "YouTube - 3Blue1Brown", "Coursera - Mathematics", "MIT OpenCourseWare", "Textbook - Chapter 5"
    ],
    "Write research paper": [
        "Google Scholar", "arXiv.org", "Overleaf - LaTeX Editor", "Mendeley Reference Manager", 
        "ResearchGate - Download PDF", "IEEE Xplore", "Zotero Library", "Word - Research_Final.docx"
    ],
    "Learn Python": [
        "Python 3.9 Documentation", "Real Python - Tutorials", "Automate the Boring Stuff", "VS Code - main.py", 
        "PyCharm", "Jupyter Notebook", "StackOverflow - List Comprehension", "YouTube - Corey Schafer Python"
    ],
    "Build a portfolio website": [
        "Dribbble - Inspiration", "Behance - Portfolio Design", "Figma - UI Design", "VS Code - index.html", 
        "MDN Web Docs - Grid Layout", "GitHub - Portfolio Repo", "Netlify - Dashboard", "Vercel - Deployment"
    ],
    "Debug backend API": [
        "Postman", "Swagger UI", "AWS CloudWatch Logs", "StackOverflow - 500 Internal Server Error", 
        "VS Code - server.py", "Django Documentation", "Flask API Guide", "Docker Desktop"
    ],
    "Learn machine learning": [
        "Kaggle", "TensorFlow Documentation", "PyTorch Tutorials", "Andrew Ng - Deep Learning", 
        "Colab - Untitled.ipynb", "Scikit-Learn Guide", "Towards Data Science", "Hugging Face Models"
    ],
    "Write technical documentation": [
        "Notion - Tech Spec", "Google Docs - Architecture Overview", "Confluence - Wiki", "Markdown Guide", 
        "Draw.io - Architecture Diagram", "Jira - Ticket 123", "GitHub - README.md", "Lucidchart"
    ],
    "Fix CSS bugs": [
        "MDN - Flexbox", "CSS Tricks - Guide to Grid", "StackOverflow - Center a div", "Chrome DevTools", 
        "VS Code - styles.css", "Can I Use - CSS Grid", "CodePen - Test", "W3Schools - CSS Selectors"
        
    
    ]
}

# Goal-specific distractions (Tricky cases: "Learn Python" -> "Python Game")
# Actually, the prompt suggests "Distraction" usually means entertainment.
# We will use generic distractions + some tricky ones.

TRICKY_DISTRACTIONS = [
    "YouTube - Top 10 Python Fails", # Contains Python but is fail compilation? Maybe productive? Let's say generic entertainment is safer.
    "Reddit - r/Python (Memes)",
    "Twitter - Tech Drama"
]

data = []

for goal in GOALS:
    # 1. Productive Samples (50)
    prods = PRODUCTIVE_MAP.get(goal, [])
    for _ in range(50):
        # Pick a base title and maybe modify slightly
        base = random.choice(prods)
        mode = random.choice(["deep", "normal"])
        
        # Add some noise to titles
        title = base if random.random() > 0.3 else f"{base} - Chrome"
        
        data.append({
            "goal": goal,
            "window_title": title,
            "mode": mode,
            "label": "PRODUCTIVE"
        })

    # 2. Distraction Samples (50)
    # Mix of Generic
    for _ in range(50):
        base = random.choice(GENERIC_DISTRACTIONS)
        mode = random.choice(["deep", "normal"])
        title = base if random.random() > 0.3 else f"{base} - Chrome"
        
        data.append({
            "goal": goal,
            "window_title": title,
            "mode": mode,
            "label": "DISTRACTION"
        })

    # 3. Neutral Samples (20)
    # System apps, file explorer, etc.
    NEUTRALS = ["File Explorer", "Settings", "Task Manager", "Calculator", "Notepad", "CMD", "Desktop"]
    for _ in range(20):
        base = random.choice(NEUTRALS)
        mode = random.choice(["deep", "normal"])
        data.append({
            "goal": goal,
            "window_title": base,
            "mode": mode,
            "label": "NEUTRAL"
        })

# Create DataFrame
df = pd.DataFrame(data)

# Save to CSV
df.to_csv("backend/training_data.csv", index=False)
print(f"Generated {len(df)} samples in backend/training_data.csv")

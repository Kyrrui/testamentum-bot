"""
Scraper for the Didascalicon — the Marcionite Church catechism Q&A.

Source: https://marcionitechurchofchrist.org/didascalicon/

Parses the page into a structured JSON of lessons and Q&A entries.
Validates the output before overwriting, so we don't corrupt the data
if the source page changes shape or is unavailable.
"""

import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

URL = "https://marcionitechurchofchrist.org/didascalicon/"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "didascalicon.json")

Q_RE = re.compile(r"^(\d+)\.(\d+)\.\s+(.+\?)\s*$")
LESSON_RE = re.compile(r"^Lesson\s+(\d+):\s*(.+)$")

# Minimum thresholds — if the scrape drops below these, we abort instead
# of overwriting the cached file. Current site has 18 lessons / 235 Q&As.
MIN_LESSONS = 15
MIN_QUESTIONS = 200

# Canary entries that must exist for the scrape to be considered valid.
CANARIES = ["1.01", "2.01"]


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def fetch_page(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def parse(soup: BeautifulSoup) -> dict:
    all_p = soup.find_all("p")

    lessons = {}  # {lesson_num: {title, questions: [...]}}
    questions = []  # flat list of {lesson, lesson_title, number, question, answer}

    current_q = None
    answer_paras: list[str] = []
    current_lesson_num = None
    current_lesson_title = None

    def flush():
        if current_q is not None:
            answer = "\n\n".join(answer_paras).strip()
            current_q["answer"] = answer
            questions.append(current_q)

    for p in all_p:
        strong = p.find("strong")
        strong_text = strong.get_text(strip=True) if strong else ""
        full_text = p.get_text(" ", strip=True)

        qm = Q_RE.match(strong_text)
        lm = LESSON_RE.match(strong_text)

        if qm:
            flush()
            number = f"{qm.group(1)}.{qm.group(2)}"
            current_q = {
                "lesson": int(qm.group(1)),
                "lesson_title": current_lesson_title or "",
                "number": number,
                "question": qm.group(3).strip(),
            }
            answer_paras = []
        elif lm:
            flush()
            current_q = None
            answer_paras = []
            current_lesson_num = int(lm.group(1))
            current_lesson_title = lm.group(2).strip()
            lessons[current_lesson_num] = {
                "number": current_lesson_num,
                "title": current_lesson_title,
                "questions": [],
            }
        else:
            if current_q and full_text:
                answer_paras.append(full_text)

    flush()

    # Backfill each lesson's questions list with their numbers
    for q in questions:
        ln = q["lesson"]
        if ln in lessons:
            lessons[ln]["questions"].append(q["number"])

    return {
        "source_url": URL,
        "lessons": [lessons[k] for k in sorted(lessons.keys())],
        "questions": questions,
    }


def validate(db: dict) -> list[str]:
    """Return list of validation errors. Empty list means OK."""
    errors = []
    n_lessons = len(db["lessons"])
    n_questions = len(db["questions"])

    if n_lessons < MIN_LESSONS:
        errors.append(f"Only {n_lessons} lessons (expected >={MIN_LESSONS})")
    if n_questions < MIN_QUESTIONS:
        errors.append(f"Only {n_questions} questions (expected >={MIN_QUESTIONS})")

    numbers = {q["number"] for q in db["questions"]}
    for canary in CANARIES:
        if canary not in numbers:
            errors.append(f"Missing canary question {canary}")

    # Every question must have non-trivial answer text
    short_answers = [q["number"] for q in db["questions"] if len(q.get("answer", "")) < 50]
    if short_answers:
        errors.append(
            f"{len(short_answers)} question(s) have very short answers: "
            f"{short_answers[:5]}"
        )

    return errors


def main() -> int:
    print(f"Fetching {URL}...")
    soup = fetch_page(URL)
    print("Parsing...")
    db = parse(soup)
    print(f"Parsed {len(db['lessons'])} lessons, {len(db['questions'])} questions.")

    errors = validate(db)
    if errors:
        print("\nValidation FAILED:")
        for e in errors:
            print(f"  - {e}")
        print("\nAborting: existing data/didascalicon.json will NOT be overwritten.")
        return 1

    print("\nValidation passed.")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    print(f"Saved to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

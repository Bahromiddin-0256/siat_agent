#!/usr/bin/env python3
"""Complex Uzbek Q&A smoke-test set for the SDMX Agent.

This runs 10 multi-step Uzbek questions end-to-end against the agent.
It is intentionally lightweight (no pytest dependency) and focuses on:
- agent can run without crashing
- each response is non-empty
- response looks like natural text (not raw tool-call JSON)

Optional keyword expectations are used only as weak signals (because the exact
indicator/values can change depending on data coverage).
"""

# Ensure imports work when running as: python tests/test_uzbek_complex_questions.py
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncio
from dataclasses import dataclass
from typing import Iterable

from core.agent import create_sdmx_agent, run_agent_async
from tools import initialize_sdmx_data, initialize_rag_vectorstore


@dataclass(frozen=True)
class Case:
    name: str
    question: str
    must_contain_any: tuple[str, ...] = ()


CASES: list[Case] = [
    Case(
        name="Yangihayot 2021-2024 tug'ilish trend",
        question=(
            "2021–2024 yillarda Yangihayot tumanida tug‘ilishlar soni trendi qanday "
            "o‘zgargan (har yil bo‘yicha raqamlarni chiqarib, foiz o‘zgarishni ham aytib bering)?"
        ),
        must_contain_any=("2021", "2022", "2023", "2024", "Yangihayot"),
    ),
    Case(
        name="Andijon vs Farg‘ona jon boshiga investitsiya 2023",
        question=(
            "2023-yilda Andijon va Farg‘ona viloyatlarida aholi jon boshiga investitsiya "
            "(asosiy kapitalga) qaysi biri yuqori, farqi qancha va necha foiz?"
        ),
        must_contain_any=("2023", "Andijon", "Farg", "foiz"),
    ),
    Case(
        name="Shahar/qishloq tug'ilish ulushi 2019-2023",
        question=(
            "2019–2023 oralig‘ida O‘zbekistonda jami tug‘ilishlar ichida shahar va qishloq "
            "ulushi qanday o‘zgargan? (har yil uchun shahar/qishloq ulushini % da chiqaring)"
        ),
        must_contain_any=("2019", "2020", "2021", "2022", "2023", "%"),
    ),
    Case(
        name="Nikoh/ajrim nisbatlari 2022 Toshkent shahar vs viloyat",
        question=(
            "2022-yilda Toshkent shahri va Toshkent viloyatida nikohlar soni va ajrimlar soni "
            "nisbatini solishtiring (ajr/nikoh koeffitsienti). Qaysi hududda ko‘rsatkich yuqoriroq?"
        ),
        must_contain_any=("2022", "Toshkent", "nikoh", "ajrim"),
    ),
    Case(
        name="2018-2022 ishsizlikga yaqin indikator, 2020 anomaliya",
        question=(
            "2020-yil pandemiya davrida ishsizlikka yaqin indikator(lar) topib, 2018–2022 "
            "kesimida dinamikasini chiqarib bering va 2020 yildagi “anomaliya”ni izohlang."
        ),
        must_contain_any=("2018", "2019", "2020", "2021", "2022"),
    ),
    Case(
        name="O'rtacha ish haqi (yoki daromad) 2015 vs 2023 nominal o'sish",
        question=(
            "2015 va 2023 yillarda O‘zbekistonda o‘rtacha ish haqi (yoki daromad) ko‘rsatkichi "
            "qancha bo‘lgan, nominal o‘sish koeffitsienti nechiga teng?"
        ),
        must_contain_any=("2015", "2023", "koeff"),
    ),
    Case(
        name="Qashqadaryo sanoat vs qishloq xo'jaligi 2021-2023",
        question=(
            "2021–2023 yillarda Qashqadaryo viloyatida sanoat ishlab chiqarishi hajmi va "
            "qishloq xo‘jaligi mahsuloti hajmi parallel qanday o‘zgargan? Qaysi biri tezroq o‘sgan?"
        ),
        must_contain_any=("2021", "2022", "2023", "Qashqadaryo"),
    ),
    Case(
        name="Tabiiy o'sish = tug'ilish - o'lim, 2023",
        question=(
            "2023-yilda O‘zbekistonda aholining tabiiy o‘sishi = tug‘ilishlar − o‘limlar. "
            "Shu qiymatni topib bering (ikkala komponentni alohida ham ko‘rsating)."
        ),
        must_contain_any=("2023", "tug", "o‘lim", "farq"),
    ),
    Case(
        name="Inflatsiya/CPI 2010-2023 min/max",
        question=(
            "2010–2023 oralig‘ida O‘zbekistonda inflatsiyaga aloqador indikatorni topib, "
            "eng yuqori va eng past yilni aniqlang, farqini ayting."
        ),
        must_contain_any=("2010", "2023", "eng yuqori", "eng past"),
    ),
    Case(
        name="Tug'ilish koeffitsienti (1000 kishiga) Surxondaryo 2022",
        question=(
            "2022-yilda Surxondaryo viloyati bo‘yicha “aholi soni” va “tug‘ilishlar soni”dan "
            "foydalanib tug‘ilish koeffitsientini (1000 kishiga) hisoblab bering."
        ),
        must_contain_any=("2022", "Surxondaryo", "1000"),
    ),
]


def _looks_like_tool_json(text: str) -> bool:
    t = text.strip()
    return bool(t) and (t.startswith("{") or t.startswith("["))


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    low = text.lower()
    return any(n.lower() in low for n in needles)


async def main() -> int:
    # Initialize data once
    json_file = Path("jsons/main.json")
    print("Initializing SDMX data...")
    initialize_sdmx_data(json_file)

    print("Initializing RAG vectorstore...")
    from tools import sdmx_tool

    initialize_rag_vectorstore(sdmx_tool._json_data)

    print("Creating agent...")
    agent, system_prompt, _ = create_sdmx_agent()

    failures: list[str] = []

    for i, case in enumerate(CASES, 1):
        print("\n" + "=" * 80)
        print(f"{i:02d}. {case.name}")
        print("-" * 80)
        print(case.question)
        print("-" * 80)

        try:
            response = await run_agent_async(agent, case.question, system_prompt)
        except Exception as e:
            failures.append(f"{i:02d}. {case.name}: crashed: {e}")
            print(f"❌ CRASH: {e}")
            continue

        response = (response or "").strip()
        print("Response:\n" + response)

        if not response:
            failures.append(f"{i:02d}. {case.name}: empty response")
            print("❌ FAIL: empty response")
            continue

        if _looks_like_tool_json(response) and len(response) < 250:
            failures.append(f"{i:02d}. {case.name}: looks like raw tool JSON")
            print("❌ FAIL: looks like raw tool JSON")
            continue

        if case.must_contain_any and not _contains_any(response, case.must_contain_any):
            # Not a hard fail (LLM can paraphrase), but mark as warning/failure signal.
            failures.append(
                f"{i:02d}. {case.name}: missing expected hints: {case.must_contain_any}"
            )
            print("⚠️  WARN: response missing expected topical hints")
        else:
            print("✅ PASS")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    if failures:
        print(f"Completed with {len(failures)} issue(s):")
        for f in failures:
            print("- " + f)
        # Return non-zero so CI/shell can detect issues.
        return 1

    print("All 10 cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

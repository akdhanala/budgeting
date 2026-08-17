import argparse
import asyncio
import json
import os
import sys
import time

import pandas as pd
from openai import AsyncOpenAI

ALLOWED_CATEGORIES = [
    "Housing & Utilities",
    "Groceries",
    "Dining Out",
    "Bars & Nightlife",
    "Transportation",
    "Subscriptions & Services",
    "Shopping & Apparel",
    "Health & Fitness",
    "Travel & Vacation",
    "Entertainment & Events",
    "Investments & Savings",
    "Emergency Fund",
    "Gifts & Donations",
    "Insurance",
    "Education",
    "Home Improvement",
    "Miscellaneous",
]


def _load_seed_keywords(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if v}


def _load_cache(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _check_static_cache(description: str, seed_keywords: dict) -> str | None:
    desc_lower = description.lower()
    for keyword, category in seed_keywords.items():
        if keyword.lower() in desc_lower:
            return category
    return None


def _prompt_category(prompt: str) -> str | None:
    while True:
        raw = input(prompt).strip()
        if not raw:
            return None
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(ALLOWED_CATEGORIES):
                return ALLOWED_CATEGORIES[n - 1]
            print(f"  Invalid number. Enter 1-{len(ALLOWED_CATEGORIES)}, category name, or Enter to skip.")
            continue
        if raw in ALLOWED_CATEGORIES:
            return raw
        print(f"  Invalid category. Enter 1-{len(ALLOWED_CATEGORIES)}, exact name, or Enter to skip.")


async def _query_llm(client: AsyncOpenAI, description: str, extended_notes: str = "") -> tuple[str, float]:
    instructions = (
        "You are a financial categorization assistant. "
        "Categorize the given transaction into exactly one of the following categories:\n"
        + "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)
    )

    user_content = f"Description: {description}"
    if extended_notes:
        user_content += f"\nExtended Notes: {extended_notes}"

    response = await client.responses.create(
        model="muse-spark-1.2-contributor",
        instructions=instructions,
        input=user_content,
        text={
            "format": {
                "type": "json_schema",
                "name": "categorization",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ALLOWED_CATEGORIES,
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                    },
                    "required": ["category", "confidence"],
                    "additionalProperties": False,
                },
            }
        },
    )

    content = response.output_text
    parsed = json.loads(content)
    category = parsed.get("category", "Miscellaneous")
    confidence = float(parsed.get("confidence", 0.0))

    if category not in ALLOWED_CATEGORIES:
        category = "Miscellaneous"

    return category, confidence


def run_bootstrap(input_csv: str, seed_file: str) -> None:
    df = pd.read_csv(input_csv)
    freq = df["Description"].value_counts().head(100)

    print(f"Found {len(freq)} unique merchants. Assign a category to each (or press Enter to skip).\n")
    for i, cat in enumerate(ALLOWED_CATEGORIES, 1):
        print(f"  {i:2d}. {cat}")
    print("\nEnter the number (1-17) or exact category name. Leave blank to skip.\n")

    seed_keywords: dict[str, str] = {}
    for idx, (merchant, count) in enumerate(freq.items(), 1):
        cat = _prompt_category(f"[{idx}/{len(freq)}] \"{merchant}\" ({count}x) -> ")
        if cat is None:
            continue
        seed_keywords[merchant] = cat

    with open(seed_file, "w") as f:
        json.dump(seed_keywords, f, indent=2)
    skipped = len(freq) - len(seed_keywords)
    print(f"\nSaved {len(seed_keywords)} mappings to {seed_file} ({skipped} skipped).")


async def run_pipeline(
    input_csv: str,
    seed_file: str,
    cache_file: str,
    output_csv: str,
) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    print(f"Loading {input_csv}...")
    df = pd.read_csv(input_csv)

    if "Description" not in df.columns:
        raise ValueError("Input CSV must contain a 'Description' column.")

    print(f"Loaded {len(df)} transactions.")
    seed_keywords = _load_seed_keywords(seed_file)
    llm_cache = _load_cache(cache_file)
    print(f"Seed keywords: {len(seed_keywords)} entries from {seed_file}")
    print(f"LLM cache: {len(llm_cache)} entries from {cache_file}")

    client = AsyncOpenAI(
        base_url="https://api.meta.ai/v1",
        api_key=os.getenv("MODEL_API_KEY"),
    )

    notes_col = "Type / Extended Notes"
    notes_lookup: dict[str, str] = {}
    if notes_col in df.columns:
        grouped = df.groupby("Description")[notes_col].apply(list)
        for desc_key, notes_list in grouped.items():
            seen: list[str] = []
            seen_set: set[str] = set()
            for n in notes_list:
                if pd.isna(n):
                    continue
                s = str(n).strip()
                if not s or s.lower() == "nan" or s in seen_set:
                    continue
                seen.append(s)
                seen_set.add(s)
                if len(seen) >= 3:
                    break
            if seen:
                notes_lookup[str(desc_key).strip()] = " | ".join(seen)

    unique_descriptions = df["Description"].dropna().unique().tolist()
    print(f"Unique merchants: {len(unique_descriptions)}")

    merchant_map: dict[str, str] = {}
    new_cache_entries: dict = {}
    pending: list[tuple[str, str]] = []
    l1_hits = 0
    l2_hits = 0

    for desc in unique_descriptions:
        desc_str = str(desc).strip()

        static_result = _check_static_cache(desc_str, seed_keywords)
        if static_result is not None:
            merchant_map[desc_str] = static_result
            l1_hits += 1
            continue

        if desc_str in llm_cache:
            cached = llm_cache[desc_str]
            if isinstance(cached, dict):
                merchant_map[desc_str] = cached.get("category", "Miscellaneous")
            else:
                merchant_map[desc_str] = str(cached)
            l2_hits += 1
            continue

        pending.append((desc_str, notes_lookup.get(desc_str, "")))

    print(f"  L1 static cache hits: {l1_hits}")
    print(f"  L2 dynamic cache hits: {l2_hits}")
    print(f"  L3 LLM needed: {len(pending)}")

    needs_review: list[tuple[str, str, str, float]] = []

    if pending:
        print(f"Classifying {len(pending)} merchants via LLM (concurrency=10)...")
        sem = asyncio.Semaphore(10)
        total = len(pending)
        completed = 0
        start = time.monotonic()

        async def _classify(desc_str: str, notes: str) -> tuple[str, str, float]:
            async with sem:
                try:
                    cat, conf = await _query_llm(client, desc_str, notes)
                    return desc_str, cat, conf
                except Exception as e:
                    print(f"  ! LLM error for \"{desc_str}\": {e}", file=sys.stderr)
                    return desc_str, "Needs Review", 0.0

        tasks = [asyncio.create_task(_classify(d, n)) for d, n in pending]

        results: list[tuple[str, str, float]] = []
        for coro in asyncio.as_completed(tasks):
            res = await coro
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == total:
                elapsed = time.monotonic() - start
                rate = completed / elapsed if elapsed > 0 else 0
                print(f"  ... {completed}/{total} classified ({rate:.1f}/s, {elapsed:.0f}s elapsed)")

        for desc_str, category, confidence in results:
            if category == "Needs Review" or confidence < 0.80:
                notes = notes_lookup.get(desc_str, "")
                needs_review.append((desc_str, notes, category, confidence))
                merchant_map[desc_str] = "Needs Review"
            else:
                merchant_map[desc_str] = category
                new_cache_entries[desc_str] = {"category": category, "confidence": confidence}

        print(f"LLM done: {len(new_cache_entries)} cached, {len(needs_review)} -> Needs Review")
    else:
        print("No LLM calls needed — all merchants resolved from cache.")

    if needs_review:
        if not sys.stdin.isatty():
            print(f"\n{len(needs_review)} merchants need review (non-interactive — leaving as \"Needs Review\").")
        else:
            print(f"\n{len(needs_review)} merchants need review (confidence < 0.80).")
            print("Assign a category for each, or press Enter to leave as Miscellaneous.\n")
            for i, cat in enumerate(ALLOWED_CATEGORIES, 1):
                print(f"  {i:2d}. {cat}")
            print()

            for idx, (desc_str, notes, llm_cat, conf) in enumerate(needs_review, 1):
                freq_count = int((df["Description"] == desc_str).sum())
                notes_preview = f" | Notes: {notes[:120]}" if notes else ""
                print(f"[{idx}/{len(needs_review)}] \"{desc_str}\" ({freq_count}x){notes_preview}")
                print(f"         LLM suggested: {llm_cat} (confidence {conf:.2f})")
                chosen = _prompt_category("         Assign -> ")
                if chosen is None:
                    merchant_map[desc_str] = "Miscellaneous"
                else:
                    merchant_map[desc_str] = chosen
                    new_cache_entries[desc_str] = {"category": chosen, "confidence": 1.0}
            print(f"\nInteractive review complete: {len([v for v in needs_review if merchant_map[v[0]] != 'Miscellaneous'])} resolved, {sum(1 for v in needs_review if merchant_map[v[0]] == 'Miscellaneous')} left as Miscellaneous.")

    if new_cache_entries:
        llm_cache.update(new_cache_entries)
        with open(cache_file, "w") as f:
            json.dump(llm_cache, f, indent=2)
        print(f"Cache updated: +{len(new_cache_entries)} entries -> {cache_file}")

    print("Mapping categories back to transactions and writing output...")
    df["Category"] = df["Description"].apply(
        lambda d: merchant_map.get(str(d).strip(), "Miscellaneous") if pd.notna(d) else "Miscellaneous"
    )

    df.to_csv(output_csv, index=False)

    categorized = len(df)
    needs_left = int((df["Category"] == "Needs Review").sum())
    if needs_left:
        print(f"Note: {needs_left} rows still marked Needs Review (non-interactive mode).")
    print(f"Done: {categorized} transactions -> {output_csv}")


def main() -> None:
    parser = argparse.ArgumentParser(description="3-Tier LLM Categorization Pipeline")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bootstrap", action="store_true", help="Generate keyword template from top merchants")
    mode.add_argument("--run", action="store_true", help="Run the categorization pipeline")

    parser.add_argument("--input-csv", dest="input_csv", default="consolidated_transactions.csv", help="Input CSV path")
    parser.add_argument("--seed-file", dest="seed_file", default="seed_keywords.json", help="Seed keywords JSON path")
    parser.add_argument("--cache-file", dest="cache_file", default="llm_cache.json", help="LLM cache JSON path")
    parser.add_argument("--output-csv", dest="output_csv", default="categorized_output.csv", help="Output CSV path")

    args = parser.parse_args()

    if args.bootstrap:
        run_bootstrap(args.input_csv, args.seed_file)
    elif args.run:
        asyncio.run(run_pipeline(args.input_csv, args.seed_file, args.cache_file, args.output_csv))


if __name__ == "__main__":
    main()

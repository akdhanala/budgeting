# Budgeting

One of the biggest problems of my post-college life is figuring out how to manage my income stream. It's not a very unique problem either. I'll try to solve my own and hopefully, in the process solve others as well by creating whatever it is I plan on building here. Stay tuned!

### Setup
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Managing input
If you imagine budgeting as a group of differently sized envelopes that you refill with cash each month, your first question would probably be "well how much cash do I put in my dining out envelope?" or something of that nature. Now you could make a simple guess of how much you'd like to actually be spending but odds are you'll probably dissatisfied with whatever number you put there. Either you overshoot it, or you undershoot it. The idea is we want to slightly squeeze what we're currently spending. In order to grasp what my "unrestrained" spending is to give my envelopes a better starting point, I need to pull my credit statements dating back the past year. Since I have multiple credit cards, I need to consolidate these sources into a single CSV. 

I present to you, `consolidate.py`. A very simple, dumb script meant to do just that.

Invoke it like so:
```bash
.venv/bin/python scripts/consolidate.py amex.csv chase.csv -o consolidated_transactions.csv
```


## Data labeling
At this point, we have uniform data from our sources. However, this data is still unlabeled. We have no idea if a transaction fits into a specific budget category. It's not like banks intuitively know what each transaction belongs to. We need to do some nifty categorization; I have about 5000+ rows to process so we'll also need to approach this from an at scale perspective. 

At Uber, I had an interesting use case that required using chatgpt's models. I was simply scoping it out but I recall the team I interacted with using [zero-shot classification](https://huggingface.co/tasks/zero-shot-classification) on places-of-interest to label them. I'm going to do that and parallelize it across all my transactions (max 10 workers) using openai's [responses api](https://developers.openai.com/api/docs/guides/migrate-to-responses) and its [async client](https://github.com/openai/openai-python#async-usage). Check out this categorization work in `scripts/categorize.py`. I've also hooked up the openai sdk to my [muse code](https://developer.meta.com/ai/products/muse-code/) api key. If you ask me why I chose this specific model? It's dirt cheap. 

### Setup

```bash
export MODEL_API_KEY=your_key  # Meta API key for https://api.meta.ai/v1
```

### 1. Bootstrap — label your frequent merchants

Scans `consolidated_transactions.csv`, finds the top 100 merchants by frequency, and walks you through them interactively. Enter `1-17`, the exact category name, or `Enter` to skip.

```bash
.venv/bin/python scripts/categorize.py --bootstrap
# custom paths:
.venv/bin/python scripts/categorize.py --bootstrap --input-csv consolidated_transactions.csv --seed-file seed_keywords.json
```

This writes `seed_keywords.json` — a `{ "merchant substring": "Category" }` map used as the L1 static cache (substring match, confidence `1.0`). Allowed categories:

`Housing & Utilities`, `Groceries`, `Dining Out`, `Bars & Nightlife`, `Transportation`, `Subscriptions & Services`, `Shopping & Apparel`, `Health & Fitness`, `Travel & Vacation`, `Entertainment & Events`, `Investments & Savings`, `Emergency Fund`, `Gifts & Donations`, `Insurance`, `Education`, `Home Improvement`, `Miscellaneous`

### 2. Run — 3-tier categorization

```bash
.venv/bin/python scripts/categorize.py --run
# custom paths:
.venv/bin/python scripts/categorize.py --run \
  --input-csv consolidated_transactions.csv \
  --seed-file seed_keywords.json \
  --cache-file llm_cache.json \
  --output-csv categorized_output.csv
```

**Pipeline:**

- **L1 Static cache** — `seed_keywords.json` substring match → instant `1.0`
- **L2 Dynamic cache** — `llm_cache.json` exact `Description` match → cached category
- **L3 LLM** — `AsyncOpenAI(base_url="https://api.meta.ai/v1")` via `client.responses.create` with `muse-spark-1.2-contributor` and a strict JSON Schema (`{category, confidence}`), using both `Description` and `Type / Extended Notes` for context. Calls are deduped to one per unique merchant and fanned out with `asyncio` at concurrency 10.

Live progress is printed (`L1/L2/L3 counts`, `... 10/342 classified (8.2/s)`), and the dynamic cache is updated silently.

- **`confidence >= 0.80`** → assigned and cached to `llm_cache.json`
- **`confidence < 0.80`** → prompted interactively (TTY only):
  ```
  [1/12] "CHIEF" (3x) | Notes: CHIEF.COM | Card Not Present
           LLM suggested: Dining Out (confidence 0.72)
           Assign ->
  ```
  Enter `1-17` / name / `Enter` for `Miscellaneous`. Your choice is cached with `1.0` so you won't be asked again. In non-interactive mode, low-confidence rows are left as `Miscellaneous`.

**Output:** only `categorized_output.csv` (plus the updated `seed_keywords.json` / `llm_cache.json` caches). No intermediate `review_queue.csv` — review happens inline.

Defaults (omit the flags to use these):

| Flag | Default |
|------|---------|
| `--input-csv` | `consolidated_transactions.csv` |
| `--seed-file` | `seed_keywords.json` |
| `--cache-file` | `llm_cache.json` |
| `--output-csv` | `categorized_output.csv` |


## Next Steps

With this latest commit, you'll have noticed I added a script that's not housed under the traditional /scripts folder. This is intentional. The purpose of this project is for me to get acquainted with LangChain, a widely used framework meant to be used when creating workflows. And what better starting point than your classic Hello World? The north star here is to convert the consolidate and categorize scripts into nodes that'll present in this graph. Let's keep building!
# Budgeting

One of the biggest problems of my post-college life is figuring out how to manage my income stream. It's not a very unique problem either. I'll try to solve my own and hopefully, in the process solve others as well by creating whatever it is I plan on building here. Stay tuned!

### Setup
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

# Managing input
If you imagine budgeting as a group of differently sized envelopes that you refill with cash each month, your first question would probably be "well how much cash do I put in my dining out envelope?" or something of that nature. Now you could make a simple guess of how much you'd like to actually be spending but odds are you'll probably dissatisfied with whatever number you put there. Either you overshoot it, or you undershoot it. The idea is we want to slightly squeeze what we're currently spending. In order to grasp what my "unrestrained" spending is to give my envelopes a better starting point, I need to pull my credit statements dating back the past year. Since I have multiple credit cards, I need to consolidate these sources into a single CSV. 

I present to you, `consolidate.py`. A very simple, dumb script meant to do just that.

Invoke it like so:
```bash
.venv/bin/python consolidate.py amex.csv chase.csv -o consolidated_transactions.csv
```
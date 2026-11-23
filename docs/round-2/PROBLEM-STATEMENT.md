**ROUND 2 PROBLEM STATEMENT**  
**Agentic GraphRAG Hackathon by TigerGraph**

Round 2 asks you to build an agentic GraphRAG system on TigerGraph that reasons across many documents, weighs sources that disagree, and says honestly what cannot be established.

Round 1 showed that every finalist can answer one-field lookups. Round 2 is harder: answers need several documents, some evidence is provisional or out of date, and some questions have no answer in the corpus.

**THE PROBLEM**

Build a system that takes a natural-language question, plans its own steps, queries a TigerGraph graph built from the corpus, and returns a cited answer with a full trace of how it got there.

Your system must:  
\- Answer from the corpus only. If the corpus and the real world disagree, the corpus wins.  
\- Use TigerGraph when answering, not only when loading data.  
\- Work on questions it has never seen. Judges will ask new questions live, so rules tuned to specific questions won't help.  
\- Report its own cost: tokens, latency and every step it took.

**WHAT YOU GET**

Everything is in one shared folder, hackathon-resources-round2. Nothing else will be released later.

\- README.md: the full technical brief, covering the data format, answer format, traces, metrics and rules.  
\- corpus.jsonl: 3,530 documents. Use it in place of your Round 1 corpus.  
\- questions\_public.jsonl: 50 questions with answers, expected status and supporting documents, for building and testing.  
\- questions\_hidden.jsonl: 50 questions without answers. Run your system on them and send us the results.

**THE CHALLENGES**

A successful answer may not be a single name or number. It may need to explain which facts are reliable, which are disputed, what was true at a particular time, and what cannot be established.

1\. Incomplete information: distinguish unknown information from a negative fact.  
2\. Conflicting information: identify disagreements and assess the evidence.  
3\. Temporal changes: distinguish original, revised and current facts.  
4\. Source reliability: differentiate provisional claims from official decisions.  
5\. Combined reasoning: reconcile multiple documents before reaching a conclusion.

```
For example, a question may be covered by several documents that disagree: an early provisional report, a later official decision, and a news post that repeats the early version after the decision. A good answer gives the result the evidence supports, says when it became official, and explains why the other documents differ.
```

**QUESTION STYLES**

Questions come without a type label and in varied wording. The 50 public questions show every style used in the 50 hidden ones.

\- Short answer: How many athletes competed in the men's decathlon at Paris 2024?  
\- Complete list: List every wrestling event at the 2024 Summer Olympics that Japan won.  
\- Count and compare: Which nation won the most rowing golds at the 2024 Summer Olympics, and how many?  
\- Trend across Games: How many nations competed in the men's 80 kg taekwondo at each Summer Olympics, and which edition had the most and the fewest?  
\- Athlete career: What Olympic medals does the corpus record for Teddy Riner?  
\- Why (article text only): Why was the women's triple jump podium at LA 2028 changed after the competition?  
\- Films and politicians: Who succeeded Angus King as governor of Maine, and whom had he succeeded?  
\- Sources that disagree or change: Where was the LA 2028 women's omnium originally planned, and where was it actually held?  
\- Partly answerable: answer what the corpus supports and say clearly what is missing.  
\- Not in the corpus: reply not\_in\_corpus. An invented answer scores 0\.  
**WHAT TO SUBMIT**

Run your system on both question sets, then send all seven items by the deadline:

1\. Repo link: your GitHub repository, with a README describing your architecture: how documents become graph data, which tools the agent has, and how it decides what to do next.  
2\. answers\_public.jsonl: your answers to the 50 public questions.  
3\. answers\_hidden.jsonl: your answers to the 50 hidden questions.  
4\. metrics.json: a summary of both runs.  
5\. A git tag on your repo for the code that produced both answer files.  
6\. Your TigerGraph query log from both runs, with timestamps that match your traces.  
7\. Graph counts: vertex and edge counts by type, after loading corpus.jsonl.

Each line in the two answer files is one question and contains:  
\- qid: the question ID  
\- status: answered, partial or not\_in\_corpus  
\- answer: the complete answer, as text or JSON  
\- explanation: a short account of how the answer was reached  
\- citations: the doc\_ids that support the answer  
\- input\_tokens and output\_tokens: all LLM tokens for this question, across every call  
\- latency\_ms: wall-clock time from question to answer  
\- trace: every step in order, including the tool, whether it queried TigerGraph, the query, the parameters, the rows returned, and the tokens for each LLM call

metrics.json gives the following for each set:  
\- accuracy (public set only, measured by you)  
\- total and average tokens  
\- average, p50 and p95 latency  
\- LLM calls and TigerGraph queries per question  
\- trace steps  
\- run time and cost

We recompute every number from your answer files, so they must match. The exact formats, with examples, are in README.md.

**HOW YOU ARE SCORED**

We score your hidden-set answers against our own answer key, fact by fact, with partial credit. Lists must be complete, and adding wrong items lowers the score.

\- Answer accuracy on the hidden set (scored by us): 40%  
\- Honesty (correct not\_in\_corpus, no invented answers): 10%  
\- Evidence (citations that actually support the answer): 10%  
\- Repeatability (clean setup, locked dependencies, complete traces and logs, and live reproduction in the judging call): 15%  
\- Efficiency (tokens, latency and cost per question, on both sets): 10%  
\- Live judging (architecture and demo): 15%

**RULES**

1\. TigerGraph must be used when answering, not only for loading data.  
2\. One-command build and run, so your results can be reproduced:  
   ./build.sh corpus.jsonl  
   ./run.sh questions\_public.jsonl answers\_public.jsonl  
   ./run.sh questions\_hidden.jsonl answers\_hidden.jsonl  
3\. Locked dependencies (a lock file or exact versions) and a .env.example listing every key you need.  
4\. No question-specific rules: no regexes on question wording, no use of question IDs, and no answers built into the code.  
5\. Live reproduction in the judging call. Be ready to screen-share your system with TigerGraph running and the full corpus loaded. Judges will give you new questions you haven't seen and watch your system answer them. They will also pick a few of your hidden-set questions and check that your system reproduces your submitted answers and traces.

Answers that your system can't reproduce, or that were produced outside your system (by hand, or by pasting the corpus or questions into a general AI assistant), are disqualified. Using AI tools to write your code is fine. The answers must come from your system.

**KEY DATES**

Round 2 opens: 22nd Nov, 2026  
Submission deadline: 29th Nov, 2026 (11:59 PM IST)  
Questions: [https\://discord.gg/J77RBNfMr](https://discord.gg/J77RBNfMr)


# ExplainBot eval suite

Measures each stage of the pipeline separately, so a regression points at one component.

| Suite | Measures | Calls the API? |
|---|---|---|
| `guardrails` | injection block rate, false-positive rate, held-out generalisation | no |
| `retrieval` | BM25 hit@k / MRR with a chunk-size ablation | no |
| `routing` | DecisionAgent accuracy, per-class P/R, stability across repeats | yes |
| `answers` | fact coverage, faithfulness, abstention on unanswerable/off-topic, language match (en/hi/es) | yes (+ LLM judge) |
| `video_plan` | plan validity, label/point grounding, narration length, layout geometry | yes |
| `tts` | STT round-trip WER/CER, speech rate, latency, voice A/B (en/hi/es) | yes |

## Run

```powershell
.\evals\run_evals.ps1                                   # everything (~2-3 min)
.\evals\run_evals.ps1 -Suites guardrails,retrieval      # free suites only
.\evals\run_evals.ps1 -Quick                            # smoke test
.\evals\run_evals.ps1 -Repeats 3                        # mean ± std; use this when comparing two versions
.\evals\run_evals.ps1 -SetBaseline                      # pin this run; later reports show Δ vs it
```

Or directly: `cd backend; .\venv\Scripts\python.exe ..\evals\run.py --suites answers --gate`
(`--gate` exits 1 when a threshold in `thresholds.json` is violated — for CI).

Output: `evals/results/latest.md` (human report) and `latest.json` (raw, incl. per-item failures).

## Method notes

- **Gold data** lives in `evals/data/`: 3 documents (an API-security note, a UPSC Fundamental Rights note, and a
  205-page Pearson supply-chain slide deck), 68 QA items (incl. unanswerable/off-topic and Hindi/Spanish), 40 routing
  queries (8 deliberately ambiguous), 37 guardrail cases (12 held-out), 9 video queries, 10 TTS sentences.
  Evidence strings are validated against the extracted document text at start-up.
- **The SCM deck is local-only** (`evals/data/docs/scm_notes.pdf`, gitignored - it is third-party material). Without it
  the runner skips those items and everything else still runs. It is a realistic, hard source: slide fragments,
  figures, and ~70 pages with no extractable text (scanned images), which the product's pypdf path cannot read.
- **LLM judge** scores fact coverage, faithfulness (claims supported by the retrieved context) and abstention.
  It defaults to the same model as the system under test — set `EVAL_JUDGE_MODEL` to a different model to avoid
  self-preference bias.
- **Noise:** one item = ~3.7 points on the answers suite, and outputs are stochastic. Single runs cannot
  separate small changes from noise; use `-Repeats`.
- **TTS** WER/CER measure intelligibility (via `whisper-1`, override with `EVAL_STT_MODEL`), not naturalness.
  `results/mos_sheet.csv` is a template for human 1–5 naturalness / accent ratings. ElevenLabs is benchmarked only
  when it has quota.
- **Guardrails** `heldout_*` metrics are cases never tuned against; the other guardrail numbers are dev-set and optimistic.

## Findings so far (what the suite changed)

| Finding | Evidence | Action |
|---|---|---|
| Content prompt gave contradictory instructions (answer from general knowledge *and* refuse) | intermittent false refusals, 0-7% run to run | single grounding policy: coverage 0.963 -> 1.000, false abstention 7.4% -> 0%, faithfulness held at 0.996 |
| Regex guard overfits | 100% on dev set, 33% on held-out attacks | dev fixes shipped (multilingual, "override"/"sudo" false positives); LLM guard is the next step |
| OpenAI voices are all weak on Hindi | CER ~0.28 for both `alloy` and `nova`, 0.32-0.44 for `shimmer`/`onyx`; an earlier run showed alloy at 0.11, which did not replicate (5 sentences is too few) | kept `alloy` (slightly lower WER), but treat voice choice as unproven until the MOS sheet / ElevenLabs is benchmarked; English loan words in Devanagari are the worst case |
| BM25 misses on a realistic corpus | hit@4 = 0.91; non-English 0.71; 300-word chunks beat 100/200 | candidates: query translation, hybrid/dense retrieval, top_k |
| Upload limit vs real notes | the SCM deck is 22 MB; `MAX_UPLOAD_BYTES` is 5 MB | product decision, not changed |

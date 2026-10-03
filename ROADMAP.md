# Roadmap

A learning-first roadmap for this project. The system design lives in [infringement-detection-plan.md](infringement-detection-plan.md); this file says what to build next, what each step should teach you, and how to check that it did.

## How we work

Every milestone follows the same loop:

1. **Learn the idea first.** Read the short reading for the milestone and try the warm-up before any project code.
2. **Predict.** Before running anything that produces numbers, write down what you expect. Being wrong is the most useful outcome.
3. **Build.** Claude writes the plumbing and a skeleton (or failing tests); you write the core. The "You write" list in each milestone is yours.
4. **Review.** Ask Claude to check it. Reviews run your code on real data and report what happened, not just what the code looks like.
5. **Explain back.** Add a few lines to `docs/learning-log.md` in your own words: what you built, what surprised you, what you'd do differently. Claude can quiz you on it.
6. **Commit** when the milestone's "done when" holds.

The self-check questions at the end of each milestone are the real exit criteria: if you can answer them without looking, you've learned it.

Time estimates assume 6–8 hours a week. They are guides, not deadlines; if a milestone overruns, use the cuts listed at the end rather than rushing.

## Progress

| # | Milestone | Weeks | Status |
|---|---|---|---|
| 0 | Setup | – | ✅ Done |
| 1 | Evaluation dataset | 1 | 🟡 Video done; photos left |
| 2 | First video matcher and the harness | 2–3 | ⬜ |
| 3 | Photo matching | 4 | ⬜ |
| 4 | Audio fingerprinting | 5 | ⬜ |
| 5 | Similarity search | 6–7 | ⬜ |
| 6 | Scoring and thresholds | 8 | ⬜ |
| 7 | Durable execution engine | 9–13 | ⬜ |
| 8 | Workflows end to end and the API | 14 | ⬜ |
| 9 | AWS deployment | 15–16 | ⬜ |
| 10 | Review UI and evidence | 17 | ⬜ |
| 11 | Load and chaos testing | 18 | ⬜ |
| 12 | Write-up | 19 | ⬜ |

This is five weeks longer than the plan's 14. The extra time goes almost entirely to the engine (milestone 7), which the plan under-budgeted, and to giving photos and audio their own milestones.

---

## 0. Setup ✅

Repo layout under `src/infringement`, local stack (Postgres + pgvector, SeaweedFS, ElasticMQ) in Docker Compose, `just` recipes, Terraform skeleton, GitHub repo.

**What you learned:** src layout and why tests should import the installed package; how boto3 finds endpoints from the environment; what each local stand-in replaces in AWS.

---

## 1. Evaluation dataset (week 1) 🟡

**Why first:** without labelled data, you can't tell whether any algorithm works. Every later number comes from this dataset.

- [x] `eval/clips.csv`: 24 originals and 12 negatives with a train/test split by original
- [x] `eval/clips.py`: cut and verify clips (you wrote `ffmpeg_cmd` and `verify`)
- [x] `eval/attacks.py`: 17 seeded video attacks and the manifest
- [x] Run `just dataset`: 612 variants, all checked for length and streams
- [ ] Spot-check a few variants per attack by eye
- [ ] Photos: a few dozen in `eval/data/raw/photos/`, with originals, near-duplicate negatives and a split
- [ ] Photo attacks: the video ones that apply, plus rotation and collage

**Concepts:** ffmpeg filter graphs; ground truth and labels; train/test splits and why they go by original; hard negatives; deterministic randomness (one seeded generator per clip and attack).

**Self-check**
1. Why is `bbb_n2` a better negative than a random YouTube video?
2. If a mirror variant of `bbb_03` were in train and its crop variant in test, what would go wrong?
3. Why does each (clip, attack) pair get its own random generator instead of one shared one?

---

## 2. First video matcher and the harness (weeks 2–3)

**Goal:** a plain pHash matcher and the harness that scores it. The first numbers will be modest; the point is a working baseline you can improve against.

**Warm-up (no project code):** load one frame with OpenCV, convert to grayscale, shrink to 32×32, run `scipy.fft.dctn` on it and look at the coefficients. Then do the same for the mirrored and the cropped versions of that frame. Which coefficients change?

**You write**
- `matcher/phash.py`: the 64-bit DCT pHash, from scratch with numpy and scipy. Afterwards, compare your output with the `imagehash` library as a reference.
- Frame sampling: decode at 2 fps into numpy (ffmpeg writing raw pixels to a pipe, or PyAV; you'll pick one and say why).
- `compare_video`: offset voting.
- `eval/harness.py`: run every train variant, then print recall per attack and the false-positive rate as a markdown table.

**Claude provides:** skeletons and tests for the parts with tricky edge cases (hash bit order, timestamp alignment).

**Experiments**
- Before the first run, predict recall for each attack. Afterwards, compare.
- Plot two histograms of Hamming distance: frames of the same scene vs frames of different clips. Where do they overlap? That overlap is your whole problem.
- Measure seconds of CPU per minute of video. This number drives the Lambda cost estimates.

**Reading:** Neal Krawetz, "Looks Like It" and "Kind of Like That" (Hacker Factor).

**Done when:** the table exists, and you can explain every row with low recall.

**Self-check**
1. Why does pHash survive re-encoding but not cropping?
2. Why does offset voting reject coincidental matches?
3. Why should near-black frames be dropped before matching?

---

## 3. Photo matching (week 4)

**Goal:** a pHash fast path plus a precise verification step for photos.

**Warm-up:** run OpenCV's "Feature Matching + Homography to find Objects" tutorial on two of your own photos.

**You write:** ORB keypoints and descriptors, the ratio test, RANSAC homography, and an inlier-count score. Then add photo rows to the harness.

**Experiments:** draw the matches before and after RANSAC for a cropped photo, and look at what RANSAC throws away.

**Done when:** photo recall per attack is in the table, and crops of 20% or less are mostly caught via ORB.

**Self-check**
1. What does the ratio test reject, and why does it work?
2. What does RANSAC assume about the inliers?
3. Why is ORB too expensive for the first stage but fine for the second?

---

## 4. Audio fingerprinting (week 5)

**Goal:** a second signal that survives the visual tricks pHash can't.

**Reading:** Lukáš Lalinský, "How does Chromaprint work?"

**You write:** `fingerprint_audio` via `fpcalc -raw`, bit-error comparison with offset voting, and a combined video and audio score.

**Experiments:** predict which attacks audio rescues (mirror? crops?) and which it can't (`strip_audio`, `replace_audio`). Rerun the harness and check.

**Done when:** mirrored and cropped variants with intact audio are now caught, and the audio-replaced ones show what frames alone achieve.

**Self-check**
1. Why are the audio-replacing attacks essential for honest crop numbers?
2. What should the score do when audio and video disagree on the offset?

---

## 5. Similarity search (weeks 6–7)

**Goal:** find candidate originals fast, and learn the trade-offs between search methods by measuring them.

**You write**
- Brute force over a numpy array of hashes: the baseline, exact by definition.
- Multi-index hashing: chunked exact lookups and the pigeonhole guarantee.
- pgvector HNSW with `bit_hamming_ops`.
- A benchmark at 100k and 1M synthetic hashes: p50/p95 latency, recall against brute force, memory, build time.

**Experiments:** before benchmarking, predict the winner at your scale and write down why. Then vary the search radius and watch what happens to multi-index hashing.

**Reading:** Norouzi, Punjani and Fleet (2012), "Fast Search in Hamming Space with Multi-Index Hashing", §1–3; the pgvector README on binary vectors and HNSW.

**Done when:** a benchmark table and a short written decision with reasons. Expect brute force to be hard to beat at this scale; if it wins, that's a good result to write up, and the plan's pgvector choice changes.

**Self-check**
1. Why can't a B-tree answer "nearest in Hamming distance" directly?
2. Why does multi-index hashing get slower as the radius grows?
3. Why is `LIMIT 10` a problem for video frames specifically?

---

## 6. Scoring and thresholds (week 8)

**Goal:** turn scores into the flag / review / clear decision, chosen from data.

**You write:** a precision-recall curve on the **train** split; `high` and `low` thresholds; the expected share of scans landing in review. Then one run on the **test** split for the reported numbers.

**Concepts:** precision vs recall; why thresholds come from train only; the rule of three (zero false positives in *n* negatives only shows the rate is below about 3/*n* with 95% confidence).

**Done when:** thresholds are in config, with a one-page justification including the dataset sizes behind them.

**Self-check**
1. With your number of test negatives, what false-positive rate can you actually claim?
2. What does widening the review band cost, and who pays it?

---

## 7. Durable execution engine (weeks 9–13)

**Goal:** the heart of the project: workflows that survive any process dying at any moment. This is the hardest and most valuable milestone, so it gets five weeks.

**How we'll work here:** Claude writes failing tests first for each step; you make them pass. The tests encode the hard cases (a crash between two writes, a late duplicate result), so you learn the failure modes by fixing them.

**Steps**
1. **Replay core** (pure, no I/O): history in, commands out. Nondeterminism detection.
2. **Storage and leases:** `workflows`, `history` with unique `(workflow_id, seq)`, `tasks`, `timers`; workers with leases.
3. **Activities:** local vs remote routing, the transactional outbox, the result consumer with attempt fencing, heartbeats, and an explicit retry owner.
4. **Timers and signals**, including a signal that arrives before the workflow waits for it, and one that arrives after the timeout.
5. **Workflow versioning:** changing workflow code while scans wait days for review.
6. **Chaos script:** kill random workers every few seconds; check exactly one verdict and at most one evidence row per scan.

**Warm-up:** write a 30-line toy: a function that replays a list of recorded results instead of calling real functions. Feel why the code must be deterministic.

**Reading:** Martin Kleppmann, "How to do distributed locking" (fencing tokens); Temporal's docs on event history and determinism; AWS Prescriptive Guidance, "Transactional outbox pattern".

**Self-check**
1. Why must workflow code never call `datetime.now()` or `random()` directly?
2. A worker pauses for a minute and wakes after its lease expired. What stops its late commit?
3. Why can the outbox send a task twice but never lose one?
4. Who retries a failed activity, SQS or the engine, and why must exactly one of them own it?

---

## 8. Workflows end to end and the API (week 14)

**Goal:** `ingest_original` and `scan_suspect` running on the engine against the local stack, driven by the FastAPI endpoints in plan §6.5.

**You write:** both workflows, the activities they call, and the API. Add the scan status and the `failed` verdict that the plan's data model is missing.

**Done when:** a scan submitted through the API reaches a verdict locally, and the chaos script still passes.

---

## 9. AWS deployment (weeks 15–16)

**Goal:** the same system on AWS, from Terraform only, then torn down cleanly.

**Before you start:** create the AWS account only now, since the Free Plan's six-month clock starts at signup. Go through the day-one checklist in plan §13 (MFA, budgets, one region, Lambda concurrency quota).

**You write:** Terraform for S3, SQS with a DLQ, ECR, Lambda from an arm64 container image, EC2 with its role and security group, and Caddy for TLS. Switching from SeaweedFS and ElasticMQ is configuration only.

**Concepts:** IAM least privilege; why this design needs no NAT gateway; Lambda memory and CPU coupling and cold starts; SQS event source mapping settings.

**Done when:** `terraform apply` from a clean account works, `terraform destroy` removes everything, and a test budget alert has fired.

---

## 10. Review UI and evidence (week 17)

**Goal:** a human in the loop: an HTMX review page showing matched frames side by side, with approve or reject sent to the workflow as a signal.

**Done when:** you can work through the review queue end to end, and an abandoned review resolves itself when its timer fires (shortened to minutes in a test config).

---

## 11. Load and chaos testing (week 18)

**Goal:** find the real bottleneck and prove the invariants under stress.

**You write:** Locust scenarios (a steady rate, then a 5,000-scan burst) and chaos runs (kill workers, stop the result consumer for 10 minutes, restart Postgres mid-burst).

**Experiments:** before the burst, predict the bottleneck using Little's law. Check afterwards.

**Done when:** a short report with graphs: throughput, p95 latency, the bottleneck, and invariant checks.

---

## 12. Write-up (week 19)

README with diagrams, evaluation tables, the benchmark, the load-test report, money actually spent, known limitations, and the worst bug you hit. Then tear down or upgrade the AWS account.

**Done when:** someone else could clone the repo, run `just dataset && just eval`, and reproduce your numbers.

---

## If time runs short

Cut in this order; none of these breaks the project:

1. The review UI (a CLI that sends signals works).
2. Multi-index hashing (keep brute force and pgvector).
3. Audio fingerprinting.
4. Picture-in-picture and speed attacks (they're "measure only" anyway).

Don't cut the engine's tests or the chaos script: they're where most of the learning is.

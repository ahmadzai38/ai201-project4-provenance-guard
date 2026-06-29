# Provenance Guard

Provenance Guard is a Flask backend system for creative writing platforms. It accepts submitted text, analyzes whether the text appears more likely to be AI-generated or human-written, returns an attribution result with a confidence score, displays a transparency label, supports creator appeals, rate-limits submissions, and records decisions in a structured audit log.

The goal is not perfect AI detection. Perfect AI detection is not possible. The goal is to combine multiple signals, communicate uncertainty honestly, avoid overconfident false positives, and give creators a path to contest a decision.

---

## Features Implemented

* `POST /submit` endpoint for text attribution analysis
* Two-signal detection pipeline:

  * Groq LLM classification signal
  * Python stylometric heuristic signal
* Confidence scoring with an uncertainty range
* Three transparency label variants:

  * likely AI-generated
  * likely human-written
  * uncertain
* `POST /appeal` endpoint for creator appeals
* Structured audit logging in JSONL format
* `GET /log` endpoint for viewing recent audit entries
* Flask-Limiter rate limiting on `/submit`

---

## Tech Stack

* Python
* Flask
* Flask-Limiter
* Groq API using `llama-3.3-70b-versatile`
* python-dotenv
* Structured JSONL audit log

---

## Setup Instructions

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_key_here
```

Run the app:

```powershell
python app.py
```

The API runs locally at:

```text
http://localhost:5000
```

---

## API Endpoints

### GET /

Health check endpoint.

Example response:

```json
{
  "message": "Provenance Guard API is running.",
  "endpoints": {
    "submit": "POST /submit",
    "appeal": "POST /appeal",
    "log": "GET /log"
  }
}
```

---

### POST /submit

Accepts text content and returns an attribution result.

Example request:

```powershell
$body = @{
  text = "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably won't go back unless someone drags me there"
  creator_id = "test-user-2"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:5000/submit" -Method POST -ContentType "application/json" -Body $body
```

Example response:

```json
{
  "ai_likelihood": 0.104,
  "attribution": "likely_human",
  "confidence": 0.896,
  "content_id": "314bfe13-8fb8-4a44-ae5d-853a6e70b783",
  "creator_id": "test-user-2",
  "label": "Provenance Guard found strong signals that this content appears to be human-written. This label is based on automated analysis and is not a guarantee of authorship.",
  "signals": {
    "llm_reasoning": "informal language and personal opinion indicate human-written",
    "llm_score": 0.0,
    "stylometric_score": 0.297
  },
  "status": "classified"
}
```

---

### POST /appeal

Allows a creator to contest a classification.

Example request:

```powershell
$appealBody = @{
  content_id = "607a57d1-b128-4975-be78-9a21a9db0345"
  creator_reasoning = "I wrote this myself from personal experience. I am a non-native English speaker, so my writing may appear more formal than typical."
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:5000/appeal" -Method POST -ContentType "application/json" -Body $appealBody
```

Example response:

```json
{
  "content_id": "607a57d1-b128-4975-be78-9a21a9db0345",
  "message": "Appeal received. This content is now under review.",
  "status": "under_review"
}
```

---

### GET /log

Returns recent structured audit-log entries.

Example request:

```powershell
Invoke-RestMethod -Uri "http://localhost:5000/log" | ConvertTo-Json -Depth 10
```

---

## Architecture Overview

A submitted piece of text moves through the system like this:

```text
POST /submit
   |
   v
Validate request body
(text + creator_id)
   |
   v
Create unique content_id
   |
   v
Signal 1: LLM classification
(Groq evaluates whether the text reads AI-generated or human-written)
   |
   v
Signal 2: Stylometric heuristics
(Python measures structural writing features)
   |
   v
Confidence scoring
(combine both signal scores)
   |
   v
Attribution decision
(likely_ai, likely_human, or uncertain)
   |
   v
Transparency label
(generate reader-facing label text)
   |
   v
Audit log
(write structured JSONL decision entry)
   |
   v
JSON response
```

The appeal flow is:

```text
POST /appeal
   |
   v
Validate content_id and creator_reasoning
   |
   v
Find original content record
   |
   v
Change status to under_review
   |
   v
Write appeal entry to audit log
   |
   v
Return confirmation response
```

This design keeps the classification pipeline and the appeal workflow connected through the shared `content_id`.

---

## Detection Signals

The system uses two distinct detection signals. This is important because single-signal AI detection is too brittle. One signal may miss what the other signal catches.

---

### Signal 1: Groq LLM Classification

The first signal uses Groq with `llama-3.3-70b-versatile`.

The LLM receives the submitted text and returns a structured JSON result:

```json
{
  "score": 0.0,
  "reasoning": "brief explanation"
}
```

The score means:

```text
0.0 = very likely human-written
0.5 = unclear or mixed
1.0 = very likely AI-generated
```

#### Why I chose this signal

The LLM can evaluate overall tone, coherence, generic phrasing, formulaic structure, and whether a text sounds like generated writing. This is useful because some writing patterns are hard to capture with simple statistics.

#### What this signal misses

The LLM can be wrong. A human writer may sound formal, polished, or structured, especially in academic or professional writing. A non-native English speaker may also write in a style that the LLM could misread as AI-like. Also, AI-generated text can be edited to sound more human. Because of this, the LLM signal is not used alone.

---

### Signal 2: Stylometric Heuristics

The second signal uses pure Python heuristics.

It measures:

* sentence length variance
* type-token ratio, which estimates vocabulary diversity
* punctuation density
* average word length

The stylometric function returns a score from `0.0` to `1.0`.

```text
0.0 = more human-like
0.5 = unclear or mixed
1.0 = more AI-like
```

#### Why I chose this signal

AI-generated writing often has smoother and more consistent structure. Human writing often has more uneven sentence length, casual punctuation, messy phrasing, and irregular vocabulary choices. Stylometric heuristics give the system a structural signal that is different from the LLM's semantic judgment.

#### What this signal misses

Stylometric heuristics can be misleading. Poems, short text, formal human essays, or writing by non-native English speakers may look statistically unusual. A short paragraph may not have enough text for stable measurements. That is why this signal is combined with the LLM signal instead of being used alone.

---

## Confidence Scoring

The system combines the two signal scores into one `ai_likelihood` score.

Formula:

```text
ai_likelihood = (0.65 * llm_score) + (0.35 * stylometric_score)
```

I weighted the LLM signal more heavily because it captures broader style and meaning. The stylometric signal still matters because it gives an independent structural measurement.

The system also returns a `confidence` score:

```text
confidence = max(ai_likelihood, 1 - ai_likelihood)
```

This means a score near `0.5` is low confidence, because the system is close to the uncertain middle. A score near `0.0` or `1.0` means higher confidence.

---

## Attribution Thresholds

The system maps `ai_likelihood` into three attribution categories:

```text
ai_likelihood >= 0.75:
    attribution = likely_ai

ai_likelihood <= 0.25:
    attribution = likely_human

0.26 <= ai_likelihood <= 0.74:
    attribution = uncertain
```

I intentionally made the AI threshold conservative. A false positive, where a real human writer is labeled as AI-generated, can unfairly harm a creator. Because of that, the system only uses `likely_ai` when the signal is strong. Middle cases are labeled `uncertain`.

---

## Confidence Scoring Examples

### Example 1: High-confidence human-written result

Input:

```text
ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably won't go back unless someone drags me there
```

Output:

```json
{
  "ai_likelihood": 0.104,
  "attribution": "likely_human",
  "confidence": 0.896,
  "llm_score": 0.0,
  "stylometric_score": 0.297
}
```

This result makes sense because the text is casual, personal, uneven, and informal.

---

### Example 2: High-confidence AI-generated result

Input:

```text
As an AI language model, I do not have personal experiences or emotions, but I can provide a general response. It is important to note that artificial intelligence can assist users by generating structured, coherent, and informative text based on patterns learned from training data.
```

Output:

```json
{
  "ai_likelihood": 0.799,
  "attribution": "likely_ai",
  "confidence": 0.799,
  "llm_score": 1.0,
  "stylometric_score": 0.425
}
```

This result makes sense because the text explicitly uses AI-style wording and says, “As an AI language model.”

---

### Example 3: Uncertain result

Input:

```text
Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment.
```

Output:

```json
{
  "ai_likelihood": 0.448,
  "attribution": "uncertain",
  "confidence": 0.552,
  "llm_score": 0.5,
  "stylometric_score": 0.35
}
```

This result is useful because the system does not force a binary answer. The writing sounds polished and generic, but not enough for a confident AI label.

---

## Transparency Labels

The system returns one of three exact transparency labels.

### High-confidence AI label

```text
"Provenance Guard found strong signals that this content may have been AI-generated. This label is based on automated analysis and may be appealed by the creator."
```

### High-confidence human label

```text
"Provenance Guard found strong signals that this content appears to be human-written. This label is based on automated analysis and is not a guarantee of authorship."
```

### Uncertain label

```text
"Provenance Guard could not confidently determine whether this content was human-written or AI-generated. Readers should treat the authorship as uncertain, and the creator may appeal if they believe this label is inaccurate."
```

The labels are written in plain English. They avoid claiming certainty because the system is automated and imperfect.

---

## Appeals Workflow

Creators can appeal a classification using `POST /appeal`.

The appeal request must include:

* `content_id`
* `creator_reasoning`

When an appeal is submitted, the system:

1. Finds the original content record.
2. Updates its status to `under_review`.
3. Stores the creator's reasoning.
4. Writes a structured appeal event to the audit log.
5. Returns a confirmation response.

Example appeal log entry:

```json
{
  "ai_likelihood": 0.448,
  "confidence": 0.552,
  "content_id": "607a57d1-b128-4975-be78-9a21a9db0345",
  "creator_id": "test-user-1",
  "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker, so my writing may appear more formal than typical.",
  "event_type": "appeal",
  "original_attribution": "uncertain",
  "status": "under_review",
  "timestamp": "2026-06-26T00:40:34.690818-04:00"
}
```

A real production version would show this information to a human reviewer. Automated re-classification is not required for this project.

---

## Rate Limiting

The `/submit` endpoint uses Flask-Limiter.

Chosen limits:

```text
10 submissions per minute
100 submissions per day
```

Reasoning:

A normal creator on a writing platform should not need to submit dozens of pieces every minute. Ten submissions per minute is enough for testing and normal use, but it blocks simple spam or script flooding. The daily limit of 100 is high enough for a serious tester or creator, while still limiting abuse.

Rate limit test output:

```text
200
200
200
200
200
200
200
200
200
200
429
429
```

The `429` responses show that the rate limit is working.

---

## Audit Log

Every classification decision is written to a structured JSONL audit log.

The log records:

* event type
* content ID
* creator ID
* timestamp
* attribution result
* confidence score
* AI-likelihood score
* LLM score
* stylometric score
* signals used
* status
* appeal reasoning when applicable

Example audit-log entries from testing:

```json
{
  "ai_likelihood": 0.104,
  "attribution": "likely_human",
  "confidence": 0.896,
  "content_id": "314bfe13-8fb8-4a44-ae5d-853a6e70b783",
  "creator_id": "test-user-2",
  "event_type": "classification",
  "llm_score": 0.0,
  "signals_used": ["llm", "stylometric"],
  "status": "classified",
  "stylometric_score": 0.297,
  "timestamp": "2026-06-26T00:42:40.595122-04:00"
}
```

```json
{
  "ai_likelihood": 0.799,
  "attribution": "likely_ai",
  "confidence": 0.799,
  "content_id": "eea39cf8-9bea-4b6f-b3d7-0b3a808c0df2",
  "creator_id": "test-user-5",
  "event_type": "classification",
  "llm_score": 1.0,
  "signals_used": ["llm", "stylometric"],
  "status": "classified",
  "stylometric_score": 0.425,
  "timestamp": "2026-06-26T00:48:10.840074-04:00"
}
```

```json
{
  "ai_likelihood": 0.448,
  "confidence": 0.552,
  "content_id": "607a57d1-b128-4975-be78-9a21a9db0345",
  "creator_id": "test-user-1",
  "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker, so my writing may appear more formal than typical.",
  "event_type": "appeal",
  "original_attribution": "uncertain",
  "status": "under_review",
  "timestamp": "2026-06-26T00:40:34.690818-04:00"
}
```

---

## Known Limitations

### 1. Formal human writing may be misclassified

A human writer who writes in a polished academic or professional style may receive a higher AI-likelihood score. This can happen because both the LLM signal and the stylometric signal may associate formal structure with AI-generated writing.

### 2. Short text is hard to classify

Very short submissions do not provide enough evidence for stable stylometric metrics. A short poem, caption, or two-sentence post may be labeled uncertain because there is not enough text to judge.

### 3. Poetry and experimental writing can confuse the system

Poems often repeat words, use unusual punctuation, or break normal sentence structure. The stylometric signal may treat those creative choices as suspicious even when they are intentionally human.

### 4. Human-edited AI text is difficult

If AI-generated text is heavily edited by a human, both signals may become less reliable. The system may return uncertain or likely human even though AI was involved.

---

## Spec Reflection

One way the spec helped was by forcing me to decide the confidence thresholds before coding. Because I defined `likely_ai`, `likely_human`, and `uncertain` in `planning.md`, the implementation had a clear scoring target instead of just returning random labels.

One way the implementation diverged from the original plan is that the LLM signal turned out to be more conservative than expected. Some formal AI-style examples were classified as human because the prompt warned the model not to over-label polished writing as AI. I kept this behavior because the project specifically emphasizes that false positives against human creators are harmful. To still demonstrate the full system, I tested an obvious AI-style text that included “As an AI language model,” which correctly produced a likely-AI result.

---

## AI Usage

I used AI assistance as a coding and planning helper, but I reviewed and tested the output myself.

### Instance 1: Planning document

I used AI to help draft the initial `planning.md` structure. I directed it to include the architecture diagram, detection signals, confidence scoring thresholds, transparency labels, appeals workflow, edge cases, and AI tool plan. I revised the plan to make the thresholds and false-positive handling clearer.

### Instance 2: Flask backend implementation

I used AI to generate the first version of the Flask backend, including `POST /submit`, `POST /appeal`, `GET /log`, Groq classification, stylometric scoring, label generation, rate limiting, and JSONL audit logging. I tested each endpoint manually in PowerShell and verified the outputs.

### Instance 3: Debugging PowerShell requests

I used AI assistance to fix my PowerShell test commands when the first curl-style JSON request failed. The issue was not the Flask endpoint; it was the JSON body formatting in PowerShell. I switched to creating a PowerShell hashtable and converting it with `ConvertTo-Json`.

---

## Portfolio Walkthrough Notes

For the walkthrough video, I will show:

1. The Flask app running with `python app.py`
2. A `/submit` request that returns likely human
3. A `/submit` request that returns likely AI
4. A `/submit` request that returns uncertain
5. A `/appeal` request that changes status to `under_review`
6. A `/log` request showing structured audit entries
7. The rate-limit test showing `429` responses

The walkthrough will briefly explain why the system uses two signals and why uncertain labels are important.
## Walkthrough Video

Demo video: https://drive.google.com/file/d/1p9B4buutDVtOCUNKzFgz7X_AhwKA3SAQ/view?usp=sharing
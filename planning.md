# Provenance Guard Planning

## Project Summary

Provenance Guard is a backend system for a creative writing platform. The system accepts text-based creative work, analyzes whether it appears more likely to be AI-generated or human-written, gives a confidence score, shows a transparency label, and allows creators to appeal a decision.

The goal is not to perfectly detect AI writing. Perfect AI detection is not possible. The goal is to combine multiple signals, communicate uncertainty honestly, keep an audit log, and give creators a fair appeal path if they think their work was misclassified.

---

## Architecture

### Submission Flow

```text
POST /submit
   |
   v
Validate request body
(text + creator_id)
   |
   v
Signal 1: LLM classification
(Groq judges whether the text reads AI-generated or human-written)
   |
   v
Signal 2: Stylometric heuristics
(Python measures sentence variation, vocabulary diversity, punctuation, etc.)
   |
   v
Confidence scoring
(combine both signals into one AI-likelihood score)
   |
   v
Attribution decision
(likely_ai, likely_human, uncertain)
   |
   v
Transparency label generation
(plain-English label shown to readers)
   |
   v
Audit log
(store content_id, creator_id, scores, label, status)
   |
   v
JSON response returned to user
```

### Appeal Flow

```text
POST /appeal
   |
   v
Validate content_id and creator_reasoning
   |
   v
Find original classification
   |
   v
Update status to under_review
   |
   v
Write appeal entry to audit log
   |
   v
Return confirmation response
```

### Architecture Narrative

When a creator submits text, the API first validates the input and creates a unique `content_id`. The text is sent through two different detection signals: an LLM-based classifier and a stylometric heuristic analyzer. The system combines both scores into one AI-likelihood score, maps that score to an attribution result, generates a plain-English transparency label, writes the decision to the audit log, and returns the result.

If a creator disagrees with the classification, they can submit an appeal using the `content_id`. The system records the creator's reasoning, changes the content status to `under_review`, logs the appeal, and returns a confirmation.

---

## API Surface

### POST /submit

Accepts a piece of text for attribution analysis.

Request body:

```json
{
  "text": "The submitted poem, story, blog post, or excerpt goes here.",
  "creator_id": "creator-123"
}
```

Response body:

```json
{
  "content_id": "unique-content-id",
  "creator_id": "creator-123",
  "attribution": "likely_ai | likely_human | uncertain",
  "confidence": 0.87,
  "ai_likelihood": 0.87,
  "label": "Transparency label text shown to readers.",
  "signals": {
    "llm_score": 0.91,
    "stylometric_score": 0.79
  },
  "status": "classified"
}
```

### POST /appeal

Allows a creator to contest a classification.

Request body:

```json
{
  "content_id": "unique-content-id",
  "creator_reasoning": "I wrote this myself from personal experience."
}
```

Response body:

```json
{
  "content_id": "unique-content-id",
  "status": "under_review",
  "message": "Appeal received. This content is now under review."
}
```

### GET /log

Returns recent structured audit-log entries.

Response body:

```json
{
  "entries": [
    {
      "event_type": "classification",
      "content_id": "unique-content-id",
      "creator_id": "creator-123",
      "timestamp": "2026-06-26T12:00:00Z",
      "attribution": "likely_ai",
      "confidence": 0.87,
      "ai_likelihood": 0.87,
      "llm_score": 0.91,
      "stylometric_score": 0.79,
      "status": "classified"
    }
  ]
}
```

---

## Detection Signals

The system will use two distinct detection signals.

---

### Signal 1: LLM-Based Classification

**What it measures:**

This signal uses Groq with `llama-3.3-70b-versatile` to judge whether the submitted text reads more like AI-generated writing or human-written writing.

The LLM will be asked to return a structured result with:

```json
{
  "score": 0.0,
  "reasoning": "brief explanation"
}
```

The score means:

* `0.0` = very likely human-written
* `0.5` = unclear or mixed
* `1.0` = very likely AI-generated

**Why I chose it:**

An LLM can look at overall style, tone, coherence, repetition, generic phrasing, and whether the text sounds overly polished or formulaic. This captures patterns that are hard to measure with simple Python statistics.

**What it misses:**

The LLM can be wrong. Some human writers write formally or cleanly, especially for school or professional writing. Some AI-generated text can be edited to sound more human. The LLM may also over-trust surface style instead of true authorship.

---

### Signal 2: Stylometric Heuristics

**What it measures:**

This signal uses pure Python to measure structural properties of the text, including:

1. Sentence length variation
2. Vocabulary diversity using type-token ratio
3. Punctuation density
4. Average word length

The function will return one score:

```json
{
  "score": 0.0,
  "metrics": {
    "sentence_length_variance": 0.0,
    "type_token_ratio": 0.0,
    "punctuation_density": 0.0,
    "average_word_length": 0.0
  }
}
```

The score means:

* `0.0` = more human-like
* `0.5` = unclear or mixed
* `1.0` = more AI-like

**Why I chose it:**

AI-generated writing often has smoother sentence patterns, more consistent structure, and less messy variation. Human writing often has more irregular sentence lengths, casual punctuation, and more uneven vocabulary choices.

**What it misses:**

Stylometric heuristics are not reliable by themselves. A poem, a short simple post, a non-native English speaker's writing, or a carefully edited human essay may look “AI-like” according to simple statistics. This is why this signal should not make the final decision alone.

---

## Confidence Scoring and Uncertainty

The system will combine the two signal scores into one `ai_likelihood` score.

Formula:

```text
ai_likelihood = (0.65 * llm_score) + (0.35 * stylometric_score)
```

I am weighting the LLM signal more heavily because it captures overall meaning and style better than simple statistics. I am still including the stylometric score because it gives an independent structural signal.

The system will also return a `confidence` score.

```text
confidence = max(ai_likelihood, 1 - ai_likelihood)
```

This means:

* If `ai_likelihood` is `0.95`, the system is very confident the text is AI-generated.
* If `ai_likelihood` is `0.05`, the system is very confident the text is human-written.
* If `ai_likelihood` is `0.51`, the system is not confident because the score is close to the middle.

### Attribution Thresholds

```text
ai_likelihood >= 0.75:
    attribution = likely_ai
    label = high-confidence AI label

ai_likelihood <= 0.25:
    attribution = likely_human
    label = high-confidence human label

0.26 <= ai_likelihood <= 0.74:
    attribution = uncertain
    label = uncertain label
```

### False Positive Handling

A false positive means the system labels a human writer's work as AI-generated. This is worse than a false negative on a creative platform because it can unfairly damage the creator's reputation.

To reduce false positives, the system does not label something as likely AI unless the AI-likelihood score is at least `0.75`. Middle scores are labeled as uncertain instead of making a harsh claim.

---

## Transparency Label Design

The label must be plain English and understandable to non-technical readers.

### High-Confidence AI Label

Exact text:

> "Provenance Guard found strong signals that this content may have been AI-generated. This label is based on automated analysis and may be appealed by the creator."

### High-Confidence Human Label

Exact text:

> "Provenance Guard found strong signals that this content appears to be human-written. This label is based on automated analysis and is not a guarantee of authorship."

### Uncertain Label

Exact text:

> "Provenance Guard could not confidently determine whether this content was human-written or AI-generated. Readers should treat the authorship as uncertain, and the creator may appeal if they believe this label is inaccurate."

---

## Appeals Workflow

### Who can submit an appeal?

A creator can submit an appeal for content they submitted.

### What information do they provide?

The appeal request must include:

* `content_id`
* `creator_reasoning`

Example:

```json
{
  "content_id": "abc-123",
  "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker, so my writing may look formal."
}
```

### What happens when an appeal is received?

When an appeal is submitted, the system will:

1. Look up the original `content_id`.
2. Change the content status from `classified` to `under_review`.
3. Save the creator's reasoning.
4. Write a new appeal event to the audit log.
5. Return a confirmation response.

### What would a human reviewer see?

A human reviewer would see:

* content ID
* creator ID
* original attribution result
* confidence score
* LLM score
* stylometric score
* transparency label
* creator's appeal reasoning
* current status: `under_review`

Automated re-classification is not required for this project.

---

## Audit Log Design

The audit log will be structured JSON stored in a local file.

The log will include classification events and appeal events.

### Classification Log Entry

```json
{
  "event_type": "classification",
  "content_id": "abc-123",
  "creator_id": "creator-1",
  "timestamp": "2026-06-26T12:00:00Z",
  "attribution": "likely_ai",
  "confidence": 0.87,
  "ai_likelihood": 0.87,
  "llm_score": 0.91,
  "stylometric_score": 0.79,
  "signals_used": ["llm", "stylometric"],
  "status": "classified"
}
```

### Appeal Log Entry

```json
{
  "event_type": "appeal",
  "content_id": "abc-123",
  "timestamp": "2026-06-26T12:05:00Z",
  "creator_reasoning": "I wrote this myself from personal experience.",
  "status": "under_review"
}
```

---

## Rate Limiting Plan

The `/submit` endpoint will use Flask-Limiter.

Chosen limits:

```text
10 submissions per minute
100 submissions per day
```

Reasoning:

A normal creator on a writing platform would not submit dozens of pieces every minute. Ten submissions per minute is enough for normal testing and normal user behavior, but it blocks scripts from flooding the system. The daily limit of 100 allows a serious creator or tester to use the system many times in one day while still preventing abuse.

The `/appeal` endpoint does not need the same strict limit for this project, but in a real production system it should also be rate-limited.

---

## Anticipated Edge Cases

### Edge Case 1: Non-native English writing

A non-native English speaker may write in a formal or slightly unusual style. The LLM or stylometric signal might incorrectly treat that as AI-like. This is why the system includes an uncertain range and an appeal workflow.

### Edge Case 2: Poetry or highly repetitive creative writing

A poem may repeat phrases on purpose. The stylometric signal might mistake repetition or simple vocabulary for AI-generated text. This is a limitation because creative writing does not always follow normal paragraph patterns.

### Edge Case 3: Very short text

A very short submission may not contain enough evidence for either signal. For example, a two-sentence poem or short caption may produce unstable scores. The system should be more likely to return uncertain for very short inputs.

### Edge Case 4: Human-edited AI text

If someone generates AI text and heavily edits it, both signals may become less reliable. The system may return human or uncertain even though AI was involved.

---

## Testing Plan

I will test the system with at least four inputs.

### Test 1: Clearly AI-like text

Expected result:

```text
ai_likelihood: high
attribution: likely_ai
label: high-confidence AI label
```

### Test 2: Clearly human-like casual text

Expected result:

```text
ai_likelihood: low
attribution: likely_human
label: high-confidence human label
```

### Test 3: Formal human writing

Expected result:

```text
ai_likelihood: middle range
attribution: uncertain
label: uncertain label
```

### Test 4: Lightly edited AI-style writing

Expected result:

```text
ai_likelihood: middle or high-middle
attribution: uncertain or likely_ai
label: uncertain or high-confidence AI label
```

I will inspect both signal scores separately when a result does not match my intuition.

---

## AI Tool Plan

### M3: Submission Endpoint + First Signal

I will provide the AI tool with:

* Architecture section
* API Surface section
* Signal 1: LLM-Based Classification section

I will ask it to generate:

* Flask app skeleton
* POST `/submit` route
* Groq-based LLM classification function
* simple audit-log helper
* GET `/log` route

I will verify the output by:

* running the Flask app
* sending a test POST request to `/submit`
* checking that the response includes `content_id`, `attribution`, `confidence`, and `label`
* checking that GET `/log` returns structured entries

---

### M4: Second Signal + Confidence Scoring

I will provide the AI tool with:

* Detection Signals section
* Confidence Scoring and Uncertainty section
* Architecture section

I will ask it to generate:

* stylometric heuristic function
* confidence scoring function
* attribution threshold logic
* updated `/submit` route using both signals

I will verify the output by:

* testing at least four different text samples
* checking that clearly AI-like and clearly human-like texts produce noticeably different scores
* printing both signal scores separately
* checking that the audit log records both signal scores and the combined score

---

### M5: Production Layer

I will provide the AI tool with:

* Transparency Label Design section
* Appeals Workflow section
* Rate Limiting Plan section
* Audit Log Design section
* Architecture section

I will ask it to generate:

* label generation function
* POST `/appeal` endpoint
* status update logic
* Flask-Limiter setup
* complete audit-log entries

I will verify the output by:

* testing that all three label variants are reachable
* submitting an appeal using a real `content_id`
* checking that the status changes to `under_review`
* checking that GET `/log` shows at least three structured entries
* testing the rate limit and confirming that extra requests return HTTP 429

---

## Stretch Features

I will focus on the required features first. If I have extra time, I may add an analytics dashboard that shows:

* number of submissions
* number of likely AI / likely human / uncertain results
* number of appeals
* appeal rate

I will update this planning document before starting any stretch feature.

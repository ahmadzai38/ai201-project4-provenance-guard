import json
import os
import re
import string
import uuid
from datetime import datetime, timezone
from statistics import variance

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from groq import Groq


load_dotenv()

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "audit.jsonl")

# Simple in-memory storage for this class project.
# The audit log is still written to file.
CONTENT_STORE = {}


HIGH_CONFIDENCE_AI_LABEL = (
    "Provenance Guard found strong signals that this content may have been "
    "AI-generated. This label is based on automated analysis and may be appealed "
    "by the creator."
)

HIGH_CONFIDENCE_HUMAN_LABEL = (
    "Provenance Guard found strong signals that this content appears to be "
    "human-written. This label is based on automated analysis and is not a "
    "guarantee of authorship."
)

UNCERTAIN_LABEL = (
    "Provenance Guard could not confidently determine whether this content was "
    "human-written or AI-generated. Readers should treat the authorship as "
    "uncertain, and the creator may appeal if they believe this label is inaccurate."
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def ensure_log_file():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            pass


def write_log(entry):
    ensure_log_file()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_log(limit=50):
    ensure_log_file()

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    entries = []
    for line in lines[-limit:]:
        line = line.strip()
        if line:
            entries.append(json.loads(line))

    return entries


def clamp_score(score):
    try:
        score = float(score)
    except (TypeError, ValueError):
        return 0.5

    return max(0.0, min(1.0, score))


def extract_json_from_text(text):
    """
    Tries to extract JSON from an LLM response.
    This helps if the model returns extra words around the JSON.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def llm_classification_signal(text):
    """
    Signal 1: Uses Groq to judge whether the text appears AI-generated.

    Returns:
        {
            "score": float from 0.0 to 1.0,
            "reasoning": str
        }
    """
    if client is None:
        # Safe fallback so the app still runs if the key is missing.
        return {
            "score": 0.5,
            "reasoning": "Groq API key was not found, so the LLM signal returned uncertain.",
        }

    prompt = f"""
You are part of Provenance Guard, a classroom project that estimates whether
a piece of writing appears more likely AI-generated or human-written.

Return ONLY valid JSON with this exact structure:
{{
  "score": 0.0,
  "reasoning": "brief reason"
}}

Score meaning:
0.0 = very likely human-written
0.5 = unclear or mixed
1.0 = very likely AI-generated

Be careful with false positives. Do not mark formal writing as AI-generated just
because it is polished. Non-native English writers may sound formal.

Text to analyze:
\"\"\"{text}\"\"\"
"""

    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a careful authorship signal. Return only valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )

        raw_output = completion.choices[0].message.content
        parsed = extract_json_from_text(raw_output)

        if not parsed:
            return {
                "score": 0.5,
                "reasoning": "The LLM response could not be parsed, so this signal returned uncertain.",
            }

        return {
            "score": clamp_score(parsed.get("score", 0.5)),
            "reasoning": str(parsed.get("reasoning", "No reasoning provided.")),
        }

    except Exception as e:
        return {
            "score": 0.5,
            "reasoning": f"LLM signal failed and returned uncertain. Error: {str(e)}",
        }


def split_sentences(text):
    sentences = re.split(r"[.!?]+", text)
    return [s.strip() for s in sentences if s.strip()]


def tokenize_words(text):
    return re.findall(r"\b[a-zA-Z']+\b", text.lower())


def stylometric_signal(text):
    """
    Signal 2: Pure Python stylometric heuristics.

    Returns:
        {
            "score": float from 0.0 to 1.0,
            "metrics": dict
        }
    """
    sentences = split_sentences(text)
    words = tokenize_words(text)

    if len(words) < 20 or len(sentences) < 2:
        return {
            "score": 0.5,
            "metrics": {
                "sentence_length_variance": 0.0,
                "type_token_ratio": 0.0,
                "punctuation_density": 0.0,
                "average_word_length": 0.0,
                "note": "Text was short, so stylometric score is uncertain.",
            },
        }

    sentence_lengths = [len(tokenize_words(sentence)) for sentence in sentences]
    sentence_length_variance = variance(sentence_lengths) if len(sentence_lengths) > 1 else 0.0

    unique_words = set(words)
    type_token_ratio = len(unique_words) / len(words)

    punctuation_count = sum(1 for ch in text if ch in string.punctuation)
    punctuation_density = punctuation_count / max(len(text), 1)

    average_word_length = sum(len(word) for word in words) / len(words)

    # Convert metrics into rough AI-likelihood components.
    # Lower sentence variation can look more AI-like.
    if sentence_length_variance < 8:
        sentence_uniformity_score = 0.8
    elif sentence_length_variance < 20:
        sentence_uniformity_score = 0.55
    else:
        sentence_uniformity_score = 0.25

    # Very low vocabulary diversity can look more formulaic.
    if type_token_ratio < 0.45:
        vocabulary_score = 0.75
    elif type_token_ratio < 0.65:
        vocabulary_score = 0.5
    else:
        vocabulary_score = 0.25

    # Very clean punctuation can look more AI-like; messy punctuation can look more human-like.
    if punctuation_density < 0.015:
        punctuation_score = 0.65
    elif punctuation_density < 0.04:
        punctuation_score = 0.45
    else:
        punctuation_score = 0.25

    # Longer average word length can reflect more formal/generated style, but weak signal.
    if average_word_length > 5.5:
        word_length_score = 0.65
    elif average_word_length > 4.5:
        word_length_score = 0.45
    else:
        word_length_score = 0.3

    score = (
        0.35 * sentence_uniformity_score
        + 0.30 * vocabulary_score
        + 0.20 * punctuation_score
        + 0.15 * word_length_score
    )

    return {
        "score": round(clamp_score(score), 3),
        "metrics": {
            "sentence_length_variance": round(sentence_length_variance, 3),
            "type_token_ratio": round(type_token_ratio, 3),
            "punctuation_density": round(punctuation_density, 4),
            "average_word_length": round(average_word_length, 3),
        },
    }


def combine_scores(llm_score, stylometric_score):
    """
    Combines both signals according to planning.md.
    """
    ai_likelihood = (0.65 * llm_score) + (0.35 * stylometric_score)
    ai_likelihood = round(clamp_score(ai_likelihood), 3)

    confidence = round(max(ai_likelihood, 1 - ai_likelihood), 3)

    if ai_likelihood >= 0.75:
        attribution = "likely_ai"
    elif ai_likelihood <= 0.25:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

    return ai_likelihood, confidence, attribution


def generate_label(attribution):
    if attribution == "likely_ai":
        return HIGH_CONFIDENCE_AI_LABEL

    if attribution == "likely_human":
        return HIGH_CONFIDENCE_HUMAN_LABEL

    return UNCERTAIN_LABEL


@app.route("/", methods=["GET"])
def home():
    return jsonify(
        {
            "message": "Provenance Guard API is running.",
            "endpoints": {
                "submit": "POST /submit",
                "appeal": "POST /appeal",
                "log": "GET /log",
            },
        }
    )


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}

    text = data.get("text", "").strip()
    creator_id = data.get("creator_id", "").strip()

    if not text:
        return jsonify({"error": "Missing required field: text"}), 400

    if not creator_id:
        return jsonify({"error": "Missing required field: creator_id"}), 400

    content_id = str(uuid.uuid4())

    llm_result = llm_classification_signal(text)
    stylometric_result = stylometric_signal(text)

    llm_score = clamp_score(llm_result["score"])
    stylometric_score = clamp_score(stylometric_result["score"])

    ai_likelihood, confidence, attribution = combine_scores(
        llm_score, stylometric_score
    )

    label = generate_label(attribution)

    content_record = {
        "content_id": content_id,
        "creator_id": creator_id,
        "text": text,
        "attribution": attribution,
        "confidence": confidence,
        "ai_likelihood": ai_likelihood,
        "label": label,
        "signals": {
            "llm_score": llm_score,
            "llm_reasoning": llm_result["reasoning"],
            "stylometric_score": stylometric_score,
            "stylometric_metrics": stylometric_result["metrics"],
        },
        "status": "classified",
        "created_at": utc_now(),
        "appeal_reasoning": None,
    }

    CONTENT_STORE[content_id] = content_record

    log_entry = {
        "event_type": "classification",
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": utc_now(),
        "attribution": attribution,
        "confidence": confidence,
        "ai_likelihood": ai_likelihood,
        "llm_score": llm_score,
        "stylometric_score": stylometric_score,
        "signals_used": ["llm", "stylometric"],
        "status": "classified",
    }

    write_log(log_entry)

    response = {
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": confidence,
        "ai_likelihood": ai_likelihood,
        "label": label,
        "signals": {
            "llm_score": llm_score,
            "llm_reasoning": llm_result["reasoning"],
            "stylometric_score": stylometric_score,
            "stylometric_metrics": stylometric_result["metrics"],
        },
        "status": "classified",
    }

    return jsonify(response), 200


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}

    content_id = data.get("content_id", "").strip()
    creator_reasoning = data.get("creator_reasoning", "").strip()

    if not content_id:
        return jsonify({"error": "Missing required field: content_id"}), 400

    if not creator_reasoning:
        return jsonify({"error": "Missing required field: creator_reasoning"}), 400

    if content_id not in CONTENT_STORE:
        return jsonify({"error": "content_id not found"}), 404

    CONTENT_STORE[content_id]["status"] = "under_review"
    CONTENT_STORE[content_id]["appeal_reasoning"] = creator_reasoning

    log_entry = {
        "event_type": "appeal",
        "content_id": content_id,
        "creator_id": CONTENT_STORE[content_id]["creator_id"],
        "timestamp": utc_now(),
        "original_attribution": CONTENT_STORE[content_id]["attribution"],
        "confidence": CONTENT_STORE[content_id]["confidence"],
        "ai_likelihood": CONTENT_STORE[content_id]["ai_likelihood"],
        "creator_reasoning": creator_reasoning,
        "status": "under_review",
    }

    write_log(log_entry)

    return (
        jsonify(
            {
                "content_id": content_id,
                "status": "under_review",
                "message": "Appeal received. This content is now under review.",
            }
        ),
        200,
    )


@app.route("/log", methods=["GET"])
def log():
    entries = read_log()
    return jsonify({"entries": entries}), 200


if __name__ == "__main__":
    app.run(debug=True)
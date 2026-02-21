#[ ExplainBot AI](https://explainbot-ai-v1.onrender.com)

> An agentic document intelligence system that converts technical documents into text, audio, or synchronized video explanations — using a custom-built multi-agent pipeline, not a single API call.
---

## 🎥 Live Demo

[▶️ Click here to watch the full demo](assets/video_1771598634.mp4)



ExplainBot dynamically selects the best explanation format based on query intent — text, narrated audio, or fully synchronized explainer video with rendered architecture diagrams.
---

## The Problem It Solves

Technical documents are dense. Most AI tools summarize them into walls of text. ExplainBot AI analyzes the intent of your question and picks the right format — a definition gets clean text, a process gets audio narration, a system flow gets a fully synchronized explainer video with a rendered architecture diagram.

---

## How It Works

```
User Query
    │
    ▼
┌─────────────────┐
│  Decision Agent │  Analyzes query intent → text / audio / video
└────────┬────────┘
         │
    ┌────┴──────────────────────┐
    │                           │
    ▼                           ▼
Content Agent              Video Agent
Multilingual explanation   Per-scene narration scripts
    │                           │
    ▼                      ┌────┴──────────────┐
Hybrid TTS                 │                   │
ElevenLabs → OpenAI        Diagram Service     TTS per scene
                           Mermaid → PNG       ElevenLabs → OpenAI
                                │                   │
                                └────────┬──────────┘
                                         ▼
                                   Video Service
                                   MoviePy composer
                                   Scene-by-scene sync
```

### Key Engineering Decisions

**Scene-by-scene A/V sync** — most video generators produce one long audio track over disconnected visuals. ExplainBot generates a separate narration and audio clip per scene. Scene duration is read from the actual audio file — not estimated. What you see always matches what you hear.

**Principle-based prompt routing** — the decision agent uses a reasoning-based prompt, not hardcoded examples. This generalizes better across query types and languages.

**Persistent TTS fallback** — when ElevenLabs quota is exhausted, the error is caught, flagged, and written to disk. All future requests skip ElevenLabs silently. No retry loops, no downtime.

**Multi-document context** — documents are stored in a session dictionary and merged with separators before being passed to the LLM. Cross-document queries work out of the box.

---

## Features

| Feature | Detail |
|---|---|
| Multi-modal output | Text, audio narration, synchronized video |
| Multi-document | Query across multiple PDFs/TXTs simultaneously |
| Auto language detection | 9 languages — Hindi (Devanagari), Spanish, German, French and more |
| PDF export | ReportLab-styled export for every text response |
| Query history | Session-level history, restore output without regenerating |
| Hybrid TTS | ElevenLabs primary → OpenAI fallback, quota persisted to disk |
| Rate limiting | Configurable daily caps with live frontend display |
| Single server | Frontend served by FastAPI — no separate process needed |

---

## Stack

```
LLM inference      Groq · llama-3.1-8b-instant
TTS primary        ElevenLabs · eleven_multilingual_v2
TTS fallback       OpenAI · tts-1-hd
Video composition  MoviePy
Diagram rendering  Mermaid.ink API
Backend            FastAPI
PDF generation     ReportLab
Language detect    langdetect
Frontend           Vanilla JS · Tailwind CSS
```

---

## Project Structure

```
explainbot-ai/
├── backend/
│   ├── main.py                  # FastAPI app, endpoints, rate limiting
│   ├── agents/
│   │   ├── decision_agent.py    # Query routing — text / audio / video
│   │   ├── content_agent.py     # Multilingual explanation generation
│   │   └── video_agent.py       # Scene planning + per-scene narration
│   └── services/
│       ├── tts_service.py       # Hybrid TTS + quota tracking
│       ├── video_service.py     # Scene rendering + composition
│       └── diagram_service.py   # Mermaid → PNG
├── frontend/
│   ├── index.html
│   └── app.js
├── .env.example
├── docker-compose.yml
└── README.md
```

---

## Local Setup

**Requirements:** Python 3.10+, ffmpeg on PATH

```bash
git clone https://github.com/Shau-19/explainbot-ai.git
cd explainbot-ai/backend
pip install -r requirements.txt
cp ../.env.example .env   # fill in your keys
uvicorn main:app --reload
```

Open `http://localhost:8000` — API and frontend on the same port.

---

## Docker Setup

```bash
cp .env.example .env   # fill in your keys
docker-compose up --build
```

Open `http://localhost:8000`

---

## Environment Variables

```env
GROQ_API_KEY=
ELEVENLABS_API_KEY=
OPENAI_API_KEY=
```

---

## API Reference

Full interactive docs at `http://localhost:8000/docs`

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/upload` | Upload PDF or TXT |
| DELETE | `/api/document/{filename}` | Remove a document |
| GET | `/api/documents` | List loaded documents |
| POST | `/api/explain` | Generate text or audio explanation |
| POST | `/api/generate-video` | Generate synchronized video |
| GET | `/api/usage` | Rate limit status |
| GET | `/api/export/{filename}` | Download PDF export |
| GET | `/api/audio/{filename}` | Serve audio |
| GET | `/api/video/{filename}` | Serve video |

---

## Sample Queries

| Query | Expected Output |
|---|---|
| `What is Proof of Work?` | Text |
| `How does a blockchain transaction work?` | Audio |
| `Walk me through the complete transaction flow` | Video |
| `ब्लॉकचेन में नोड्स की क्या भूमिका है?` | Hindi text |
| Upload 2 docs → `Compare both architectures` | Cross-document text |

---

## Share Publicly

Without a server — use ngrok:

```bash
ngrok http 8000
```

With Docker on a VPS — just expose port 8000.

---

*MIT License*

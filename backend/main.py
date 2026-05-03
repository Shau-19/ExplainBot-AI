from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil, time, re
from pypdf import PdfReader
from dotenv import load_dotenv
from langdetect import detect, LangDetectException
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors

from agents.decision_agent import DecisionAgent
from agents.content_agent import ContentAgent
from agents.video_agent import VideoAgent
from services.tts_service import HybridTTSService
from services.diagram_service import DiagramService
from services.video_service import VideoService
from guardrails import (
    validate_query,
    validate_context,
    validate_upload_size,
    check_ip_rate,
    MAX_UPLOAD_BYTES
)

load_dotenv()

# ── Daily rate limits (video/audio are expensive) ────────────────────────────

from datetime import datetime

LIMITS = {"video": 5, "audio": 5}
usage = {"video": 0, "audio": 0, "reset_date": datetime.now().date().isoformat()}


def check_and_increment(type_: str) -> tuple[bool, int]:
    today = datetime.now().date().isoformat()
    if usage["reset_date"] != today:
        usage["video"] = 0
        usage["audio"] = 0
        usage["reset_date"] = today
    limit = LIMITS.get(type_, 999)
    if usage.get(type_, 0) >= limit:
        return False, 0
    usage[type_] = usage.get(type_, 0) + 1
    return True, limit - usage[type_]


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="ExplainBot AI", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

decision_agent = DecisionAgent()
content_agent  = ContentAgent()
video_agent    = VideoAgent()
tts_service    = HybridTTSService()
diagram_service = DiagramService()
video_service  = VideoService()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# ── Multi-document store ──────────────────────────────────────────────────────

documents: dict[str, str] = {}
current_content: str = ""

SUPPORTED_LANGUAGES = {"en", "hi", "es", "de", "fr", "pt", "it", "pl", "nl"}


def detect_language(text: str) -> str:
    try:
        lang = detect(text)
        return lang if lang in SUPPORTED_LANGUAGES else "en"
    except LangDetectException:
        return "en"


def combine_documents() -> str:
    return "\n\n---\n\n".join(
        f"[Document: {name}]\n{text}" for name, text in documents.items()
    )


def generate_pdf_export(query: str, explanation_text: str, language: str) -> str:
    output_dir = Path("outputs/exports")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    output_path = output_dir / f"export_{timestamp}.pdf"

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=inch, leftMargin=inch,
        topMargin=inch, bottomMargin=inch
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Title'],
        fontSize=18, textColor=colors.HexColor('#1e3a8a'), spaceAfter=12
    )
    meta_style = ParagraphStyle(
        'Meta', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor('#94a3b8'), spaceAfter=20
    )
    body_style = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontSize=11, leading=18, spaceAfter=8
    )

    clean_text = re.sub(r'\*\*(.*?)\*\*', r'\1', explanation_text)
    clean_text = re.sub(r'\*(.*?)\*', r'\1', clean_text)

    story = [
        Paragraph("ExplainBot AI", title_style),
        Paragraph(f"Query: {query} &nbsp;|&nbsp; Language: {language.upper()}", meta_style),
        Spacer(1, 0.2 * inch),
    ]
    for para in clean_text.split('\n\n'):
        para = para.strip()
        if para:
            story.append(Paragraph(para.replace('\n', '<br/>'), body_style))
            story.append(Spacer(1, 0.1 * inch))

    doc.build(story)
    return str(output_path)


# ── Helper: get real client IP ────────────────────────────────────────────────

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "llm": "groq",
        "tts": tts_service.get_status()['active_provider'],
        "video": "moviepy",
        "documents_loaded": len(documents),
        "combined_length": len(current_content)
    }


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_document(request: Request, file: UploadFile = File(...)):
    global current_content

    # IP rate limit
    ip = get_client_ip(request)
    allowed, reason = check_ip_rate(ip)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    # File type guard
    if not (file.filename.endswith('.pdf') or file.filename.endswith('.txt')):
        raise HTTPException(status_code=400, detail="Only PDF and TXT files accepted.")

    # File size guard — read into memory first to check size
    contents = await file.read()
    size_ok, size_msg = validate_upload_size(len(contents))
    if not size_ok:
        raise HTTPException(status_code=413, detail=size_msg)

    # Sanitise filename — no path traversal
    safe_name = Path(file.filename).name
    file_path = UPLOAD_DIR / safe_name

    with open(file_path, "wb") as buffer:
        buffer.write(contents)

    try:
        if safe_name.endswith('.pdf'):
            reader = PdfReader(file_path)
            text = "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        else:
            text = contents.decode("utf-8", errors="ignore")

        # Context sanity check
        ctx_ok, ctx_msg = validate_context(text)
        if not ctx_ok:
            raise HTTPException(status_code=422, detail=ctx_msg)
        if ctx_msg:
            print(f"[Upload] {ctx_msg}")

        documents[safe_name] = text
        current_content = combine_documents()

        return {
            "success": True,
            "filename": safe_name,
            "content_length": len(text),
            "total_documents": len(documents),
            "document_names": list(documents.keys()),
            "preview": text[:200] + "..." if len(text) > 200 else text
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")


@app.delete("/api/document/{filename}")
async def remove_document(filename: str):
    global current_content
    safe_name = Path(filename).name   # prevent path traversal
    if safe_name in documents:
        del documents[safe_name]
        current_content = combine_documents()
        return {"success": True, "remaining": list(documents.keys())}
    raise HTTPException(status_code=404, detail="Document not found")


@app.get("/api/documents")
def list_documents():
    return {
        "documents": [{"name": k, "length": len(v)} for k, v in documents.items()],
        "total": len(documents)
    }


@app.get("/api/status")
def document_status():
    return {
        "document_loaded": len(documents) > 0,
        "documents": list(documents.keys()),
        "combined_length": len(current_content),
        "agents_ready": True,
        "tts": tts_service.get_status()
    }


# ── Explain ───────────────────────────────────────────────────────────────────

@app.post("/api/explain")
async def generate_explanation(
    request: Request,
    query: str = Form(...),
    language: str = Form("auto"),
    generate_audio: bool = Form(True),
    format_hint: str = Form("auto")
):
    # IP rate limit
    ip = get_client_ip(request)
    allowed, reason = check_ip_rate(ip)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    # Query guardrail — before ANY LLM call
    q_ok, q_msg = validate_query(query)
    if not q_ok:
        raise HTTPException(status_code=400, detail=q_msg)

    if not current_content:
        raise HTTPException(status_code=400, detail="No document uploaded.")

    try:
        effective_language = (
            language if language != "auto" else detect_language(query)
        )
        decision = decision_agent.analyze_and_decide(
            query, current_content, format_hint
        )

        # Rate limit audio
        if decision["format"] in ["audio"] and generate_audio:
            a_ok, _ = check_and_increment("audio")
            if not a_ok:
                raise HTTPException(
                    status_code=429,
                    detail=f"Audio limit reached ({LIMITS['audio']}/day). "
                           f"Try text format or come back tomorrow."
                )

        explanation = content_agent.generate_explanation(
            query=query,
            context=current_content,
            format_type=decision['format'],
            language=effective_language
        )

        audio_result = None
        if generate_audio and decision['format'] in ['audio', 'video']:
            script = explanation['script'] or explanation['text']
            audio_result = tts_service.generate_audio(
                text=script, language=effective_language
            )

        pdf_path = generate_pdf_export(query, explanation['text'], effective_language)
        pdf_filename = Path(pdf_path).name

        return {
            "success": True,
            "query": query,
            "detected_language": effective_language,
            "agent_decision": decision,
            "explanation": explanation,
            "audio": audio_result,
            "format": decision['format'],
            "pdf_export": pdf_filename
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Explanation failed: {str(e)}")


# ── Video ─────────────────────────────────────────────────────────────────────

@app.post("/api/generate-video")
async def generate_video(
    request: Request,
    query: str = Form(...),
    language: str = Form("auto")
):
    # IP rate limit
    ip = get_client_ip(request)
    allowed, reason = check_ip_rate(ip)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    # Query guardrail
    q_ok, q_msg = validate_query(query)
    if not q_ok:
        raise HTTPException(status_code=400, detail=q_msg)

    if not current_content:
        raise HTTPException(status_code=400, detail="No document uploaded")

    # Daily video limit
    v_ok, _ = check_and_increment("video")
    if not v_ok:
        raise HTTPException(
            status_code=429,
            detail=f"Video limit reached ({LIMITS['video']}/day). "
                   f"Try audio or text format instead."
        )

    try:
        effective_language = (
            language if language != "auto" else detect_language(query)
        )

        print(f"\n{'='*60}")
        print(f"🎬 VIDEO GENERATION: {query}")
        print(f"{'='*60}")

        print("📝 Generating explanation...")
        explanation = content_agent.generate_explanation(
            query=query,
            context=current_content,
            format_type='video',
            language=effective_language
        )
        print(f"✅ Explanation: {len(explanation['text'])} chars")

        # Get grounded context for video agent — avoids hallucination cascading
        grounded_context = content_agent.retrieve_for_video(
            query=query,
            context=current_content,
            top_k=5
        )

        print("\n🎞️  Planning video scenes...")
        scene_plan = video_agent.plan_scenes(
            query=query,
            explanation=explanation['text'],
            language=effective_language,
            grounded_context=grounded_context   # ← grounded, not hallucinated
        )
        print(f"✅ {len(scene_plan['scenes'])} scenes planned")
        for scene in scene_plan['scenes']:
            print(f"   Scene {scene['id']}: {scene['type']} (~{scene.get('duration', 0):.0f}s)")

        print("\n📊 Rendering diagram...")
        diagram_path = diagram_service.mermaid_to_png(scene_plan['mermaid_diagram'])
        print("✅ Diagram rendered")

        print("\n🎤 Generating scene audio...")
        audio_clips = tts_service.generate_audio_batch(
            scenes=scene_plan['scenes'],
            language=effective_language
        )

        if not audio_clips:
            raise Exception("Audio generation failed for all scenes")

        total_duration = sum(clip['duration'] for clip in audio_clips)
        print(f"✅ {len(audio_clips)} audio clips ({total_duration:.1f}s total)")

        print("\n🎬 Composing video...")
        video_path = video_service.create_video(
            scenes=scene_plan['scenes'],
            audio_clips=audio_clips,
            diagram_path=diagram_path
        )

        filename = Path(video_path).name

        print(f"\n{'='*60}")
        print(f"✅ VIDEO COMPLETE: {filename}")
        print(f"{'='*60}\n")

        return {
            "success": True,
            "query": query,
            "detected_language": effective_language,
            "video_filename": filename,
            "video_url": f"/api/video/{filename}",
            "scenes": len(scene_plan['scenes']),
            "duration": int(total_duration),
            "audio_clips": len(audio_clips),
            "sync_method": "scene-by-scene"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"\n❌ VIDEO GENERATION FAILED: {e}\n")
        raise HTTPException(status_code=500, detail=f"Video generation failed: {str(e)}")


# ── Media serving ─────────────────────────────────────────────────────────────

@app.get("/api/video/{filename}")
async def serve_video(filename: str):
    # Prevent path traversal
    safe = Path(filename).name
    file_path = Path("outputs/video") / safe
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path=file_path, media_type="video/mp4", filename=safe)


@app.get("/api/audio/{filename}")
async def serve_audio(filename: str):
    safe = Path(filename).name
    file_path = Path("outputs/audio") / safe
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path=file_path, media_type="audio/mpeg", filename=safe)


@app.get("/api/export/{filename}")
async def serve_export(filename: str):
    safe = Path(filename).name
    file_path = Path("outputs/exports") / safe
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(path=file_path, media_type="application/pdf", filename=safe)


@app.get("/api/usage")
def get_usage():
    today = datetime.now().date().isoformat()
    if usage["reset_date"] != today:
        usage["video"] = 0
        usage["audio"] = 0
        usage["reset_date"] = today
    return {
        "video": {
            "used": usage["video"],
            "limit": LIMITS["video"],
            "remaining": LIMITS["video"] - usage["video"]
        },
        "audio": {
            "used": usage["audio"],
            "limit": LIMITS["audio"],
            "remaining": LIMITS["audio"] - usage["audio"]
        },
        "resets": "daily"
    }


@app.get("/api/tts/status")
def tts_status():
    return tts_service.get_status()


# Serve frontend — must be LAST
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

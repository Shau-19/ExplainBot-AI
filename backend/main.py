'''
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil
from pypdf import PdfReader
from dotenv import load_dotenv

from agents.decision_agent import DecisionAgent
from agents.content_agent import ContentAgent
from agents.video_agent import VideoAgent
from services.tts_service import HybridTTSService
from services.diagram_service import DiagramService
from services.video_service import VideoService

# Load environment variables
load_dotenv()

# ═══════════════════════════════════════════════════════════
# App Initialization
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="ExplainBot AI",
    description="Agentic AI for document explanations with scene-by-scene video generation",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on deployment environment
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════
# Service Initialization
# ═══════════════════════════════════════════════════════════

# AI Agents
decision_agent = DecisionAgent()
content_agent = ContentAgent()
video_agent = VideoAgent()

# Media Services
tts_service = HybridTTSService()
diagram_service = DiagramService()
video_service = VideoService()

# ═══════════════════════════════════════════════════════════
# Storage Setup
# ═══════════════════════════════════════════════════════════

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# In-memory document store (use Redis/DB for production scale)
current_content = ""

# ═══════════════════════════════════════════════════════════
# Core Endpoints
# ═══════════════════════════════════════════════════════════

@app.get("/")
def root():
    """API root - service info"""
    return {
        "service": "ExplainBot AI",
        "version": "1.0.0",
        "status": "online",
        "features": ["text", "audio", "video"],
        "docs": "/docs"
    }


@app.get("/api/health")
def health_check():
    """
    System health check
    Returns active providers and readiness status
    """
    return {
        "status": "healthy",
        "llm": "groq",
        "tts": tts_service.get_status()['active_provider'],
        "video": "moviepy",
        "document_loaded": len(current_content) > 0
    }

# ═══════════════════════════════════════════════════════════
# Document Management
# ═══════════════════════════════════════════════════════════

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Upload and process document (PDF/TXT)
    
    Process:
    1. Validate file type
    2. Extract text content
    3. Store in memory for query processing
    
    Returns: Document metadata and preview
    """
    global current_content

    # Validate file type
    if not (file.filename.endswith('.pdf') or file.filename.endswith('.txt')):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Only PDF and TXT files are accepted."
        )

    # Save uploaded file
    file_path = UPLOAD_DIR / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Extract text content
    try:
        if file.filename.endswith('.pdf'):
            reader = PdfReader(file_path)
            text = "\n".join([page.extract_text() for page in reader.pages])
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()

        current_content = text
        
        return {
            "success": True,
            "filename": file.filename,
            "content_length": len(text),
            "preview": text[:200] + "..." if len(text) > 200 else text
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process document: {str(e)}"
        )


@app.get("/api/status")
def document_status():
    """
    Check if document is loaded and system status
    """
    return {
        "document_loaded": len(current_content) > 0,
        "content_length": len(current_content),
        "agents_ready": True,
        "tts": tts_service.get_status()
    }

# ═══════════════════════════════════════════════════════════
# Explanation Generation
# ═══════════════════════════════════════════════════════════

@app.post("/api/explain")
async def generate_explanation(
    query: str = Form(...),
    language: str = Form("en"),
    generate_audio: bool = Form(True)
):
    """
    Generate text/audio explanation
    
    Pipeline:
    1. Decision agent analyzes query complexity
    2. Content agent generates explanation
    3. TTS service creates audio (if format requires it)
    
    Returns: Explanation text, agent decision, and optional audio
    """
    
    if not current_content:
        raise HTTPException(
            status_code=400,
            detail="No document uploaded. Please upload a document first."
        )

    try:
        # Step 1: Agent decides output format
        decision = decision_agent.analyze_and_decide(query, current_content)

        # Step 2: Generate explanation content
        explanation = content_agent.generate_explanation(
            query=query,
            context=current_content,
            format_type=decision['format']
        )

        # Step 3: Generate audio if needed
        audio_result = None
        if generate_audio and decision['format'] in ['audio', 'video']:
            script = explanation['script'] or explanation['text']
            audio_result = tts_service.generate_audio(
                text=script,
                language=language
            )

        return {
            "success": True,
            "query": query,
            "agent_decision": decision,
            "explanation": explanation,
            "audio": audio_result,
            "format": decision['format']
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Explanation generation failed: {str(e)}"
        )

# ═══════════════════════════════════════════════════════════
# Video Generation (Scene-by-Scene Sync)
# ═══════════════════════════════════════════════════════════

@app.post("/api/generate-video")
async def generate_video(
    query: str = Form(...),
    language: str = Form("en")
):
    
    
    if not current_content:
        raise HTTPException(
            status_code=400,
            detail="No document uploaded"
        )

    try:
        print(f"\n{'='*60}")
        print(f"🎬 VIDEO GENERATION: {query}")
        print(f"{'='*60}")
        
        # Step 1: Generate base explanation
        print("📝 Generating explanation...")
        explanation = content_agent.generate_explanation(
            query=query,
            context=current_content,
            format_type='video'
        )
        print(f"✅ Explanation: {len(explanation['text'])} chars")
        
        # Step 2: Plan scenes with per-scene narration
        print("\n🎞️  Planning video scenes...")
        scene_plan = video_agent.plan_scenes(query, explanation['text'])
        print(f"✅ {len(scene_plan['scenes'])} scenes planned")
        for scene in scene_plan['scenes']:
            print(f"   Scene {scene['id']}: {scene['type']} (~{scene.get('duration', 0):.0f}s)")
        
        # Step 3: Render diagram
        print("\n📊 Rendering diagram...")
        diagram_path = diagram_service.mermaid_to_png(scene_plan['mermaid_diagram'])
        print(f"✅ Diagram rendered")
        
        # Step 4: Generate audio for each scene (KEY FEATURE)
        print("\n🎤 Generating scene audio...")
        audio_clips = tts_service.generate_audio_batch(
            scenes=scene_plan['scenes'],
            language=language
        )
        
        if not audio_clips:
            raise Exception("Audio generation failed for all scenes")
        
        total_duration = sum(clip['duration'] for clip in audio_clips)
        print(f"✅ {len(audio_clips)} audio clips generated ({total_duration:.1f}s total)")
        
        # Step 5: Compose final video
        print("\n🎬 Composing video...")
        video_path = video_service.create_video(
            scenes=scene_plan['scenes'],
            audio_clips=audio_clips,
            diagram_path=diagram_path
        )
        
        filename = Path(video_path).name
        
        print(f"\n{'='*60}")
        print(f"✅ VIDEO COMPLETE: {filename}")
        print(f"   Duration: {total_duration:.0f}s")
        print(f"   Scenes: {len(scene_plan['scenes'])}")
        print(f"   Sync: scene-by-scene")
        print(f"{'='*60}\n")
        
        return {
            "success": True,
            "query": query,
            "video_filename": filename,
            "video_url": f"/api/video/{filename}",
            "scenes": len(scene_plan['scenes']),
            "duration": int(total_duration),
            "audio_clips": len(audio_clips),
            "sync_method": "scene-by-scene"
        }

    except Exception as e:
        print(f"\n❌ VIDEO GENERATION FAILED: {e}\n")
        raise HTTPException(
            status_code=500,
            detail=f"Video generation failed: {str(e)}"
        )

# ═══════════════════════════════════════════════════════════
# Media Serving
# ═══════════════════════════════════════════════════════════

@app.get("/api/video/{filename}")
async def serve_video(filename: str):
    """Serve generated video files"""
    file_path = Path("outputs/video") / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=filename
    )


@app.get("/api/audio/{filename}")
async def serve_audio(filename: str):
    """Serve generated audio files"""
    file_path = Path("outputs/audio") / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    
    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        filename=filename
    )


@app.get("/api/tts/status")
def tts_status():
    """
    TTS service status and quota information
    Useful for monitoring ElevenLabs free tier usage
    """
    return tts_service.get_status()

# ═══════════════════════════════════════════════════════════
# Frontend (Static Files)
# ═══════════════════════════════════════════════════════════

# Serve frontend UI (uncomment for production deployment)
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")

# ═══════════════════════════════════════════════════════════
# Development Server
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )


    '''
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
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

load_dotenv()

# ── Rate Limiting ─────────────────────────────────────────
from datetime import datetime

LIMITS = {"video": 5, "audio": 20}

usage = {"video": 0, "audio": 0, "reset_date": datetime.now().date().isoformat()}

def check_and_increment(type_: str) -> tuple[bool, int]:
    """Returns (allowed, remaining). Resets daily."""
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


app = FastAPI(title="ExplainBot AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

decision_agent = DecisionAgent()
content_agent = ContentAgent()
video_agent = VideoAgent()
tts_service = HybridTTSService()
diagram_service = DiagramService()
video_service = VideoService()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# ── Multi-document store ─────────────────────────────────
documents = {}          # {filename: text}
current_content = ""    # combined text of all uploaded docs

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
    """Generate a styled PDF from explanation text using reportlab."""
    output_dir = Path("outputs/exports")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    output_path = output_dir / f"export_{timestamp}.pdf"

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=18,
        textColor=colors.HexColor('#1e3a8a'),
        spaceAfter=12
    )

    meta_style = ParagraphStyle(
        'Meta',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#94a3b8'),
        spaceAfter=20
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontSize=11,
        leading=18,
        spaceAfter=8
    )

    # Strip markdown — reportlab doesn't render it
    clean_text = re.sub(r'\*\*(.*?)\*\*', r'\1', explanation_text)
    clean_text = re.sub(r'\*(.*?)\*', r'\1', clean_text)

    story = []
    story.append(Paragraph("ExplainBot AI", title_style))
    story.append(Paragraph(f"Query: {query} &nbsp;|&nbsp; Language: {language.upper()}", meta_style))
    story.append(Spacer(1, 0.2 * inch))

    for para in clean_text.split('\n\n'):
        para = para.strip()
        if para:
            story.append(Paragraph(para.replace('\n', '<br/>'), body_style))
            story.append(Spacer(1, 0.1 * inch))

    doc.build(story)
    return str(output_path)


# ── Health ───────────────────────────────────────────────

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


# ── Upload (multi-doc) ───────────────────────────────────

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    global current_content

    if not (file.filename.endswith('.pdf') or file.filename.endswith('.txt')):
        raise HTTPException(status_code=400, detail="Only PDF and TXT files accepted.")

    file_path = UPLOAD_DIR / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        if file.filename.endswith('.pdf'):
            reader = PdfReader(file_path)
            text = "\n".join([page.extract_text() for page in reader.pages])
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()

        documents[file.filename] = text
        current_content = combine_documents()

        return {
            "success": True,
            "filename": file.filename,
            "content_length": len(text),
            "total_documents": len(documents),
            "document_names": list(documents.keys()),
            "preview": text[:200] + "..." if len(text) > 200 else text
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")


@app.delete("/api/document/{filename}")
async def remove_document(filename: str):
    global current_content
    if filename in documents:
        del documents[filename]
        current_content = combine_documents()
        return {"success": True, "remaining": list(documents.keys())}
    raise HTTPException(status_code=404, detail="Document not found")


@app.get("/api/documents")
def list_documents():
    return {
        "documents": [
            {"name": k, "length": len(v)} for k, v in documents.items()
        ],
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


# ── Explain ──────────────────────────────────────────────

@app.post("/api/explain")
async def generate_explanation(
    query: str = Form(...),
    language: str = Form("auto"),
    generate_audio: bool = Form(True),
    format_hint: str = Form("auto")
):
    if not current_content:
        raise HTTPException(status_code=400, detail="No document uploaded.")

    try:
        effective_language = language if language != "auto" else detect_language(query)
        decision = decision_agent.analyze_and_decide(query, current_content, format_hint)

        # Rate limit audio
        if decision["format"] == "audio" or (generate_audio and decision["format"] in ["audio"]):
            allowed, remaining = check_and_increment("audio")
            if not allowed:
                raise HTTPException(status_code=429, detail=f"Audio limit reached ({LIMITS['audio']}/day). Try text format or come back tomorrow.")

        explanation = content_agent.generate_explanation(
            query=query,
            context=current_content,
            format_type=decision['format'],
            language=effective_language
        )

        audio_result = None
        if generate_audio and decision['format'] in ['audio', 'video']:
            script = explanation['script'] or explanation['text']
            audio_result = tts_service.generate_audio(text=script, language=effective_language)

        # Generate PDF export
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Explanation failed: {str(e)}")


# ── Video ────────────────────────────────────────────────

@app.post("/api/generate-video")
async def generate_video(
    query: str = Form(...),
    language: str = Form("auto")
):
    if not current_content:
        raise HTTPException(status_code=400, detail="No document uploaded")

    # Rate limit video
    allowed, remaining = check_and_increment("video")
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Video limit reached ({LIMITS['video']}/day). Try audio or text format instead.")

    try:
        effective_language = language if language != "auto" else detect_language(query)

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

        print("\n🎞️  Planning video scenes...")
        scene_plan = video_agent.plan_scenes(query, explanation['text'], language=effective_language)
        print(f"✅ {len(scene_plan['scenes'])} scenes planned")
        for scene in scene_plan['scenes']:
            print(f"   Scene {scene['id']}: {scene['type']} (~{scene.get('duration', 0):.0f}s)")

        print("\n📊 Rendering diagram...")
        diagram_path = diagram_service.mermaid_to_png(scene_plan['mermaid_diagram'])
        print(f"✅ Diagram rendered")

        print("\n🎤 Generating scene audio...")
        audio_clips = tts_service.generate_audio_batch(scenes=scene_plan['scenes'], language=effective_language)

        if not audio_clips:
            raise Exception("Audio generation failed for all scenes")

        total_duration = sum(clip['duration'] for clip in audio_clips)
        print(f"✅ {len(audio_clips)} audio clips generated ({total_duration:.1f}s total)")

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

    except Exception as e:
        print(f"\n❌ VIDEO GENERATION FAILED: {e}\n")
        raise HTTPException(status_code=500, detail=f"Video generation failed: {str(e)}")


# ── Media Serving ────────────────────────────────────────

@app.get("/api/video/{filename}")
async def serve_video(filename: str):
    file_path = Path("outputs/video") / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path=file_path, media_type="video/mp4", filename=filename)


@app.get("/api/audio/{filename}")
async def serve_audio(filename: str):
    file_path = Path("outputs/audio") / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path=file_path, media_type="audio/mpeg", filename=filename)


@app.get("/api/export/{filename}")
async def serve_export(filename: str):
    file_path = Path("outputs/exports") / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(path=file_path, media_type="application/pdf", filename=filename)


@app.get("/api/usage")
def get_usage():
    today = datetime.now().date().isoformat()
    if usage["reset_date"] != today:
        usage["video"] = 0
        usage["audio"] = 0
        usage["reset_date"] = today
    return {
        "video": {"used": usage["video"], "limit": LIMITS["video"], "remaining": LIMITS["video"] - usage["video"]},
        "audio": {"used": usage["audio"], "limit": LIMITS["audio"], "remaining": LIMITS["audio"] - usage["audio"]},
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
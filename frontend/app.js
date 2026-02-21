const API_BASE = '';

// ─── State ────────────────────────────────────────────────
let queryHistory = [];

// ─── Markdown Parser ──────────────────────────────────────
function parseMarkdown(text) {
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong style="color:white;font-weight:600;">$1</strong>')
        .replace(/\*(.*?)\*/g, '<em style="color:#c4c8e0;">$1</em>')
        .replace(/^### (.*$)/gm, '<h3 style="font-size:1rem;font-weight:600;color:white;margin-top:16px;margin-bottom:4px;">$1</h3>')
        .replace(/^## (.*$)/gm, '<h2 style="font-size:1.1rem;font-weight:600;color:white;margin-top:20px;margin-bottom:6px;">$1</h2>')
        .replace(/^- (.*$)/gm, '<li style="margin-left:16px;list-style:disc;color:#c4c8e0;">$1</li>')
        .replace(/^(\d+)\. (.*$)/gm, '<li style="margin-left:16px;color:#c4c8e0;"><span style="color:#60a5fa;font-family:monospace;margin-right:6px;">$1.</span>$2</li>')
        .replace(/\n\n/g, '</p><p style="margin-top:12px;color:#c4c8e0;">')
        .replace(/\n/g, '<br>');
}

// ─── Upload ───────────────────────────────────────────────
document.getElementById('fileInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const statusDiv = document.getElementById('uploadStatus');
    statusDiv.classList.remove('hidden');
    statusDiv.innerHTML = `
        <div style="display:flex;align-items:center;gap:12px;padding:14px;border-radius:8px;background:rgba(59,130,246,0.06);border:1px solid #1d4ed8;">
            <div style="width:16px;height:16px;border:2px solid #3b82f6;border-top-color:transparent;border-radius:50%;animation:spin 0.9s linear infinite;"></div>
            <p style="color:#60a5fa;font-size:0.8rem;font-family:monospace;">Uploading ${file.name}...</p>
        </div>`;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: formData });
        const data = await response.json();
        if (data.success) {
            renderDocumentList(data.document_names);
            document.getElementById('querySection').style.display = 'block';
            document.getElementById('querySection').scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    } catch (error) {
        statusDiv.innerHTML = `<div style="padding:14px;border-radius:8px;border:1px solid #7f1d1d;color:#f87171;font-size:0.8rem;">Upload failed: ${error.message}</div>`;
    }
});

function renderDocumentList(names) {
    const statusDiv = document.getElementById('uploadStatus');
    statusDiv.classList.remove('hidden');
    statusDiv.innerHTML = `
        <div style="padding:14px;border-radius:8px;background:#12121f;border:1px solid #22223a;">
            <p style="font-size:0.65rem;font-family:monospace;color:#6b7099;margin-bottom:8px;">LOADED DOCUMENTS (${names.length})</p>
            <div style="display:flex;flex-wrap:wrap;gap:8px;">
                ${names.map(name => `
                    <div style="display:flex;align-items:center;gap:8px;padding:5px 12px;background:#1a1a2e;border-radius:6px;border:1px solid #22223a;font-size:0.8rem;">
                        <span style="color:#4ade80;">✓</span>
                        <span>${name}</span>
                        <button onclick="removeDocument('${name}')" style="color:#444;background:none;border:none;cursor:pointer;font-size:0.8rem;" onmouseenter="this.style.color='#f87171'" onmouseleave="this.style.color='#444'">✕</button>
                    </div>`).join('')}
            </div>
            <label for="fileInput" style="margin-top:10px;display:inline-block;font-size:0.7rem;color:#3b82f6;cursor:pointer;font-family:monospace;">+ Add another document</label>
        </div>`;
}

async function removeDocument(filename) {
    try {
        const response = await fetch(`${API_BASE}/api/document/${encodeURIComponent(filename)}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.remaining.length === 0) {
            document.getElementById('uploadStatus').innerHTML = '';
            document.getElementById('querySection').style.display = 'none';
        } else {
            renderDocumentList(data.remaining);
        }
    } catch (e) { console.error(e); }
}

// ─── Query Submit ─────────────────────────────────────────
document.getElementById('queryForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = document.getElementById('queryInput').value;
    const language = document.getElementById('languageSelect').value;
    const formatHint = document.getElementById('formatHint').value;

    try {
        if (formatHint === 'video') {
            await generateVideo(query, language);
        } else {
            await generateExplanation(query, language, formatHint);
        }
    } catch (error) {
        hideLoading();
        alert('Error: ' + error.message);
    }
});

// ─── Generate Explanation ─────────────────────────────────
async function generateExplanation(query, language, formatHint = 'auto') {
    showLoading('text');

    const formData = new FormData();
    formData.append('query', query);
    formData.append('language', language);
    formData.append('generate_audio', 'true');
    formData.append('format_hint', formatHint);

    const response = await fetch(`${API_BASE}/api/explain`, { method: 'POST', body: formData });
    const data = await response.json();

    if (response.status === 429) { hideLoading(); alert(data.detail); fetchUsage(); return; }

    if (data.format === 'video') {
        hideLoading();
        await generateVideo(query, language);
        return;
    }

    hideLoading();
    displayResults(data);
    addToHistory(query, data.detected_language, data.agent_decision.format, 'text', data);
}

// ─── Generate Video ───────────────────────────────────────
async function generateVideo(query, language) {
    showLoading('video');

    const formData = new FormData();
    formData.append('query', query);
    formData.append('language', language);

    // Step-by-step progress
    const steps = ['step1','step2','step3','step4'];
    let stepIndex = 0;
    setStep(steps[stepIndex], 'active');

    const stepTimings = [0, 4000, 9000, 16000];
    stepTimings.forEach((delay, i) => {
        setTimeout(() => {
            if (i > 0) setStep(steps[i-1], 'done');
            if (i < steps.length) setStep(steps[i], 'active');
        }, delay);
    });

    const response = await fetch(`${API_BASE}/api/generate-video`, { method: 'POST', body: formData });
    const data = await response.json();

    // Mark all done
    steps.forEach(s => setStep(s, 'done'));
    await new Promise(r => setTimeout(r, 400));

    hideLoading();
    if (response.status === 429) { alert(data.detail); fetchUsage(); return; }
    displayVideoResults(data);
    fetchUsage();
    addToHistory(query, data.detected_language, 'video', 'video', data);
}

function setStep(id, state) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('active', 'done');
    if (state) el.classList.add(state);
}

// ─── Display Results ──────────────────────────────────────
function displayResults(data) {
    const resultsSection = document.getElementById('resultsSection');
    resultsSection.style.display = 'block';

    const decision = data.agent_decision;
    document.getElementById('agentDecision').innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px;">
            <div style="padding:12px;border-radius:8px;background:#12121f;border:1px solid #22223a;text-align:center;">
                <p style="font-size:0.65rem;font-family:monospace;color:#6b7099;margin-bottom:4px;">FORMAT</p>
                <p style="font-weight:600;color:#60a5fa;">${decision.format.toUpperCase()}</p>
            </div>
            <div style="padding:12px;border-radius:8px;background:#12121f;border:1px solid #22223a;text-align:center;">
                <p style="font-size:0.65rem;font-family:monospace;color:#6b7099;margin-bottom:4px;">COMPLEXITY</p>
                <p style="font-weight:600;text-transform:capitalize;">${decision.complexity}</p>
            </div>
            <div style="padding:12px;border-radius:8px;background:#12121f;border:1px solid #22223a;text-align:center;">
                <p style="font-size:0.65rem;font-family:monospace;color:#6b7099;margin-bottom:4px;">LANGUAGE</p>
                <p style="font-weight:600;color:#a78bfa;">${(data.detected_language || 'en').toUpperCase()}</p>
            </div>
        </div>
        <div style="padding:10px 14px;border-radius:6px;background:#12121f;border:1px solid #22223a;font-size:0.7rem;font-family:monospace;color:#6b7099;">
            AI: ${decision.reasoning}
        </div>`;

    let html = `<div style="margin-top:20px;color:#c4c8e0;line-height:1.8;">
        <p style="color:#c4c8e0;">${parseMarkdown(data.explanation.text)}</p>
    </div>`;

    if (data.audio) {
        html += `
        <div style="margin-top:20px;padding:16px;border-radius:8px;background:#12121f;border:1px solid #22223a;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                <p style="font-size:0.85rem;font-weight:600;">Audio Narration <span style="font-size:0.65rem;font-family:monospace;color:#6b7099;margin-left:6px;">${data.audio.provider}</span></p>
                <a href="${API_BASE}/api/audio/${data.audio.filename}" download style="font-size:0.7rem;color:#60a5fa;">Download</a>
            </div>
            <audio controls style="width:100%;">
                <source src="${API_BASE}/api/audio/${data.audio.filename}" type="audio/mpeg">
            </audio>
        </div>`;
    }

    if (data.pdf_export) {
        html += `
        <div style="margin-top:14px;">
            <a href="${API_BASE}/api/export/${data.pdf_export}" download
               style="display:inline-flex;align-items:center;gap:8px;padding:8px 16px;background:#1a1a2e;border:1px solid #22223a;border-radius:6px;font-size:0.8rem;color:#c4c8e0;text-decoration:none;"
               onmouseenter="this.style.borderColor='#3b82f6'" onmouseleave="this.style.borderColor='#22223a'">
                📄 Download as PDF
            </a>
        </div>`;
    }

    document.getElementById('explanationOutput').innerHTML = html;
    resultsSection.scrollIntoView({ behavior: 'smooth' });
}

// ─── Display Video Results ────────────────────────────────
function displayVideoResults(data) {
    const resultsSection = document.getElementById('resultsSection');
    resultsSection.style.display = 'block';

    document.getElementById('agentDecision').innerHTML = `
        <div style="padding:14px;border-radius:8px;background:#12121f;border:1px solid #22223a;display:flex;align-items:center;gap:20px;font-size:0.8rem;font-family:monospace;">
            <span style="color:#4ade80;">✓ VIDEO</span>
            <span style="color:#6b7099;">${data.scenes} scenes</span>
            <span style="color:#6b7099;">${data.duration}s</span>
            <span style="color:#6b7099;">${data.audio_clips} audio tracks</span>
            <span style="color:#a78bfa;">${(data.detected_language || 'en').toUpperCase()}</span>
        </div>`;

    document.getElementById('explanationOutput').innerHTML = `
        <div style="margin-top:16px;border-radius:10px;overflow:hidden;border:1px solid #22223a;">
            <video controls style="width:100%;aspect-ratio:16/9;background:black;" autoplay>
                <source src="${API_BASE}${data.video_url}" type="video/mp4">
            </video>
        </div>
        <div style="margin-top:14px;display:flex;gap:10px;">
            <a href="${API_BASE}${data.video_url}" download
               style="flex:1;padding:10px;background:#3b82f6;color:white;text-align:center;border-radius:8px;font-weight:600;font-size:0.85rem;text-decoration:none;">
                Download MP4
            </a>
            <button onclick="location.reload()"
                    style="padding:10px 16px;background:#12121f;border:1px solid #22223a;border-radius:8px;font-size:0.85rem;color:#c4c8e0;cursor:pointer;">
                New Query
            </button>
        </div>`;

    resultsSection.scrollIntoView({ behavior: 'smooth' });
}

// ─── History ──────────────────────────────────────────────
function addToHistory(query, language, format, type, data) {
    queryHistory.unshift({ query, language, format, type, data, timestamp: Date.now() });
    renderHistory();
}

function renderHistory() {
    const container = document.getElementById('historyList');
    const section = document.getElementById('historySection');
    if (!container || queryHistory.length === 0) return;
    section.style.display = 'block';
    container.innerHTML = queryHistory.map((item, i) => `
        <div style="padding:12px;border-radius:8px;background:#12121f;border:1px solid #22223a;cursor:pointer;transition:border-color 0.2s;"
             onclick="replayHistory(${i})"
             onmouseenter="this.style.borderColor='#3b82f6'" onmouseleave="this.style.borderColor='#22223a'">
            <div style="display:flex;align-items:center;justify-content:space-between;">
                <p style="font-size:0.85rem;color:white;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;margin-right:16px;">${item.query}</p>
                <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;font-family:monospace;font-size:0.7rem;">
                    <span style="color:#60a5fa;">${item.format.toUpperCase()}</span>
                    <span style="color:#a78bfa;">${(item.language || 'en').toUpperCase()}</span>
                    <span style="color:#444;">${new Date(item.timestamp).toLocaleTimeString()}</span>
                </div>
            </div>
        </div>`).join('');
}

function replayHistory(index) {
    const item = queryHistory[index];
    if (item.type === 'video') displayVideoResults(item.data);
    else displayResults(item.data);
    document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
}

// ─── Loading Overlay ──────────────────────────────────────
function showLoading(type) {
    document.getElementById('loadingOverlay').classList.remove('hidden');
    const stepsEl = document.getElementById('loadingSteps');
    const noteEl = document.getElementById('loadingNote');

    if (type === 'video') {
        document.getElementById('loadingTitle').textContent = 'Generating Video';
        document.getElementById('loadingText').textContent = 'This may take 1–3 minutes on free tier';
        stepsEl.style.display = 'flex';
        noteEl.textContent = '⏱ Video generation is CPU-intensive — please wait';
        // reset steps
        ['step1','step2','step3','step4'].forEach(s => setStep(s, ''));
    } else {
        document.getElementById('loadingTitle').textContent = 'Processing';
        document.getElementById('loadingText').textContent = 'Analyzing your query…';
        stepsEl.style.display = 'none';
        noteEl.textContent = '';
    }
}

function hideLoading() {
    document.getElementById('loadingOverlay').classList.add('hidden');
}

function updateLoadingText(text) {
    document.getElementById('loadingText').textContent = text;
}

// ─── Utilities ────────────────────────────────────────────
function askQuestion(question) {
    document.getElementById('queryInput').value = question;
    document.getElementById('queryInput').focus();
    document.getElementById('queryForm').scrollIntoView({ behavior: 'smooth' });
}

// ─── Health Check ─────────────────────────────────────────
fetch(`${API_BASE}/api/health`)
    .then(r => r.json())
    .then(() => {
        const b = document.getElementById('statusBadge');
        b.innerHTML = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#4ade80;margin-right:6px;"></span>Online';
        b.style.borderColor = '#166534';
        b.style.color = '#4ade80';
    })
    .catch(() => {
        const b = document.getElementById('statusBadge');
        b.innerHTML = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#f87171;margin-right:6px;"></span>Offline';
        b.style.borderColor = '#7f1d1d';
        b.style.color = '#f87171';
    });

// ─── Usage ────────────────────────────────────────────────
async function fetchUsage() {
    try {
        const res = await fetch(`${API_BASE}/api/usage`);
        const data = await res.json();
        const el = document.getElementById('usageIndicator');
        if (!el) return;
        el.innerHTML = `
            <span style="color:#6b7099;">Video</span>
            <span style="color:${data.video.remaining===0?'#f87171':'#c4c8e0'}">${data.video.remaining}/${data.video.limit}</span>
            <span style="color:#333;">•</span>
            <span style="color:#6b7099;">Audio</span>
            <span style="color:${data.audio.remaining===0?'#f87171':'#c4c8e0'}">${data.audio.remaining}/${data.audio.limit}</span>`;
    } catch(e) {}
}
fetchUsage();

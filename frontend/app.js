const API_BASE = '';

// ─── State ───────────────────────────────────────────────
let queryHistory = []; // [{query, format, language, output, timestamp}]

// ─── Markdown Parser ─────────────────────────────────────
function parseMarkdown(text) {
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
        .replace(/\*(.*?)\*/g, '<em class="text-zinc-300">$1</em>')
        .replace(/^### (.*$)/gm, '<h3 class="text-base font-semibold text-white mt-4 mb-1">$1</h3>')
        .replace(/^## (.*$)/gm, '<h2 class="text-lg font-semibold text-white mt-6 mb-2">$1</h2>')
        .replace(/^- (.*$)/gm, '<li class="ml-4 list-disc text-zinc-300">$1</li>')
        .replace(/^(\d+)\. (.*$)/gm, '<li class="ml-4 text-zinc-300"><span class="text-blue-400 font-mono mr-2">$1.</span>$2</li>')
        .replace(/\n\n/g, '</p><p class="mt-3 text-zinc-300">')
        .replace(/\n/g, '<br>');
}

// ─── Upload Handling ──────────────────────────────────────
document.getElementById('fileInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const statusDiv = document.getElementById('uploadStatus');
    statusDiv.classList.remove('hidden');
    statusDiv.innerHTML = `
        <div class="flex items-center gap-3 p-4 rounded-lg bg-blue-500/10 border border-blue-800">
            <div class="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
            <p class="text-blue-400 text-sm mono">Uploading ${file.name}...</p>
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
        statusDiv.innerHTML = `<div class="p-4 rounded border border-red-900 text-red-400 text-sm">Upload failed: ${error.message}</div>`;
    }
});

function renderDocumentList(names) {
    const statusDiv = document.getElementById('uploadStatus');
    statusDiv.classList.remove('hidden');
    statusDiv.innerHTML = `
        <div class="p-4 rounded border border-zinc-700 bg-zinc-900">
            <p class="text-xs text-zinc-500 mono mb-2">LOADED DOCUMENTS (${names.length})</p>
            <div class="flex flex-wrap gap-2">
                ${names.map(name => `
                    <div class="flex items-center gap-2 px-3 py-1 bg-zinc-800 rounded text-sm">
                        <span class="text-green-400">✓</span>
                        <span>${name}</span>
                        <button onclick="removeDocument('${name}')" class="text-zinc-600 hover:text-red-400 ml-1">✕</button>
                    </div>
                `).join('')}
            </div>
            <label for="fileInput" class="mt-3 inline-block text-xs text-blue-400 hover:text-blue-300 cursor-pointer">+ Add another document</label>
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
    } catch (e) {
        console.error('Remove failed:', e);
    }
}

// ─── Query Submission ─────────────────────────────────────
document.getElementById('queryForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = document.getElementById('queryInput').value;
    const language = document.getElementById('languageSelect').value;
    const formatHint = document.getElementById('formatHint').value;

    showLoading('Analyzing query...');

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
    updateLoadingText('Generating explanation...');

    const formData = new FormData();
    formData.append('query', query);
    formData.append('language', language);
    formData.append('generate_audio', 'true');
    formData.append('format_hint', formatHint);

    const response = await fetch(`${API_BASE}/api/explain`, { method: 'POST', body: formData });
    const data = await response.json();
    if (response.status === 429) { hideLoading(); alert(data.detail); fetchUsage(); return; }

    if (data.format === 'video') {
        updateLoadingText('Switching to video mode...');
        await generateVideo(query, language);
        return;
    }

    hideLoading();
    displayResults(data);
    addToHistory(query, data.detected_language, data.agent_decision.format, 'text', data);
}

// ─── Generate Video ───────────────────────────────────────
async function generateVideo(query, language) {
    updateLoadingText('Planning scenes...');

    const formData = new FormData();
    formData.append('query', query);
    formData.append('language', language);

    setTimeout(() => updateLoadingText('Rendering diagram...'), 3000);
    setTimeout(() => updateLoadingText('Generating narration...'), 8000);
    setTimeout(() => updateLoadingText('Composing video...'), 15000);

    const response = await fetch(`${API_BASE}/api/generate-video`, { method: 'POST', body: formData });
    const data = await response.json();
    hideLoading();
    if (response.status === 429) { alert(data.detail); fetchUsage(); return; }
    displayVideoResults(data);
    fetchUsage();
    addToHistory(query, data.detected_language, 'video', 'video', data);
}

// ─── Display Results ──────────────────────────────────────
function displayResults(data) {
    const resultsSection = document.getElementById('resultsSection');
    resultsSection.style.display = 'block';

    const decision = data.agent_decision;
    document.getElementById('agentDecision').innerHTML = `
        <div class="grid grid-cols-3 gap-3 mb-4">
            <div class="p-3 rounded border border-zinc-800 bg-zinc-900 text-center">
                <p class="text-xs text-zinc-600 mono mb-1">FORMAT</p>
                <p class="font-semibold text-blue-400">${decision.format.toUpperCase()}</p>
            </div>
            <div class="p-3 rounded border border-zinc-800 bg-zinc-900 text-center">
                <p class="text-xs text-zinc-600 mono mb-1">COMPLEXITY</p>
                <p class="font-semibold capitalize">${decision.complexity}</p>
            </div>
            <div class="p-3 rounded border border-zinc-800 bg-zinc-900 text-center">
                <p class="text-xs text-zinc-600 mono mb-1">LANGUAGE</p>
                <p class="font-semibold text-purple-400">${(data.detected_language || 'en').toUpperCase()}</p>
            </div>
        </div>
        <div class="p-3 rounded border border-zinc-800 bg-zinc-900 text-xs text-zinc-500 mono">
            AI: ${decision.reasoning}
        </div>`;

    let explanationHTML = `
        <div class="mt-6 text-zinc-300 leading-8">
            <p class="mt-3 text-zinc-300">${parseMarkdown(data.explanation.text)}</p>
        </div>`;

    if (data.audio) {
        explanationHTML += `
            <div class="mt-6 p-4 rounded border border-zinc-800 bg-zinc-900">
                <div class="flex items-center justify-between mb-3">
                    <p class="text-sm font-medium">Audio Narration <span class="text-xs text-zinc-600 mono ml-2">${data.audio.provider}</span></p>
                    <a href="${API_BASE}/api/audio/${data.audio.filename}" download class="text-xs text-blue-400 hover:text-blue-300">Download</a>
                </div>
                <audio controls class="w-full">
                    <source src="${API_BASE}/api/audio/${data.audio.filename}" type="audio/mpeg">
                </audio>
            </div>`;
    }

    // PDF Export button
    if (data.pdf_export) {
        explanationHTML += `
            <div class="mt-4">
                <a href="${API_BASE}/api/export/${data.pdf_export}" download
                   class="inline-flex items-center gap-2 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded text-sm transition">
                    📄 Download as PDF
                </a>
            </div>`;
    }

    document.getElementById('explanationOutput').innerHTML = explanationHTML;
    resultsSection.scrollIntoView({ behavior: 'smooth' });
}

// ─── Display Video Results ────────────────────────────────
function displayVideoResults(data) {
    const resultsSection = document.getElementById('resultsSection');
    resultsSection.style.display = 'block';

    document.getElementById('agentDecision').innerHTML = `
        <div class="p-4 rounded border border-zinc-800 bg-zinc-900 flex items-center gap-6 text-sm mono">
            <span class="text-green-400">✓ VIDEO</span>
            <span class="text-zinc-500">${data.scenes} scenes</span>
            <span class="text-zinc-500">${data.duration}s</span>
            <span class="text-zinc-500">${data.audio_clips} audio tracks</span>
            <span class="text-purple-400">${(data.detected_language || 'en').toUpperCase()}</span>
        </div>`;

    document.getElementById('explanationOutput').innerHTML = `
        <div class="mt-4 rounded overflow-hidden border border-zinc-800">
            <video controls class="w-full aspect-video bg-black" autoplay>
                <source src="${API_BASE}${data.video_url}" type="video/mp4">
            </video>
        </div>
        <div class="mt-4 flex gap-3">
            <a href="${API_BASE}${data.video_url}" download
               class="flex-1 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded text-center transition">
                Download MP4
            </a>
            <button onclick="location.reload()"
                    class="px-4 py-2 border border-zinc-700 hover:border-zinc-600 text-sm rounded transition">
                New Query
            </button>
        </div>`;

    resultsSection.scrollIntoView({ behavior: 'smooth' });
}

// ─── Query History ────────────────────────────────────────
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
        <div class="p-3 rounded border border-zinc-800 bg-zinc-900 hover:border-zinc-700 transition cursor-pointer"
             onclick="replayHistory(${i})">
            <div class="flex items-center justify-between">
                <p class="text-sm text-white truncate flex-1 mr-4">${item.query}</p>
                <div class="flex items-center gap-2 shrink-0">
                    <span class="text-xs mono text-blue-400">${item.format.toUpperCase()}</span>
                    <span class="text-xs mono text-purple-400">${(item.language || 'en').toUpperCase()}</span>
                    <span class="text-xs text-zinc-600">${new Date(item.timestamp).toLocaleTimeString()}</span>
                </div>
            </div>
        </div>`).join('');
}

function replayHistory(index) {
    const item = queryHistory[index];
    if (item.type === 'video') {
        displayVideoResults(item.data);
    } else {
        displayResults(item.data);
    }
    document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
}

// ─── Utilities ────────────────────────────────────────────
function showLoading(text) {
    document.getElementById('loadingOverlay').classList.remove('hidden');
    document.getElementById('loadingText').textContent = text;
}
function hideLoading() {
    document.getElementById('loadingOverlay').classList.add('hidden');
}
function updateLoadingText(text) {
    document.getElementById('loadingText').textContent = text;
}
function askQuestion(question) {
    document.getElementById('queryInput').value = question;
    document.getElementById('queryInput').focus();
    document.getElementById('queryForm').scrollIntoView({ behavior: 'smooth' });
}

// ─── Health Check ─────────────────────────────────────────
fetch(`${API_BASE}/api/health`)
    .then(r => r.json())
    .then(() => {
        const badge = document.getElementById('statusBadge');
        badge.innerHTML = '<span class="inline-block w-2 h-2 rounded-full bg-green-500 mr-1"></span>Online';
        badge.className = 'px-2 py-1 rounded text-xs bg-zinc-900 border border-green-900 text-green-400';
    })
    .catch(() => {
        const badge = document.getElementById('statusBadge');
        badge.innerHTML = '<span class="inline-block w-2 h-2 rounded-full bg-red-500 mr-1"></span>Backend Offline';
        badge.className = 'px-2 py-1 rounded text-xs bg-zinc-900 border border-red-900 text-red-400';
    });


// ─── Usage Indicator ──────────────────────────────────────
async function fetchUsage() {
    try {
        const res = await fetch(`${API_BASE}/api/usage`);
        const data = await res.json();
        const el = document.getElementById('usageIndicator');
        if (!el) return;
        el.innerHTML = `
            <span class="text-zinc-600">Video</span>
            <span class="${data.video.remaining === 0 ? 'text-red-400' : 'text-zinc-400'}">${data.video.remaining}/${data.video.limit}</span>
            <span class="text-zinc-700">•</span>
            <span class="text-zinc-600">Audio</span>
            <span class="${data.audio.remaining === 0 ? 'text-red-400' : 'text-zinc-400'}">${data.audio.remaining}/${data.audio.limit}</span>
        `;
    } catch(e) {}
}
fetchUsage();
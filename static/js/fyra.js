// ── SocketIO ─────────────────────────────────────────────────
const _token = new URLSearchParams(window.location.search).get('token') || '';
const socket = io({ query: { token: _token } });

// ── DOM ──────────────────────────────────────────────────────
const canvas       = document.getElementById('orbCanvas');
const textInput    = document.getElementById('textInput');
const sendBtn      = document.getElementById('sendBtn');
const micBtn       = document.getElementById('micBtn');
const statusDot    = document.getElementById('statusDot');
const orbStateText = document.getElementById('orbStateText');
const orbResponse  = document.getElementById('orbResponse');
const convLog      = document.getElementById('conversationLog');
const lastIntentEl = document.getElementById('lastIntent');

// ── State ────────────────────────────────────────────────────
let orbState = 'idle';
let time = 0;
const STATE_LABEL = { idle: 'standby', listening: 'listening', processing: 'thinking', speaking: 'speaking', searching: 'browsing' };

function setOrbState(state) {
    if (state === orbState) return;
    orbState = state;
    orbStateText.textContent = STATE_LABEL[state] || state;
    statusDot.className = 'status-indicator ' + (state !== 'idle' ? state : '');
    setTargets(state);
}

// ── Response display ─────────────────────────────────────────
let responseFadeTimer = null;
let streamingText = '';

function showResponse(text) {
    if (responseFadeTimer) clearTimeout(responseFadeTimer);
    orbResponse.textContent = text;
    orbResponse.classList.add('visible');
    responseFadeTimer = setTimeout(() => orbResponse.classList.remove('visible'), 3000);
}

// ── Three.js Particle Orb ─────────────────────────────────────
const scene    = new THREE.Scene();
const camera   = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 1, 3000);
camera.position.set(0, 0, 580);

const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

function resizeRenderer() {
    renderer.setSize(window.innerWidth, window.innerHeight);
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
}
resizeRenderer();
window.addEventListener('resize', resizeRenderer);

// Centre glow sprite
const glowTex = (() => {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0,   'rgba(60,140,255,0.6)');
    grad.addColorStop(0.4, 'rgba(20,80,200,0.2)');
    grad.addColorStop(1,   'rgba(0,0,0,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
})();
const glowSprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, depthWrite: false }));
glowSprite.scale.set(260, 260, 1);
scene.add(glowSprite);

// ── Particles ────────────────────────────────────────────────
const COUNT  = 6000;
const posArr = new Float32Array(COUNT * 3);
const colArr = new Float32Array(COUNT * 3);
const tgtArr = new Float32Array(COUNT * 3);
const spdArr = new Float32Array(COUNT);
const phsArr = new Float32Array(COUNT);

for (let i = 0; i < COUNT; i++) {
    const j = i * 3;
    posArr[j]   = (Math.random() - 0.5) * 600;
    posArr[j+1] = (Math.random() - 0.5) * 600;
    posArr[j+2] = (Math.random() - 0.5) * 600;
    spdArr[i] = 0.013 + Math.random() * 0.02;
    phsArr[i] = Math.random() * Math.PI * 2;
}

const geo = new THREE.BufferGeometry();
geo.setAttribute('position', new THREE.BufferAttribute(posArr, 3));
geo.setAttribute('color',    new THREE.BufferAttribute(colArr, 3));

const mat = new THREE.PointsMaterial({
    size: 1.8,
    vertexColors: true,
    transparent: true,
    opacity: 0.88,
    sizeAttenuation: true,
    depthWrite: false,
});

const cloud = new THREE.Points(geo, mat);
scene.add(cloud);

function rndSphere(r) {
    const u = Math.random() * Math.PI * 2;
    const v = Math.acos(2 * Math.random() - 1);
    return [Math.sin(v) * Math.cos(u) * r, Math.sin(v) * Math.sin(u) * r, Math.cos(v) * r];
}

function setTargets(state) {
    for (let i = 0; i < COUNT; i++) {
        const j = i * 3;
        let x, y, z;
        if (state === 'idle') {
            const r = 90 + Math.random() * 70;
            const [sx, sy, sz] = rndSphere(r);
            x = sx * 2.2; y = sy * 0.58; z = sz * 0.82;
        } else if (state === 'listening') {
            const r = 185 + Math.random() * 105;
            [x, y, z] = rndSphere(r);
        } else if (state === 'processing' || state === 'searching') {
            const r = 30 + Math.random() * 85;
            [x, y, z] = rndSphere(r);
        } else {
            const r = 80 + Math.random() * 80;
            [x, y, z] = rndSphere(r);
        }
        tgtArr[j] = x; tgtArr[j+1] = y; tgtArr[j+2] = z;
    }
}
setTargets('idle');

// ── Colour palettes ───────────────────────────────────────────
// Each row: [rMin, rMax, gMin, gMax, bMin, bMax]
const PALETTES = [
    [0.05, 0.60, 0.25, 0.80, 0.65, 1.00], // electric blue
    [0.40, 0.80, 0.05, 0.30, 0.70, 1.00], // violet
    [0.02, 0.20, 0.55, 1.00, 0.45, 0.80], // emerald
    [0.60, 1.00, 0.05, 0.30, 0.25, 0.55], // crimson
    [0.65, 1.00, 0.50, 0.90, 0.05, 0.30], // gold
    [0.60, 1.00, 0.05, 0.35, 0.55, 0.90], // magenta
];
const PALETTE_SECS = 12; // seconds each palette holds before blending to next

function animate() {
    requestAnimationFrame(animate);
    time += 0.016;

    const speedMult = orbState === 'processing' ? 3.8 : orbState === 'searching' ? 5 : orbState === 'speaking' ? 2 : 1;
    cloud.rotation.y += 0.0022 * speedMult;

    const pulse = orbState === 'speaking' ? 1 + Math.sin(time * 4.5) * 0.11 : 1;
    const drift = orbState === 'processing' ? 1.8 : 0.55;

    // Palette cycling — smooth ease-in-out blend between palettes
    const pi  = Math.floor(time / PALETTE_SECS) % PALETTES.length;
    const ni  = (pi + 1) % PALETTES.length;
    const pt  = (time % PALETTE_SECS) / PALETTE_SECS;
    const ps  = pt < 0.5 ? 2 * pt * pt : -1 + (4 - 2 * pt) * pt;
    const P = PALETTES[pi], N = PALETTES[ni];
    const rMn = P[0]+(N[0]-P[0])*ps, rMx = P[1]+(N[1]-P[1])*ps;
    const gMn = P[2]+(N[2]-P[2])*ps, gMx = P[3]+(N[3]-P[3])*ps;
    const bMn = P[4]+(N[4]-P[4])*ps, bMx = P[5]+(N[5]-P[5])*ps;
    glowSprite.material.color.setRGB((rMn+rMx)*0.5, (gMn+gMx)*0.5, (bMn+bMx)*0.5);

    for (let i = 0; i < COUNT; i++) {
        const j = i * 3;
        // Lerp toward target
        posArr[j]   += (tgtArr[j]   - posArr[j])   * spdArr[i];
        posArr[j+1] += (tgtArr[j+1] - posArr[j+1]) * spdArr[i];
        posArr[j+2] += (tgtArr[j+2] - posArr[j+2]) * spdArr[i];
        // Organic drift
        posArr[j]   += Math.sin(time * 0.48 + phsArr[i]) * drift;
        posArr[j+1] += Math.cos(time * 0.37 + phsArr[i] * 1.3) * drift;

        // Depth-based colour using current palette
        const depth = Math.max(0, Math.min(1, (posArr[j+2] + 300) / 600));
        colArr[j]   = rMn + depth * (rMx - rMn);
        colArr[j+1] = gMn + depth * (gMx - gMn);
        colArr[j+2] = bMn + depth * (bMx - bMn);
    }

    geo.attributes.position.needsUpdate = true;
    geo.attributes.color.needsUpdate    = true;

    cloud.scale.setScalar(pulse);
    glowSprite.scale.set(260 * pulse, 260 * pulse, 1);

    renderer.render(scene, camera);
}
animate();

// ── Audio queue (for streaming TTS) ──────────────────────────
let audioQueue     = [];
let isPlayingAudio = false;
let activeSource   = null;
let audioContext   = null;
let _fyraPlaying   = false;  // true while Fyra's own audio is playing — suppresses VAD
let _autoListenTimer = null;

function ensureAudioContext() {
    if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state === 'suspended') audioContext.resume();
}

function playNextChunk() {
    if (audioQueue.length === 0) {
        isPlayingAudio = false;
        if (orbState === 'speaking') setOrbState('idle');
        // Auto-open mic 400ms after last audio chunk ends (continuous voice mode)
        if (!vadActive && !greetingMode) {
            setTimeout(() => {
                _fyraPlaying = false;
                if (orbState === 'idle' && !vadActive && !greetingMode) {
                    startVAD();
                    _autoListenTimer = setTimeout(() => {
                        if (vadActive && orbState === 'listening') stopVAD(false);
                    }, 4000);
                }
            }, 400);
        } else {
            _fyraPlaying = false;
        }
        return;
    }
    isPlayingAudio = true;
    _fyraPlaying   = true;
    const b64 = audioQueue.shift();
    if (!b64) { playNextChunk(); return; }

    const binary = atob(b64);
    const buf = new ArrayBuffer(binary.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < binary.length; i++) view[i] = binary.charCodeAt(i);

    ensureAudioContext();
    if (activeSource) { try { activeSource.stop(); } catch (_) {} activeSource = null; }

    audioContext.decodeAudioData(buf, decoded => {
        const src = audioContext.createBufferSource();
        src.buffer = decoded;
        src.connect(audioContext.destination);
        setOrbState('speaking');
        src.start(0);
        src.onended = () => { activeSource = null; playNextChunk(); };
        activeSource = src;
    }, err => {
        console.error('[Audio] decode error:', err);
        playNextChunk();
    });
}

// ── WebRTC VAD ────────────────────────────────────────────────
let vadStream    = null;
let vadAnalyser  = null;
let vadMonitor   = null;
let silenceTimer = null;
let vadActive    = false;

const VAD_THRESHOLD    = 0.010; // RMS voice threshold
const SILENCE_MS       = 2800;  // stop after 2.8s silence

function getRMS(analyser) {
    const buf = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let s of buf) sum += s * s;
    return Math.sqrt(sum / buf.length);
}

async function startVAD() {
    if (vadActive) return;
    ensureAudioContext();
    try {
        vadStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        const source = audioContext.createMediaStreamSource(vadStream);
        vadAnalyser = audioContext.createAnalyser();
        vadAnalyser.fftSize = 512;
        source.connect(vadAnalyser);
        vadActive = true;

        setOrbState('listening');
        micBtn.classList.add('active');


        // Start speech recognition
        if (recognition) recognition.start();

        // Monitor silence (VAD threshold raised when Fyra is playing to suppress self-echo)
        function monitor() {
            if (!vadActive) return;
            const rms = getRMS(vadAnalyser);
            const threshold = _fyraPlaying ? 0.9 : VAD_THRESHOLD;
            if (rms > threshold) {
                if (_autoListenTimer) { clearTimeout(_autoListenTimer); _autoListenTimer = null; }
                if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
            } else if (!silenceTimer) {
                silenceTimer = setTimeout(() => stopVAD(true), SILENCE_MS);
            }
            vadMonitor = requestAnimationFrame(monitor);
        }
        monitor();
    } catch (e) {
        console.error('[VAD] mic error:', e);
    }
}

function stopVAD(sendResult = false) {
    vadActive = false;
    if (vadMonitor)   { cancelAnimationFrame(vadMonitor); vadMonitor = null; }
    if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
    if (vadStream)    { vadStream.getTracks().forEach(t => t.stop()); vadStream = null; }
    if (recognition && sendResult) recognition.stop();
    micBtn.classList.remove('active');
    if (orbState === 'listening') setOrbState('idle');
}

// Speech recognition
let recognition = null;
let partialTranscript = '';

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SR();
    recognition.continuous    = true;
    recognition.interimResults = true;
    recognition.lang          = 'en-US';

    recognition.onresult = e => {
        let interim = '';
        let final   = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
            const t = e.results[i][0].transcript;
            e.results[i].isFinal ? (final += t) : (interim += t);
        }
        partialTranscript = interim;
        // Reset silence timer on any speech activity
        if ((interim || final) && silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
        }
        if (final) {
            stopVAD(false);
            sendMessage(final.trim());
        }
    };

    recognition.onerror = () => stopVAD(false);
    recognition.onend   = () => { if (vadActive) recognition.start(); };
}

micBtn.addEventListener('click', () => {
    ensureAudioContext();
    vadActive ? stopVAD(true) : startVAD();
});

// ── Voice ID ──────────────────────────────────────────────────
let _voiceIdSampling   = false;
let _voiceIdAnalyser   = null;
let _voiceIdStream     = null;
let _voiceIdSamples    = [];  // collected RMS values
const VOICE_ID_SECS    = 3;

async function _collectVoiceSample() {
    if (_voiceIdSampling) return;
    _voiceIdSampling = true;
    _voiceIdSamples  = [];
    try {
        ensureAudioContext();
        const stream   = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        const source   = audioContext.createMediaStreamSource(stream);
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        _voiceIdStream   = stream;
        _voiceIdAnalyser = analyser;

        const freqBuf = new Float32Array(analyser.frequencyBinCount);
        const timeBuf = new Float32Array(analyser.fftSize);
        const endTime = Date.now() + VOICE_ID_SECS * 1000;

        function sample() {
            if (Date.now() >= endTime || !_voiceIdSampling) {
                // Finish and send
                stream.getTracks().forEach(t => t.stop());
                _voiceIdSampling = false;
                if (_voiceIdSamples.length > 0) {
                    const avgRms  = _voiceIdSamples.reduce((a, b) => a + b, 0) / _voiceIdSamples.length;
                    socket.emit('voice_sample', { avg_rms: avgRms });
                }
                return;
            }
            analyser.getFloatTimeDomainData(timeBuf);
            let sum = 0;
            for (let s of timeBuf) sum += s * s;
            _voiceIdSamples.push(Math.sqrt(sum / timeBuf.length));
            requestAnimationFrame(sample);
        }
        sample();
    } catch (e) {
        _voiceIdSampling = false;
    }
}

socket.on('voice_id_result', data => {
    if (data.matched && data.person) {
        // Server recognised the voice — skip name prompt, emit as greeting
        greetingMode = false;
        textInput.placeholder = 'ask fyra anything...';
        socket.emit('greeting_response', { text: data.person });
    }
    // If not matched, fall through to the normal name prompt (already shown)
});

// ── Greeting mode ─────────────────────────────────────────────
// false | 'name' | 'gender'
let greetingMode = false;

// ── Send ──────────────────────────────────────────────────────
function sendMessage(text) {
    text = text.trim();
    if (!text) return;
    ensureAudioContext();
    dismissChart();

    if (greetingMode === 'name') {
        greetingMode = false;
        textInput.placeholder = 'ask fyra anything...';
        setOrbState('processing');
        socket.emit('greeting_response', { text });
        textInput.value = '';
        return;
    }

    if (greetingMode === 'gender') {
        greetingMode = false;
        textInput.placeholder = 'ask fyra anything...';
        setOrbState('processing');
        socket.emit('greeting_gender', { text });
        textInput.value = '';
        return;
    }

    setOrbState('processing');
    socket.emit('user_message', { text });
    textInput.value = '';
}

// ── SocketIO events ───────────────────────────────────────────
socket.on('stream_start', () => {
    streamingText = '';
    if (activeSource) { try { activeSource.stop(); } catch (_) {} activeSource = null; }
    audioQueue = [];
    isPlayingAudio = false;
    if (responseFadeTimer) clearTimeout(responseFadeTimer);
    orbResponse.textContent = '';
    orbResponse.classList.remove('visible');
});

socket.on('stream_chunk', data => {
    if (orbState === 'searching') setOrbState('processing');
    streamingText += data.text;
});

socket.on('tool_use', data => {
    if (data.tool === 'web_search' || data.tool === 'fetch_page') setOrbState('searching');
});

socket.on('audio_chunk', data => {
    if (data.audio) {
        audioQueue.push(data.audio);
        if (!isPlayingAudio) playNextChunk();
    }
});

socket.on('stream_end', data => {
    if (data.intent) lastIntentEl.textContent = data.intent;
    if (streamingText) {
        orbResponse.textContent = streamingText;
        orbResponse.classList.add('visible');
    }
    responseFadeTimer = setTimeout(() => orbResponse.classList.remove('visible'), 3000);
    // After greeting completes, send voice sample attribution if we have one
    if (data.intent === 'greeting' && data.person) {
        socket.emit('voice_learn_confirm', { person: data.person });
    }
    // Don't go idle here — let playNextChunk() handle it when audio actually finishes
});

socket.on('status', data => setOrbState(data.state));
socket.on('connect', () => {
    setOrbState('idle');
    document.getElementById('connText').textContent = 'connected';
    if (window.FYRA_STARTUP_CONTEXT) {
        const msg = window.FYRA_STARTUP_CONTEXT;
        window.FYRA_STARTUP_CONTEXT = '';
        setTimeout(() => sendMessage(msg), 800);
    }
});
socket.on('disconnect', () => { document.getElementById('connText').textContent = 'offline'; });

socket.on('profile_update', data => {
    const f = data.favour || {}, fi = data.fiyin || {};
    document.getElementById('favourName').textContent  = (f.name  || 'FAVOUR').toUpperCase();
    document.getElementById('favourLikes').textContent = f.likes?.length  ? f.likes.join(', ')  : '—';
    document.getElementById('fiyinName').textContent   = (fi.name || 'FIYIN').toUpperCase();
    document.getElementById('fiyinLikes').textContent  = fi.likes?.length ? fi.likes.join(', ') : '—';
    document.getElementById('openTasks').textContent   = data.open_tasks > 0 ? `${data.open_tasks} OPEN` : 'NONE';
});

socket.on('greeting_prompt', data => {
    greetingMode = 'name';
    textInput.placeholder = 'type your name...';
    showResponse(data.text);
    if (data.audio) {
        ensureAudioContext();
        audioQueue.push(data.audio);
        if (!isPlayingAudio) playNextChunk();
    }
    // Silently try voice recognition in parallel with the name prompt
    setTimeout(() => _collectVoiceSample(), 500);
});

socket.on('voice_learn', () => {
    // Collect a training sample for the identified person
    setTimeout(() => {
        _collectVoiceSample();
    }, 800);
});

socket.on('greeting_ask_gender', data => {
    greetingMode = 'gender';
    textInput.placeholder = 'male or female...';
    showResponse(data.text);
    if (data.audio) {
        ensureAudioContext();
        audioQueue.push(data.audio);
        if (!isPlayingAudio) playNextChunk();
    }
});

socket.on('conversation_history', () => {});
socket.on('startup_brief', () => {});
socket.on('voice_set', () => {});

// ── Proactive brief (market/scheduler push) ───────────────────
socket.on('proactive_brief', data => {
    if (data.text) showResponse(data.text);
});

// ── Chart panel ───────────────────────────────────────────────
let _chartInstance = null;
let _chartDismissTimer = null;

function showChart(payload) {
    const panel   = document.getElementById('chartPanel');
    const titleEl = document.getElementById('chartTitle');
    const canvas  = document.getElementById('chartCanvas');

    titleEl.textContent = payload.title || '';

    if (_chartInstance) { _chartInstance.destroy(); _chartInstance = null; }
    if (_chartDismissTimer) clearTimeout(_chartDismissTimer);

    _chartInstance = new Chart(canvas, {
        type: payload.type || 'bar',
        data: {
            labels: payload.labels || [],
            datasets: (payload.datasets || []).map(ds => ({
                label: ds.label,
                data: ds.data,
                backgroundColor: ds.data.map(v => v >= 0 ? 'rgba(0,200,120,0.55)' : 'rgba(255,60,80,0.55)'),
                borderColor:     ds.data.map(v => v >= 0 ? 'rgba(0,220,140,0.9)' : 'rgba(255,80,100,0.9)'),
                borderWidth: 1,
                borderRadius: 4,
            })),
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { labels: { color: 'rgba(180,220,255,0.7)', font: { size: 10 } } },
            },
            scales: {
                x: { ticks: { color: 'rgba(150,200,255,0.7)', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: 'rgba(150,200,255,0.7)', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
            },
        },
    });

    panel.style.display = 'block';
    _chartDismissTimer = setTimeout(() => dismissChart(), 10000);
}

function dismissChart() {
    const panel = document.getElementById('chartPanel');
    panel.style.display = 'none';
    if (_chartInstance) { _chartInstance.destroy(); _chartInstance = null; }
    if (_chartDismissTimer) { clearTimeout(_chartDismissTimer); _chartDismissTimer = null; }
}

socket.on('chart_data', payload => {
    try { showChart(payload); } catch (e) { console.error('[Chart]', e); }
});

// Dismiss chart when user speaks
const _origSendMessage = sendMessage;
document.getElementById('chartPanel').addEventListener('click', dismissChart);

// ── Input ─────────────────────────────────────────────────────
sendBtn.addEventListener('click', () => sendMessage(textInput.value));
textInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(textInput.value); });
textInput.addEventListener('input', () => {
    textInput.placeholder = textInput.value.length > 300
        ? 'paste a filing or article to interpret...'
        : 'ask fyra anything...';
});
document.addEventListener('touchstart', () => ensureAudioContext(), { once: true, passive: true });

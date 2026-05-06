// ── SocketIO ─────────────────────────────────────────────────
const socket = io();

// ── DOM ──────────────────────────────────────────────────────
const canvas       = document.getElementById('orbCanvas');
const ctx          = canvas.getContext('2d');
const textInput    = document.getElementById('textInput');
const sendBtn      = document.getElementById('sendBtn');
const micBtn       = document.getElementById('micBtn');
const statusDot    = document.getElementById('statusDot');
const orbStateText = document.getElementById('orbStateText');
const orbResponse  = document.getElementById('orbResponse');
const convLog      = document.getElementById('conversationLog');
const lastIntentEl = document.getElementById('lastIntent');

let responseFadeTimer = null;

function showResponse(text) {
    if (responseFadeTimer) clearTimeout(responseFadeTimer);
    orbResponse.textContent = text;
    orbResponse.classList.add('visible');
    // Fade out after 12 seconds
    responseFadeTimer = setTimeout(() => {
        orbResponse.classList.remove('visible');
    }, 12000);
}

// ── State ────────────────────────────────────────────────────
let orbState = 'idle';
let time = 0;

const STATE_LABEL  = { idle: 'STANDBY', listening: 'LISTENING', processing: 'THINKING', speaking: 'SPEAKING' };

// ── Particle System ───────────────────────────────────────────
const N = 1600;
const pts = Array.from({ length: N }, () => ({
    x: (Math.random() - 0.5) * 500,
    y: (Math.random() - 0.5) * 500,
    z: (Math.random() - 0.5) * 500,
    tx: 0, ty: 0, tz: 0,
    phase: Math.random() * Math.PI * 2,
    spd:  0.016 + Math.random() * 0.022,
    sz:   Math.random() * 1.4 + 0.4,
    op:   0.35 + Math.random() * 0.65,
}));

let cloudRotY = 0;

function rndSphere(r) {
    const u = Math.random(), v = Math.random();
    const th = 2 * Math.PI * u;
    const ph = Math.acos(2 * v - 1);
    return {
        x: Math.sin(ph) * Math.cos(th) * r,
        y: Math.sin(ph) * Math.sin(th) * r,
        z: Math.cos(ph) * r,
    };
}

function setTargets(state) {
    pts.forEach(p => {
        let t;
        if (state === 'idle') {
            // Elongated horizontal capsule — the galaxy shape
            const r = 90 + Math.random() * 75;
            const s = rndSphere(r);
            t = { x: s.x * 2.2, y: s.y * 0.6, z: s.z * 0.8 };
        } else if (state === 'listening') {
            // Large scattered cloud
            const r = 170 + Math.random() * 110;
            t = rndSphere(r);
        } else if (state === 'processing') {
            // Dense compressed brain cluster
            const r = 35 + Math.random() * 85;
            t = rndSphere(r);
        } else {
            // Speaking — medium sphere
            const r = 80 + Math.random() * 80;
            t = rndSphere(r);
        }
        p.tx = t.x; p.ty = t.y; p.tz = t.z;
    });
}

// Initialise targets
setTargets('idle');

// ── Set state ─────────────────────────────────────────────────
function setOrbState(state) {
    if (state === orbState) return;
    orbState = state;
    orbStateText.textContent = STATE_LABEL[state];
    statusDot.className = 'status-indicator ' + (state !== 'idle' ? state : '');
    setTargets(state);
}

// ── Draw ──────────────────────────────────────────────────────
function drawOrb() {
    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H / 2;
    ctx.clearRect(0, 0, W, H);
    time += 0.016;

    const speedMult = orbState === 'processing' ? 3.5 : orbState === 'speaking' ? 2 : 1;
    cloudRotY += 0.0025 * speedMult;

    const pulse = orbState === 'speaking'
        ? 1 + Math.sin(time * 4.5) * 0.12
        : orbState === 'listening'
        ? 1 + Math.sin(time * 1.8) * 0.04
        : 1 + Math.sin(time * 0.9) * 0.02;

    // Center glow
    const glowR = orbState === 'processing' ? 75 : orbState === 'listening' ? 130 : 95;
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR * pulse);
    glow.addColorStop(0,   'rgba(0,140,255,0.28)');
    glow.addColorStop(0.45,'rgba(0,100,220,0.12)');
    glow.addColorStop(1,   'transparent');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(cx, cy, glowR * pulse * 1.6, 0, Math.PI * 2);
    ctx.fill();

    // Rotate + project particles
    const cy_ = Math.cos(cloudRotY), sy_ = Math.sin(cloudRotY);
    const fov = 520;

    pts.forEach(p => {
        // Lerp toward target
        p.x += (p.tx - p.x) * p.spd;
        p.y += (p.ty - p.y) * p.spd;
        p.z += (p.tz - p.z) * p.spd;

        // Organic drift
        const d = orbState === 'processing' ? 1.6 : 0.5;
        p.x += Math.sin(time * 0.5 + p.phase) * d;
        p.y += Math.cos(time * 0.38 + p.phase * 1.2) * d;

        // Rotate around Y
        const rx =  p.x * cy_ + p.z * sy_;
        const rz = -p.x * sy_ + p.z * cy_;
        const ry =  p.y;

        // Perspective project
        const scale = fov / (fov + rz + 200);
        const sx = cx + rx * scale * pulse;
        const sy = cy + ry * scale * pulse;
        const depth = Math.max(0, (rz + 280) / 560);

        const size = Math.max(0.5, p.sz * scale * pulse);
        const alpha = p.op * (0.1 + 0.9 * depth);

        const bright = depth > 0.72;
        ctx.globalAlpha = alpha;
        ctx.fillStyle = bright ? '#ffffff' : depth > 0.45 ? '#55bbff' : '#1166cc';
        ctx.fillRect(sx - size * 0.5, sy - size * 0.5, size, size);
    });

    ctx.globalAlpha = 1;
    requestAnimationFrame(drawOrb);
}


// ── Conversation ──────────────────────────────────────────────
function addMessage(text, sender) {
    const div   = document.createElement('div');
    div.className = `message ${sender}-message`;
    const label = document.createElement('span');
    label.className = 'msg-label';
    label.textContent = sender === 'fyra' ? 'FYRA' : 'YOU';
    const msg = document.createElement('span');
    msg.className = 'msg-text';
    div.appendChild(label);
    div.appendChild(msg);
    convLog.appendChild(div);
    convLog.scrollTop = convLog.scrollHeight;
    sender === 'fyra' ? typeWrite(msg, text) : (msg.textContent = text);
}

function typeWrite(el, text, i = 0) {
    if (i < text.length) {
        el.textContent += text[i];
        convLog.scrollTop = convLog.scrollHeight;
        setTimeout(() => typeWrite(el, text, i + 1), 16);
    }
}

// ── Audio ─────────────────────────────────────────────────────
let activeSource = null;
let audioContext = null;

function ensureAudioContext() {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === 'suspended') {
        audioContext.resume();
    }
}

function playAudio(b64) {
    if (!b64) { setOrbState('idle'); return; }

    // Decode base64 → ArrayBuffer
    const binary = atob(b64);
    const buf = new ArrayBuffer(binary.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < binary.length; i++) view[i] = binary.charCodeAt(i);

    ensureAudioContext();

    // Stop any currently playing audio
    if (activeSource) {
        try { activeSource.stop(); } catch (_) {}
        activeSource = null;
    }

    // Decode and play via AudioContext (works in Safari)
    audioContext.decodeAudioData(buf, (decoded) => {
        const src = audioContext.createBufferSource();
        src.buffer = decoded;
        src.connect(audioContext.destination);
        setOrbState('speaking');
        src.start(0);
        src.onended = () => { activeSource = null; setOrbState('idle'); };
        activeSource = src;
    }, (err) => {
        console.error('[Audio] Decode failed:', err);
        setOrbState('idle');
    });
}

// ── Send ──────────────────────────────────────────────────────
function sendMessage(text) {
    text = text.trim();
    if (!text) return;
    setOrbState('processing');
    socket.emit('user_message', { text });
    textInput.value = '';
}

// ── Voice ─────────────────────────────────────────────────────
let recognition = null;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SR();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';
    recognition.onstart  = () => { setOrbState('listening'); micBtn.classList.add('active'); };
    recognition.onresult = e  => { micBtn.classList.remove('active'); sendMessage(e.results[0][0].transcript); };
    recognition.onerror  = () => { micBtn.classList.remove('active'); setOrbState('idle'); };
    recognition.onend    = () => micBtn.classList.remove('active');
}

let muted = false;
micBtn.addEventListener('click', () => {
    ensureAudioContext();
    if (!recognition) return;
    if (orbState === 'listening') {
        recognition.stop();
        micBtn.textContent = 'MUTE';
        micBtn.classList.remove('active');
    } else {
        recognition.start();
        micBtn.textContent = 'STOP';
        micBtn.classList.add('active');
    }
});

// ── SocketIO events ───────────────────────────────────────────
socket.on('fyra_response', data => {
    showResponse(data.text);
    if (data.intent) lastIntentEl.textContent = data.intent.replace(/_/g, ' ').toUpperCase();
    data.audio ? playAudio(data.audio) : setOrbState('idle');
});

socket.on('status',     data => setOrbState(data.state));
socket.on('connect',    ()   => { setOrbState('idle'); document.getElementById('connText').textContent = 'connected'; });
socket.on('disconnect', ()   => { document.getElementById('connText').textContent = 'offline'; statusDot.className = 'status-indicator'; statusDot.style.background = '#ff4444'; });

socket.on('profile_update', data => {
    const f = data.favour || {};
    const fi = data.fiyin  || {};

    document.getElementById('favourName').textContent =
        (f.name || 'FAVOUR').toUpperCase();
    document.getElementById('favourLikes').textContent =
        f.likes && f.likes.length ? f.likes.join(', ') : '—';

    document.getElementById('fiyinName').textContent =
        (fi.name || 'FIYIN').toUpperCase();
    document.getElementById('fiyinLikes').textContent =
        fi.likes && fi.likes.length ? fi.likes.join(', ') : '—';

    document.getElementById('openTasks').textContent =
        data.open_tasks > 0 ? `${data.open_tasks} OPEN` : 'NONE';
});

socket.on('conversation_history', data => {
    const history = data.history || [];
    // Remove default welcome message first
    convLog.innerHTML = '';
    history.forEach(turn => {
        addMessageInstant(turn.user, 'user');
        addMessageInstant(turn.fyra, 'fyra');
    });
    // Re-add welcome if history was empty
    if (history.length === 0) {
        addMessageInstant("Systems online. I'm ready, Favour — what do you need?", 'fyra');
    }
    convLog.scrollTop = convLog.scrollHeight;
});

socket.on('startup_brief', data => {
    if (data.text) showResponse(data.text);
});

socket.on('voice_set', data => {
    const el = document.getElementById('voiceStatus');
    el.textContent = data.voice_id ? data.voice_id.slice(0, 20) + '...' : 'DEFAULT';
});

// ── Voice setting ─────────────────────────────────────────────
document.getElementById('voiceSetBtn').addEventListener('click', () => {
    const voiceId = document.getElementById('voiceIdInput').value.trim();
    socket.emit('set_voice', { voice_id: voiceId });
});

// ── Add message without typewriter (for history restore) ──────
function addMessageInstant(text, sender) {
    const div   = document.createElement('div');
    div.className = `message ${sender}-message`;
    const label = document.createElement('span');
    label.className = 'msg-label';
    label.textContent = sender === 'fyra' ? 'FYRA' : 'YOU';
    const msg = document.createElement('span');
    msg.className = 'msg-text';
    msg.textContent = text;
    div.appendChild(label);
    div.appendChild(msg);
    convLog.appendChild(div);
}

// ── Input ─────────────────────────────────────────────────────
sendBtn.addEventListener('click', () => { ensureAudioContext(); sendMessage(textInput.value); });
textInput.addEventListener('keydown', e => { if (e.key === 'Enter') { ensureAudioContext(); sendMessage(textInput.value); } });
micBtn.addEventListener('touchstart', () => ensureAudioContext(), { passive: true });
document.addEventListener('touchstart', () => ensureAudioContext(), { once: true, passive: true });

// ── Start ─────────────────────────────────────────────────────
drawOrb();

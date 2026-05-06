// ── SocketIO ─────────────────────────────────────────────────
const socket = io();

// ── DOM ──────────────────────────────────────────────────────
const canvas       = document.getElementById('orbCanvas');
const ctx          = canvas.getContext('2d');
const textInput    = document.getElementById('textInput');
const sendBtn      = document.getElementById('sendBtn');
const micBtn       = document.getElementById('micBtn');
const statusDot    = document.getElementById('statusDot');
const statusText   = document.getElementById('statusText');
const orbStateText = document.getElementById('orbStateText');
const orbResponse  = document.getElementById('orbResponse');
const convLog      = document.getElementById('conversationLog');
const lastIntentEl = document.getElementById('lastIntent');
const dateTimeEl   = document.getElementById('dateTime');

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

const COLORS = {
    idle:       { node: '#00ccff', hub: '#ffffff', line: '#0099dd', glow: 'rgba(0,180,255,0.18)',  core: '#00d4ff' },
    listening:  { node: '#00ffaa', hub: '#ffffff', line: '#00cc88', glow: 'rgba(0,255,160,0.20)',  core: '#00ffbb' },
    processing: { node: '#aa88ff', hub: '#ffffff', line: '#7755ee', glow: 'rgba(130,80,255,0.22)', core: '#cc99ff' },
    speaking:   { node: '#44ddff', hub: '#ffffff', line: '#00aaff', glow: 'rgba(0,210,255,0.25)',  core: '#88eeff' },
};

const STATE_LABEL  = { idle: 'STANDBY', listening: 'LISTENING', processing: 'PROCESSING', speaking: 'SPEAKING' };
const STATUS_LABEL = { idle: 'READY',   listening: 'LISTENING', processing: 'THINKING',   speaking: 'RESPONDING' };

// ── Sphere node network ───────────────────────────────────────
const SPHERE_R    = 148;
const NODE_COUNT  = 88;
const CONN_DIST   = 68;   // max 3D distance for a connection
const MAX_CONN    = 5;    // max connections per node

// Fibonacci-distributed nodes on sphere surface
const BASE_NODES = (() => {
    const nodes = [];
    const phi = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < NODE_COUNT; i++) {
        const y  = 1 - (i / (NODE_COUNT - 1)) * 2;
        const r  = Math.sqrt(Math.max(0, 1 - y * y));
        const th = phi * i;
        nodes.push({
            bx: Math.cos(th) * r * SPHERE_R,
            by: y * SPHERE_R,
            bz: Math.sin(th) * r * SPHERE_R,
            isHub: i % 8 === 0,
        });
    }
    return nodes;
})();

// Precompute which node pairs are connected
const CONNECTIONS = (() => {
    const conns = [];
    const counts = new Array(NODE_COUNT).fill(0);
    for (let i = 0; i < NODE_COUNT; i++) {
        for (let j = i + 1; j < NODE_COUNT; j++) {
            if (counts[i] >= MAX_CONN || counts[j] >= MAX_CONN) continue;
            const dx = BASE_NODES[i].bx - BASE_NODES[j].bx;
            const dy = BASE_NODES[i].by - BASE_NODES[j].by;
            const dz = BASE_NODES[i].bz - BASE_NODES[j].bz;
            if (Math.sqrt(dx*dx + dy*dy + dz*dz) < CONN_DIST) {
                conns.push([i, j]);
                counts[i]++;
                counts[j]++;
            }
        }
    }
    return conns;
})();

// Particles that burst outward during processing
const particles = [];
function spawnParticles(cx, cy) {
    for (let i = 0; i < 18; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = 1.2 + Math.random() * 2.5;
        particles.push({
            x: cx, y: cy,
            vx: Math.cos(angle) * speed,
            vy: Math.sin(angle) * speed,
            life: 1.0,
            decay: 0.018 + Math.random() * 0.015,
            r: 1 + Math.random() * 2,
        });
    }
}

let rotY = 0;
let rotX = 0.28; // fixed slight tilt

function rotPt(bx, by, bz, ry, rx) {
    // Y rotation
    const x1 =  bx * Math.cos(ry) + bz * Math.sin(ry);
    const z1 = -bx * Math.sin(ry) + bz * Math.cos(ry);
    // X rotation
    const y2 = by * Math.cos(rx) - z1 * Math.sin(rx);
    const z2 = by * Math.sin(rx) + z1 * Math.cos(rx);
    return { x: x1, y: y2, z: z2 };
}

// ── Set state ─────────────────────────────────────────────────
let prevOrbState = 'idle';
function setOrbState(state) {
    prevOrbState = orbState;
    orbState = state;
    orbStateText.textContent = STATE_LABEL[state];
    statusText.textContent   = STATUS_LABEL[state];
    statusDot.className = 'status-indicator ' + (state !== 'idle' ? state : '');
}

// ── Draw ──────────────────────────────────────────────────────
let particleTimer = 0;

function drawOrb() {
    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H / 2;
    ctx.clearRect(0, 0, W, H);
    time += 0.016;

    const c = COLORS[orbState];
    const speedMult = orbState === 'processing' ? 3.2 : orbState === 'speaking' ? 1.6 : 1;
    rotY += 0.0038 * speedMult;

    // Pulse factor
    const pulse = orbState === 'speaking'
        ? 1 + Math.sin(time * 5.5) * 0.10
        : orbState === 'listening'
        ? 1 + Math.sin(time * 2.5) * 0.05
        : 1 + Math.sin(time * 1.2) * 0.025;

    // ── Ambient glow behind sphere ──
    const glowR = SPHERE_R * 1.15 * pulse;
    const bgGlow = ctx.createRadialGradient(cx, cy, SPHERE_R * 0.3, cx, cy, glowR * 1.4);
    bgGlow.addColorStop(0,   c.glow);
    bgGlow.addColorStop(0.6, c.glow.replace(/[\d.]+\)$/, '0.06)'));
    bgGlow.addColorStop(1,   'transparent');
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, glowR * 1.4, 0, Math.PI * 2);
    ctx.fillStyle = bgGlow;
    ctx.fill();

    // ── Project all nodes ──
    const proj = BASE_NODES.map(n => {
        const r = rotPt(n.bx, n.by, n.bz, rotY, rotX);
        const depth = (r.z + SPHERE_R) / (SPHERE_R * 2); // 0=back, 1=front
        return { x: cx + r.x * pulse, y: cy + r.y * pulse, z: r.z, depth, isHub: n.isHub };
    });

    // ── Connection lines ──
    ctx.lineWidth = 0.9;
    for (const [i, j] of CONNECTIONS) {
        const a = proj[i], b = proj[j];
        const avg = (a.depth + b.depth) * 0.5;
        if (avg < 0.08) continue;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = c.line;
        ctx.globalAlpha = avg * 0.55;
        ctx.stroke();
    }

    // ── Nodes (back to front) ──
    const sorted = proj.map((p, i) => ({ ...p, i })).sort((a, b) => a.z - b.z);
    for (const p of sorted) {
        const alpha = 0.25 + 0.75 * p.depth;
        const baseR = p.isHub ? 3.8 : 1.8;
        const nr    = baseR * (0.4 + 0.6 * p.depth) * pulse;

        if (p.isHub && p.depth > 0.35) {
            // Hub halo
            const halo = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, nr * 5);
            halo.addColorStop(0,   c.core + '55');
            halo.addColorStop(1,   'transparent');
            ctx.beginPath();
            ctx.arc(p.x, p.y, nr * 5, 0, Math.PI * 2);
            ctx.fillStyle = halo;
            ctx.globalAlpha = alpha * 0.7;
            ctx.fill();
        }

        // Node dot
        ctx.beginPath();
        ctx.arc(p.x, p.y, nr, 0, Math.PI * 2);
        ctx.fillStyle = p.isHub ? '#ffffff' : c.node;
        ctx.globalAlpha = alpha;
        ctx.fill();
    }

    // ── Processing: burst particles ──
    if (orbState === 'processing') {
        particleTimer++;
        if (particleTimer % 8 === 0) spawnParticles(cx, cy);
    } else {
        particleTimer = 0;
    }

    for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x  += p.vx;
        p.y  += p.vy;
        p.life -= p.decay;
        if (p.life <= 0) { particles.splice(i, 1); continue; }
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * p.life, 0, Math.PI * 2);
        ctx.fillStyle = c.core;
        ctx.globalAlpha = p.life * 0.8;
        ctx.fill();
    }

    // ── Listening: waveform ring ──
    if (orbState === 'listening') {
        const wR = SPHERE_R * 0.55;
        ctx.beginPath();
        for (let i = 0; i <= 80; i++) {
            const angle = (i / 80) * Math.PI * 2 - Math.PI / 2;
            const wave  = Math.sin(time * 3 + i * 0.4) * 10 + Math.sin(time * 1.8 + i * 0.8) * 5;
            const r     = wR + wave;
            const x = cx + Math.cos(angle) * r;
            const y = cy + Math.sin(angle) * r;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = c.node;
        ctx.globalAlpha = 0.45;
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }

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
    addMessage(text, 'user');
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

micBtn.addEventListener('click', () => {
    ensureAudioContext();
    if (!recognition) { alert('Voice input requires Chrome or Safari.'); return; }
    orbState === 'listening' ? recognition.stop() : recognition.start();
});

// ── SocketIO events ───────────────────────────────────────────
socket.on('fyra_response', data => {
    showResponse(data.text);
    if (data.intent) lastIntentEl.textContent = data.intent.replace(/_/g, ' ').toUpperCase();
    data.audio ? playAudio(data.audio) : setOrbState('idle');
});

socket.on('status',     data => setOrbState(data.state));
socket.on('connect',    ()   => setOrbState('idle'));
socket.on('disconnect', ()   => statusText.textContent = 'OFFLINE');

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

// ── Clock ─────────────────────────────────────────────────────
function tick() {
    const t = new Date().toTimeString().slice(0, 8);
    const d = new Date().toDateString().slice(4).toUpperCase();
    dateTimeEl.textContent = `${t} // ${d}`;
}
tick();
setInterval(tick, 1000);

// ── Start ─────────────────────────────────────────────────────
drawOrb();

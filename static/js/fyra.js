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
const convLog      = document.getElementById('conversationLog');
const lastIntentEl = document.getElementById('lastIntent');
const dateTimeEl   = document.getElementById('dateTime');

// ── State ────────────────────────────────────────────────────
let orbState = 'idle';
let time = 0;

const COLORS = {
    idle:       { core: '#ffaa00', mid: '#ff6600', outer: '#331100', glow: 'rgba(255,160,0,0.5)',   ring: '#ffaa00' },
    listening:  { core: '#ffee44', mid: '#ffaa00', outer: '#221100', glow: 'rgba(255,220,0,0.6)',   ring: '#ffdd00' },
    processing: { core: '#ff6600', mid: '#ff3300', outer: '#220000', glow: 'rgba(255,80,0,0.6)',    ring: '#ff6600' },
    speaking:   { core: '#ffcc44', mid: '#ffaa00', outer: '#331a00', glow: 'rgba(255,200,0,0.65)',  ring: '#ffcc00' },
};

const STATE_LABEL  = { idle: 'STANDBY', listening: 'LISTENING', processing: 'PROCESSING', speaking: 'SPEAKING' };
const STATUS_LABEL = { idle: 'READY',   listening: 'LISTENING', processing: 'THINKING',   speaking: 'RESPONDING' };

// ── Orbital rings — each has a tilt axis and rotation speed ──
const orbits = [
    { tiltX: 0,   tiltY: 0,   rot: 0,           speed:  0.004,  r: 125, nodeCount: 6  },
    { tiltX: 65,  tiltY: 0,   rot: 0.6,          speed: -0.003,  r: 125, nodeCount: 8  },
    { tiltX: 115, tiltY: 0,   rot: 1.8,          speed:  0.0025, r: 125, nodeCount: 5  },
    { tiltX: 35,  tiltY: 20,  rot: 3.0,          speed: -0.0035, r: 108, nodeCount: 6  },
    { tiltX: 90,  tiltY: 45,  rot: 1.2,          speed:  0.005,  r: 108, nodeCount: 4  },
    { tiltX: 150, tiltY: 30,  rot: 0.3,          speed: -0.002,  r: 145, nodeCount: 7  },
    { tiltX: 55,  tiltY: 70,  rot: 2.4,          speed:  0.003,  r: 138, nodeCount: 5  },
];

// Project a 3D ring onto 2D canvas
function getOrbitPoints(cx, cy, orbit, steps = 120) {
    const { tiltX, tiltY, rot, r } = orbit;
    const tx = tiltX * Math.PI / 180;
    const ty = tiltY * Math.PI / 180;
    const points = [];

    for (let i = 0; i <= steps; i++) {
        const a = (i / steps) * Math.PI * 2 + rot;

        // Circle in local space
        let x = Math.cos(a) * r;
        let y = Math.sin(a) * r;
        let z = 0;

        // Rotate around X axis
        let y1 = y * Math.cos(tx) - z * Math.sin(tx);
        let z1 = y * Math.sin(tx) + z * Math.cos(tx);

        // Rotate around Y axis
        let x2 = x * Math.cos(ty) + z1 * Math.sin(ty);
        let z2 = -x * Math.sin(ty) + z1 * Math.cos(ty);

        points.push({ x: cx + x2, y: cy + y1, z: z2 });
    }
    return points;
}

// ── Set state ─────────────────────────────────────────────────
function setOrbState(state) {
    orbState = state;
    orbStateText.textContent = STATE_LABEL[state];
    statusText.textContent   = STATUS_LABEL[state];
    statusDot.className = 'status-indicator ' + (state !== 'idle' ? state : '');
}

// ── Draw ──────────────────────────────────────────────────────
function drawOrb() {
    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H / 2;
    ctx.clearRect(0, 0, W, H);
    time += 0.016;

    const c = COLORS[orbState];
    const speedMult = orbState === 'processing' ? 4 : orbState === 'speaking' ? 1.8 : 1;

    // Update ring rotations
    orbits.forEach(o => { o.rot += o.speed * speedMult; });

    // ── Deep background glow ──
    const bgGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, 180);
    bgGlow.addColorStop(0,   c.glow);
    bgGlow.addColorStop(0.5, c.glow.replace('0.5', '0.1').replace('0.6', '0.1').replace('0.65', '0.1'));
    bgGlow.addColorStop(1,   'transparent');
    ctx.beginPath();
    ctx.arc(cx, cy, 180, 0, Math.PI * 2);
    ctx.fillStyle = bgGlow;
    ctx.globalAlpha = 1;
    ctx.fill();

    // ── Orbital rings ──
    orbits.forEach((orbit, idx) => {
        const pts = getOrbitPoints(cx, cy, orbit);

        // Sort by z for depth
        const alpha = 0.35 + 0.2 * Math.sin(time * 0.7 + idx);

        ctx.beginPath();
        pts.forEach((p, i) => {
            // Fade segments on far side (z < 0 = behind)
            if (i === 0) { ctx.moveTo(p.x, p.y); return; }
            const prev = pts[i - 1];
            // Simple depth fade — far side dimmer
            const depth = (p.z + orbit.r) / (orbit.r * 2);
            ctx.globalAlpha = alpha * (0.3 + 0.7 * depth);
            ctx.beginPath();
            ctx.moveTo(prev.x, prev.y);
            ctx.lineTo(p.x, p.y);
            ctx.strokeStyle = c.ring;
            ctx.lineWidth = 1.2;
            ctx.stroke();
        });

        // ── Glowing nodes on ring ──
        const nodeSpacing = Math.floor(pts.length / orbit.nodeCount);
        for (let n = 0; n < orbit.nodeCount; n++) {
            const p = pts[n * nodeSpacing];
            const depth = (p.z + orbit.r) / (orbit.r * 2);
            const nodeSize = 2 + depth * 2.5;

            ctx.beginPath();
            ctx.arc(p.x, p.y, nodeSize, 0, Math.PI * 2);
            ctx.fillStyle = c.core;
            ctx.globalAlpha = 0.5 + 0.5 * depth;
            ctx.fill();

            // Node glow
            const ng = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, nodeSize * 3);
            ng.addColorStop(0, c.core + '88');
            ng.addColorStop(1, 'transparent');
            ctx.beginPath();
            ctx.arc(p.x, p.y, nodeSize * 3, 0, Math.PI * 2);
            ctx.fillStyle = ng;
            ctx.globalAlpha = 0.6 * depth;
            ctx.fill();
        }
    });

    ctx.globalAlpha = 1;

    // ── Pulse scale ──
    const pulse = orbState === 'speaking'
        ? 1 + Math.sin(time * 5) * 0.12
        : 1 + Math.sin(time * 1.5) * 0.04;

    // ── Mid glow ring ──
    const midR = 68 * pulse;
    const midGlow = ctx.createRadialGradient(cx, cy, midR * 0.4, cx, cy, midR * 1.8);
    midGlow.addColorStop(0,   c.mid + 'aa');
    midGlow.addColorStop(0.5, c.mid + '33');
    midGlow.addColorStop(1,   'transparent');
    ctx.beginPath();
    ctx.arc(cx, cy, midR * 1.8, 0, Math.PI * 2);
    ctx.fillStyle = midGlow;
    ctx.globalAlpha = 0.9;
    ctx.fill();

    // ── Core orb ──
    const cr = 52 * pulse;
    const coreGrad = ctx.createRadialGradient(cx - 16, cy - 16, 2, cx, cy, cr);
    coreGrad.addColorStop(0,   '#ffffff');
    coreGrad.addColorStop(0.15, c.core);
    coreGrad.addColorStop(0.6,  c.mid);
    coreGrad.addColorStop(1,    c.outer);
    ctx.beginPath();
    ctx.arc(cx, cy, cr, 0, Math.PI * 2);
    ctx.fillStyle = coreGrad;
    ctx.globalAlpha = 0.95;
    ctx.fill();

    // ── Specular ──
    const sg = ctx.createRadialGradient(cx - 14, cy - 14, 0, cx - 14, cy - 14, cr * 0.4);
    sg.addColorStop(0, 'rgba(255,255,255,0.65)');
    sg.addColorStop(1, 'transparent');
    ctx.beginPath();
    ctx.arc(cx - 14, cy - 14, cr * 0.4, 0, Math.PI * 2);
    ctx.fillStyle = sg;
    ctx.globalAlpha = 1;
    ctx.fill();

    // ── Waveform bubble (listening / speaking) ──
    if (orbState === 'listening' || orbState === 'speaking') {
        const wR = 78;
        const pts = 80;
        const amp = orbState === 'speaking' ? 20 : 12;
        const freq = orbState === 'speaking' ? 4.5 : 2.5;

        ctx.beginPath();
        for (let i = 0; i <= pts; i++) {
            const angle = (i / pts) * Math.PI * 2 - Math.PI / 2;
            const wave  = Math.sin(time * freq + i * 0.35) * amp
                        + Math.sin(time * freq * 0.55 + i * 0.7) * (amp * 0.35);
            const r     = wR + wave;
            const x = cx + Math.cos(angle) * r;
            const y = cy + Math.sin(angle) * r;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = c.core;
        ctx.globalAlpha = 0.5;
        ctx.lineWidth = 2;
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
let activeAudio = null;

function playAudio(b64) {
    if (!b64) { setOrbState('idle'); return; }
    const bytes = atob(b64);
    const arr   = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([arr], { type: 'audio/mpeg' }));
    if (activeAudio) { activeAudio.pause(); activeAudio = null; }
    activeAudio = new Audio(url);
    setOrbState('speaking');
    activeAudio.play();
    activeAudio.onended = () => { URL.revokeObjectURL(url); setOrbState('idle'); };
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
    if (!recognition) { alert('Voice input requires Chrome.'); return; }
    orbState === 'listening' ? recognition.stop() : recognition.start();
});

// ── SocketIO ──────────────────────────────────────────────────
socket.on('fyra_response', data => {
    addMessage(data.text, 'fyra');
    if (data.intent) lastIntentEl.textContent = data.intent.replace('_', ' ').toUpperCase();
    data.audio ? playAudio(data.audio) : setOrbState('idle');
});
socket.on('status',     data => setOrbState(data.state));
socket.on('connect',    ()   => setOrbState('idle'));
socket.on('disconnect', ()   => statusText.textContent = 'OFFLINE');

// ── Input ─────────────────────────────────────────────────────
sendBtn.addEventListener('click', () => sendMessage(textInput.value));
textInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(textInput.value); });

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

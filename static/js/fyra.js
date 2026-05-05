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
    idle:       { primary: '#00d4ff', secondary: '#002299', glow: 'rgba(0,212,255,0.35)' },
    listening:  { primary: '#00ff99', secondary: '#005533', glow: 'rgba(0,255,153,0.45)' },
    processing: { primary: '#ff8800', secondary: '#661100', glow: 'rgba(255,136,0,0.45)' },
    speaking:   { primary: '#bb44ff', secondary: '#440099', glow: 'rgba(187,68,255,0.45)' },
};

const STATE_LABEL = {
    idle: 'STANDBY', listening: 'LISTENING', processing: 'PROCESSING', speaking: 'SPEAKING'
};
const STATUS_LABEL = {
    idle: 'READY', listening: 'LISTENING', processing: 'THINKING', speaking: 'RESPONDING'
};

// ── Orb rings ────────────────────────────────────────────────
const rings = [
    { r: 118, rot: 0,              speed:  0.0045, segs: 8,  segLen: 0.18 },
    { r: 150, rot: Math.PI / 3,   speed: -0.0030, segs: 12, segLen: 0.09 },
    { r: 178, rot: Math.PI * 0.7, speed:  0.0020, segs: 6,  segLen: 0.28 },
];

// ── Set orb state ─────────────────────────────────────────────
function setOrbState(state) {
    orbState = state;
    orbStateText.textContent = STATE_LABEL[state];
    statusText.textContent   = STATUS_LABEL[state];
    statusDot.className = 'status-indicator ' + (state !== 'idle' ? state : '');
}

// ── Draw loop ─────────────────────────────────────────────────
function drawOrb() {
    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H / 2;
    ctx.clearRect(0, 0, W, H);
    time += 0.016;

    const c = COLORS[orbState];
    const speedMult = orbState === 'processing' ? 5 : orbState === 'speaking' ? 2.2 : 1;

    // ── Rings ──
    rings.forEach(ring => {
        ring.rot += ring.speed * speedMult;
        const r = ring.r + Math.sin(time * 1.5) * 4;
        const arc = (Math.PI * 2) / ring.segs;

        for (let i = 0; i < ring.segs; i++) {
            const a = ring.rot + i * arc;
            const len = arc * ring.segLen;

            ctx.beginPath();
            ctx.arc(cx, cy, r, a, a + len);
            ctx.strokeStyle = c.primary;
            ctx.globalAlpha = 0.45 + 0.25 * Math.sin(time * 2 + i * 0.9);
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // dot at segment start
            ctx.beginPath();
            ctx.arc(cx + Math.cos(a) * r, cy + Math.sin(a) * r, 2, 0, Math.PI * 2);
            ctx.fillStyle = c.primary;
            ctx.globalAlpha = 0.9;
            ctx.fill();
        }
    });

    // ── Outer glow halo ──
    const pulse = orbState === 'speaking'
        ? 1 + Math.sin(time * 5) * 0.18
        : 1 + Math.sin(time * 1.8) * 0.06;

    const halo = ctx.createRadialGradient(cx, cy, 0, cx, cy, 105 * pulse);
    halo.addColorStop(0,   c.primary + '44');
    halo.addColorStop(0.5, c.primary + '18');
    halo.addColorStop(1,   'transparent');
    ctx.beginPath();
    ctx.arc(cx, cy, 105 * pulse, 0, Math.PI * 2);
    ctx.fillStyle = halo;
    ctx.globalAlpha = 1;
    ctx.fill();

    // ── Core orb ──
    const cr = 58 * pulse;
    const coreGrad = ctx.createRadialGradient(cx - 18, cy - 18, 0, cx, cy, cr);
    coreGrad.addColorStop(0,   '#ffffff');
    coreGrad.addColorStop(0.2, c.primary);
    coreGrad.addColorStop(0.7, c.secondary);
    coreGrad.addColorStop(1,   '#000011');
    ctx.beginPath();
    ctx.arc(cx, cy, cr, 0, Math.PI * 2);
    ctx.fillStyle = coreGrad;
    ctx.globalAlpha = 0.92;
    ctx.fill();

    // ── Specular highlight ──
    const specGrad = ctx.createRadialGradient(cx - 16, cy - 16, 0, cx - 16, cy - 16, cr * 0.32);
    specGrad.addColorStop(0, 'rgba(255,255,255,0.55)');
    specGrad.addColorStop(1, 'transparent');
    ctx.beginPath();
    ctx.arc(cx - 16, cy - 16, cr * 0.32, 0, Math.PI * 2);
    ctx.fillStyle = specGrad;
    ctx.globalAlpha = 1;
    ctx.fill();

    // ── Waveform bubble (listening / speaking) ──
    if (orbState === 'listening' || orbState === 'speaking') {
        const wR = 80;
        const pts = 80;
        const freq = orbState === 'speaking' ? 5 : 3;
        const amp  = orbState === 'speaking' ? 16 : 10;

        ctx.beginPath();
        for (let i = 0; i <= pts; i++) {
            const angle = (i / pts) * Math.PI * 2 - Math.PI / 2;
            const wave  = Math.sin(time * freq + i * 0.35) * amp
                        + Math.sin(time * (freq * 0.6) + i * 0.6) * (amp * 0.4);
            const r     = wR + wave;
            const x = cx + Math.cos(angle) * r;
            const y = cy + Math.sin(angle) * r;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = c.primary;
        ctx.globalAlpha = 0.55;
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

    if (sender === 'fyra') {
        typeWrite(msg, text);
    } else {
        msg.textContent = text;
    }
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

// ── Voice (Web Speech API) ────────────────────────────────────
let recognition = null;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SR();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    recognition.onstart = () => { setOrbState('listening'); micBtn.classList.add('active'); };
    recognition.onresult = e => {
        micBtn.classList.remove('active');
        sendMessage(e.results[0][0].transcript);
    };
    recognition.onerror = () => { micBtn.classList.remove('active'); setOrbState('idle'); };
    recognition.onend   = () => micBtn.classList.remove('active');
}

micBtn.addEventListener('click', () => {
    if (!recognition) {
        alert('Voice input requires Chrome or Safari.');
        return;
    }
    orbState === 'listening' ? recognition.stop() : recognition.start();
});

// ── SocketIO events ───────────────────────────────────────────
socket.on('fyra_response', data => {
    addMessage(data.text, 'fyra');
    if (data.intent) lastIntentEl.textContent = data.intent.replace('_', ' ').toUpperCase();
    data.audio ? playAudio(data.audio) : setOrbState('idle');
});

socket.on('status', data => setOrbState(data.state));

socket.on('connect',    () => setOrbState('idle'));
socket.on('disconnect', () => statusText.textContent = 'OFFLINE');

// ── Input events ──────────────────────────────────────────────
sendBtn.addEventListener('click', () => sendMessage(textInput.value));
textInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(textInput.value); });

// ── Clock ─────────────────────────────────────────────────────
function tick() {
    const now = new Date();
    const t = now.toTimeString().slice(0, 8);
    const d = now.toDateString().slice(4).toUpperCase();
    dateTimeEl.textContent = `${t} // ${d}`;
}
tick();
setInterval(tick, 1000);

// ── Start ─────────────────────────────────────────────────────
drawOrb();

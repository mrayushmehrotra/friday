// Jarvis HUD + Command Interface Logic

let isListening = false;
let recognition = null;
let synth = window.speechSynthesis;

function initHUD() {
    setupDates();
    startClock();
    setupEqualizer();
    setupGraphs();
    fetchSystemStats();
    setInterval(fetchSystemStats, 3000);
    initJarvis();
    setupChatUI();
}

function setupDates() {
    const container = document.getElementById('dates-container');
    const today = new Date().getDate();
    for (let i = 1; i <= 30; i++) {
        const span = document.createElement('span');
        span.className = 'date-item';
        span.textContent = String(i).padStart(2, '0');
        if (i === today) span.classList.add('active');
        container.appendChild(span);
    }
}

function startClock() {
    const clockDisplay = document.getElementById('clock-display');
    const monthDisplay = document.getElementById('month-display');
    const dayDisplay = document.getElementById('day-display');
    const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

    function update() {
        const now = new Date();
        clockDisplay.textContent =
            String(now.getHours()).padStart(2, '0') + ':' +
            String(now.getMinutes()).padStart(2, '0');
        monthDisplay.textContent = months[now.getMonth()];
        dayDisplay.textContent = now.getDate();
    }
    setInterval(update, 1000);
    update();
}

function setupEqualizer() {
    const container = document.getElementById('equalizer');
    const numBars = 12;
    const bars = [];
    for (let i = 0; i < numBars; i++) {
        const bar = document.createElement('div');
        bar.className = 'equalizer-bar';
        bar.style.height = (Math.random() * 40 + 10) + 'px';
        container.appendChild(bar);
        bars.push(bar);
    }
    setInterval(() => {
        bars.forEach(bar => {
            bar.style.height = (Math.random() * 40 + 5) + 'px';
        });
    }, 150);
}

function setupGraphs() {
    const dlCanvas = document.getElementById('downloadGraph');
    const ulCanvas = document.getElementById('uploadGraph');
    if (!dlCanvas || !ulCanvas) return;
    const dlCtx = dlCanvas.getContext('2d');
    const ulCtx = ulCanvas.getContext('2d');
    const color = '#00f3ff';
    const dlData = new Array(50).fill(0).map(() => Math.random() * 30);
    const ulData = new Array(50).fill(0).map(() => Math.random() * 20);

    function drawGraph(ctx, data, width, height) {
        ctx.clearRect(0, 0, width, height);
        ctx.beginPath();
        ctx.moveTo(0, height);
        const step = width / (data.length - 1);
        for (let i = 0; i < data.length; i++) {
            ctx.lineTo(i * step, height - data[i]);
        }
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        const gradient = ctx.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, 'rgba(0, 243, 255, 0.5)');
        gradient.addColorStop(1, 'rgba(0, 243, 255, 0)');
        ctx.fillStyle = gradient;
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.stroke();
    }

    function updateData(data, max) {
        data.shift();
        data.push(Math.random() * max + (Math.random() > 0.8 ? 20 : 0));
    }

    function render() {
        updateData(dlData, 25);
        updateData(ulData, 15);
        drawGraph(dlCtx, dlData, dlCanvas.width, dlCanvas.height);
        drawGraph(ulCtx, ulData, ulCanvas.width, ulCanvas.height);
        requestAnimationFrame(render);
    }
    render();
}

function fetchSystemStats() {
    fetch('/api/system')
        .then(r => r.json())
        .then(data => {
            document.getElementById('cpu-value').textContent = Math.round(data.cpu) + '%';
            document.getElementById('ram-value').textContent = Math.round(data.ram) + '%';
            document.getElementById('ip-address').textContent = 'IP: ' + data.ip;

            if (data.battery_percent !== null) {
                document.getElementById('energy-value').textContent = Math.round(data.battery_percent) + '%';
            } else {
                document.getElementById('energy-value').textContent = '100%';
            }

            document.getElementById('disk-total').textContent = 'Total: ' + formatBytes(data.disk_total);
            document.getElementById('disk-used').textContent = 'Used: ' + formatBytes(data.disk_used) + ' (' + data.disk_percent + '%)';
            document.getElementById('disk-free').textContent = 'Free: ' + formatBytes(data.disk_free);

            document.getElementById('net-download').textContent = 'Download: ' + formatBytes(data.net_recv);
            document.getElementById('net-upload').textContent = 'Upload: ' + formatBytes(data.net_sent);

            document.getElementById('io-read').textContent = formatBytes(data.net_recv) + '/s';
            document.getElementById('io-write').textContent = formatBytes(data.net_sent) + '/s';

            const now = new Date();
            document.querySelector('.update-time').textContent =
                'Updated ' + now.toLocaleDateString() + ' ' + now.toLocaleTimeString();
        })
        .catch(() => {});
}

function formatBytes(bytes) {
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let b = bytes;
    for (const unit of units) {
        if (b < 1024) return b.toFixed(1) + ' ' + unit;
        b /= 1024;
    }
    return b.toFixed(1) + ' PB';
}

function weatherCodeToEmoji(code) {
    const map = {
        '113': '☀️', '116': '⛅', '119': '☁️', '122': '☁️', '143': '🌫️',
        '176': '🌧️', '179': '🌧️', '182': '🌧️', '185': '🌧️', '200': '⛈️',
        '227': '🌨️', '230': '🌨️', '248': '🌫️', '260': '🌫️', '263': '🌦️',
        '266': '🌦️', '281': '🌧️', '284': '🌧️', '293': '🌦️', '296': '🌦️',
        '299': '🌧️', '302': '🌧️', '305': '🌧️', '308': '🌧️', '311': '🌧️',
        '314': '🌧️', '317': '🌧️', '320': '🌨️', '323': '🌨️', '326': '🌨️',
        '329': '🌨️', '332': '🌨️', '335': '🌨️', '338': '🌨️', '350': '🧊',
        '353': '🌦️', '356': '🌧️', '359': '🌧️', '362': '🌧️', '365': '🌧️',
        '368': '🌨️', '371': '🌨️', '374': '🌧️', '377': '🌧️', '386': '⛈️',
        '389': '⛈️', '392': '🌨️', '395': '🌨️',
    };
    return map[String(code)] || '🌍';
}

// ---- JARVIS CHAT UI ----

function initJarvis() {
    fetch('/api/init')
        .then(r => r.json())
        .then(data => {
            if (data.weather_json) {
                updateWeatherUI(data.weather_json);
            }
            addJarvisMessage(data.greeting, true);
            setTimeout(() => {
                if (data.notes) {
                    addJarvisMessage(data.notes, true);
                }
            }, 2000);
            setTimeout(() => {
                if (data.weather) {
                    addJarvisMessage('weather is ' + data.weather, true);
                }
            }, 4000);
        })
        .catch(() => {
            addJarvisMessage('welcome home, sir', true);
        });
}

function updateWeatherUI(data) {
    const cc = data.current_condition[0];
    if (!cc) return;
    document.getElementById('weather-temp').textContent = cc.temp_C + '°C';
    document.getElementById('weather-icon').textContent = weatherCodeToEmoji(cc.weatherCode);
    document.getElementById('weather-humidity').textContent = 'Humidity: ' + cc.humidity + '%';
    document.getElementById('weather-wind').textContent = 'Wind: ' + cc.windspeedKmph + ' km/h';
    document.getElementById('weather-visibility').textContent = 'Visibility: ' + cc.visibility + ' km';
    if (data.weather && data.weather.length >= 2) {
        document.getElementById('forecast-today').textContent =
            data.weather[0].mintempC + '° / ' + data.weather[0].maxtempC + '°';
        document.getElementById('forecast-today-icon').textContent =
            weatherCodeToEmoji(data.weather[0].hourly[0].weatherCode);
        document.getElementById('forecast-tomorrow').textContent =
            data.weather[1].mintempC + '° / ' + data.weather[1].maxtempC + '°';
        document.getElementById('forecast-tomorrow-icon').textContent =
            weatherCodeToEmoji(data.weather[1].hourly[0].weatherCode);
    }
}

function setupChatUI() {
    const input = document.getElementById('commandInput');
    const sendBtn = document.getElementById('sendBtn');
    const micBtn = document.getElementById('micBtn');
    const chatPanel = document.getElementById('chatPanel');
    const chatToggle = document.getElementById('chatToggle');

    sendBtn.addEventListener('click', sendCommand);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') sendCommand();
    });
    micBtn.addEventListener('click', toggleVoiceInput);
    chatToggle.addEventListener('click', () => {
        chatPanel.classList.toggle('collapsed');
        chatToggle.textContent = chatPanel.classList.contains('collapsed') ? '+' : '−';
    });
    document.addEventListener('keydown', e => {
        if (e.target.tagName !== 'INPUT' && e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
            input.focus();
        }
    });
}

function sendCommand() {
    const input = document.getElementById('commandInput');
    const query = input.value.trim();
    if (!query) return;
    addUserMessage(query);
    input.value = '';

    fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
    })
        .then(r => r.json())
        .then(data => {
            addJarvisMessage(data.response, true);
        })
        .catch(() => {
            addJarvisMessage('Connection error, sir.', false);
        });
}

function addUserMessage(text) {
    const conversation = document.getElementById('conversation');
    const msg = document.createElement('div');
    msg.className = 'message user-message';
    msg.innerHTML = '<span class="msg-label">YOU</span><span class="msg-text">' + escapeHtml(text) + '</span>';
    conversation.appendChild(msg);
    scrollConversation();
}

function addJarvisMessage(text, speakIt) {
    const conversation = document.getElementById('conversation');
    const msg = document.createElement('div');
    msg.className = 'message jarvis-message';
    msg.innerHTML = '<span class="msg-label">JARVIS</span><span class="msg-text"></span>';
    conversation.appendChild(msg);
    const textSpan = msg.querySelector('.msg-text');
    typeText(textSpan, text, 0);
    scrollConversation();
    if (speakIt && synth) {
        speakText(text);
    }
}

function typeText(element, text, index) {
    if (index < text.length) {
        element.textContent += text[index];
        setTimeout(() => typeText(element, text, index + 1), 15 + Math.random() * 20);
        scrollConversation();
    }
}

function scrollConversation() {
    const conversation = document.getElementById('conversation');
    conversation.scrollTop = conversation.scrollHeight;
}

function speakText(text) {
    if (!synth) return;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.1;
    utterance.pitch = 0.9;
    utterance.volume = 1;
    synth.speak(utterance);
}

function toggleVoiceInput() {
    const micBtn = document.getElementById('micBtn');
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
        addJarvisMessage('Voice input is not supported in this browser.', false);
        return;
    }
    if (isListening) { stopVoiceInput(); return; }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.lang = 'en-IN';
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = event => {
        document.getElementById('commandInput').value = event.results[0][0].transcript;
        sendCommand();
        stopVoiceInput();
    };
    recognition.onerror = () => { stopVoiceInput(); addJarvisMessage('Voice input failed, sir.', false); };
    recognition.onend = () => { stopVoiceInput(); };

    isListening = true;
    micBtn.classList.add('listening');
    micBtn.textContent = '🔴';
    recognition.start();
}

function stopVoiceInput() {
    const micBtn = document.getElementById('micBtn');
    isListening = false;
    micBtn.classList.remove('listening');
    micBtn.textContent = '🎤';
    if (recognition) {
        try { recognition.stop(); } catch (e) {}
        recognition = null;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', initHUD);

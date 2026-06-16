<script lang="ts">
    import TypingText from './TypingText.svelte';

    let dates = $state(Array.from({length: 30}, (_, i) => i + 1));
    let today = $state(new Date().getDate());

    let clockDisplay = $state('00:00');
    let monthDisplay = $state('JUN');
    let dayDisplay = $state('21');
    const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

    let cpuValue = $state('--');
    let ramValue = $state('--');
    let energyValue = $state('--%');
    let diskTotal = $state('--');
    let diskUsed = $state('--');
    let diskFree = $state('--');
    let ioRead = $state('--');
    let ioWrite = $state('--');
    let ipAddress = $state('--');
    let updateTime = $state('');

    let news: Array<{title: string, source: string, link: string, date: string}> = $state([]);
    let newsLoading = $state(true);

    let weatherTemp = $state('--°C');
    let weatherIcon = $state('🌍');
    let weatherHumidity = $state('--');
    let weatherWind = $state('--');
    let weatherVisibility = $state('--');
    let forecastToday = $state('--° / --°');
    let forecastTodayIcon = $state('❓');
    let forecastTomorrow = $state('--° / --°');
    let forecastTomorrowIcon = $state('❓');

    let eqBars = $state(Array.from({length: 12}, () => Math.random() * 40 + 10));

    let messages: Array<{type: string, text: string, displayedText: string, typing: boolean}> = $state([]);
    let commandText = $state('');
    let chatCollapsed = $state(false);
    let isListening = $state(false);
    let recognition: SpeechRecognition | null = null;
    let conversationEl: HTMLDivElement | undefined = $state(undefined);

    function fetchPublicIP() {
        fetch('https://api.ipify.org/?format=json')
            .then(r => r.json())
            .then(data => { ipAddress = 'IP: ' + data.ip; })
            .catch(() => {
                fetch('/api/system')
                    .then(r => r.json())
                    .then(data => { if (data.ip) ipAddress = 'IP: ' + data.ip; })
                    .catch(() => {});
            });
    }

    function fetchSystemStats() {
        fetch('/api/system')
            .then(r => r.json())
            .then(data => {
                cpuValue = Math.round(data.cpu) + '%';
                ramValue = Math.round(data.ram) + '%';
                energyValue = data.battery_percent !== null ? Math.round(data.battery_percent) + '%' : '100%';
                diskTotal = 'Total: ' + formatBytes(data.disk_total);
                diskUsed = 'Used: ' + formatBytes(data.disk_used) + ' (' + data.disk_percent + '%)';
                diskFree = 'Free: ' + formatBytes(data.disk_free);
                ioRead = formatBytes(data.net_recv) + '/s';
                ioWrite = formatBytes(data.net_sent) + '/s';
                const now = new Date();
                updateTime = 'Updated ' + now.toLocaleDateString() + ' ' + now.toLocaleTimeString();
            })
            .catch(() => {});
    }

    function formatBytes(bytes: number) {
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let b = bytes;
        for (const unit of units) {
            if (b < 1024) return b.toFixed(1) + ' ' + unit;
            b /= 1024;
        }
        return b.toFixed(1) + ' PB';
    }

    function weatherCodeToEmoji(code: number | string) {
        const map: Record<string, string> = {
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

    function updateWeatherUI(data: any) {
        const cc = data.current_condition?.[0];
        if (!cc) return;
        weatherTemp = cc.temp_C + '°C';
        weatherIcon = weatherCodeToEmoji(cc.weatherCode);
        weatherHumidity = 'Humidity: ' + cc.humidity + '%';
        weatherWind = 'Wind: ' + cc.windspeedKmph + ' km/h';
        weatherVisibility = 'Visibility: ' + cc.visibility + ' km';
        if (data.weather && data.weather.length >= 2) {
            forecastToday = data.weather[0].mintempC + '° / ' + data.weather[0].maxtempC + '°';
            forecastTodayIcon = weatherCodeToEmoji(data.weather[0].hourly[0].weatherCode);
            forecastTomorrow = data.weather[1].mintempC + '° / ' + data.weather[1].maxtempC + '°';
            forecastTomorrowIcon = weatherCodeToEmoji(data.weather[1].hourly[0].weatherCode);
        }
    }

    function fetchMarketNews() {
        fetch('/api/news')
            .then(r => r.json())
            .then(data => {
                newsLoading = false;
                if (!data || data.length === 0) return;
                news = data;
            })
            .catch(() => { newsLoading = false; });
    }

    function scrollConversation() {
        if (conversationEl) {
            requestAnimationFrame(() => {
                conversationEl!.scrollTop = conversationEl!.scrollHeight;
            });
        }
    }

    function typeText(element: HTMLElement, text: string, index: number) {
        if (index < text.length) {
            element.textContent += text[index];
            setTimeout(() => typeText(element, text, index + 1), 15 + Math.random() * 20);
            scrollConversation();
        }
    }

    function addJarvisMessage(text: string, speakIt: boolean) {
        messages = [...messages, {type: 'jarvis', text, displayedText: '', typing: true}];
        scrollConversation();
        setTimeout(() => {
            messages = messages.map((m, i) =>
                i === messages.length - 1 ? {...m, typing: false, displayedText: m.text} : m
            );
            scrollConversation();
        }, text.length * 20 + 200);
        if (speakIt && window.speechSynthesis) {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.rate = 1.1;
            utterance.pitch = 0.9;
            window.speechSynthesis.speak(utterance);
        }
    }

    function addUserMessage(text: string) {
        messages = [...messages, {type: 'user', text, displayedText: text, typing: false}];
        scrollConversation();
    }

    async function sendCommand() {
        const query = commandText.trim();
        if (!query) return;
        addUserMessage(query);
        commandText = '';

        try {
            const r = await fetch('/api/command', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({query}),
            });
            const data = await r.json();
            addJarvisMessage(data.response, true);
        } catch {
            addJarvisMessage('Connection error, sir.', false);
        }
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter') sendCommand();
    }

    function toggleVoiceInput() {
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

        recognition.onresult = (event: SpeechRecognitionEvent) => {
            commandText = event.results[0][0].transcript;
            sendCommand();
            stopVoiceInput();
        };
        recognition.onerror = () => { stopVoiceInput(); addJarvisMessage('Voice input failed, sir.', false); };
        recognition.onend = () => { stopVoiceInput(); };

        isListening = true;
        recognition.start();
    }

    function stopVoiceInput() {
        isListening = false;
        if (recognition) {
            try { recognition.stop(); } catch (e) {}
            recognition = null;
        }
    }

    function handleGlobalKeydown(e: KeyboardEvent) {
        const target = e.target as HTMLElement;
        if (target.tagName !== 'INPUT' && e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
            const input = document.querySelector('.command-input') as HTMLInputElement;
            if (input) input.focus();
        }
    }

    function escapeHtml(text: string) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function getMessageText(msg: {type: string, text: string, displayedText: string, typing: boolean}) {
        if (msg.type === 'user') return escapeHtml(msg.text);
        if (msg.typing) return '';
        return escapeHtml(msg.text);
    }

    function openLink(url: string) {
        window.open(url, '_blank');
    }

    $effect(() => {
        const clockInterval = setInterval(() => {
            const now = new Date();
            clockDisplay = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
            monthDisplay = months[now.getMonth()];
            dayDisplay = String(now.getDate());
        }, 1000);

        const eqInterval = setInterval(() => {
            eqBars = eqBars.map(() => Math.random() * 40 + 5);
        }, 150);

        fetchPublicIP();
        fetchSystemStats();
        const statsInterval = setInterval(fetchSystemStats, 3000);

        fetch('/api/init')
            .then(r => r.json())
            .then(data => {
                if (data.weather_json) updateWeatherUI(data.weather_json);
                addJarvisMessage(data.greeting, true);
                setTimeout(() => {
                    if (data.notes) addJarvisMessage(data.notes, true);
                }, 2000);
                setTimeout(() => {
                    if (data.weather) addJarvisMessage('weather is ' + data.weather, true);
                }, 4000);
            })
            .catch(() => {
                addJarvisMessage('welcome home, sir', true);
            });

        fetchMarketNews();

        const tradingViewScript = document.createElement('script');
        tradingViewScript.type = 'text/javascript';
        tradingViewScript.src = 'https://s3.tradingview.com/external-embedding/embed-widget-symbol-overview.js';
        tradingViewScript.async = true;
        tradingViewScript.innerHTML = JSON.stringify({
            "lineWidth": 2, "lineType": 0, "chartType": "area",
            "fontColor": "rgb(106, 109, 120)",
            "gridLineColor": "rgba(242, 242, 242, 0.06)",
            "volumeUpColor": "rgba(34, 171, 148, 0.5)",
            "volumeDownColor": "rgba(247, 82, 95, 0.5)",
            "backgroundColor": "#0F0F0F", "widgetFontColor": "#DBDBDB",
            "upColor": "#22ab94", "downColor": "#f7525f",
            "borderUpColor": "#22ab94", "borderDownColor": "#f7525f",
            "wickUpColor": "#22ab94", "wickDownColor": "#f7525f",
            "colorTheme": "dark", "isTransparent": false, "locale": "en",
            "chartOnly": false, "scalePosition": "right", "scaleMode": "Normal",
            "fontFamily": "-apple-system, BlinkMacSystemFont, Trebuchet MS, Roboto, Ubuntu, sans-serif",
            "valuesTracking": "1", "changeMode": "price-and-percent",
            "symbols": [["BSE:SENSEX|1D"], ["FX_IDC:USDINR|1D"], ["BSE:RELIANCE|1D"], ["BSE:HDFCBANK|1D"], ["BSE:INFY|1D"], ["BSE:TMCV|1M"]],
            "dateRanges": ["1d|1", "1m|30", "3m|60", "12m|1D", "60m|1W", "all|1M"],
            "fontSize": "10", "headerFontSize": "medium", "autosize": true,
            "width": "100%", "height": "100%", "noTimeScale": false,
            "hideDateRanges": false, "hideMarketStatus": false, "hideSymbolLogo": false
        });
        const widgetContainer = document.querySelector('.tradingview-widget-container');
        if (widgetContainer) widgetContainer.appendChild(tradingViewScript);

        document.addEventListener('keydown', handleGlobalKeydown);

        return () => {
            clearInterval(clockInterval);
            clearInterval(eqInterval);
            clearInterval(statsInterval);
            document.removeEventListener('keydown', handleGlobalKeydown);
        };
    });
</script>

<div class="hud-container">
    <div class="scanline"></div>
    <div class="vignette"></div>

    <header class="top-bar">
        <div class="dates-row">
            {#each dates as d}
                <span class="date-item" class:active={d === today}>{String(d).padStart(2, '0')}</span>
            {/each}
        </div>
        <div class="system-status">
            <span class="location">Mau, India</span>
            <span class="update-time">{updateTime}</span>
        </div>
    </header>

    <main class="main-hud">
        <aside class="left-panel">
            <div class="widget news-widget tech-box">
                <h3 class="box-title">INDIA & TECH</h3>
                <div class="news-list">
                    {#if newsLoading}
                        <div class="news-loading">Loading...</div>
                    {:else if news.length === 0}
                        <div class="news-loading">No news available</div>
                    {:else}
                        {#each news as item}
                            <div class="news-item" role="button" tabindex="0" onclick={() => openLink(item.link)} onkeydown={(e) => e.key === 'Enter' && openLink(item.link)}>
                                <div class="news-title">{escapeHtml(item.title)}</div>
                                <div class="news-meta">
                                    <span>{escapeHtml(item.source || 'Unknown')}</span>
                                    <span>{escapeHtml(item.date ? item.date.slice(0, 16) : '')}</span>
                                </div>
                            </div>
                        {/each}
                    {/if}
                </div>
            </div>

            <div class="widget">
                <div class="circle-outer large date-circle">
                    <div class="circle-inner">
                        <span class="month">{monthDisplay}</span>
                        <span class="day">{dayDisplay}</span>
                    </div>
                    <div class="ring rotating-slow"></div>
                    <div class="ring dashed rotating-reverse"></div>
                    <div class="ring thick-partial"></div>
                </div>
            </div>

            <div class="widget disk-info tech-box">
                <div class="info-row">
                    <span class="icon">💿</span>
                    <div class="details">
                        <div>{diskTotal}</div>
                        <div>{diskUsed}</div>
                        <div>{diskFree}</div>
                    </div>
                </div>
            </div>

            <div class="widget">
                <div class="circle-outer medium energy-circle">
                    <div class="circle-inner">
                        <span class="label">Energy</span>
                        <span class="value">{energyValue}</span>
                    </div>
                    <div class="ring dashed rotating-fast"></div>
                    <div class="ring glowing"></div>
                </div>
            </div>

            <div class="widget bottom-left-gauges">
                <div class="circle-outer small">
                    <div class="circle-inner">
                        <span class="value">{ioRead}</span>
                        <span class="label">{ioWrite}</span>
                    </div>
                    <div class="ring thick-partial rotating-slow"></div>
                </div>
            </div>
        </aside>

        <section class="center-panel">
            <div class="system-gauges top-gauges">
                <div class="gauge">
                    <div class="circle-outer small gauge-cpu">
                        <div class="circle-inner">
                            <span class="label">CPU</span>
                            <span class="value">{cpuValue}</span>
                        </div>
                        <div class="ring rotating-normal"></div>
                    </div>
                </div>
                <div class="gauge">
                    <div class="circle-outer small gauge-ram">
                        <div class="circle-inner">
                            <span class="label">RAM</span>
                            <span class="value">{ramValue}</span>
                        </div>
                        <div class="ring rotating-reverse dashed"></div>
                    </div>
                </div>
            </div>

            <div class="arc-reactor">
                <div class="core"></div>
                <div class="ring ring-1"></div>
                <div class="ring ring-2 rotating-slow"></div>
                <div class="ring ring-3 rotating-reverse"></div>
                <div class="ring ring-4 dashed rotating-fast"></div>
                <div class="ring ring-5"></div>
                <div class="ring ring-6 dashed rotating-slow-reverse"></div>

                <div class="reactor-lines">
                    <div class="line line-horiz"></div>
                    <div class="line line-vert"></div>
                    <div class="line line-diag-1"></div>
                    <div class="line line-diag-2"></div>
                </div>

                <div class="reactor-text text-left">
                    STARK<br />EXPO<br /><span class="highlight">2010</span>
                </div>
                <div class="reactor-text text-right">SYSTEM<br />ONLINE</div>
            </div>

            <div class="center-bottom-labels">
                <div class="label-item">Games</div>
                <div class="label-item">Programs</div>
                <div class="label-item">Skydrive</div>
                <div class="label-item">Electronics</div>
            </div>
        </section>

        <aside class="right-panel">
            <div class="widget top-right-clock">
                <div class="circle-outer medium clock-circle">
                    <div class="circle-inner" id="clock-display">{clockDisplay}</div>
                    <div class="ring thick-partial rotating-normal"></div>
                    <div class="ring dashed rotating-reverse"></div>
                </div>
            </div>

            <div class="widget tv-widget tech-box">
                <h3 class="box-title">MARKETS</h3>
                <div class="tradingview-widget-container">
                    <div class="tradingview-widget-container__widget"></div>
                    <div class="tradingview-widget-copyright">
                        <a href="https://www.tradingview.com/markets/" rel="noopener nofollow" target="_blank">
                            <span class="blue-text">World markets</span>
                        </a>
                        by TradingView
                    </div>
                </div>
            </div>

            <div class="widget weather-panel tech-box">
                <div class="weather-main">
                    <span class="temp">{weatherTemp}</span>
                    <div class="weather-icon">{weatherIcon}</div>
                </div>
                <div class="weather-details">
                    <div>{weatherHumidity}</div>
                    <div>{weatherWind}</div>
                    <div>{weatherVisibility}</div>
                </div>
                <div class="forecast">
                    <div class="day">
                        <span>Today</span>
                        <span>{forecastToday}</span>
                        <span>{forecastTodayIcon}</span>
                    </div>
                    <div class="day">
                        <span>Tomorrow</span>
                        <span>{forecastTomorrow}</span>
                        <span>{forecastTomorrowIcon}</span>
                    </div>
                </div>
            </div>
        </aside>
    </main>

    <footer class="bottom-bar">
        <div class="ip-address">{ipAddress}</div>
        <div class="logo">STARK INDUSTRIES</div>
        <div class="media-controls">
            <span>⏮</span>
            <span>⏯</span>
            <span>⏭</span>
            <span>🔊</span>
        </div>
    </footer>

    <div class="chat-panel" class:collapsed={chatCollapsed}>
        <div class="chat-header" role="button" tabindex="0" onclick={() => chatCollapsed = !chatCollapsed} onkeydown={(e) => e.key === 'Enter' && (chatCollapsed = !chatCollapsed)}>
            <span class="chat-title">JARVIS TERMINAL</span>
            <span style="scale: 1.8" class="chat-toggle">{chatCollapsed ? '+' : '−'}</span>
        </div>
        <div class="conversation" bind:this={conversationEl}>
            {#each messages as msg}
                <div class="message {msg.type}-message">
                    <span class="msg-label">{msg.type === 'user' ? 'YOU' : 'JARVIS'}</span>
                    <span class="msg-text">
                        {#if msg.type === 'user'}
                            {escapeHtml(msg.text)}
                        {:else if msg.typing}
                            <TypingText text={msg.text} />
                        {:else}
                            {escapeHtml(msg.text)}
                        {/if}
                    </span>
                </div>
            {/each}
        </div>
        <div class="input-area">
            <button class="mic-btn" class:listening={isListening} onclick={toggleVoiceInput} title="Voice input">
                {isListening ? '🔴' : '🎤'}
            </button>
            <!-- svelte-ignore a11y_autofocus -->
            <input
                type="text"
                class="command-input"
                bind:value={commandText}
                onkeydown={handleKeydown}
                placeholder="Enter command..."
                autofocus
            />
            <button class="send-btn" onclick={sendCommand}>SEND</button>
        </div>
    </div>
</div>


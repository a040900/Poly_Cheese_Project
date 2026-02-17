/**
 * 🧀 乳酪のBTC預測室 — Polymarket 智慧交易輔助系統
 * 前端主應用程式 - WebSocket 連線管理、Dashboard 數據渲染、UI 互動控制
 */

(function () {
    'use strict';

    // ═══════════════════════════════════════════════════════════
    // 常數與狀態
    // ═══════════════════════════════════════════════════════════
    // 自動偵測子路徑（支援反向代理，如 /polycheese）
    // 優先使用 <base> 標籤中的 href（由伺服器端動態注入 main.py:382-386）
    const baseEl = document.querySelector('base');
    let basePath = '';
    if (baseEl && baseEl.getAttribute('href')) {
        // <base href="/polycheese/"> → basePath = "/polycheese"
        basePath = baseEl.getAttribute('href').replace(/\/+$/, '');
    }
    // 如果沒有 <base> 標籤，則假設直接部署（無子路徑）
    const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const WS_URL = `${wsProto}//${location.host}${basePath}/ws`;
    const API_BASE = `${location.protocol}//${location.host}${basePath}/api`;

    let ws = null;
    let wsReconnectTimer = null;
    let dashboardData = {};
    let isConnected = false;

    // PnL 圖表歷史
    let pnlHistory = [];

    // ═══════════════════════════════════════════════════════════
    // 初始化
    // ═══════════════════════════════════════════════════════════
    document.addEventListener('DOMContentLoaded', () => {
        initTheme();
        initEventListeners();
        connectWebSocket();
        startClock();
    });

    // ═══════════════════════════════════════════════════════════
    // WebSocket 連線管理
    // ═══════════════════════════════════════════════════════════
    function connectWebSocket() {
        if (ws && ws.readyState === WebSocket.OPEN) return;

        updateWsStatus('connecting');

        try {
            ws = new WebSocket(WS_URL);

            ws.onopen = () => {
                isConnected = true;
                updateWsStatus('connected');
                console.log('🔗 WebSocket 已連線');
                if (wsReconnectTimer) {
                    clearTimeout(wsReconnectTimer);
                    wsReconnectTimer = null;
                }
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    // 處理不同類型的訊息
                    if (data.type) {
                        handleCommand(data);
                    } else {
                        dashboardData = data;
                        renderDashboard(data);
                    }
                } catch (e) {
                    console.error('訊息解析錯誤:', e);
                }
            };

            ws.onclose = () => {
                isConnected = false;
                updateWsStatus('disconnected');
                console.log('🔌 WebSocket 已斷線，5秒後重連...');
                wsReconnectTimer = setTimeout(connectWebSocket, 5000);
            };

            ws.onerror = (err) => {
                console.error('WebSocket 錯誤:', err);
                ws.close();
            };
        } catch (e) {
            console.error('WebSocket 建立失敗:', e);
            wsReconnectTimer = setTimeout(connectWebSocket, 5000);
        }
    }

    function sendCommand(action, data = {}) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action, ...data }));
        }
    }

    function handleCommand(data) {
        switch (data.type) {
            case 'mode_changed':
                updateModeUI(data.mode);
                showToast(`交易模式已切換: ${data.mode_name}`);
                break;
            case 'simulation_toggled':
                updateSimToggle(data.running);
                showToast(data.running ? '模擬交易已啟動' : '模擬交易已停止');
                break;
            case 'simulation_reset':
                showToast(`模擬帳戶已重置: $${data.balance}`);
                break;
            case 'password_requested':
                document.getElementById('modal-password').style.display = 'flex';
                break;
            case 'password_verified':
                handlePasswordResult(data);
                break;
        }
    }

    function updateWsStatus(status) {
        const el = document.getElementById('footer-ws-status');
        if (!el) return;
        switch (status) {
            case 'connecting':
                el.textContent = '⏳ WebSocket 連線中...';
                el.className = 'ws-status';
                break;
            case 'connected':
                el.textContent = '⚡ WebSocket 已連線';
                el.className = 'ws-status connected';
                break;
            case 'disconnected':
                el.textContent = '🔴 WebSocket 已斷線';
                el.className = 'ws-status disconnected';
                break;
        }
    }

    // ═══════════════════════════════════════════════════════════
    // Dashboard 數據渲染
    // ═══════════════════════════════════════════════════════════
    function renderDashboard(data) {
        renderConnections(data.connections);
        renderMarket(data.market);
        renderSignal(data.signal);
        renderIndicators(data.indicators);
        renderTrading(data.trading);
    }

    function renderConnections(conn) {
        if (!conn) return;

        setConnectionStatus('status-binance', conn.binance);
        setConnectionStatus('status-polymarket', conn.polymarket);
        setConnectionStatus('status-chainlink', conn.chainlink);
    }

    function setConnectionStatus(id, state) {
        const el = document.getElementById(id);
        if (!el || !state) return;
        el.classList.toggle('connected', state.connected);
        el.classList.toggle('error', !!state.error && !state.connected);
    }

    function renderMarket(market) {
        if (!market) return;

        // BTC 價格
        const btcPrice = market.btc_price;
        setTextContent('val-btc-price', btcPrice ? `$${formatNumber(btcPrice, 2)}` : '--');
        setTextContent('val-btc-change', btcPrice ? 'Binance 即時' : '等待數據...');

        // Polymarket 合約價格
        setTextContent('val-pm-up', market.pm_up_price ? `$${(market.pm_up_price).toFixed(4)}` : '--');
        setTextContent('val-pm-down', market.pm_down_price ? `$${(market.pm_down_price).toFixed(4)}` : '--');
        setTextContent('val-pm-market', market.pm_market_title || '--');
        setTextContent('val-pm-liquidity',
            market.pm_liquidity ? `流動性: $${formatNumber(market.pm_liquidity, 0)}` : '--');
    }

    function renderSignal(signal) {
        if (!signal) return;

        const el = document.getElementById('val-signal');
        if (!el) return;

        const dir = signal.direction || 'NEUTRAL';
        const labels = {
            'BUY_UP': '📈 看漲',
            'SELL_DOWN': '📉 看跌',
            'NEUTRAL': '⏸ 中性',
        };

        el.textContent = labels[dir] || dir;
        el.className = 'metric-value';
        if (dir === 'BUY_UP') {
            el.classList.add('signal-bullish', 'signal-active');
        } else if (dir === 'SELL_DOWN') {
            el.classList.add('signal-bearish', 'signal-active');
        } else {
            el.classList.add('signal-neutral');
        }

        // 信號分數
        const score = signal.score || 0;
        const confidence = signal.confidence || 0;
        setTextContent('val-signal-score',
            `分數: ${score > 0 ? '+' : ''}${score.toFixed(1)} | 信心度: ${confidence.toFixed(0)}%`);

        // 更新儀表盤
        updateGauge(score);
    }

    function renderIndicators(indicators) {
        if (!indicators) return;

        const rows = document.querySelectorAll('.indicator-row');
        rows.forEach(row => {
            const key = row.dataset.indicator;
            const ind = indicators[key];
            if (!ind) return;

            const valueEl = row.querySelector('.ind-value');
            const signalEl = row.querySelector('.ind-signal');

            // 設定數值
            if (valueEl) {
                switch (key) {
                    case 'ema':
                        valueEl.textContent = ind.short ? `${ind.short.toFixed(0)} / ${ind.long.toFixed(0)}` : '--';
                        break;
                    case 'obi':
                        valueEl.textContent = ind.value !== undefined ? (ind.value * 100).toFixed(1) + '%' : '--';
                        break;
                    case 'macd':
                        valueEl.textContent = ind.histogram !== undefined ? ind.histogram.toFixed(2) : '--';
                        break;
                    case 'cvd':
                        valueEl.textContent = ind.cvd_5m !== undefined ? formatNumber(ind.cvd_5m, 0) : '--';
                        break;
                    case 'rsi':
                        valueEl.textContent = ind.value !== undefined ? ind.value.toFixed(1) : '--';
                        break;
                    case 'vwap':
                        valueEl.textContent = ind.value ? `$${formatNumber(ind.value, 0)}` : '--';
                        break;
                    case 'heikin_ashi':
                        valueEl.textContent = ind.streak !== undefined ? (ind.streak > 0 ? `+${ind.streak}` : ind.streak) : '--';
                        break;
                    case 'poc':
                        valueEl.textContent = ind.value ? `$${formatNumber(ind.value, 0)}` : '--';
                        break;
                    case 'walls':
                        valueEl.textContent = ind.bid_walls !== undefined ? `Bid:${ind.bid_walls} Ask:${ind.ask_walls}` : '--';
                        break;
                }
            }

            // 設定信號標籤
            if (signalEl) {
                const sig = ind.signal || '--';
                signalEl.textContent = {
                    'BULLISH': '看漲',
                    'BEARISH': '看跌',
                    'NEUTRAL': '中性',
                    'OVERSOLD': '超賣',
                    'OVERBOUGHT': '超買',
                }[sig] || sig;

                signalEl.className = 'ind-signal';
                if (sig === 'BULLISH' || sig === 'OVERSOLD') {
                    signalEl.classList.add('bullish');
                } else if (sig === 'BEARISH' || sig === 'OVERBOUGHT') {
                    signalEl.classList.add('bearish');
                } else {
                    signalEl.classList.add('neutral');
                }
            }
        });
    }

    function renderTrading(trading) {
        if (!trading) return;

        const sim = trading.simulation;
        if (sim) {
            setTextContent('sim-balance', `$${formatNumber(sim.balance, 2)}`);

            const pnlEl = document.getElementById('sim-pnl');
            if (pnlEl) {
                const pnl = sim.total_pnl || 0;
                pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${formatNumber(pnl, 2)}`;
                pnlEl.className = 'sim-stat-value ' + (pnl >= 0 ? 'positive' : 'negative');
            }

            setTextContent('sim-winrate', `${sim.win_rate || 0}%`);
            setTextContent('sim-trades', `${sim.total_trades || 0}`);

            // 更新模擬開關
            updateSimToggle(sim.is_running);
        }

        // 更新模式
        if (trading.mode) {
            updateModeUI(trading.mode);
            const badge = document.getElementById('badge-mode');
            if (badge) badge.textContent = trading.mode_name || trading.mode;
        }

        // 渲染最近交易記錄
        renderRecentTrades(trading.recent_trades);

        // 更新 PnL 曲線
        if (trading.pnl_curve) {
            pnlHistory = trading.pnl_curve;
            drawPnlChart();
        }
    }

    function renderRecentTrades(trades) {
        const tbody = document.getElementById('trades-body');
        if (!tbody) return;

        if (!trades || trades.length === 0) {
            tbody.innerHTML = '<div class="trade-empty">暫無交易記錄</div>';
            return;
        }

        const rows = trades.map(t => {
            const dirLabel = t.direction === 'BUY_UP' ? '📈 看漲' : '📉 看跌';
            const dirClass = t.direction === 'BUY_UP' ? 'bullish' : 'bearish';

            let statusLabel, statusClass, pnlText;

            if (t.status === 'open') {
                statusLabel = `⏳ ${t.elapsed_min || 0}m`;
                statusClass = 'open';
                pnlText = '持倉中';
            } else {
                const won = t.won;
                statusLabel = won ? '✅ 勝' : '❌ 負';
                statusClass = won ? 'won' : 'lost';
                const pnl = t.pnl || 0;
                pnlText = `${pnl >= 0 ? '+' : ''}$${formatNumber(pnl, 2)}`;
            }

            return `<div class="trade-row ${statusClass}">
                <span class="trade-dir ${dirClass}">${dirLabel}</span>
                <span class="trade-qty">$${formatNumber(t.quantity, 2)}</span>
                <span class="trade-pnl ${t.pnl >= 0 ? 'positive' : 'negative'}">${pnlText}</span>
                <span class="trade-status ${statusClass}">${statusLabel}</span>
            </div>`;
        });

        tbody.innerHTML = rows.join('');
    }

    // ═══════════════════════════════════════════════════════════
    // 儀表盤繪製
    // ═══════════════════════════════════════════════════════════
    function updateGauge(score) {
        const needle = document.getElementById('gauge-needle');
        const text = document.getElementById('gauge-text');
        const arc = document.getElementById('gauge-arc');

        if (!needle || !text) return;

        // 分數夾緊在 [-100, 100]
        score = Math.max(-100, Math.min(100, score));

        // 映射到角度（-90° 到 +90°）
        // score -100 = -90°, score 0 = 0°, score 100 = 90°
        const angle = (score / 100) * 90;
        const radians = (angle - 90) * Math.PI / 180;

        // 更新指針位置
        const cx = 100, cy = 100, len = 65;
        const x2 = cx + len * Math.cos(radians);
        const y2 = cy + len * Math.sin(radians);
        needle.setAttribute('x2', x2);
        needle.setAttribute('y2', y2);

        // 更新文字
        text.textContent = score > 0 ? `+${score.toFixed(0)}` : score.toFixed(0);

        // 更新弧的顏色
        if (score > 0) {
            arc.setAttribute('stroke', 'url(#grad-bullish)');
        } else {
            arc.setAttribute('stroke', 'url(#grad-bearish)');
        }
    }

    // ═══════════════════════════════════════════════════════════
    // PnL 曲線繪製
    // ═══════════════════════════════════════════════════════════
    function drawPnlChart() {
        const canvas = document.getElementById('pnl-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        // 高解析度支援
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        const w = rect.width;
        const h = rect.height;
        const pad = { top: 15, right: 15, bottom: 25, left: 50 };

        // 清除畫布
        ctx.clearRect(0, 0, w, h);

        if (pnlHistory.length < 2) {
            // 無數據時顯示提示
            ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--text-muted');
            ctx.font = '12px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('交易開始後此處將顯示 PnL 曲線', w / 2, h / 2);
            return;
        }

        const values = pnlHistory.map(p => p.cumulative_pnl);
        const minVal = Math.min(0, ...values);
        const maxVal = Math.max(0, ...values);
        const range = maxVal - minVal || 1;

        const plotW = w - pad.left - pad.right;
        const plotH = h - pad.top - pad.bottom;

        // 繪製零線
        const zeroY = pad.top + plotH * (1 - (0 - minVal) / range);
        ctx.beginPath();
        ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue('--border-color');
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.moveTo(pad.left, zeroY);
        ctx.lineTo(w - pad.right, zeroY);
        ctx.stroke();
        ctx.setLineDash([]);

        // 繪製 PnL 曲線
        ctx.beginPath();
        values.forEach((val, i) => {
            const x = pad.left + (i / (values.length - 1)) * plotW;
            const y = pad.top + plotH * (1 - (val - minVal) / range);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });

        // 曲線顏色
        const lastVal = values[values.length - 1];
        const lineColor = lastVal >= 0 ? '#22c55e' : '#ef4444';
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.stroke();

        // 漸變填充
        const gradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
        if (lastVal >= 0) {
            gradient.addColorStop(0, 'rgba(34, 197, 94, 0.15)');
            gradient.addColorStop(1, 'rgba(34, 197, 94, 0)');
        } else {
            gradient.addColorStop(0, 'rgba(239, 68, 68, 0)');
            gradient.addColorStop(1, 'rgba(239, 68, 68, 0.15)');
        }

        ctx.lineTo(pad.left + plotW, h - pad.bottom);
        ctx.lineTo(pad.left, h - pad.bottom);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        // Y 軸標籤
        ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--text-muted');
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`$${maxVal.toFixed(0)}`, pad.left - 5, pad.top + 4);
        ctx.fillText(`$${minVal.toFixed(0)}`, pad.left - 5, h - pad.bottom + 4);
        ctx.fillText('$0', pad.left - 5, zeroY + 4);

        // 最新值圓點
        const lastX = w - pad.right;
        const lastY = pad.top + plotH * (1 - (lastVal - minVal) / range);
        ctx.beginPath();
        ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
        ctx.fillStyle = lineColor;
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }

    // ═══════════════════════════════════════════════════════════
    // UI 互動控制
    // ═══════════════════════════════════════════════════════════
    function initEventListeners() {
        // 主題切換
        document.getElementById('btn-theme-toggle')?.addEventListener('click', toggleTheme);

        // 緊急停止
        document.getElementById('btn-emergency-stop')?.addEventListener('click', () => {
            if (confirm('⛔ 確認要緊急停止所有交易操作嗎？')) {
                sendCommand('toggle_simulation');
                showToast('⛔ 已執行緊急停止');
            }
        });

        // 模式選擇
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.mode;
                sendCommand('set_mode', { mode });
            });
        });

        // 模擬交易開關
        document.getElementById('btn-sim-toggle')?.addEventListener('click', () => {
            sendCommand('toggle_simulation');
        });

        // 重置模擬
        document.getElementById('btn-sim-reset')?.addEventListener('click', () => {
            const balance = prompt('請輸入重置後的初始金額 (USDC):', '1000');
            if (balance !== null) {
                sendCommand('reset_simulation', { balance: parseFloat(balance) || 1000 });
            }
        });

        // 實盤交易按鈕
        document.getElementById('btn-live-trading')?.addEventListener('click', () => {
            sendCommand('request_password');
        });

        // 密碼驗證
        document.getElementById('btn-verify-password')?.addEventListener('click', () => {
            const password = document.getElementById('input-password')?.value;
            if (password) {
                sendCommand('verify_password', { password });
            }
        });

        // 密碼彈窗關閉
        document.getElementById('modal-close')?.addEventListener('click', () => {
            document.getElementById('modal-password').style.display = 'none';
        });

        // ESC 關閉彈窗
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.getElementById('modal-password').style.display = 'none';
            }
        });

        // 密碼輸入框 Enter
        document.getElementById('input-password')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('btn-verify-password')?.click();
            }
        });

        // 視窗大小變更
        window.addEventListener('resize', drawPnlChart);
    }

    // ── 模式 UI 更新 ─────────────────────────────────────────
    function updateModeUI(mode) {
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
    }

    // ── 模擬開關 UI ──────────────────────────────────────────
    function updateSimToggle(running) {
        const btn = document.getElementById('btn-sim-toggle');
        if (btn) {
            btn.textContent = running ? '⏸ 暫停' : '▶ 啟動';
            btn.classList.toggle('btn-primary', running);
        }
    }

    // ── 密碼驗證結果 ─────────────────────────────────────────
    function handlePasswordResult(data) {
        const resultEl = document.getElementById('password-result');
        if (resultEl) {
            resultEl.textContent = data.message;
            resultEl.className = 'password-result ' + (data.valid ? 'success' : 'error');
        }
        if (data.valid) {
            setTimeout(() => {
                document.getElementById('modal-password').style.display = 'none';
            }, 1500);
        }
    }

    // ═══════════════════════════════════════════════════════════
    // 主題管理
    // ═══════════════════════════════════════════════════════════
    function initTheme() {
        const saved = localStorage.getItem('cheesedog-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        updateThemeIcon(saved);
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('cheesedog-theme', next);
        updateThemeIcon(next);
    }

    function updateThemeIcon(theme) {
        const icon = document.querySelector('.theme-icon');
        if (icon) icon.textContent = theme === 'dark' ? '🌙' : '☀️';
    }

    // ═══════════════════════════════════════════════════════════
    // 工具函數
    // ═══════════════════════════════════════════════════════════
    function setTextContent(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function formatNumber(num, decimals = 2) {
        if (num === null || num === undefined) return '--';
        return Number(num).toLocaleString('en-US', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
    }

    function startClock() {
        function update() {
            const now = new Date();
            setTextContent('footer-time',
                now.toLocaleString('zh-TW', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: false,
                })
            );
        }
        update();
        setInterval(update, 1000);
    }

    function showToast(message) {
        // 簡單的 Toast 通知
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            bottom: 50px;
            left: 50%;
            transform: translateX(-50%);
            padding: 0.6rem 1.2rem;
            background: var(--bg-elevated);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            color: var(--text-primary);
            font-size: 0.82rem;
            font-weight: 500;
            z-index: 2000;
            box-shadow: var(--shadow-lg);
            animation: slideUp 0.3s ease;
        `;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, 2500);
    }

    // ═══════════════════════════════════════════════════════════
    // Phase 2: Tab 切換系統
    // ═══════════════════════════════════════════════════════════
    function initTabs() {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.dataset.tab;
                // 切換按鈕 active
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                // 切換內容 active
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                const content = document.getElementById(tabId);
                if (content) content.classList.add('active');
            });
        });
    }

    // ═══════════════════════════════════════════════════════════
    // Phase 2: 績效面板
    // ═══════════════════════════════════════════════════════════
    async function fetchPerformance() {
        try {
            const resp = await fetch(`${API_BASE}/performance`);
            const data = await resp.json();
            renderPerformance(data);
        } catch (e) {
            console.error('績效資料載入失敗:', e);
        }
    }

    function renderPerformance(data) {
        if (!data || !data.summary) return;
        const s = data.summary;
        const dd = data.drawdown || {};

        setTextContent('perf-winrate', `${s.win_rate || 0}%`);
        setTextContent('perf-profit-factor', s.profit_factor || '--');
        setTextContent('perf-sharpe', s.sharpe_ratio || '--');
        setTextContent('perf-max-dd', `-${dd.max_dd_pct || 0}%`);

        const pnlEl = document.getElementById('perf-total-pnl');
        if (pnlEl) {
            const pnl = s.total_pnl || 0;
            pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${formatNumber(pnl, 2)}`;
            pnlEl.className = 'kpi-value ' + (pnl >= 0 ? 'kpi-positive' : 'kpi-negative');
        }
        setTextContent('perf-total-fees', `$${formatNumber(s.total_fees || 0, 4)}`);

        // 權益曲線
        if (data.equity_curve && data.equity_curve.length > 1) {
            drawEquityCurve('equity-canvas', data.equity_curve);
        }

        // 模式分組
        renderModeStats(data.by_mode);
    }

    function renderModeStats(byMode) {
        const el = document.getElementById('mode-stats-table');
        if (!el || !byMode || Object.keys(byMode).length === 0) return;

        let html = `<div class="mode-stats-header">
            <span>模式</span><span>交易</span><span>勝率</span>
            <span>PnL</span><span>收益因子</span><span>期望值</span>
        </div>`;

        for (const [mode, stats] of Object.entries(byMode)) {
            const pnlClass = stats.total_pnl >= 0 ? 'kpi-positive' : 'kpi-negative';
            html += `<div class="mode-stats-row">
                <span>${mode}</span>
                <span>${stats.trades}</span>
                <span>${stats.win_rate}%</span>
                <span class="${pnlClass}">$${formatNumber(stats.total_pnl, 2)}</span>
                <span>${stats.profit_factor}</span>
                <span>${formatNumber(stats.expectancy, 4)}</span>
            </div>`;
        }
        el.innerHTML = html;
    }

    function drawEquityCurve(canvasId, curve) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !curve || curve.length < 2) return;
        const ctx = canvas.getContext('2d');

        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        const w = rect.width;
        const h = rect.height;
        const pad = { top: 15, right: 15, bottom: 20, left: 55 };

        ctx.clearRect(0, 0, w, h);

        const minVal = Math.min(...curve);
        const maxVal = Math.max(...curve);
        const range = maxVal - minVal || 1;
        const plotW = w - pad.left - pad.right;
        const plotH = h - pad.top - pad.bottom;

        // 初始值線
        const initY = pad.top + plotH * (1 - (curve[0] - minVal) / range);
        ctx.beginPath();
        ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue('--border-color');
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.moveTo(pad.left, initY);
        ctx.lineTo(w - pad.right, initY);
        ctx.stroke();
        ctx.setLineDash([]);

        // 曲線
        ctx.beginPath();
        curve.forEach((val, i) => {
            const x = pad.left + (i / (curve.length - 1)) * plotW;
            const y = pad.top + plotH * (1 - (val - minVal) / range);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });

        const lastVal = curve[curve.length - 1];
        const lineColor = lastVal >= curve[0] ? '#22c55e' : '#ef4444';
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.stroke();

        // 漸變
        const gradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
        gradient.addColorStop(0, lastVal >= curve[0] ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0)');
        gradient.addColorStop(1, lastVal >= curve[0] ? 'rgba(34,197,94,0)' : 'rgba(239,68,68,0.12)');
        ctx.lineTo(pad.left + plotW, h - pad.bottom);
        ctx.lineTo(pad.left, h - pad.bottom);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        // Y 軸
        ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--text-muted');
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`$${maxVal.toFixed(0)}`, pad.left - 5, pad.top + 4);
        ctx.fillText(`$${minVal.toFixed(0)}`, pad.left - 5, h - pad.bottom + 4);

        // 末端圓點
        const lastX = w - pad.right;
        const lastY = pad.top + plotH * (1 - (lastVal - minVal) / range);
        ctx.beginPath();
        ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
        ctx.fillStyle = lineColor;
        ctx.fill();
    }

    // ═══════════════════════════════════════════════════════════
    // Phase 2: 回測面板
    // ═══════════════════════════════════════════════════════════
    async function runBacktest() {
        const status = document.getElementById('bt-status');
        const results = document.getElementById('bt-results');
        const compare = document.getElementById('bt-compare-results');

        status.style.display = 'flex';
        results.style.display = 'none';
        compare.style.display = 'none';

        const body = {
            mode: document.getElementById('bt-mode').value,
            initial_balance: parseFloat(document.getElementById('bt-balance').value) || 1000,
            limit: parseInt(document.getElementById('bt-limit').value) || 5000,
            use_fees: document.getElementById('bt-fees').checked,
        };

        try {
            const resp = await fetch(`${API_BASE}/backtest`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            status.style.display = 'none';
            renderBacktestResult(data);
        } catch (e) {
            status.style.display = 'none';
            showToast('❌ 回測失敗: ' + e.message);
        }
    }

    async function runCompare() {
        const status = document.getElementById('bt-status');
        const results = document.getElementById('bt-results');
        const compare = document.getElementById('bt-compare-results');

        status.style.display = 'flex';
        results.style.display = 'none';
        compare.style.display = 'none';

        const body = {
            initial_balance: parseFloat(document.getElementById('bt-balance').value) || 1000,
            limit: parseInt(document.getElementById('bt-limit').value) || 5000,
        };

        try {
            const resp = await fetch(`${API_BASE}/backtest/compare`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            status.style.display = 'none';
            renderCompareResult(data);
        } catch (e) {
            status.style.display = 'none';
            showToast('❌ 比較失敗: ' + e.message);
        }
    }

    function renderBacktestResult(data) {
        if (data.error) {
            showToast('⚠️ ' + data.error);
            return;
        }

        const results = document.getElementById('bt-results');
        results.style.display = 'block';

        const s = data.summary || {};
        const info = data.backtest_info || {};
        const dd = data.drawdown || {};

        const summaryEl = document.getElementById('bt-summary');
        const pnlClass = (s.total_pnl || 0) >= 0 ? 'kpi-positive' : 'kpi-negative';
        summaryEl.innerHTML = `<div class="bt-summary-grid">
            <div class="bt-summary-item">
                <span class="bt-summary-label">交易數</span>
                <span class="bt-summary-value">${s.total_trades || 0}</span>
            </div>
            <div class="bt-summary-item">
                <span class="bt-summary-label">勝率</span>
                <span class="bt-summary-value">${s.win_rate || 0}%</span>
            </div>
            <div class="bt-summary-item">
                <span class="bt-summary-label">PnL</span>
                <span class="bt-summary-value ${pnlClass}">${s.total_pnl >= 0 ? '+' : ''}$${formatNumber(s.total_pnl, 2)}</span>
            </div>
            <div class="bt-summary-item">
                <span class="bt-summary-label">報酬率</span>
                <span class="bt-summary-value ${pnlClass}">${s.total_return_pct >= 0 ? '+' : ''}${s.total_return_pct}%</span>
            </div>
            <div class="bt-summary-item">
                <span class="bt-summary-label">夏普</span>
                <span class="bt-summary-value">${s.sharpe_ratio || 0}</span>
            </div>
            <div class="bt-summary-item">
                <span class="bt-summary-label">最大回撤</span>
                <span class="bt-summary-value kpi-negative">-${dd.max_dd_pct || 0}%</span>
            </div>
            <div class="bt-summary-item">
                <span class="bt-summary-label">手續費</span>
                <span class="bt-summary-value">$${formatNumber(s.total_fees, 4)}</span>
            </div>
            <div class="bt-summary-item">
                <span class="bt-summary-label">耗時</span>
                <span class="bt-summary-value">${info.elapsed_seconds || 0}s</span>
            </div>
        </div>`;

        if (data.equity_curve && data.equity_curve.length > 1) {
            drawEquityCurve('bt-equity-canvas', data.equity_curve);
        }
    }

    function renderCompareResult(data) {
        if (!data.comparison) return;

        const compare = document.getElementById('bt-compare-results');
        compare.style.display = 'block';

        const tbl = document.getElementById('compare-table');
        let html = `<div class="compare-table-grid">
            <div class="compare-header">
                <span>模式</span><span>PnL</span><span>報酬率</span>
                <span>勝率</span><span>夏普</span><span>交易數</span><span>手續費</span>
            </div>`;

        for (const [mode, d] of Object.entries(data.comparison)) {
            if (d.error) continue;
            const isBest = mode === data.best_mode;
            const pnlClass = (d.total_pnl || 0) >= 0 ? 'kpi-positive' : 'kpi-negative';
            html += `<div class="compare-row ${isBest ? 'best' : ''}">
                <span>${isBest ? '🏆 ' : ''}${mode}</span>
                <span class="${pnlClass}">${d.total_pnl >= 0 ? '+' : ''}$${formatNumber(d.total_pnl, 2)}</span>
                <span>${d.total_return_pct >= 0 ? '+' : ''}${d.total_return_pct}%</span>
                <span>${d.win_rate}%</span>
                <span>${d.sharpe_ratio}</span>
                <span>${d.total_trades}</span>
                <span>$${formatNumber(d.total_fees, 4)}</span>
            </div>`;
        }
        html += '</div>';
        tbl.innerHTML = html;

        if (data.best_mode) {
            showToast(`🏆 回測最佳模式: ${data.best_mode}`);
        }
    }

    // ═══════════════════════════════════════════════════════════
    // Phase 2: AI 建議面板
    // ═══════════════════════════════════════════════════════════
    async function fetchAIContext() {
        try {
            const resp = await fetch(`${API_BASE}/llm/context`);
            const data = await resp.json();
            const area = document.getElementById('ai-context-area');
            const json = document.getElementById('ai-context-json');
            area.style.display = 'block';
            json.textContent = JSON.stringify(data, null, 2);
        } catch (e) {
            showToast('❌ 取得上下文失敗');
        }
    }

    async function fetchAIPrompt() {
        const focus = document.getElementById('ai-focus').value;
        try {
            const resp = await fetch(`${API_BASE}/llm/prompt?focus=${focus}`);
            const data = await resp.json();
            const area = document.getElementById('ai-prompt-area');
            const text = document.getElementById('ai-prompt-text');
            area.style.display = 'block';
            text.textContent = data.prompt || '';
        } catch (e) {
            showToast('❌ 產生 Prompt 失敗');
        }
    }

    async function fetchAIHistory() {
        try {
            const [histResp, statsResp] = await Promise.all([
                fetch(`${API_BASE}/llm/history`),
                fetch(`${API_BASE}/llm/stats`),
            ]);
            const history = await histResp.json();
            const stats = await statsResp.json();

            renderAIHistory(history);
            setTextContent('ai-stats-text',
                `收到: ${stats.total_received || 0} | 已套用: ${stats.applied || 0} | 拒絕: ${stats.rejected || 0}`);
        } catch (e) {
            console.error('AI 歷史載入失敗:', e);
        }
    }

    function renderAIHistory(history) {
        const items = document.getElementById('advice-items');
        const empty = document.getElementById('advice-empty');
        if (!items) return;

        if (!history || history.length === 0) {
            empty.style.display = 'block';
            items.innerHTML = '';
            return;
        }

        empty.style.display = 'none';
        items.innerHTML = history.map(a => {
            const time = new Date(a.timestamp * 1000).toLocaleString('zh-TW');
            const action = a.advice_type || 'HOLD';
            const ctx = a.market_context || {};
            return `<div class="advice-card">
                <div class="advice-card-header">
                    <span class="advice-action ${action}">${action}</span>
                    <span class="advice-time">${time}</span>
                </div>
                <div class="advice-body">${a.reasoning || '無說明'}</div>
                <div class="advice-meta">
                    <span>推薦: ${a.recommended_mode || '--'}</span>
                    <span>信心: ${ctx.confidence || 0}%</span>
                    <span>風險: ${ctx.risk_level || '--'}</span>
                    <span>${a.applied ? '✅ 已套用' : '⏳ 未套用'}</span>
                </div>
            </div>`;
        }).join('');
    }

    // ═══════════════════════════════════════════════════════════
    // Phase 2: 元件健康面板
    // ═══════════════════════════════════════════════════════════
    async function fetchHealth() {
        try {
            const [compResp, busResp] = await Promise.all([
                fetch(`${API_BASE}/components`),
                fetch(`${API_BASE}/bus/stats`),
            ]);
            const compData = await compResp.json();
            const busData = await busResp.json();

            renderComponentHealth(compData.components || []);
            renderBusStats(busData);
        } catch (e) {
            console.error('健康狀態載入失敗:', e);
        }
    }

    function renderComponentHealth(components) {
        const nameMap = {
            'BinanceFeed': 'binance',
            'PolymarketFeed': 'polymarket',
            'ChainlinkFeed': 'chainlink',
        };

        components.forEach(c => {
            const key = nameMap[c.name] || c.name.toLowerCase();
            const card = document.getElementById(`health-${key}`);
            const stateEl = document.getElementById(`health-${key}-state`);
            const detailEl = document.getElementById(`health-${key}-detail`);

            if (card) {
                card.className = 'health-card ' + (c.state || '').toLowerCase();
            }
            if (stateEl) {
                stateEl.textContent = c.state || '--';
            }
            if (detailEl) {
                const uptime = c.uptime_seconds ? `${Math.floor(c.uptime_seconds / 60)}m` : '--';
                detailEl.textContent = `執行時間: ${uptime}`;
            }
        });
    }

    function renderBusStats(data) {
        if (!data) return;
        setTextContent('bus-published', formatNumber(data.total_published || 0, 0));
        setTextContent('bus-processed', formatNumber(data.total_processed || 0, 0));
        setTextContent('bus-errors', data.total_errors || 0);
        setTextContent('bus-queue', data.queue_size || 0);
    }

    // ═══════════════════════════════════════════════════════════
    // Phase 2: 初始化和事件綁定
    // ═══════════════════════════════════════════════════════════
    function initPhase2() {
        initTabs();

        // 績效
        document.getElementById('btn-refresh-perf')?.addEventListener('click', fetchPerformance);

        // 回測
        document.getElementById('btn-run-backtest')?.addEventListener('click', runBacktest);
        document.getElementById('btn-run-compare')?.addEventListener('click', runCompare);

        // AI
        document.getElementById('btn-get-context')?.addEventListener('click', fetchAIContext);
        document.getElementById('btn-get-prompt')?.addEventListener('click', fetchAIPrompt);
        document.getElementById('ai-focus')?.addEventListener('change', fetchAIPrompt);
        document.getElementById('btn-refresh-ai')?.addEventListener('click', fetchAIHistory);
        document.getElementById('btn-copy-prompt')?.addEventListener('click', () => {
            const text = document.getElementById('ai-prompt-text')?.textContent;
            if (text) {
                navigator.clipboard.writeText(text).then(() => showToast('📋 Prompt 已複製'));
            }
        });

        // 健康
        document.getElementById('btn-refresh-health')?.addEventListener('click', fetchHealth);

        // 首次載入
        fetchPerformance();
        fetchAIHistory();
        fetchHealth();
    }

    // 加入到 DOMContentLoaded（靠前面的已有，這裡補入 Phase 2）
    document.addEventListener('DOMContentLoaded', initPhase2);

    // resize 時重繪權益曲線
    window.addEventListener('resize', () => {
        fetchPerformance();
    });

})();

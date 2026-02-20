"""
🧀 CheeseDog - Telegram Bot (Phase 4: HITL 遠端審核)

透過 Telegram 實現 Human-in-the-Loop 的遠端操控：
  - 📋 新提案 → 即時推播 + Inline 核准/拒絕按鈕
  - 🚨 緊急安全閥 → 強提醒通知
  - ⚙️ 指令控制 → /status, /mode, /proposals 等
  - 📊 定時報告 → 每小時系統簡報（可選）

技術設計：
  - 使用 python-telegram-bot v20+ (async)
  - 訂閱 MessageBus 事件驅動推播
  - 所有 Token/ChatID 支援動態配置（不需重啟）
"""

import asyncio
import logging
import time
from typing import Optional

from app import config
from app.core.event_bus import bus

logger = logging.getLogger("cheesedog.telegram")

# ═══════════════════════════════════════════════════════════════
# 嘗試匯入 telegram 套件（非必要依賴）
# ═══════════════════════════════════════════════════════════════
try:
    from telegram import (
        Bot,
        Update,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
    )
    from telegram.ext import (
        Application,
        CommandHandler,
        CallbackQueryHandler,
        ContextTypes,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.info(
        "ℹ️ python-telegram-bot 未安裝。"
        "執行 `pip install python-telegram-bot` 以啟用 Telegram 功能。"
    )


class TelegramBot:
    """
    CheeseDog Telegram Bot

    提供 HITL 遠端操控、提案推播、系統監控等功能。
    可在運行中動態配置 Token 和 Chat ID。
    """

    def __init__(self):
        self._bot: Optional["Bot"] = None
        self._app: Optional["Application"] = None
        self._running = False
        self._polling_task: Optional[asyncio.Task] = None

        # 統計
        self._stats = {
            "messages_sent": 0,
            "commands_handled": 0,
            "callbacks_handled": 0,
            "errors": 0,
        }

        logger.info(
            f"🤖 TelegramBot 已初始化 | "
            f"Available={TELEGRAM_AVAILABLE} | "
            f"Enabled={config.TELEGRAM_ENABLED} | "
            f"Token={'設定' if config.TELEGRAM_BOT_TOKEN else '未設定'}"
        )

    # ── 生命週期 ──────────────────────────────────────────────

    async def start(self):
        """啟動 Telegram Bot"""
        if not TELEGRAM_AVAILABLE:
            logger.warning("⚠️ python-telegram-bot 未安裝，跳過啟動")
            return False

        if not config.TELEGRAM_ENABLED:
            logger.info("⚪ Telegram Bot 未啟用 (TELEGRAM_ENABLED=false)")
            return False

        if not config.TELEGRAM_BOT_TOKEN:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN 未設定，跳過啟動")
            return False

        try:
            self._app = (
                Application.builder()
                .token(config.TELEGRAM_BOT_TOKEN)
                .build()
            )

            # 註冊指令處理器
            self._register_handlers()

            # 初始化 Bot
            await self._app.initialize()
            self._bot = self._app.bot

            # 啟動 Polling（在背景 Task 中）
            self._running = True
            self._polling_task = asyncio.create_task(self._polling_loop())

            # 訂閱 MessageBus 事件
            self._subscribe_events()

            logger.info("🟢 Telegram Bot 已啟動")

            # 發送上線通知
            await self.send_message(
                "🧀 *乳酪のBTC預測室 已上線*\n\n"
                f"🛡️ Navigator: `{config.AI_NAVIGATOR}`\n"
                f"🔐 AuthMode: `{config.AUTHORIZATION_MODE}`\n\n"
                "輸入 /help 查看可用指令"
            )

            return True

        except Exception as e:
            logger.error(f"❌ Telegram Bot 啟動失敗: {e}")
            self._stats["errors"] += 1
            return False

    async def stop(self):
        """停止 Telegram Bot"""
        if self._running:
            self._running = False

            if self._polling_task:
                self._polling_task.cancel()
                try:
                    await self._polling_task
                except asyncio.CancelledError:
                    pass

            if self._app:
                try:
                    await self._app.shutdown()
                except Exception:
                    pass

            logger.info("🔴 Telegram Bot 已停止")

    async def _polling_loop(self):
        """Polling 迴圈（背景 Task）"""
        try:
            # 使用 updater 的 polling
            await self._app.updater.start_polling(drop_pending_updates=True)
            await self._app.start()

            # 等待直到被取消
            while self._running:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Telegram polling 錯誤: {e}")
            self._stats["errors"] += 1
        finally:
            try:
                await self._app.updater.stop()
                await self._app.stop()
            except Exception:
                pass

    # ── 指令註冊 ──────────────────────────────────────────────

    def _register_handlers(self):
        """註冊所有指令與回調處理器"""
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("proposals", self._cmd_proposals))
        self._app.add_handler(CommandHandler("mode", self._cmd_mode))
        self._app.add_handler(CommandHandler("setnavigator", self._cmd_set_navigator))
        self._app.add_handler(CommandHandler("setauth", self._cmd_set_auth))
        self._app.add_handler(CommandHandler("report", self._cmd_report))

        # Inline Button 回調 (核准/拒絕提案)
        self._app.add_handler(
            CallbackQueryHandler(self._callback_handler)
        )

        logger.info("📋 已註冊 8 個指令 + 1 個回調處理器")

    # ── 事件訂閱 ──────────────────────────────────────────────

    def _subscribe_events(self):
        """訂閱 MessageBus 事件"""

        async def on_proposal_created(event):
            if config.TELEGRAM_NOTIFY_ON_PROPOSAL:
                await self._notify_new_proposal(event.data)

        async def on_proposal_resolved(event):
            data = event.data or {}
            status = data.get("status", "")
            if status == "auto_approved" and config.TELEGRAM_NOTIFY_ON_EMERGENCY:
                await self._notify_emergency(data)

        async def on_auto_executed(event):
            if config.TELEGRAM_NOTIFY_ON_TRADE:
                await self._notify_auto_executed(event.data)

        bus.subscribe("supervisor.proposal_created", on_proposal_created)
        bus.subscribe("supervisor.proposal_resolved", on_proposal_resolved)
        bus.subscribe("supervisor.auto_executed", on_auto_executed)
        logger.info("📬 已訂閱 Supervisor 事件")

    # ── 推播方法 ──────────────────────────────────────────────

    async def send_message(
        self,
        text: str,
        reply_markup=None,
        chat_id: str = None,
    ) -> bool:
        """發送訊息到指定 Chat"""
        target = chat_id or config.TELEGRAM_CHAT_ID
        if not target or not self._bot:
            return False

        try:
            await self._bot.send_message(
                chat_id=target,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
            self._stats["messages_sent"] += 1
            return True
        except Exception as e:
            logger.error(f"Telegram 發送失敗: {e}")
            self._stats["errors"] += 1
            return False

    async def _notify_new_proposal(self, proposal_data: dict):
        """推播新提案通知 + Inline Buttons"""
        p = proposal_data
        priority_emoji = {
            "critical": "🔴",
            "high": "🟠",
            "normal": "🟡",
            "low": "🟢",
        }
        emoji = priority_emoji.get(p.get("priority", "normal"), "🟡")

        text = (
            f"{emoji} *新提案等待審核*\n\n"
            f"🆔 ID: `{p.get('id', 'N/A')}`\n"
            f"📌 動作: *{p.get('action', 'N/A')}*\n"
            f"🎯 建議模式: `{p.get('recommended_mode', 'N/A')}`\n"
            f"💪 信心度: {p.get('confidence', 0)}%\n"
            f"⚠️ 風險: {p.get('risk_level', 'N/A')}\n"
            f"🏷️ 優先級: {p.get('priority', 'N/A')}\n"
            f"⏰ 剩餘: {p.get('remaining_seconds', 0):.0f}s\n\n"
            f"💬 理由: _{p.get('reasoning', '無')}_"
        )

        # Inline Buttons
        proposal_id = p.get("id", "")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ 核准", callback_data=f"approve:{proposal_id}"
                ),
                InlineKeyboardButton(
                    "❌ 拒絕", callback_data=f"reject:{proposal_id}"
                ),
            ]
        ])

        await self.send_message(text, reply_markup=keyboard)

    async def _notify_emergency(self, data: dict):
        """推播緊急安全閥觸發通知"""
        proposal = data.get("proposal", {})
        text = (
            "🚨🚨🚨 *緊急安全閥觸發* 🚨🚨🚨\n\n"
            f"提案 `{proposal.get('id', 'N/A')}` 已自動放行！\n\n"
            f"📌 動作: *{proposal.get('action', 'N/A')}*\n"
            f"💪 信心度: {proposal.get('confidence', 0)}%\n"
            f"⚠️ 風險: {proposal.get('risk_level', 'N/A')}\n"
            f"💬 理由: _{proposal.get('reasoning', '無')}_\n\n"
            "⚡ 系統已自動執行保護性操作"
        )
        await self.send_message(text)

    async def _notify_auto_executed(self, data: dict):
        """推播 AUTO 模式下的自動執行通知"""
        text = (
            "⚡ *AUTO 模式自動執行*\n\n"
            f"📌 動作: `{data.get('action', 'N/A')}`\n"
            f"✅ 已套用: {data.get('apply_result', {}).get('applied', False)}"
        )
        await self.send_message(text)

    # ── 指令處理器 ────────────────────────────────────────────

    async def _cmd_start(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """處理 /start 指令"""
        self._stats["commands_handled"] += 1
        chat_id = str(update.effective_chat.id)

        # 如果 CHAT_ID 尚未設定，自動記錄
        if not config.TELEGRAM_CHAT_ID:
            config.TELEGRAM_CHAT_ID = chat_id
            logger.info(f"📝 自動記錄 Chat ID: {chat_id}")

        await update.message.reply_text(
            "🧀 *乳酪のBTC預測室 Telegram Bot*\n\n"
            "我是 CheeseDog 的遠端控制台。\n"
            f"你的 Chat ID: `{chat_id}`\n\n"
            "輸入 /help 查看所有指令",
            parse_mode="Markdown",
        )

    async def _cmd_help(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """處理 /help 指令"""
        self._stats["commands_handled"] += 1
        await update.message.reply_text(
            "📖 *CheeseDog 指令列表*\n\n"
            "🔹 /status — 系統狀態總覽\n"
            "🔹 /proposals — 待審核提案列表\n"
            "🔹 /report — 詳細績效報告\n"
            "🔹 /mode — 查看當前交易模式\n"
            "🔹 /setnavigator `<值>` — 設定 AI Navigator\n"
            "   選項: `openclaw` / `internal` / `none`\n"
            "🔹 /setauth `<值>` — 設定授權模式\n"
            "   選項: `auto` / `hitl` / `monitor`\n\n"
            "📋 提案通知會自動推播，直接點按鈕即可核准/拒絕",
            parse_mode="Markdown",
        )

    async def _cmd_status(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """處理 /status 指令"""
        self._stats["commands_handled"] += 1
        try:
            from app.supervisor.authorization import auth_manager
            from app.supervisor.proposal_queue import proposal_queue

            status = auth_manager.get_status()
            pq_stats = proposal_queue.get_stats()

            text = (
                "📊 *CheeseDog 系統狀態*\n\n"
                f"🛡️ Navigator: `{status['navigator']}`\n"
                f"🔐 AuthMode: `{status['auth_mode']}`\n"
                f"📋 待審提案: {pq_stats['pending_count']}\n"
                f"📈 已處理: {pq_stats['total_created']}\n"
                f"  ✅ 核准: {pq_stats['total_approved']}\n"
                f"  ❌ 拒絕: {pq_stats['total_rejected']}\n"
                f"  ⏰ 過期: {pq_stats['total_expired']}\n"
                f"  🚨 自動放行: {pq_stats['total_auto_approved']}\n\n"
                f"🤖 Telegram 訊息: {self._stats['messages_sent']}\n"
                f"⌨️ 指令處理: {self._stats['commands_handled']}"
            )
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ 取得狀態失敗: {e}")

    async def _cmd_proposals(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """處理 /proposals 指令 — 列出待審核提案"""
        self._stats["commands_handled"] += 1
        try:
            from app.supervisor.proposal_queue import proposal_queue

            pending = proposal_queue.get_pending()

            if not pending:
                await update.message.reply_text("✅ 目前沒有待審核的提案")
                return

            for p in pending[:5]:  # 最多顯示 5 筆
                await self._notify_new_proposal(p)

            if len(pending) > 5:
                await update.message.reply_text(
                    f"⚠️ 還有 {len(pending) - 5} 筆提案未顯示"
                )
        except Exception as e:
            await update.message.reply_text(f"❌ 取得提案失敗: {e}")

    async def _cmd_mode(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """處理 /mode 指令"""
        self._stats["commands_handled"] += 1
        try:
            from app.main import signal_generator
            mode = signal_generator.current_mode
            mode_info = config.TRADING_MODES.get(mode, {})

            text = (
                "🎯 *當前交易模式*\n\n"
                f"模式: `{mode}`\n"
                f"名稱: {mode_info.get('name', 'N/A')}\n"
                f"說明: {mode_info.get('description', 'N/A')}"
            )
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ 取得模式失敗: {e}")

    async def _cmd_set_navigator(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """處理 /setnavigator <值> 指令"""
        self._stats["commands_handled"] += 1
        args = context.args
        if not args:
            await update.message.reply_text(
                "❓ 用法: /setnavigator `<值>`\n"
                "可選: `openclaw` / `internal` / `none`",
                parse_mode="Markdown",
            )
            return

        value = args[0].lower()
        try:
            from app.supervisor.authorization import auth_manager
            result = auth_manager.update_settings(navigator=value)

            if result["success"]:
                await update.message.reply_text(
                    f"✅ Navigator 已更新為: `{value}`",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(f"❌ {result['error']}")
        except Exception as e:
            await update.message.reply_text(f"❌ 設定失敗: {e}")

    async def _cmd_set_auth(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """處理 /setauth <值> 指令"""
        self._stats["commands_handled"] += 1
        args = context.args
        if not args:
            await update.message.reply_text(
                "❓ 用法: /setauth `<值>`\n"
                "可選: `auto` / `hitl` / `monitor`",
                parse_mode="Markdown",
            )
            return

        value = args[0].lower()
        try:
            from app.supervisor.authorization import auth_manager
            result = auth_manager.update_settings(auth_mode=value)

            if result["success"]:
                await update.message.reply_text(
                    f"✅ AuthMode 已更新為: `{value}`",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(f"❌ {result['error']}")
        except Exception as e:
            await update.message.reply_text(f"❌ 設定失敗: {e}")

    async def _cmd_report(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """處理 /report 指令 — 取得系統績效報告"""
        self._stats["commands_handled"] += 1
        try:
            from app.main import (
                signal_generator, sim_engine,
                binance_feed, chainlink_feed,
            )

            sig_stats = signal_generator.get_cro_stats()
            sim_stats = sim_engine.get_stats()
            btc_price = chainlink_feed.state.btc_price or binance_feed.state.mid

            text = (
                "📊 *CheeseDog 績效報告*\n\n"
                f"💰 BTC: ${btc_price:,.2f}\n"
                f"🎯 模式: `{sig_stats.get('current_mode', 'N/A')}`\n\n"
                f"📈 *近 6h 績效*\n"
                f"  勝率: {sig_stats.get('win_rate_6h', 0):.1f}%\n"
                f"  交易數: {sig_stats.get('total_trades_24h', 0)} (24h)\n"
                f"  連敗: {sig_stats.get('consecutive_losses', 0)}\n\n"
                f"💼 *模擬帳戶*\n"
                f"  餘額: ${sim_stats.get('balance', 0):,.2f}\n"
                f"  PnL: ${sim_stats.get('total_pnl', 0):,.2f}\n"
                f"  未平倉: {sim_stats.get('open_trades', 0)}"
            )
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ 取得報告失敗: {e}")

    # ── 回調處理器（Inline Button） ──────────────────────────

    async def _callback_handler(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """處理 Inline Button 的回調"""
        self._stats["callbacks_handled"] += 1
        query = update.callback_query
        await query.answer()  # 確認收到

        data = query.data  # 格式: "approve:proposal_id" 或 "reject:proposal_id"
        if ":" not in data:
            await query.edit_message_text("❌ 無效的操作")
            return

        action, proposal_id = data.split(":", 1)

        try:
            from app.supervisor.proposal_queue import proposal_queue

            if action == "approve":
                result = proposal_queue.approve(
                    proposal_id,
                    note="透過 Telegram 核准",
                )
            elif action == "reject":
                result = proposal_queue.reject(
                    proposal_id,
                    note="透過 Telegram 拒絕",
                )
            else:
                await query.edit_message_text(f"❌ 未知操作: {action}")
                return

            if result["success"]:
                emoji = "✅" if action == "approve" else "❌"
                status_text = "已核准" if action == "approve" else "已拒絕"
                await query.edit_message_text(
                    f"{emoji} 提案 `{proposal_id}` {status_text}\n\n"
                    f"👤 操作者: Telegram\n"
                    f"⏰ 時間: {time.strftime('%H:%M:%S')}",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text(
                    f"⚠️ 操作失敗: {result.get('error', '未知錯誤')}"
                )

        except Exception as e:
            await query.edit_message_text(f"❌ 處理失敗: {e}")

    # ── 動態配置 ──────────────────────────────────────────────

    async def configure(
        self,
        bot_token: str = None,
        chat_id: str = None,
        enabled: bool = None,
    ) -> dict:
        """
        動態配置 Telegram Bot

        可由 AI Agent 透過 API 呼叫來設定 Token 和 Chat ID。
        設定完成後如果 enabled=True 且尚未啟動，會自動嘗試啟動。

        Args:
            bot_token: Telegram Bot Token
            chat_id: Telegram Chat ID
            enabled: 是否啟用

        Returns:
            配置結果
        """
        changes = []

        if bot_token is not None:
            config.TELEGRAM_BOT_TOKEN = bot_token
            changes.append("bot_token 已更新")

        if chat_id is not None:
            config.TELEGRAM_CHAT_ID = chat_id
            changes.append(f"chat_id 已設定為 {chat_id}")

        if enabled is not None:
            config.TELEGRAM_ENABLED = enabled
            changes.append(f"enabled 已設定為 {enabled}")

        # 如果新設定且尚未執行，嘗試啟動
        if (config.TELEGRAM_ENABLED
                and config.TELEGRAM_BOT_TOKEN
                and not self._running):
            started = await self.start()
            if started:
                changes.append("Bot 已自動啟動")
            else:
                changes.append("Bot 啟動失敗")

        return {
            "success": True,
            "changes": changes,
            "status": self.get_status(),
        }

    # ── 狀態查詢 ──────────────────────────────────────────────

    def get_status(self) -> dict:
        """取得 Bot 完整狀態"""
        return {
            "available": TELEGRAM_AVAILABLE,
            "enabled": config.TELEGRAM_ENABLED,
            "running": self._running,
            "token_set": bool(config.TELEGRAM_BOT_TOKEN),
            "chat_id": config.TELEGRAM_CHAT_ID or None,
            "stats": self._stats.copy(),
            "notify_settings": {
                "on_proposal": config.TELEGRAM_NOTIFY_ON_PROPOSAL,
                "on_emergency": config.TELEGRAM_NOTIFY_ON_EMERGENCY,
                "on_trade": config.TELEGRAM_NOTIFY_ON_TRADE,
                "hourly_report": config.TELEGRAM_HOURLY_REPORT,
            },
        }


# ═══════════════════════════════════════════════════════════════
# 全域單例
# ═══════════════════════════════════════════════════════════════
telegram_bot = TelegramBot()

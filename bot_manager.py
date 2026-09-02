"""
BotManager: مسؤول عن تشغيل/إيقاف بوتات الدعم الفرعية كـ asyncio tasks
داخل نفس العملية، كل بوت له Bot + Dispatcher خاص به.

ملاحظة مهمة للتوسع لاحقًا:
عندما يصبح لديك عشرات/مئات العملاء، الأفضل الانتقال من Polling إلى Webhooks
(endpoint واحد لكل بوت على نفس السيرفر) لأنه أخف على الموارد بكثير من
تشغيل عملية polling منفصلة لكل بوت. هذا الهيكل الحالي مثالي للبداية
والتجربة مع عدد عملاء محدود.
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from bots.support_bot_template import build_support_bot_router
from database.models import SupportBot
from database.db import get_decrypted_token

logger = logging.getLogger(__name__)


class BotManager:
    def __init__(self):
        # bot_id -> {"bot": Bot, "dp": Dispatcher, "task": asyncio.Task}
        self._running: dict[int, dict] = {}
        self.transport_mode = os.getenv("BOT_TRANSPORT", "polling").lower()
        self.public_base_url = (
            os.getenv("PUBLIC_BASE_URL")
            or os.getenv("RENDER_EXTERNAL_URL")
            or ""
        ).rstrip("/")
        self.webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")

        if self.transport_mode not in {"polling", "webhook"}:
            raise ValueError("BOT_TRANSPORT يجب أن يكون polling أو webhook")
        if self.transport_mode == "webhook" and (
            not self.public_base_url or not self.webhook_secret
        ):
            raise RuntimeError(
                "وضع Webhook يتطلب PUBLIC_BASE_URL وTELEGRAM_WEBHOOK_SECRET"
            )

    def is_running(self, bot_id: int) -> bool:
        return bot_id in self._running

    async def start_bot(self, support_bot: SupportBot):
        """يشغّل بوت دعم فرعي واحد بناءً على بيانات العميل المخزّنة"""
        if self.is_running(support_bot.id):
            logger.info(f"البوت {support_bot.id} شغّال أصلاً، تخطي.")
            return

        try:
            real_token = get_decrypted_token(support_bot)
            bot = Bot(
                token=real_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            dp = Dispatcher()

            # نبني الراوتر الخاص ببوت الدعم ونمرر له إعدادات هذا العميل تحديدًا
            router = build_support_bot_router(support_bot)
            dp.include_router(router)

            if self.transport_mode == "webhook":
                webhook_url = (
                    f"{self.public_base_url}/telegram/webhook/{support_bot.id}"
                )
                await bot.set_webhook(
                    url=webhook_url,
                    secret_token=self.webhook_secret,
                    allowed_updates=dp.resolve_used_update_types(),
                )
                task = asyncio.create_task(self._hold_webhook(bot, support_bot.id))
            else:
                task = asyncio.create_task(self._run_polling(bot, dp, support_bot.id))

            self._running[support_bot.id] = {
                "bot": bot,
                "dp": dp,
                "task": task,
                "webhook_url": webhook_url if self.transport_mode == "webhook" else None,
            }
            logger.info(f"تم تشغيل بوت الدعم #{support_bot.id} (@{support_bot.bot_username})")

        except Exception as e:
            logger.error(f"فشل تشغيل البوت #{support_bot.id}: {e}")
            raise

    async def _run_polling(self, bot: Bot, dp: Dispatcher, bot_id: int):
        try:
            await dp.start_polling(bot, handle_signals=False)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"توقف بوت الدعم #{bot_id} بسبب خطأ: {e}")

    async def _hold_webhook(self, bot: Bot, bot_id: int):
        """يبقي مهمة البوت حية بينما يستقبل السيرفر تحديثاته عبر Webhook"""
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    async def handle_webhook_update(
        self, bot_id: int, update_payload: dict, secret_token: str | None
    ) -> tuple[int, dict]:
        """يعالج Webhook مباشرة من مسار FastAPI الموحد."""
        if self.transport_mode != "webhook":
            return 404, {"detail": "webhook mode is disabled"}
        if secret_token != self.webhook_secret:
            return 401, {"detail": "invalid webhook secret"}

        try:
            entry = self._running.get(bot_id)
            if not entry:
                return 404, {"detail": "unknown bot"}
            update = Update.model_validate(update_payload)
            await entry["dp"].feed_webhook_update(entry["bot"], update)
            return 200, {"status": "ok"}
        except (ValueError, TypeError):
            return 400, {"detail": "invalid webhook payload"}
        except Exception:
            logger.exception("فشل معالجة Webhook للبوت #%s", bot_id)
            return 500, {"detail": "webhook processing failed"}

    async def stop_bot(self, bot_id: int):
        """يوقف بوت دعم فرعي (مثلًا بعد انتهاء الاشتراك)"""
        entry = self._running.pop(bot_id, None)
        if not entry:
            return
        entry["task"].cancel()
        if entry["webhook_url"]:
            try:
                await entry["bot"].delete_webhook()
            except Exception:
                logger.exception("فشل حذف Webhook للبوت #%s", bot_id)
        await entry["bot"].session.close()
        logger.info(f"تم إيقاف بوت الدعم #{bot_id}")

    async def stop_all(self):
        for bot_id in list(self._running.keys()):
            await self.stop_bot(bot_id)

# نسخة واحدة مشتركة تُستخدم في كل المشروع (Singleton بسيط)
manager = BotManager()

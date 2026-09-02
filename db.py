"""
إعداد الاتصال بقاعدة البيانات ودوال مساعدة (CRUD) للتعامل معها
"""
import os
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import delete, func, inspect, select

from database.models import (
    Base,
    Client,
    SupportBot,
    Ticket,
    TicketMessage,
    BotCommand,
    BotButton,
    BotAutoReply,
    BotChannel,
    PublishOperation,
    BaridiMobPayment,
)
from core.security import encrypt_token, decrypt_token, hash_token

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data.db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    """إنشاء الجداول عند أول تشغيل"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_token_hash_schema)
    await _backfill_token_hashes()


def _ensure_token_hash_schema(connection):
    """يضيف أعمدة/فهارس الاشتراكات عند ترقية قاعدة قديمة"""
    columns = {column["name"] for column in inspect(connection).get_columns("support_bots")}
    if "token_hash" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE support_bots ADD COLUMN token_hash VARCHAR(64)"
        )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ix_support_bots_token_hash_unique ON support_bots (token_hash)"
    )
    if "stripe_subscription_id" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE support_bots ADD COLUMN stripe_subscription_id VARCHAR(255)"
        )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ix_support_bots_stripe_subscription_id_unique "
        "ON support_bots (stripe_subscription_id)"
    )
    columns = {column["name"] for column in inspect(connection).get_columns("support_bots")}
    if "language" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE support_bots ADD COLUMN language VARCHAR(10) NOT NULL DEFAULT 'ar'"
        )


async def _backfill_token_hashes():
    """يملأ بصمات البوتات القديمة دون الاحتفاظ بالتوكن الأصلي"""
    async with async_session() as session:
        result = await session.execute(
            select(SupportBot).where(SupportBot.token_hash.is_(None))
        )
        legacy_bots = list(result.scalars().all())
        for support_bot in legacy_bots:
            try:
                support_bot.token_hash = hash_token(
                    decrypt_token(support_bot.bot_token)
                )
            except Exception:
                logger.warning(
                    "تعذّر إنشاء بصمة التوكن للبوت القديم #%s",
                    support_bot.id,
                )
        if legacy_bots:
            await session.commit()


async def get_or_create_client(telegram_id: int, full_name: str, username: str) -> Client:
    async with async_session() as session:
        result = await session.execute(select(Client).where(Client.telegram_id == telegram_id))
        client = result.scalar_one_or_none()
        if client:
            return client
        client = Client(telegram_id=telegram_id, full_name=full_name, username=username)
        session.add(client)
        await session.commit()
        await session.refresh(client)
        return client


async def create_support_bot(owner_id: int, bot_token: str, bot_username: str) -> SupportBot:
    """يخزّن التوكن مشفّرًا في القاعدة"""
    async with async_session() as session:
        bot = SupportBot(
            owner_id=owner_id,
            bot_token=encrypt_token(bot_token),
            token_hash=hash_token(bot_token),
            bot_username=bot_username,
            subscription_active=False,
            is_active=False,
        )
        session.add(bot)
        await session.commit()
        await session.refresh(bot)
        return bot


async def update_bot_language(bot_id: int, language: str) -> SupportBot | None:
    """يغيّر لغة واجهة بوت الدعم"""
    allowed = {"ar", "en", "fr", "tr", "es"}
    if language not in allowed:
        raise ValueError("لغة البوت غير مدعومة")
    async with async_session() as session:
        result = await session.execute(select(SupportBot).where(SupportBot.id == bot_id))
        bot = result.scalar_one_or_none()
        if not bot:
            return None
        bot.language = language
        await session.commit()
        await session.refresh(bot)
        return bot


async def update_support_group(bot_id: int, group_id: int | None) -> SupportBot | None:
    async with async_session() as session:
        result = await session.execute(select(SupportBot).where(SupportBot.id == bot_id))
        bot = result.scalar_one_or_none()
        if not bot:
            return None
        bot.support_group_id = group_id
        await session.commit()
        await session.refresh(bot)
        return bot


def get_decrypted_token(support_bot: SupportBot) -> str:
    """يُستخدم عند الحاجة الفعلية لتشغيل البوت بتوكنه الحقيقي"""
    return decrypt_token(support_bot.bot_token)


async def activate_subscription(bot_id: int, days: int = 30) -> SupportBot | None:
    """تُستدعى بعد تأكيد الدفع لتفعيل اشتراك بوت العميل"""
    async with async_session() as session:
        result = await session.execute(select(SupportBot).where(SupportBot.id == bot_id))
        bot = result.scalar_one_or_none()
        if not bot:
            return None
        bot.subscription_active = True
        bot.is_active = True
        bot.subscription_expires_at = datetime.utcnow() + timedelta(days=days)
        await session.commit()
        await session.refresh(bot)
        return bot


async def get_active_bots() -> list[SupportBot]:
    """كل بوتات الدعم التي يجب أن تكون شغّالة الآن (تُستخدم عند إقلاع النظام)"""
    async with async_session() as session:
        result = await session.execute(
            select(SupportBot).where(SupportBot.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())


async def get_inactive_bots() -> list[SupportBot]:
    """كل البوتات غير النشطة لمزامنة الإيقاف مع عملية main.py"""
    async with async_session() as session:
        result = await session.execute(
            select(SupportBot).where(SupportBot.is_active == False)  # noqa: E712
        )
        return list(result.scalars().all())


async def get_bots_by_owner(owner_id: int) -> list[SupportBot]:
    async with async_session() as session:
        result = await session.execute(select(SupportBot).where(SupportBot.owner_id == owner_id))
        return list(result.scalars().all())


async def update_bot_welcome(bot_id: int, welcome_message: str) -> SupportBot | None:
    async with async_session() as session:
        result = await session.execute(select(SupportBot).where(SupportBot.id == bot_id))
        bot = result.scalar_one_or_none()
        if not bot:
            return None
        bot.welcome_message = welcome_message
        await session.commit()
        await session.refresh(bot)
        return bot


async def upsert_bot_command(
    bot_id: int, command: str, response_text: str
) -> BotCommand:
    async with async_session() as session:
        result = await session.execute(
            select(BotCommand).where(
                BotCommand.bot_id == bot_id,
                BotCommand.command == command,
            )
        )
        item = result.scalar_one_or_none()
        if item:
            item.response_text = response_text
        else:
            item = BotCommand(
                bot_id=bot_id,
                command=command,
                response_text=response_text,
            )
            session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def get_bot_command(bot_id: int, command: str) -> BotCommand | None:
    async with async_session() as session:
        result = await session.execute(
            select(BotCommand).where(
                BotCommand.bot_id == bot_id,
                BotCommand.command == command,
            )
        )
        return result.scalar_one_or_none()


async def upsert_bot_button(bot_id: int, label: str, response_text: str) -> BotButton:
    async with async_session() as session:
        result = await session.execute(
            select(BotButton).where(
                BotButton.bot_id == bot_id,
                BotButton.label == label,
            )
        )
        item = result.scalar_one_or_none()
        if item:
            item.response_text = response_text
        else:
            item = BotButton(
                bot_id=bot_id,
                label=label,
                response_text=response_text,
            )
            session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def get_bot_buttons(bot_id: int) -> list[BotButton]:
    async with async_session() as session:
        result = await session.execute(
            select(BotButton).where(BotButton.bot_id == bot_id).order_by(BotButton.id)
        )
        return list(result.scalars().all())


async def get_bot_button(bot_id: int, button_id: int) -> BotButton | None:
    async with async_session() as session:
        result = await session.execute(
            select(BotButton).where(
                BotButton.id == button_id,
                BotButton.bot_id == bot_id,
            )
        )
        return result.scalar_one_or_none()


async def upsert_bot_auto_reply(
    bot_id: int, trigger: str, response_text: str
) -> BotAutoReply:
    async with async_session() as session:
        result = await session.execute(
            select(BotAutoReply).where(
                BotAutoReply.bot_id == bot_id,
                BotAutoReply.trigger == trigger,
            )
        )
        item = result.scalar_one_or_none()
        if item:
            item.response_text = response_text
        else:
            item = BotAutoReply(
                bot_id=bot_id,
                trigger=trigger,
                response_text=response_text,
            )
            session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def get_matching_auto_reply(bot_id: int, text: str) -> BotAutoReply | None:
    async with async_session() as session:
        result = await session.execute(
            select(BotAutoReply).where(BotAutoReply.bot_id == bot_id)
        )
        for item in result.scalars():
            if item.trigger.casefold() in text.casefold():
                return item
        return None


async def upsert_bot_channel(
    bot_id: int, chat_id: int, title: str | None = None
) -> BotChannel:
    async with async_session() as session:
        result = await session.execute(
            select(BotChannel).where(
                BotChannel.bot_id == bot_id,
                BotChannel.chat_id == chat_id,
            )
        )
        item = result.scalar_one_or_none()
        if item:
            if title:
                item.title = title
        else:
            item = BotChannel(bot_id=bot_id, chat_id=chat_id, title=title)
            session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def get_bot_channels(bot_id: int) -> list[BotChannel]:
    async with async_session() as session:
        result = await session.execute(
            select(BotChannel).where(BotChannel.bot_id == bot_id).order_by(BotChannel.id)
        )
        return list(result.scalars().all())


async def remove_bot_channel(bot_id: int, chat_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(BotChannel).where(
                BotChannel.bot_id == bot_id,
                BotChannel.chat_id == chat_id,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return False
        await session.delete(item)
        await session.commit()
        return True


async def get_next_post_number(bot_id: int) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(func.max(PublishOperation.post_number)).where(
                PublishOperation.bot_id == bot_id,
                PublishOperation.action == "publish",
            )
        )
        return (result.scalar_one() or 0) + 1


async def record_publish_operation(
    bot_id: int,
    post_number: int,
    action: str,
    destination_chat_id: int,
    destination_title: str | None,
    status: str,
    telegram_message_id: int | None = None,
    error_message: str | None = None,
) -> PublishOperation:
    if action not in {"publish", "delete"}:
        raise ValueError("نوع العملية غير صالح")
    if status not in {"success", "failed"}:
        raise ValueError("حالة العملية غير صالحة")
    async with async_session() as session:
        operation = PublishOperation(
            bot_id=bot_id,
            post_number=post_number,
            action=action,
            destination_chat_id=destination_chat_id,
            destination_title=destination_title,
            telegram_message_id=telegram_message_id,
            status=status,
            error_message=error_message,
        )
        session.add(operation)
        await session.commit()
        await session.refresh(operation)
        return operation


async def get_publication_numbers(bot_id: int) -> list[int]:
    async with async_session() as session:
        result = await session.execute(
            select(PublishOperation.post_number)
            .where(
                PublishOperation.bot_id == bot_id,
                PublishOperation.action == "publish",
                PublishOperation.status == "success",
            )
            .distinct()
            .order_by(PublishOperation.post_number.desc())
        )
        return list(result.scalars().all())


async def get_publication_deliveries(
    bot_id: int, post_number: int
) -> list[PublishOperation]:
    async with async_session() as session:
        result = await session.execute(
            select(PublishOperation).where(
                PublishOperation.bot_id == bot_id,
                PublishOperation.post_number == post_number,
                PublishOperation.action == "publish",
                PublishOperation.status == "success",
            )
        )
        return list(result.scalars().all())


async def get_bot_publish_stats(bot_id: int) -> dict[str, int]:
    async with async_session() as session:
        result = await session.execute(
            select(
                PublishOperation.action,
                PublishOperation.status,
                func.count(PublishOperation.id),
            )
            .where(PublishOperation.bot_id == bot_id)
            .group_by(PublishOperation.action, PublishOperation.status)
        )
        counts = {
            (action, status): count
            for action, status, count in result.all()
        }
        successful_channels = await session.execute(
            select(func.count(func.distinct(PublishOperation.destination_chat_id))).where(
                PublishOperation.bot_id == bot_id,
                PublishOperation.action == "publish",
                PublishOperation.status == "success",
            )
        )
        failed_channels = await session.execute(
            select(func.count(func.distinct(PublishOperation.destination_chat_id))).where(
                PublishOperation.bot_id == bot_id,
                PublishOperation.action == "publish",
                PublishOperation.status == "failed",
            )
        )
        channel_count = await session.execute(
            select(func.count(BotChannel.id)).where(BotChannel.bot_id == bot_id)
        )
        return {
            "published": counts.get(("publish", "success"), 0),
            "failed": counts.get(("publish", "failed"), 0),
            "deleted": counts.get(("delete", "success"), 0),
            "delete_failed": counts.get(("delete", "failed"), 0),
            "successful_channels": successful_channels.scalar_one() or 0,
            "failed_channels": failed_channels.scalar_one() or 0,
            "channels": channel_count.scalar_one() or 0,
        }


async def get_bot_by_id(bot_id: int) -> SupportBot | None:
    async with async_session() as session:
        result = await session.execute(select(SupportBot).where(SupportBot.id == bot_id))
        return result.scalar_one_or_none()


async def get_owned_bot(bot_id: int, owner_telegram_id: int) -> SupportBot | None:
    async with async_session() as session:
        result = await session.execute(
            select(SupportBot)
            .join(Client, Client.id == SupportBot.owner_id)
            .where(
                SupportBot.id == bot_id,
                Client.telegram_id == owner_telegram_id,
            )
        )
        return result.scalar_one_or_none()


async def get_bot_owner_telegram_id(bot_id: int) -> int | None:
    async with async_session() as session:
        result = await session.execute(
            select(Client.telegram_id)
            .join(SupportBot, SupportBot.owner_id == Client.id)
            .where(SupportBot.id == bot_id)
        )
        return result.scalar_one_or_none()


async def delete_bot_permanently(bot_id: int) -> bool:
    """يحذف البوت وإعداداته وتذاكره بعد تأكيد المستخدم"""
    async with async_session() as session:
        bot_result = await session.execute(
            select(SupportBot).where(SupportBot.id == bot_id)
        )
        support_bot = bot_result.scalar_one_or_none()
        if not support_bot:
            return False

        ticket_result = await session.execute(
            select(Ticket.id).where(Ticket.bot_id == bot_id)
        )
        ticket_ids = [ticket_id for (ticket_id,) in ticket_result.all()]
        if ticket_ids:
            await session.execute(
                delete(TicketMessage).where(TicketMessage.ticket_id.in_(ticket_ids))
            )
            await session.execute(delete(Ticket).where(Ticket.id.in_(ticket_ids)))
        await session.execute(delete(BotCommand).where(BotCommand.bot_id == bot_id))
        await session.execute(delete(BotButton).where(BotButton.bot_id == bot_id))
        await session.execute(
            delete(BotAutoReply).where(BotAutoReply.bot_id == bot_id)
        )
        await session.execute(delete(BotChannel).where(BotChannel.bot_id == bot_id))
        await session.execute(
            delete(PublishOperation).where(PublishOperation.bot_id == bot_id)
        )
        await session.execute(
            delete(BaridiMobPayment).where(BaridiMobPayment.bot_id == bot_id)
        )
        await session.delete(support_bot)
        await session.commit()
        return True


async def create_baridimob_payment(
    bot_id: int,
    client_telegram_id: int,
    amount_dzd: int,
    proof_file_id: str,
    proof_type: str,
) -> BaridiMobPayment:
    async with async_session() as session:
        payment = BaridiMobPayment(
            bot_id=bot_id,
            client_telegram_id=client_telegram_id,
            amount_dzd=amount_dzd,
            proof_file_id=proof_file_id,
            proof_type=proof_type,
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        return payment


async def get_baridimob_payment(payment_id: int) -> BaridiMobPayment | None:
    async with async_session() as session:
        result = await session.execute(
            select(BaridiMobPayment).where(BaridiMobPayment.id == payment_id)
        )
        return result.scalar_one_or_none()


async def review_baridimob_payment(
    payment_id: int, status: str
) -> BaridiMobPayment | None:
    if status not in {"approved", "rejected"}:
        raise ValueError("حالة BaridiMob غير صالحة")
    async with async_session() as session:
        result = await session.execute(
            select(BaridiMobPayment).where(BaridiMobPayment.id == payment_id)
        )
        payment = result.scalar_one_or_none()
        if not payment or payment.status != "pending":
            return None
        payment.status = status
        payment.reviewed_at = datetime.utcnow()
        await session.commit()
        await session.refresh(payment)
        return payment


async def get_expired_bots() -> list[SupportBot]:
    """بوتات انتهى اشتراكها ويجب إيقافها"""
    async with async_session() as session:
        result = await session.execute(
            select(SupportBot).where(
                SupportBot.is_active == True,  # noqa: E712
                SupportBot.subscription_expires_at < datetime.utcnow(),
            )
        )
        return list(result.scalars().all())


async def deactivate_bot(bot_id: int):
    async with async_session() as session:
        result = await session.execute(select(SupportBot).where(SupportBot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot:
            bot.is_active = False
            bot.subscription_active = False
            await session.commit()


async def set_stripe_subscription_id(bot_id: int, subscription_id: str):
    """يحفظ معرّف اشتراك Stripe لربط أحداث التجديد والإلغاء بالبوت"""
    async with async_session() as session:
        result = await session.execute(select(SupportBot).where(SupportBot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot:
            bot.stripe_subscription_id = subscription_id
            await session.commit()


async def get_bot_by_stripe_subscription(subscription_id: str) -> SupportBot | None:
    """يعثر على البوت المرتبط بمعرّف اشتراك Stripe"""
    async with async_session() as session:
        result = await session.execute(
            select(SupportBot).where(
                SupportBot.stripe_subscription_id == subscription_id
            )
        )
        return result.scalar_one_or_none()


async def create_ticket(bot_id: int, end_user_id: int, end_user_name: str) -> Ticket:
    async with async_session() as session:
        ticket = Ticket(bot_id=bot_id, end_user_telegram_id=end_user_id, end_user_name=end_user_name)
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        return ticket


async def create_ticket_message(
    ticket_id: int,
    forwarded_message_id: int,
    support_group_id: int,
    end_user_telegram_id: int,
) -> TicketMessage:
    """يحفظ ربط رسالة الجروب المُحوّلة بالتذكرة والمستخدم النهائي"""
    async with async_session() as session:
        ticket_message = TicketMessage(
            ticket_id=ticket_id,
            forwarded_message_id=forwarded_message_id,
            support_group_id=support_group_id,
            end_user_telegram_id=end_user_telegram_id,
        )
        session.add(ticket_message)
        await session.commit()
        await session.refresh(ticket_message)
        return ticket_message


async def get_ticket_message(
    support_group_id: int, forwarded_message_id: int
) -> TicketMessage | None:
    """يبحث عن تذكرة مرتبطة برسالة مُحوّلة داخل جروب دعم محدد"""
    async with async_session() as session:
        result = await session.execute(
            select(TicketMessage).where(
                TicketMessage.support_group_id == support_group_id,
                TicketMessage.forwarded_message_id == forwarded_message_id,
            )
        )
        return result.scalar_one_or_none()

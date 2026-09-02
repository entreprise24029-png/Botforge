"""
البوت الرئيسي (Manager Bot)
هذا هو البوت الذي يتحدث معه عملاؤك مباشرة لإنشاء بوت دعم خاص بهم.

تدفق الاستخدام المبسّط:
/start          -> ترحيب + شرح الخدمة
/create_bot     -> يطلب من العميل توكن البوت (من BotFather) ثم ينشئه في القاعدة
/my_bots        -> يعرض بوتات العميل وحالة اشتراكها
(الأدمن فقط) /activate <bot_id> <days> -> تفعيل الاشتراك يدويًا بعد تأكد الدفع
"""
import asyncio
import logging
import os
from html import escape
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Update,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database.db import (
    init_db,
    get_or_create_client,
    create_support_bot,
    get_bots_by_owner,
    activate_subscription,
    get_active_bots,
    get_inactive_bots,
    get_expired_bots,
    deactivate_bot,
    update_bot_welcome,
    upsert_bot_command,
    upsert_bot_button,
    upsert_bot_auto_reply,
    upsert_bot_channel,
    get_bot_channels,
    remove_bot_channel,
    get_owned_bot,
    delete_bot_permanently,
    update_bot_language,
    update_support_group,
    create_baridimob_payment,
    get_baridimob_payment,
    review_baridimob_payment,
)
from core.bot_manager import manager
from core.payments import create_checkout_session
from core.payments_redotpay import create_payment_order as create_redotpay_order

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAIN_BOT_TOKEN = os.getenv("MAIN_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SUB_PRICE = os.getenv("SUBSCRIPTION_PRICE", "10")
SUB_CURRENCY = os.getenv("SUBSCRIPTION_CURRENCY", "USD")
SUB_PRICE_DZD = int(os.getenv("SUBSCRIPTION_PRICE_DZD", "1500"))
BARIDIMOB_ACCOUNT_NAME = os.getenv("BARIDIMOB_ACCOUNT_NAME", "")
BARIDIMOB_RIP = os.getenv("BARIDIMOB_RIP", "")
BARIDIMOB_PHONE = os.getenv("BARIDIMOB_PHONE", "")
MAIN_BOT_NAME = os.getenv("MAIN_BOT_NAME", "ChannelForge | مطوّر القنوات")
MAIN_BOT_DESCRIPTION = os.getenv(
    "MAIN_BOT_DESCRIPTION",
    "اصنع بوتك، طوّر قناتك، وانشر محتواك بسهولة.",
)
CHANNELFORGE_CHANNEL_URL = os.getenv(
    "CHANNELFORGE_CHANNEL_URL", "https://t.me/Glow_digitali"
)

bot = Bot(token=MAIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ---------- حالات المحادثة (FSM) لإنشاء بوت جديد ----------
class CreateBotStates(StatesGroup):
    waiting_for_token = State()
    waiting_for_language = State()


class DeleteBotStates(StatesGroup):
    waiting_for_bot = State()


class BaridiMobStates(StatesGroup):
    waiting_for_proof = State()


def manager_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 صنع بوت جديد", callback_data="manager:create")],
            [
                InlineKeyboardButton(text="📋 بوتاتي", callback_data="manager:list"),
                InlineKeyboardButton(text="❓ المساعدة", callback_data="manager:help"),
            ],
            [
                InlineKeyboardButton(
                    text="📣 تابع ChannelForge",
                    url=CHANNELFORGE_CHANNEL_URL,
                )
            ],
        ]
    )


def payment_keyboard(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 بطاقة بنكية (Stripe)",
                    callback_data=f"pay:stripe:{bot_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🇩🇿 BaridiMob بالدينار الجزائري",
                    callback_data=f"pay:baridimob:{bot_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪙 عملات مستقرة/كريبتو (RedotPay)",
                    callback_data=f"pay:redotpay:{bot_id}",
                )
            ],
        ]
    )


def language_keyboard(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇸🇦 العربية", callback_data=f"lang:{bot_id}:ar"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data=f"lang:{bot_id}:en"),
            ],
            [
                InlineKeyboardButton(text="🇫🇷 Français", callback_data=f"lang:{bot_id}:fr"),
                InlineKeyboardButton(text="🇹🇷 Türkçe", callback_data=f"lang:{bot_id}:tr"),
            ],
            [
                InlineKeyboardButton(text="🇪🇸 Español", callback_data=f"lang:{bot_id}:es"),
            ],
        ]
    )


def baridimob_instructions() -> str:
    account = escape(BARIDIMOB_ACCOUNT_NAME or "يُرسل لك الأدمن بيانات الحساب")
    rip = escape(BARIDIMOB_RIP or "غير مضبوط بعد")
    phone = escape(BARIDIMOB_PHONE or "غير مضبوط بعد")
    return (
        "🇩🇿 <b>الدفع عبر BaridiMob</b>\n\n"
        f"💰 المبلغ: <b>{SUB_PRICE_DZD} DZD</b>\n"
        f"👤 اسم الحساب: <code>{account}</code>\n"
        f"🏦 RIP/CCP: <code>{rip}</code>\n"
        f"📱 الهاتف: <code>{phone}</code>\n\n"
        "حوّل المبلغ عبر BaridiMob، ثم أرسل هنا صورة الإيصال "
        "أو الملف الذي يثبت العملية.\n"
        "سيُراجع الأدمن الإثبات يدويًا، وبعد الموافقة يُفعّل البوت."
    )


async def send_my_bots(message: Message, user=None):
    user = user or message.from_user
    client = await get_or_create_client(
        telegram_id=user.id,
        full_name=user.full_name,
        username=user.username,
    )
    bots = await get_bots_by_owner(client.id)

    if not bots:
        await message.answer(
            "لا تملك أي بوت بعد. اضغط «صنع بوت جديد» أو استخدم /create_bot.",
            reply_markup=manager_keyboard(),
        )
        return

    lines = ["📋 <b>بوتاتك:</b>\n"]
    buttons = []
    for support_bot in bots:
        status = "🟢 نشط" if support_bot.is_active else "🔴 غير مفعّل"
        language = {"ar": "العربية", "en": "English", "fr": "Français", "tr": "Türkçe", "es": "Español"}.get(
            support_bot.language or "ar", "العربية"
        )
        lines.append(
            f"• @{escape(support_bot.bot_username or 'بدون اسم')} — {status} "
            f"— 🌐 {language}"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 حذف @{support_bot.bot_username or support_bot.id}",
                    callback_data=f"delete:ask:{support_bot.id}",
                )
            ]
        )
    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def send_help(message: Message):
    await message.answer(
        f"📚 <b>مساعدة {escape(MAIN_BOT_NAME)}</b>\n\n"
        "🤖 /create_bot — تسجيل بوت جديد من BotFather\n"
        "📋 /my_bots — عرض بوتاتك وحالتها\n"
        "🗑 /delete_bot — حذف بوت بعد التأكيد\n\n"
        "بعد التفعيل، يمكن إعداد الأوامر والأزرار والردود التلقائية "
        "والنشر في القنوات من إعدادات المصنع.\n\n"
        f"📣 لمعرفة المزيد عن <b>ChannelForge</b> تابعنا:\n{CHANNELFORGE_CHANNEL_URL}"
    )


async def can_manage_bot(user_id: int, bot_id: int) -> bool:
    """الأدمن أو مالك البوت يستطيع تعديل إعدادات بوتِه فقط"""
    return user_id == ADMIN_ID or bool(await get_owned_bot(bot_id, user_id))


async def configure_main_bot_profile():
    """يضبط اسم ووصف البوت الرئيسي من الإعدادات عند كل تشغيل"""
    try:
        if hasattr(bot, "set_my_name"):
            await bot.set_my_name(name=MAIN_BOT_NAME)
        if hasattr(bot, "set_my_description"):
            await bot.set_my_description(description=MAIN_BOT_DESCRIPTION)
    except Exception as exc:
        # لا نمنع تشغيل المصنع إذا كانت صلاحية API أو نسخة Telegram مختلفة.
        logger.warning("تعذّر تحديث اسم/وصف البوت الرئيسي: %s", exc)


# ---------- أوامر عامة ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await get_or_create_client(
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )
    await message.answer(
        f"👋 أهلاً بك في <b>{escape(MAIN_BOT_NAME)}</b>!\n\n"
        "اصنع بوتك الخاص، أضف له أوامر وأزرار، وانشر منشوراتك في القنوات.\n\n"
        "اختر من القائمة أو استخدم الأوامر مباشرة:",
        reply_markup=manager_keyboard(),
    )


@dp.callback_query(F.data == "manager:create")
async def callback_create_bot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "🔑 أرسل الآن توكن البوت الذي أنشأته عبر @BotFather.\n\n"
        "مثال: <code>123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11</code>"
    )
    await state.set_state(CreateBotStates.waiting_for_token)


@dp.callback_query(F.data == "manager:list")
async def callback_my_bots(callback: CallbackQuery):
    await callback.answer()
    await send_my_bots(callback.message, callback.from_user)


@dp.callback_query(F.data == "manager:help")
async def callback_help(callback: CallbackQuery):
    await callback.answer()
    await send_help(callback.message)


@dp.message(Command("create_bot"))
async def cmd_create_bot(message: Message, state: FSMContext):
    await message.answer(
        "🔑 أرسل الآن توكن البوت الذي أنشأته عبر @BotFather\n\n"
        "مثال: <code>123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11</code>"
    )
    await state.set_state(CreateBotStates.waiting_for_token)


@dp.message(CreateBotStates.waiting_for_token)
async def process_token(message: Message, state: FSMContext):
    token = (message.text or "").strip()

    # تحقق مبدئي من شكل التوكن
    if ":" not in token or len(token) < 20:
        await message.answer("❌ هذا لا يبدو توكن صالح. حاول مرة أخرى أو أرسل /cancel")
        return

    # التحقق من التوكن فعليًا عبر استدعاء getMe
    try:
        temp_bot = Bot(token=token)
        bot_info = await temp_bot.get_me()
        await temp_bot.session.close()
    except Exception:
        await message.answer("❌ التوكن غير صالح أو منتهي. تأكد منه وحاول مجددًا.")
        return

    client = await get_or_create_client(
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )

    new_bot = await create_support_bot(
        owner_id=client.id,
        bot_token=token,
        bot_username=bot_info.username,
    )

    await state.update_data(language_bot_id=new_bot.id)
    await state.set_state(CreateBotStates.waiting_for_language)
    await message.answer(
        f"✅ تم تسجيل بوتك @{bot_info.username} بنجاح!\n"
        f"🆔 رقم طلبك: <code>{new_bot.id}</code>\n\n"
        "🌐 اختر لغة واجهة البوت قبل متابعة الدفع:",
        reply_markup=language_keyboard(new_bot.id),
    )


@dp.callback_query(F.data.startswith("lang:"))
async def process_language_choice(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 3 or parts[2] not in {"ar", "en", "fr", "tr", "es"}:
        await callback.answer("⚠️ اللغة غير صالحة.", show_alert=True)
        return
    bot_id = int(parts[1])
    owned_bot = await get_owned_bot(bot_id, callback.from_user.id)
    if not owned_bot:
        await callback.answer("هذا البوت غير مرتبط بحسابك.", show_alert=True)
        return
    await update_bot_language(bot_id, parts[2])
    await state.clear()
    await callback.answer("تم حفظ اللغة ✅")
    await callback.message.answer(
        f"💰 قيمة الاشتراك الدولي: {SUB_PRICE} {SUB_CURRENCY}/شهريًا\n"
        f"🇩🇿 السعر المحلي: {SUB_PRICE_DZD} DZD/شهريًا\n\n"
        "اختر طريقة الدفع:",
        reply_markup=payment_keyboard(bot_id),
    )


@dp.message(CreateBotStates.waiting_for_language)
async def process_language_text(message: Message, state: FSMContext):
    if (message.text or "").strip().casefold() == "/cancel":
        await state.clear()
        await message.answer("↩️ تم إلغاء العملية.")
        return
    await message.answer(
        "اختر اللغة من الأزرار الظاهرة، أو أرسل /cancel لإلغاء العملية."
    )

@dp.callback_query(F.data.startswith("pay:"))
async def process_payment_choice(callback: CallbackQuery, state: FSMContext):
    _, provider, bot_id_str = callback.data.split(":")
    bot_id = int(bot_id_str)

    await callback.answer()  # إغلاق مؤشر التحميل على الزر

    if provider == "baridimob":
        owned_bot = await get_owned_bot(bot_id, callback.from_user.id)
        if not owned_bot:
            await callback.message.answer("❌ هذا البوت غير مرتبط بحسابك.")
            return
        await state.update_data(baridimob_bot_id=bot_id)
        await state.set_state(BaridiMobStates.waiting_for_proof)
        await callback.message.answer(baridimob_instructions())
        return

    try:
        if provider == "stripe":
            pay_url = create_checkout_session(
                bot_id=bot_id, client_telegram_id=callback.from_user.id
            )
        else:  # redotpay
            pay_url = await create_redotpay_order(
                bot_id=bot_id,
                client_telegram_id=callback.from_user.id,
                amount=float(SUB_PRICE),
                currency=SUB_CURRENCY,
            )

        await callback.message.answer(
            f"💳 أكمل الدفع عبر الرابط التالي:\n{pay_url}\n\n"
            "سيتم تفعيل بوتك تلقائيًا وفوريًا بعد نجاح الدفع ✅"
        )
    except Exception as e:
        logger.error(f"فشل إنشاء جلسة دفع ({provider}) للبوت #{bot_id}: {e}")
        await callback.message.answer(
            "⚠️ تعذّر إنشاء رابط الدفع تلقائيًا حاليًا. سيتواصل معك الأدمن لإتمام العملية يدويًا."
        )
        if ADMIN_ID:
            await bot.send_message(
                ADMIN_ID,
                f"🔔 فشل الدفع التلقائي ({provider}) للبوت #{bot_id} — فعّله يدويًا:\n"
                f"/activate {bot_id} 30",
            )


@dp.message(Command("my_bots"))
async def cmd_my_bots(message: Message):
    await send_my_bots(message)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await send_help(message)


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("↩️ تم إلغاء العملية.")


def delete_confirmation_keyboard(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ نعم، احذف البوت",
                    callback_data=f"delete:confirm:{bot_id}",
                ),
                InlineKeyboardButton(
                    text="↩️ إلغاء",
                    callback_data=f"delete:cancel:{bot_id}",
                ),
            ]
        ]
    )


async def ask_delete_confirmation(callback: CallbackQuery, bot_id: int):
    owned_bot = await get_owned_bot(bot_id, callback.from_user.id)
    if not owned_bot:
        await callback.message.answer("❌ هذا البوت غير مرتبط بحسابك.")
        return
    await callback.message.answer(
        f"⚠️ هل أنت متأكد من حذف @{escape(owned_bot.bot_username or str(bot_id))}؟\n\n"
        "سيتم إيقاف البوت وحذف إعداداته وتذاكره نهائيًا.",
        reply_markup=delete_confirmation_keyboard(bot_id),
    )


@dp.message(Command("delete_bot"))
async def cmd_delete_bot(message: Message, state: FSMContext):
    client = await get_or_create_client(
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )
    bots = await get_bots_by_owner(client.id)
    if not bots:
        await message.answer("لا تملك أي بوت لحذفه.")
        return
    await state.set_state(DeleteBotStates.waiting_for_bot)
    options = "\n".join(
        f"• @{escape(item.bot_username or 'بدون اسم')} (ID: {item.id})"
        for item in bots
    )
    await message.answer(
        "أرسل @username أو رقم البوت الذي تريد حذفه:\n\n" + options
    )


@dp.message(DeleteBotStates.waiting_for_bot)
async def process_delete_bot_choice(message: Message, state: FSMContext):
    identifier = (message.text or "").strip().lstrip("@").casefold()
    if not identifier:
        await message.answer("❌ أرسل username البوت أو رقمه.")
        return

    client = await get_or_create_client(
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )
    bots = await get_bots_by_owner(client.id)
    selected = next(
        (
            item
            for item in bots
            if str(item.id) == identifier
            or (item.bot_username or "").casefold() == identifier
        ),
        None,
    )
    if not selected:
        await message.answer("❌ لم أجد هذا البوت ضمن بوتاتك. أرسل username أو الرقم مرة أخرى.")
        return

    await state.clear()
    await message.answer(
        f"⚠️ هل أنت متأكد من حذف @{escape(selected.bot_username or str(selected.id))}؟\n\n"
        "سيتم إيقاف البوت وحذف إعداداته وتذاكره نهائيًا.",
        reply_markup=delete_confirmation_keyboard(selected.id),
    )


@dp.callback_query(F.data.startswith("delete:"))
async def process_delete_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("⚠️ طلب غير صالح.", show_alert=True)
        return
    action, bot_id_text = parts[1], parts[2]
    try:
        bot_id = int(bot_id_text)
    except ValueError:
        await callback.answer("⚠️ رقم البوت غير صالح.", show_alert=True)
        return

    if action == "cancel":
        await callback.answer("تم الإلغاء.")
        await callback.message.answer("↩️ لم يتم حذف البوت.")
        return
    if action != "confirm":
        await callback.answer("⚠️ طلب غير صالح.", show_alert=True)
        return

    owned_bot = await get_owned_bot(bot_id, callback.from_user.id)
    if not owned_bot:
        await callback.answer("هذا البوت غير مرتبط بحسابك.", show_alert=True)
        return

    await callback.answer()
    await manager.stop_bot(bot_id)
    await delete_bot_permanently(bot_id)
    await callback.message.answer(
        f"✅ تم حذف البوت @{escape(owned_bot.bot_username or str(bot_id))} نهائيًا."
    )


@dp.message(BaridiMobStates.waiting_for_proof)
async def process_baridimob_proof(message: Message, state: FSMContext):
    if not message.photo and not message.document:
        await message.answer(
            "❌ أرسل صورة إيصال BaridiMob أو أرسله كملف PDF/صورة."
        )
        return

    data = await state.get_data()
    bot_id = data.get("baridimob_bot_id")
    owned_bot = await get_owned_bot(bot_id, message.from_user.id)
    if not owned_bot:
        await state.clear()
        await message.answer("❌ لم يعد البوت مرتبطًا بحسابك.")
        return

    if message.photo:
        proof_file_id = message.photo[-1].file_id
        proof_type = "photo"
    else:
        proof_file_id = message.document.file_id
        proof_type = "document"

    payment = await create_baridimob_payment(
        bot_id=bot_id,
        client_telegram_id=message.from_user.id,
        amount_dzd=SUB_PRICE_DZD,
        proof_file_id=proof_file_id,
        proof_type=proof_type,
    )
    await state.clear()
    await message.answer(
        f"✅ تم استلام إثبات الدفع رقم <code>{payment.id}</code>.\n"
        "سيُراجعه الأدمن، وستصلك رسالة بعد الموافقة."
    )

    if not ADMIN_ID:
        return
    admin_caption = (
        "🇩🇿 <b>طلب دفع BaridiMob جديد</b>\n\n"
        f"🧾 رقم الطلب: <code>{payment.id}</code>\n"
        f"🤖 البوت: @{escape(owned_bot.bot_username or str(bot_id))}\n"
        f"💰 المبلغ: <b>{payment.amount_dzd} DZD</b>\n"
        f"👤 المستخدم: <code>{message.from_user.id}</code>\n\n"
        "راجع الإيصال ثم اختر القرار:"
    )
    review_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ موافقة",
                    callback_data=f"baridi_review:approve:{payment.id}",
                ),
                InlineKeyboardButton(
                    text="❌ رفض",
                    callback_data=f"baridi_review:reject:{payment.id}",
                ),
            ]
        ]
    )
    if proof_type == "photo":
        await bot.send_photo(
            chat_id=ADMIN_ID,
            photo=proof_file_id,
            caption=admin_caption,
            reply_markup=review_keyboard,
        )
    else:
        await bot.send_document(
            chat_id=ADMIN_ID,
            document=proof_file_id,
            caption=admin_caption,
            reply_markup=review_keyboard,
        )


@dp.callback_query(F.data.startswith("baridi_review:"))
async def review_baridimob_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("غير مسموح.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or parts[1] not in {"approve", "reject"}:
        await callback.answer("⚠️ طلب غير صالح.", show_alert=True)
        return
    try:
        payment_id = int(parts[2])
    except ValueError:
        await callback.answer("⚠️ رقم الطلب غير صالح.", show_alert=True)
        return

    payment = await get_baridimob_payment(payment_id)
    if not payment or payment.status != "pending":
        await callback.answer("تمت مراجعة هذا الطلب مسبقًا.", show_alert=True)
        return

    approved = parts[1] == "approve"
    reviewed = await review_baridimob_payment(
        payment_id, "approved" if approved else "rejected"
    )
    if not reviewed:
        await callback.answer("تمت مراجعة هذا الطلب مسبقًا.", show_alert=True)
        return

    await callback.answer("تم حفظ القرار.")
    if approved:
        activated_bot = await activate_subscription(payment.bot_id, days=30)
        if activated_bot:
            await manager.start_bot(activated_bot)
        await bot.send_message(
            payment.client_telegram_id,
            "✅ تمت الموافقة على دفع BaridiMob وتفعيل بوتك لمدة 30 يومًا.",
        )
        await callback.message.answer(f"✅ تمت الموافقة على طلب BaridiMob #{payment.id}.")
    else:
        await bot.send_message(
            payment.client_telegram_id,
            "❌ لم تتم الموافقة على إثبات دفع BaridiMob. تواصل مع الأدمن لإعادة المراجعة.",
        )
        await callback.message.answer(f"❌ تم رفض طلب BaridiMob #{payment.id}.")


# ---------- أوامر الأدمن ----------
@dp.message(Command("activate"))
async def cmd_activate(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("الاستخدام: /activate <bot_id> <days>")
        return

    bot_id, days = int(parts[1]), int(parts[2])
    support_bot = await activate_subscription(bot_id, days)

    if not support_bot:
        await message.answer("لم يتم العثور على بوت بهذا الرقم.")
        return

    await manager.start_bot(support_bot)
    await message.answer(f"✅ تم تفعيل وتشغيل البوت #{bot_id} لمدة {days} يوم.")


def _parse_builder_payload(message: Message, usage: str):
    """يقرأ bot_id والقيمة المفصولة بعلامة | من أوامر إعداد المصنع"""
    parts = message.text.split(maxsplit=2)
    if len(parts) != 3 or "|" not in parts[2]:
        return None, usage
    try:
        bot_id = int(parts[1])
    except ValueError:
        return None, "❌ رقم البوت غير صالح."
    left, response = parts[2].split("|", 1)
    left, response = left.strip(), response.strip()
    if not left or not response:
        return None, usage
    return (bot_id, left, response), None


@dp.message(Command("set_welcome"))
async def cmd_set_welcome(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) != 3:
        await message.answer("الاستخدام: /set_welcome <bot_id> <رسالة الترحيب>")
        return
    try:
        bot_id = int(parts[1])
    except ValueError:
        await message.answer("❌ رقم البوت غير صالح.")
        return
    if not await can_manage_bot(message.from_user.id, bot_id):
        await message.answer("❌ لا يمكنك تعديل هذا البوت.")
        return
    if not await update_bot_welcome(bot_id, parts[2].strip()):
        await message.answer("❌ لم يتم العثور على البوت.")
        return
    await message.answer(f"✅ تم تحديث رسالة ترحيب البوت #{bot_id}.")


@dp.message(Command("add_command"))
async def cmd_add_command(message: Message):
    parsed, error = _parse_builder_payload(
        message,
        "الاستخدام: /add_command <bot_id> <command> | <response>",
    )
    if error:
        await message.answer(error)
        return
    bot_id, command, response = parsed
    if not await can_manage_bot(message.from_user.id, bot_id):
        await message.answer("❌ لا يمكنك تعديل هذا البوت.")
        return
    command = command.lstrip("/").casefold()
    if not command.replace("_", "").isalnum():
        await message.answer("❌ اسم الأمر يجب أن يحتوي على حروف أو أرقام أو _.")
        return
    await upsert_bot_command(bot_id, command, response)
    await message.answer(f"✅ تم حفظ الأمر /{command} للبوت #{bot_id}.")


@dp.message(Command("add_button"))
async def cmd_add_button(message: Message):
    parsed, error = _parse_builder_payload(
        message,
        "الاستخدام: /add_button <bot_id> <label> | <response>",
    )
    if error:
        await message.answer(error)
        return
    bot_id, label, response = parsed
    if not await can_manage_bot(message.from_user.id, bot_id):
        await message.answer("❌ لا يمكنك تعديل هذا البوت.")
        return
    await upsert_bot_button(bot_id, label, response)
    await message.answer(f"✅ تم حفظ الزر «{label}» للبوت #{bot_id}.")


@dp.message(Command("add_auto_reply"))
async def cmd_add_auto_reply(message: Message):
    parsed, error = _parse_builder_payload(
        message,
        "الاستخدام: /add_auto_reply <bot_id> <trigger> | <response>",
    )
    if error:
        await message.answer(error)
        return
    bot_id, trigger, response = parsed
    if not await can_manage_bot(message.from_user.id, bot_id):
        await message.answer("❌ لا يمكنك تعديل هذا البوت.")
        return
    await upsert_bot_auto_reply(bot_id, trigger, response)
    await message.answer(f"✅ تم حفظ الرد التلقائي للبوت #{bot_id}.")


@dp.message(Command("add_channel"))
async def cmd_add_channel(message: Message):
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(
            "الاستخدام: /add_channel <bot_id> <channel_id> [اسم القناة]"
        )
        return
    try:
        bot_id = int(parts[1])
        channel_id = int(parts[2])
    except ValueError:
        await message.answer("❌ bot_id وchannel_id يجب أن يكونا أرقامًا.")
        return
    if not await can_manage_bot(message.from_user.id, bot_id):
        await message.answer("❌ لا يمكنك تعديل هذا البوت.")
        return
    title = parts[3].strip() if len(parts) == 4 else None
    await upsert_bot_channel(bot_id, channel_id, title)
    await message.answer(
        f"✅ تمت إضافة القناة {channel_id} إلى قائمة نشر البوت #{bot_id}.\n"
        "تأكد من أن البوت مشرف في القناة."
    )


@dp.message(Command("channels"))
async def cmd_channels(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("الاستخدام: /channels <bot_id>")
        return
    try:
        bot_id = int(parts[1])
    except ValueError:
        await message.answer("❌ رقم البوت غير صالح.")
        return
    if not await can_manage_bot(message.from_user.id, bot_id):
        await message.answer("❌ لا يمكنك رؤية إعدادات هذا البوت.")
        return
    channels = await get_bot_channels(bot_id)
    if not channels:
        await message.answer("لا توجد قنوات مضافة لهذا البوت.")
        return
    lines = [f"📣 قنوات نشر البوت #{bot_id}:"]
    lines.extend(
        f"• {channel.title or 'بدون اسم'} — {channel.chat_id}"
        for channel in channels
    )
    await message.answer("\n".join(lines))


@dp.message(Command("remove_channel"))
async def cmd_remove_channel(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("الاستخدام: /remove_channel <bot_id> <channel_id>")
        return
    try:
        bot_id = int(parts[1])
        channel_id = int(parts[2])
    except ValueError:
        await message.answer("❌ bot_id وchannel_id يجب أن يكونا أرقامًا.")
        return
    if not await can_manage_bot(message.from_user.id, bot_id):
        await message.answer("❌ لا يمكنك تعديل هذا البوت.")
        return
    removed = await remove_bot_channel(bot_id, channel_id)
    await message.answer(
        "✅ تمت إزالة القناة." if removed else "❌ القناة غير موجودة."
    )


@dp.message(Command("set_support_group"))
async def cmd_set_support_group(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer(
            "الاستخدام: /set_support_group <bot_id> <group_id>\n"
            "مثال: /set_support_group 12 -1001234567890"
        )
        return
    try:
        bot_id, group_id = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("❌ bot_id وgroup_id يجب أن يكونا أرقامًا.")
        return
    if not await can_manage_bot(message.from_user.id, bot_id):
        await message.answer("❌ لا يمكنك تعديل هذا البوت.")
        return
    if not await update_support_group(bot_id, group_id):
        await message.answer("❌ لم يتم العثور على البوت.")
        return
    await message.answer(
        f"✅ تم ربط مجموعة الدعم {group_id} بالبوت #{bot_id}.\n"
        "تأكد من إضافة البوت إلى المجموعة ومنحه صلاحية إرسال الرسائل."
    )


# ---------- مهام دورية ----------
async def check_expired_subscriptions():
    """يفحص كل ساعة الاشتراكات المنتهية ويوقف البوتات المعنية"""
    expired = await get_expired_bots()
    for b in expired:
        await manager.stop_bot(b.id)
        await deactivate_bot(b.id)
        logger.info(f"تم إيقاف البوت #{b.id} لانتهاء الاشتراك")


async def sync_newly_activated_bots():
    """
    يفحص كل دقيقة عن بوتات أصبحت is_active=True (مثلًا عبر ويبهوك Stripe
    الذي يعمل في عملية لوحة التحكم المنفصلة) ولم تُشغَّل بعد في هذه العملية.
    """
    active_bots = await get_active_bots()
    for b in active_bots:
        if not manager.is_running(b.id):
            await manager.start_bot(b)
            logger.info(f"تمت مزامنة وتشغيل البوت #{b.id} بعد تفعيله عبر الدفع.")


async def sync_deactivated_bots():
    """يوقف البوتات التي عُطّلت عبر إلغاء Stripe أو لوحة التحكم"""
    inactive_bots = await get_inactive_bots()
    for support_bot in inactive_bots:
        if manager.is_running(support_bot.id):
            await manager.stop_bot(support_bot.id)
            logger.info(f"تمت مزامنة وإيقاف البوت #{support_bot.id}.")


# ---------- الإقلاع ----------
runtime_scheduler = None
main_polling_task = None


async def start_runtime():
    """يشغّل كل مكونات ChannelForge داخل عملية واحدة."""
    global runtime_scheduler, main_polling_task

    if runtime_scheduler:
        return

    await init_db()
    await configure_main_bot_profile()

    if manager.transport_mode == "webhook":
        await bot.set_webhook(
            url=f"{manager.public_base_url}/telegram/webhook/main",
            secret_token=manager.webhook_secret,
            allowed_updates=dp.resolve_used_update_types(),
        )
        logger.info("تم تسجيل Webhook للبوت الرئيسي.")
    else:
        main_polling_task = asyncio.create_task(
            dp.start_polling(bot, handle_signals=False)
        )

    # تشغيل كل بوتات الدعم الفرعية النشطة بعد إعادة تشغيل الخادم.
    active_bots = await get_active_bots()
    for support_bot in active_bots:
        await manager.start_bot(support_bot)

    runtime_scheduler = AsyncIOScheduler()
    runtime_scheduler.add_job(check_expired_subscriptions, "interval", hours=1)
    runtime_scheduler.add_job(sync_newly_activated_bots, "interval", minutes=1)
    runtime_scheduler.add_job(sync_deactivated_bots, "interval", minutes=1)
    runtime_scheduler.start()
    logger.info("🚀 ChannelForge يعمل الآن عبر عملية واحدة.")


async def stop_runtime():
    """يوقف الـ polling والـ webhooks والبوتات الفرعية عند إغلاق العملية."""
    global runtime_scheduler, main_polling_task

    if runtime_scheduler:
        runtime_scheduler.shutdown(wait=False)
        runtime_scheduler = None

    if main_polling_task:
        main_polling_task.cancel()
        try:
            await main_polling_task
        except asyncio.CancelledError:
            pass
        main_polling_task = None

    if manager.transport_mode == "webhook":
        try:
            await bot.delete_webhook()
        except Exception:
            logger.exception("فشل حذف Webhook البوت الرئيسي.")
    await manager.stop_all()


async def handle_main_webhook(update_payload: dict, secret_token: str | None):
    """يتعامل مع Webhook البوت الرئيسي من مسار FastAPI الموحد."""
    if manager.transport_mode != "webhook":
        return 404, {"detail": "webhook mode is disabled"}
    if secret_token != manager.webhook_secret:
        return 401, {"detail": "invalid webhook secret"}
    try:
        update = Update.model_validate(update_payload)
        await dp.feed_webhook_update(bot, update)
        return 200, {"status": "ok"}
    except (ValueError, TypeError):
        return 400, {"detail": "invalid webhook payload"}
    except Exception:
        logger.exception("فشل معالجة Webhook البوت الرئيسي.")
        return 500, {"detail": "webhook processing failed"}


async def main():
    await start_runtime()
    try:
        # في وضعي polling وwebhook تبقى العملية حية حتى يغلقها الخادم.
        await asyncio.Event().wait()
    finally:
        await stop_runtime()


if __name__ == "__main__":
    asyncio.run(main())

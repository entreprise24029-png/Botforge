"""
قالب بوت الدعم والنشر لكل بوت ينشئه ChannelForge.

يستطيع مالك البوت من داخل البوت نفسه:
- إضافة القنوات بتمرير منشور منها أو إرسال @username/ID (وتُقبل الصورة مع
  username في التعليق).
- إنشاء منشور، معرفة رقم المنشور، وحذف منشور سبق نشره.
- مشاهدة إحصائيات النجاح والفشل وتغيير لغة الواجهة.
"""
from html import escape
import os
import re

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.filters import CommandStart

from database.db import (
    create_ticket,
    create_ticket_message,
    get_bot_buttons,
    get_bot_channels,
    get_bot_command,
    get_bot_owner_telegram_id,
    get_bot_publish_stats,
    get_bot_button,
    get_matching_auto_reply,
    get_next_post_number,
    get_publication_deliveries,
    get_publication_numbers,
    get_ticket_message,
    record_publish_operation,
    remove_bot_channel,
    update_bot_language,
    upsert_bot_channel,
)
from database.models import SupportBot


MAX_TELEGRAM_CAPTION_LENGTH = 1024
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNELFORGE_CHANNEL_URL = os.getenv(
    "CHANNELFORGE_CHANNEL_URL", "https://t.me/Glow_digitali"
)
MAIN_BOT_URL = os.getenv("MAIN_BOT_URL", "")
if not MAIN_BOT_URL and os.getenv("MAIN_BOT_USERNAME"):
    MAIN_BOT_URL = f"https://t.me/{os.getenv('MAIN_BOT_USERNAME').lstrip('@')}"

LANGUAGE_NAMES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Français",
    "tr": "Türkçe",
    "es": "Español",
}

TEXT = {
    "ar": {
        "add": "➕ إضافة قناة",
        "channels": "📣 قنوات النشر",
        "publish": "➕ إضافة منشور",
        "delete": "🗑 حذف منشور",
        "stats": "📊 إحصائياتي",
        "language": "🌐 اللغة",
        "help": "❓ المساعدة",
        "forge": "📣 ChannelForge",
        "choose_language": "اختر لغة البوت:",
        "no_channels": "لا توجد قنوات مضافة بعد.",
        "add_prompt": "أرسل منشورًا مُعاد توجيهه من القناة، أو أرسل @username/ID القناة. ويمكنك إرسال صورة من القناة مع @username في التعليق.",
        "photo_need_ref": "تم استلام الصورة ✅ أرسل @username أو ID القناة في رسالة تالية، أو أعد توجيه منشور من القناة حتى أتعرف عليها تلقائيًا.",
        "publish_prompt": "أرسل الآن نص المنشور أو الصورة أو الفيديو أو الملف مع تعليق اختياري.",
        "delete_prompt": "أرسل رقم المنشور الذي تريد حذفه. الأرقام المتاحة:",
        "no_posts": "لا توجد منشورات ناجحة يمكن حذفها.",
        "bad_number": "أرسل رقم منشور صحيحًا.",
        "not_found": "لم أجد هذا الرقم ضمن منشورات البوت.",
        "support_group": "مجموعة الدعم",
        "published": "تم النشر",
        "failed": "فشل",
        "deleted": "تم الحذف",
        "delete_failed": "فشل الحذف",
        "check": "🔎 فحص الصلاحيات",
        "back": "↩️ رجوع",
        "help_text": "أرسل رسالتك وسيتواصل معك فريق الدعم.\n\nيمكن لمالك البوت إدارة القنوات والمنشورات من أزرار الإدارة.",
        "own_bot": "هل تريد بوت دعم خاصًا بك؟ اصنعه عبر ChannelForge:",
    },
    "en": {
        "add": "➕ Add channel", "channels": "📣 Publishing channels",
        "publish": "➕ Add post", "delete": "🗑 Delete post",
        "stats": "📊 My statistics", "language": "🌐 Language",
        "help": "❓ Help", "forge": "📣 ChannelForge",
        "choose_language": "Choose the bot language:", "no_channels": "No channels added yet.",
        "add_prompt": "Forward a post from the channel, or send its @username/ID. You can also send a channel screenshot with @username in the caption.",
        "photo_need_ref": "Screenshot received ✅ Send the channel @username or ID next, or forward a post from that channel so I can identify it automatically.",
        "publish_prompt": "Send the post text, image, video, or file with an optional caption.",
        "delete_prompt": "Send the post number to delete. Available numbers:",
        "no_posts": "There are no successful posts to delete.", "bad_number": "Send a valid post number.",
        "not_found": "That number was not found.", "support_group": "Support groups",
        "published": "Published", "failed": "Failed", "deleted": "Deleted",
        "delete_failed": "Delete failed", "check": "🔎 Check permissions",
        "back": "↩️ Back", "help_text": "Send your message and the support team will reply.",
        "own_bot": "Want your own support bot? Create one with ChannelForge:",
    },
    "fr": {
        "add": "➕ Ajouter une chaîne", "channels": "📣 Chaînes de publication",
        "publish": "➕ Ajouter une publication", "delete": "🗑 Supprimer",
        "stats": "📊 Mes statistiques", "language": "🌐 Langue",
        "help": "❓ Aide", "forge": "📣 ChannelForge",
        "choose_language": "Choisissez la langue du bot :", "no_channels": "Aucune chaîne ajoutée.",
        "add_prompt": "Transférez une publication de la chaîne ou envoyez son @username/ID. Une capture avec @username en légende est aussi acceptée.",
        "photo_need_ref": "Image reçue ✅ Envoyez ensuite le @username ou l'ID de la chaîne.",
        "publish_prompt": "Envoyez le texte, l'image, la vidéo ou le fichier.",
        "delete_prompt": "Envoyez le numéro de la publication à supprimer :", "no_posts": "Aucune publication à supprimer.",
        "bad_number": "Envoyez un numéro valide.", "not_found": "Numéro introuvable.",
        "support_group": "Groupes support", "published": "Publié", "failed": "Échec",
        "deleted": "Supprimé", "delete_failed": "Échec de suppression", "check": "🔎 Vérifier",
        "back": "↩️ Retour", "help_text": "Envoyez votre message et l'équipe support vous répondra.",
        "own_bot": "Vous voulez votre propre bot ? Créez-le avec ChannelForge:",
    },
    "tr": {
        "add": "➕ Kanal ekle", "channels": "📣 Yayın kanalları",
        "publish": "➕ Gönderi ekle", "delete": "🗑 Gönderiyi sil",
        "stats": "📊 İstatistiklerim", "language": "🌐 Dil",
        "help": "❓ Yardım", "forge": "📣 ChannelForge",
        "choose_language": "Bot dilini seçin:", "no_channels": "Henüz kanal eklenmedi.",
        "add_prompt": "Kanaldan bir gönderi iletin veya @kullanıcı adı/ID gönderin. Açıklamada @kullanıcı adı bulunan ekran görüntüsü de kabul edilir.",
        "photo_need_ref": "Görüntü alındı ✅ Kanal @kullanıcı adını veya ID'sini gönderin.",
        "publish_prompt": "Metin, resim, video veya dosya gönderin.", "delete_prompt": "Silinecek gönderi numarasını gönderin:",
        "no_posts": "Silinecek başarılı gönderi yok.", "bad_number": "Geçerli bir numara gönderin.",
        "not_found": "Numara bulunamadı.", "support_group": "Destek grupları",
        "published": "Yayınlandı", "failed": "Başarısız", "deleted": "Silindi",
        "delete_failed": "Silme başarısız", "check": "🔎 Yetkileri kontrol et",
        "back": "↩️ Geri", "help_text": "Mesajınızı gönderin, destek ekibi yanıtlayacaktır.",
        "own_bot": "Kendi destek botunuzu mu istiyorsunuz? ChannelForge ile oluşturun:",
    },
    "es": {
        "add": "➕ Añadir canal", "channels": "📣 Canales de publicación",
        "publish": "➕ Añadir publicación", "delete": "🗑 Eliminar publicación",
        "stats": "📊 Mis estadísticas", "language": "🌐 Idioma",
        "help": "❓ Ayuda", "forge": "📣 ChannelForge",
        "choose_language": "Elige el idioma del bot:", "no_channels": "Aún no hay canales.",
        "add_prompt": "Reenvía una publicación del canal o envía su @usuario/ID. También se acepta una captura con @usuario en el comentario.",
        "photo_need_ref": "Imagen recibida ✅ Envía el @usuario o ID del canal.",
        "publish_prompt": "Envía el texto, imagen, vídeo o archivo.", "delete_prompt": "Envía el número de la publicación:",
        "no_posts": "No hay publicaciones para eliminar.", "bad_number": "Envía un número válido.",
        "not_found": "Número no encontrado.", "support_group": "Grupos de soporte",
        "published": "Publicado", "failed": "Fallido", "deleted": "Eliminado",
        "delete_failed": "Error al eliminar", "check": "🔎 Comprobar permisos",
        "back": "↩️ Volver", "help_text": "Envía tu mensaje y el equipo de soporte responderá.",
        "own_bot": "¿Quieres tu propio bot de soporte? Créalo con ChannelForge:",
    },
}


def _t(support_bot: SupportBot, key: str) -> str:
    return TEXT.get(support_bot.language or "ar", TEXT["ar"]).get(key, TEXT["ar"][key])


def _escape_and_limit(value: str | None) -> str | None:
    if value is None:
        return None
    escaped = escape(value)
    if len(escaped) <= MAX_TELEGRAM_CAPTION_LENGTH:
        return escaped
    truncated = escaped[: MAX_TELEGRAM_CAPTION_LENGTH - 1]
    if truncated.rfind("&") > truncated.rfind(";"):
        truncated = truncated[: truncated.rfind("&")]
    return f"{truncated}…"


def _ticket_header(ticket, message: Message) -> str:
    username = message.from_user.username or "بدون يوزر"
    return (
        f"🎫 تذكرة جديدة #{ticket.id}\n"
        f"👤 من: {message.from_user.full_name} (@{username})\n\n"
    )


def _message_description(message: Message) -> str:
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    if message.photo:
        return "[صورة]"
    if message.video:
        return "[فيديو]"
    if message.document:
        return f"[ملف: {message.document.file_name or 'ملف'}]"
    return "[محتوى غير نصي]"


async def _send_to_support_group(bot: Bot, support_bot: SupportBot, ticket, message: Message) -> Message:
    caption = _escape_and_limit(
        f"{_ticket_header(ticket, message)}💬 {_message_description(message)}\n\n"
        "↩️ للرد: اعمل Reply على هذه الرسالة"
    )
    chat_id = support_bot.support_group_id
    if message.photo:
        return await bot.send_photo(chat_id=chat_id, photo=message.photo[-1].file_id, caption=caption)
    if message.video:
        return await bot.send_video(chat_id=chat_id, video=message.video.file_id, caption=caption)
    if message.document:
        return await bot.send_document(chat_id=chat_id, document=message.document.file_id, caption=caption)
    if message.text:
        return await bot.send_message(chat_id=chat_id, text=caption)
    return await bot.forward_message(chat_id=chat_id, from_chat_id=message.chat.id, message_id=message.message_id)


async def _send_to_end_user(bot: Bot, user_id: int, message: Message, ticket_id: int):
    reply_text = message.text or message.caption
    safe_reply_caption = _escape_and_limit(reply_text)
    if message.photo:
        return await bot.send_photo(chat_id=user_id, photo=message.photo[-1].file_id, caption=safe_reply_caption)
    if message.video:
        return await bot.send_video(chat_id=user_id, video=message.video.file_id, caption=safe_reply_caption)
    if message.document:
        return await bot.send_document(chat_id=user_id, document=message.document.file_id, caption=safe_reply_caption)
    if reply_text:
        return await bot.send_message(
            chat_id=user_id,
            text=f"📩 <b>رد فريق الدعم على تذكرتك #{ticket_id}</b>\n\n{_escape_and_limit(reply_text)}",
        )
    return None


def _management_keyboard(support_bot: SupportBot) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_t(support_bot, "channels"), callback_data="cf:channels"),
                InlineKeyboardButton(text=_t(support_bot, "publish"), callback_data="cf:publish"),
            ],
            [
                InlineKeyboardButton(text=_t(support_bot, "delete"), callback_data="cf:delete"),
                InlineKeyboardButton(text=_t(support_bot, "stats"), callback_data="cf:stats"),
            ],
            [
                InlineKeyboardButton(text=_t(support_bot, "language"), callback_data="cf:language"),
                InlineKeyboardButton(text=_t(support_bot, "help"), callback_data="cf:help"),
            ],
            [InlineKeyboardButton(text=_t(support_bot, "forge"), url=CHANNELFORGE_CHANNEL_URL)],
        ]
    )


def _language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🇸🇦 {LANGUAGE_NAMES['ar']}", callback_data="cf_lang:ar"),
                InlineKeyboardButton(text=f"🇬🇧 {LANGUAGE_NAMES['en']}", callback_data="cf_lang:en"),
            ],
            [
                InlineKeyboardButton(text=f"🇫🇷 {LANGUAGE_NAMES['fr']}", callback_data="cf_lang:fr"),
                InlineKeyboardButton(text=f"🇹🇷 {LANGUAGE_NAMES['tr']}", callback_data="cf_lang:tr"),
            ],
            [InlineKeyboardButton(text=f"🇪🇸 {LANGUAGE_NAMES['es']}", callback_data="cf_lang:es")],
        ]
    )


async def _can_manage(support_bot: SupportBot, user_id: int) -> bool:
    owner_id = await get_bot_owner_telegram_id(support_bot.id)
    return user_id == ADMIN_ID or user_id == owner_id


async def _publish_to_channels(bot: Bot, support_bot: SupportBot, message: Message, channels, post_number: int):
    sent_count = 0
    failed_count = 0
    for channel in channels:
        try:
            if message.photo:
                sent = await bot.send_photo(
                    chat_id=channel.chat_id,
                    photo=message.photo[-1].file_id,
                    caption=_escape_and_limit(message.caption),
                )
            elif message.video:
                sent = await bot.send_video(
                    chat_id=channel.chat_id,
                    video=message.video.file_id,
                    caption=_escape_and_limit(message.caption),
                )
            elif message.document:
                sent = await bot.send_document(
                    chat_id=channel.chat_id,
                    document=message.document.file_id,
                    caption=_escape_and_limit(message.caption),
                )
            elif message.text:
                sent = await bot.send_message(
                    chat_id=channel.chat_id, text=_escape_and_limit(message.text)
                )
            else:
                sent = await bot.forward_message(
                    chat_id=channel.chat_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
            await record_publish_operation(
                support_bot.id, post_number, "publish", channel.chat_id,
                channel.title, "success", sent.message_id,
            )
            sent_count += 1
        except Exception as exc:
            await record_publish_operation(
                support_bot.id, post_number, "publish", channel.chat_id,
                channel.title, "failed", error_message=str(exc)[:1000],
            )
            failed_count += 1
    return sent_count, failed_count


def _channel_reference(message: Message):
    """يستخرج القناة من منشور مُعاد توجيهه أو من النص/تعليق الصورة."""
    origin = getattr(message, "forward_origin", None)
    source_chat = getattr(origin, "chat", None)
    if source_chat and getattr(source_chat, "type", None) == "channel":
        return source_chat.id, source_chat.title or source_chat.username
    value = (message.caption if message.photo else message.text) or ""
    username = re.search(r"@[A-Za-z0-9_]{4,32}", value)
    if username:
        return username.group(0), None
    value = value.strip()
    return (value if value.lstrip("-").isdigit() else None), None


async def _add_channel_from_message(bot: Bot, support_bot: SupportBot, message: Message):
    reference, forwarded_title = _channel_reference(message)
    if not reference:
        await message.answer(_t(support_bot, "photo_need_ref"))
        return False
    try:
        lookup = reference
        if isinstance(lookup, str) and lookup.lstrip("-").isdigit():
            lookup = int(lookup)
        chat = await bot.get_chat(lookup)
        if chat.type not in {"channel", "group", "supergroup"}:
            raise ValueError("chat is not a channel or group")
        title = getattr(chat, "title", None) or forwarded_title or getattr(chat, "username", None)
        await upsert_bot_channel(support_bot.id, chat.id, title)
        await message.answer(
            f"✅ تمت إضافة {title or chat.id}.\n"
            "تأكد من منح البوت صلاحية النشر، ثم استخدم «إضافة منشور».",
            reply_markup=_management_keyboard(support_bot),
        )
        return True
    except Exception:
        await message.answer(
            "❌ لم أتعرف على القناة أو لا أملك صلاحية الوصول إليها. "
            "أرسل @username صحيحًا أو ID يبدأ بـ -100، وتأكد من إضافة البوت كمشرف."
        )
        return False


async def _channel_menu(message: Message, bot: Bot, support_bot: SupportBot):
    channels = await get_bot_channels(support_bot.id)
    rows = [
        [InlineKeyboardButton(text=_t(support_bot, "add"), callback_data="cf:add_channel")],
        [InlineKeyboardButton(text=_t(support_bot, "check"), callback_data="cf:check")],
    ]
    if channels:
        text = f"{_t(support_bot, 'channels')}:\n" + "\n".join(
            f"• {channel.title or channel.chat_id} — {channel.chat_id}" for channel in channels
        )
        for channel in channels:
            rows.append([
                InlineKeyboardButton(
                    text=f"🗑 {channel.title or channel.chat_id}",
                    callback_data=f"cf:remove:{channel.chat_id}",
                )
            ])
    else:
        text = _t(support_bot, "no_channels")
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _stats_message(message: Message, support_bot: SupportBot):
    stats = await get_bot_publish_stats(support_bot.id)
    group_count = 1 if support_bot.support_group_id else 0
    await message.answer(
        f"📊 <b>{_t(support_bot, 'stats')}</b>\n\n"
        f"📣 القنوات المضافة: <b>{stats['channels']}</b>\n"
        f"✅ القنوات التي نجح فيها النشر: <b>{stats['successful_channels']}</b>\n"
        f"❌ القنوات التي فشل فيها النشر: <b>{stats['failed_channels']}</b>\n"
        f"📤 عمليات النشر الناجحة: <b>{stats['published']}</b>\n"
        f"⚠️ عمليات النشر الفاشلة: <b>{stats['failed']}</b>\n"
        f"🗑 عمليات الحذف الناجحة: <b>{stats['deleted']}</b>\n"
        f"👥 {_t(support_bot, 'support_group')}: <b>{group_count}</b>"
    )


def build_support_bot_router(support_bot: SupportBot) -> Router:
    router = Router()
    publish_mode = False
    add_channel_mode = False
    delete_post_mode = False

    @router.message(CommandStart())
    async def start_handler(message: Message):
        buttons = await get_bot_buttons(support_bot.id)
        rows = [[InlineKeyboardButton(text=item.label, callback_data=f"botbtn:{item.id}")] for item in buttons]
        if await _can_manage(support_bot, message.from_user.id):
            rows.extend(_management_keyboard(support_bot).inline_keyboard)
        elif MAIN_BOT_URL:
            rows.append([InlineKeyboardButton(text="🤖 ChannelForge", url=MAIN_BOT_URL)])
        await message.answer(
            f"👋 <b>{escape(support_bot.company_name)}</b>\n\n"
            f"{support_bot.welcome_message}\n\n"
            f"{_t(support_bot, 'own_bot')}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
        )

    @router.callback_query(F.data.startswith("botbtn:"))
    async def handle_custom_button(callback: CallbackQuery):
        try:
            button_id = int(callback.data.split(":", 1)[1])
        except (AttributeError, ValueError):
            await callback.answer("⚠️ هذا الزر غير صالح.", show_alert=True)
            return
        button = await get_bot_button(support_bot.id, button_id)
        if not button:
            await callback.answer("⚠️ هذا الزر غير متاح.", show_alert=True)
            return
        await callback.answer()
        await callback.message.answer(button.response_text)

    @router.callback_query(F.data.startswith("cf:"))
    async def handle_management_callback(callback: CallbackQuery):
        nonlocal publish_mode, add_channel_mode, delete_post_mode
        if not await _can_manage(support_bot, callback.from_user.id):
            await callback.answer("غير مسموح.", show_alert=True)
            return
        parts = callback.data.split(":")
        action = parts[1]
        await callback.answer()
        if action == "channels":
            await _channel_menu(callback.message, callback.bot, support_bot)
        elif action == "add_channel":
            add_channel_mode, publish_mode, delete_post_mode = True, False, False
            await callback.message.answer(_t(support_bot, "add_prompt"))
        elif action == "publish":
            publish_mode, add_channel_mode, delete_post_mode = True, False, False
            await callback.message.answer(_t(support_bot, "publish_prompt"))
        elif action == "delete":
            numbers = await get_publication_numbers(support_bot.id)
            if not numbers:
                await callback.message.answer(_t(support_bot, "no_posts"))
            else:
                delete_post_mode, publish_mode, add_channel_mode = True, False, False
                await callback.message.answer(
                    f"{_t(support_bot, 'delete_prompt')} {', '.join(map(str, numbers))}"
                )
        elif action == "stats":
            await _stats_message(callback.message, support_bot)
        elif action == "language":
            await callback.message.answer(_t(support_bot, "choose_language"), reply_markup=_language_keyboard())
        elif action == "help":
            await callback.message.answer(_t(support_bot, "help_text"))
        elif action == "check":
            channels = await get_bot_channels(support_bot.id)
            good, bad = 0, 0
            for channel in channels:
                try:
                    chat_member = await callback.bot.get_chat_member(channel.chat_id, (await callback.bot.get_me()).id)
                    if chat_member.status in {"administrator", "creator"}:
                        good += 1
                    else:
                        bad += 1
                except Exception:
                    bad += 1
            await callback.message.answer(f"✅ {good}  |  ❌ {bad}")
        elif action == "remove" and len(parts) == 3:
            try:
                removed = await remove_bot_channel(support_bot.id, int(parts[2]))
                await callback.message.answer("✅ تمت إزالة القناة." if removed else "❌ القناة غير موجودة.")
            except ValueError:
                await callback.message.answer("❌ رقم القناة غير صالح.")

    @router.callback_query(F.data.startswith("cf_lang:"))
    async def handle_language_callback(callback: CallbackQuery):
        if not await _can_manage(support_bot, callback.from_user.id):
            await callback.answer("غير مسموح.", show_alert=True)
            return
        language = callback.data.split(":", 1)[1]
        if language not in LANGUAGE_NAMES:
            await callback.answer("لغة غير صالحة.", show_alert=True)
            return
        await update_bot_language(support_bot.id, language)
        support_bot.language = language
        await callback.answer("✅")
        await callback.message.answer(
            f"✅ {LANGUAGE_NAMES[language]}",
            reply_markup=_management_keyboard(support_bot),
        )

    @router.message(F.chat.type == "private")
    async def handle_user_message(message: Message, bot: Bot):
        nonlocal publish_mode, add_channel_mode, delete_post_mode
        is_manager = await _can_manage(support_bot, message.from_user.id)

        if is_manager and message.text and message.text.strip().casefold() == "/cancel":
            publish_mode = add_channel_mode = delete_post_mode = False
            await message.answer(_t(support_bot, "back"))
            return

        if is_manager and add_channel_mode:
            if message.text and message.text.strip().startswith("/cancel"):
                add_channel_mode = False
                await message.answer(_t(support_bot, "back"))
                return
            if await _add_channel_from_message(bot, support_bot, message):
                add_channel_mode = False
            return

        if is_manager and delete_post_mode:
            try:
                post_number = int((message.text or "").strip())
            except ValueError:
                await message.answer(_t(support_bot, "bad_number"))
                return
            numbers = await get_publication_numbers(support_bot.id)
            if post_number not in numbers:
                await message.answer(_t(support_bot, "not_found"))
                return
            delete_post_mode = False
            deliveries = await get_publication_deliveries(support_bot.id, post_number)
            deleted, failed = 0, 0
            for delivery in deliveries:
                try:
                    await bot.delete_message(delivery.destination_chat_id, delivery.telegram_message_id)
                    await record_publish_operation(
                        support_bot.id, post_number, "delete",
                        delivery.destination_chat_id, delivery.destination_title,
                        "success", delivery.telegram_message_id,
                    )
                    deleted += 1
                except Exception as exc:
                    await record_publish_operation(
                        support_bot.id, post_number, "delete",
                        delivery.destination_chat_id, delivery.destination_title,
                        "failed", delivery.telegram_message_id, str(exc)[:1000],
                    )
                    failed += 1
            await message.answer(f"🗑 {_t(support_bot, 'deleted')}: {deleted} | ❌ {_t(support_bot, 'delete_failed')}: {failed}")
            return

        if is_manager and message.text:
            command = message.text.strip().split(maxsplit=1)[0].split("@", 1)[0].casefold()
            if command in {"/publish", "/add_post"}:
                publish_mode, add_channel_mode, delete_post_mode = True, False, False
                await message.answer(_t(support_bot, "publish_prompt"))
                return
            if command in {"/add_channel", "/channels"}:
                add_channel_mode = command == "/add_channel"
                if command == "/channels":
                    await _channel_menu(message, bot, support_bot)
                else:
                    await message.answer(_t(support_bot, "add_prompt"))
                return
            if command in {"/delete_post", "/delete"}:
                numbers = await get_publication_numbers(support_bot.id)
                delete_post_mode = bool(numbers)
                await message.answer(
                    (_t(support_bot, "delete_prompt") + " " + ", ".join(map(str, numbers)))
                    if numbers else _t(support_bot, "no_posts")
                )
                return
            if command in {"/stats", "/language", "/help"}:
                if command == "/stats":
                    await _stats_message(message, support_bot)
                elif command == "/language":
                    await message.answer(_t(support_bot, "choose_language"), reply_markup=_language_keyboard())
                else:
                    await message.answer(_t(support_bot, "help_text"), reply_markup=_management_keyboard(support_bot))
                return

        if is_manager and publish_mode:
            publish_mode = False
            channels = await get_bot_channels(support_bot.id)
            if not channels:
                await message.answer(_t(support_bot, "no_channels"))
                return
            post_number = await get_next_post_number(support_bot.id)
            sent_count, failed_count = await _publish_to_channels(
                bot, support_bot, message, channels, post_number
            )
            await message.answer(
                f"✅ {_t(support_bot, 'published')}: {sent_count} | "
                f"❌ {_t(support_bot, 'failed')}: {failed_count}\n"
                f"🔢 رقم المنشور: <b>{post_number}</b>"
            )
            return

        if message.text:
            command = message.text.strip().split(maxsplit=1)[0].split("@", 1)[0].lstrip("/").casefold()
            if command:
                configured_command = await get_bot_command(support_bot.id, command)
                if configured_command:
                    await message.answer(configured_command.response_text)
                    return
            auto_reply = await get_matching_auto_reply(support_bot.id, message.text)
            if auto_reply:
                await message.answer(auto_reply.response_text)
                return

        ticket = await create_ticket(
            bot_id=support_bot.id,
            end_user_id=message.from_user.id,
            end_user_name=message.from_user.full_name,
        )
        if support_bot.support_group_id:
            forwarded = await _send_to_support_group(bot, support_bot, ticket, message)
            await create_ticket_message(
                ticket.id, forwarded.message_id, support_bot.support_group_id,
                ticket.end_user_telegram_id,
            )
            await message.answer("✅ تم استلام رسالتك، سيتواصل معك فريق الدعم قريبًا.")
        else:
            await message.answer("⚠️ عذرًا، فريق الدعم غير متاح حاليًا. حاول لاحقًا.")

    @router.message(F.chat.type.in_({"group", "supergroup"}) & F.reply_to_message)
    async def handle_support_reply(message: Message, bot: Bot):
        reply_text = message.text or message.caption
        if not reply_text and not (message.photo or message.video or message.document):
            await message.answer("⚠️ أرسل نصًا أو صورة أو فيديو أو ملفًا.")
            return
        linked_message = await get_ticket_message(
            support_group_id=support_bot.support_group_id,
            forwarded_message_id=message.reply_to_message.message_id,
        )
        if not linked_message:
            await message.answer("⚠️ الرسالة غير مرتبطة بتذكرة معروفة.")
            return
        await _send_to_end_user(bot, linked_message.end_user_telegram_id, message, linked_message.ticket_id)
        await message.answer("✅ تم إرسال الرد إلى المستخدم النهائي.")

    return router
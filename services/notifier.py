import os
import requests

ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")
MAIN_BOT_TOKEN = os.getenv("MAIN_BOT_TOKEN")

def notify_admin_payment_proof(user_id, username, full_name, proof_text=None):
    """
    إرسال إشعار للأدمن مع زر تفعيل بنقرة واحدة
    """
    if not ADMIN_TELEGRAM_ID or not MAIN_BOT_TOKEN:
        return

    message = (
        f"📥 **وصل دفع جديد ينتظر التفعيل!**\n\n"
        f"👤 **المستخدم:** {full_name} (@{username or 'بدون_معرف'})\n"
        f"🆔 **Telegram ID:** `{user_id}`\n"
        f"📝 **الملاحظة / الإثبات:** {proof_text or 'تم رفع صورة الوصل'}\n\n"
        f"اضغطي على الزر أدناه لتفعيل اشتراك المستخدم لمدة 30 يوماً فوراً:"
    )
    
    inline_keyboard = {
        "inline_keyboard": [[
            {
                "text": "✅ تفعيل الاشتراك (30 يوماً)", 
                "callback_data": f"activate_sub:{user_id}"
            }
        ]]
    }
    
    url = f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_TELEGRAM_ID,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": inline_keyboard
    }
    
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error sending admin notification: {e}")

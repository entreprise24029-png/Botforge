"""
تكامل Stripe لتفعيل الاشتراكات تلقائيًا بدون تدخل يدوي من الأدمن.

آلية العمل:
1. العميل يطلب /create_bot وينتهي بتسجيل البوت (غير مفعّل)
2. البوت الرئيسي يولّد رابط دفع Stripe عبر create_checkout_session()
3. العميل يدفع على صفحة Stripe المستضافة (Stripe Checkout)
4. Stripe يستدعي endpoint الويبهوك في لوحة التحكم (dashboard/app.py) عند نجاح الدفع
5. الويبهوك يفعّل الاشتراك تلقائيًا ويشغّل بوت الدعم فورًا

المتطلبات:
- STRIPE_SECRET_KEY: مفتاحك السري من https://dashboard.stripe.com/apikeys
- STRIPE_WEBHOOK_SECRET: سرّ التحقق من الويبهوك (يظهر عند إنشاء الويبهوك في لوحة Stripe)
- STRIPE_PRICE_ID: معرّف السعر (Price) الذي أنشأته في Stripe لخطة الاشتراك الشهري
- PUBLIC_BASE_URL: رابط سيرفرك العام (لروابط success/cancel الخاصة بـ Checkout)
"""
import os
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
PUBLIC_BASE_URL = (
    os.getenv("PUBLIC_BASE_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or f"http://localhost:{os.getenv('PORT', '8000')}"
)


def create_checkout_session(bot_id: int, client_telegram_id: int) -> str:
    """
    ينشئ جلسة دفع Stripe ويرجع رابط الدفع الذي تُرسله للعميل داخل تليجرام.
    bot_id و client_telegram_id يُمرَّران في metadata لنتعرف عليهما لاحقًا في الويبهوك.
    """
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        success_url=f"{PUBLIC_BASE_URL}/payment/success?bot_id={bot_id}",
        cancel_url=f"{PUBLIC_BASE_URL}/payment/cancel?bot_id={bot_id}",
        metadata={
            "bot_id": str(bot_id),
            "client_telegram_id": str(client_telegram_id),
        },
        subscription_data={
            "metadata": {
                "bot_id": str(bot_id),
                "client_telegram_id": str(client_telegram_id),
            }
        },
    )
    return session.url


def verify_webhook(payload: bytes, sig_header: str) -> stripe.Event:
    """
    يتحقق من أن طلب الويبهوك جاء فعلًا من Stripe (وليس مزوّرًا) باستخدام التوقيع.
    يرمي استثناء (stripe.error.SignatureVerificationError) لو التوقيع غير صحيح.
    """
    return stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)

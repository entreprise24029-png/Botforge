"""
تكامل RedotPay Connect (دفع بعملات مستقرة/كريبتو، تسوية بعملتك المحلية).
نستخدم هنا "Flow 1: Payment via Paylink" — الأبسط للتكامل: نطلب رابط دفع
جاهز ونعيد توجيه العميل إليه، تمامًا مثل أسلوب Stripe Checkout.

المتطلبات في .env:
- REDOTPAY_APP_KEY: معرّف التاجر (appKey) من لوحة RedotPay
- REDOTPAY_PRIVATE_KEY_PATH: مسار ملف مفتاحك الخاص (PEM) المستخدم لتوقيع طلباتك
- REDOTPAY_ENV: "sandbox" أو "production" (يحدد الـ base URL والمفتاح العام المستخدم للتحقق)
- REDOTPAY_PUBLIC_KEY_VERSION: نسخة مفتاح RedotPay العام المستخدم في الويبهوك (افتراضي 1)
- PUBLIC_BASE_URL: نفس المتغير المستخدم مع Stripe (رابط سيرفرك العام)

خطوات الإعداد على منصة RedotPay قبل الاستخدام:
1. سجّل كتاجر (merchant) وأكمل التحقق (KYC)
2. اطلب تفعيل صلاحية المطورين (Developer Access)
3. ولّد زوج مفاتيح RSA:
     openssl genrsa -out redotpay_private_key.pem 2048
     openssl rsa -in redotpay_private_key.pem -pubout -out redotpay_public_key.pem
4. ارفع الملف العام (redotpay_public_key.pem) في لوحة تاجر RedotPay
5. احفظ الملف الخاص بأمان على سيرفرك ولا ترفعه لـ Git أبدًا
6. اضبط رابط الويبهوك في لوحة RedotPay إلى: https://your-domain.com/redotpay/webhook
"""
import os
import json
import uuid
from decimal import Decimal, InvalidOperation

import httpx

from core.redotpay_signature import sign_request, verify_callback_signature

REDOTPAY_APP_KEY = os.getenv("REDOTPAY_APP_KEY")
REDOTPAY_PRIVATE_KEY_PATH = os.getenv("REDOTPAY_PRIVATE_KEY_PATH", "redotpay_private_key.pem")
REDOTPAY_ENV = os.getenv("REDOTPAY_ENV", "sandbox")
REDOTPAY_PUBLIC_KEY_VERSION = os.getenv("REDOTPAY_PUBLIC_KEY_VERSION", "1")
PUBLIC_BASE_URL = (
    os.getenv("PUBLIC_BASE_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or f"http://localhost:{os.getenv('PORT', '8000')}"
)
SUBSCRIPTION_PRICE = Decimal(os.getenv("SUBSCRIPTION_PRICE", "10"))

BASE_URLS = {
    "sandbox": "https://acquirersandbox.rp-2023app.com",
    "production": "https://api.redotpay.com",
}


def is_subscription_amount(amount: object) -> bool:
    """يتحقق بدقة من أن مبلغ الويبهوك يساوي سعر الاشتراك المعلن"""
    try:
        return Decimal(str(amount)) == SUBSCRIPTION_PRICE
    except (InvalidOperation, TypeError, ValueError):
        return False

# المفاتيح العامة الرسمية لـ RedotPay (لاستخدامها في التحقق من الويبهوك فقط)
# مصدرها: https://redotpay.readme.io/docs/redotpay-api-request-signature-and-verification-guide
# ملاحظة: انسخها بدقة من التوثيق الرسمي قبل الاستخدام الفعلي وتأكد من مطابقتها
# للنسخة/البيئة الصحيحة عند كل تحديث من RedotPay.
REDOTPAY_PLATFORM_PUBLIC_KEYS = {
    ("sandbox", "1"): os.getenv("REDOTPAY_SANDBOX_PUBLIC_KEY_PEM", ""),
    ("production", "1"): os.getenv("REDOTPAY_PRODUCTION_PUBLIC_KEY_PEM", ""),
}


def _load_private_key_pem() -> str:
    with open(REDOTPAY_PRIVATE_KEY_PATH, "r") as f:
        return f.read()


async def create_payment_order(bot_id: int, client_telegram_id: int,
                                amount: float, currency: str = "USD") -> str:
    """
    ينشئ طلب دفع عبر RedotPay (Paylink flow) ويرجع رابط الدفع لإرساله للعميل.
    """
    uri = "/openapi/v2/order/create"
    url = BASE_URLS[REDOTPAY_ENV] + uri

    body_dict = {
        "outerOrderSn": f"bot{bot_id}-{uuid.uuid4().hex[:10]}",
        "outerUid": str(client_telegram_id),
        "orderAmount": amount,
        "orderCurrency": currency,
        "env": "WEB",
        "orderDesc": f"اشتراك بوت الدعم رقم {bot_id}",
        "goods": [{
            "goodsType": "02",  # 02 = منتج/خدمة رقمية
            "goodsCategory": "Z000",
            "goodsCode": f"support-bot-{bot_id}",
            "goodsName": "اشتراك شهري - بوت دعم فني",
            "goodsCount": 1,
            "goodsAmount": amount,
            "goodsCoin": currency,
        }],
        "buyer": {
            "redirectUrl": f"{PUBLIC_BASE_URL}/payment/success?bot_id={bot_id}&provider=redotpay",
        },
    }
    # JSON مضغوط بدون مسافات زائدة، كما يشترط توثيق RedotPay بالضبط لتوليد توقيع صحيح
    request_body = json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False)

    private_key_pem = _load_private_key_pem()
    timestamp, signature = sign_request(
        http_method="POST",
        http_uri=uri,
        app_key=REDOTPAY_APP_KEY,
        private_key_pem=private_key_pem,
        request_body=request_body,
    )

    headers = {
        "Content-Type": "application/json",
        "X-R-Ak": REDOTPAY_APP_KEY,
        "X-R-Ts": str(timestamp),
        "X-R-Signature": signature,
        "X-R-Key-Version": "1",  # نسخة مفتاحك أنت المرفوع للوحة RedotPay
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, headers=headers, content=request_body)
        response.raise_for_status()
        data = response.json()

    # هيكل الاستجابة الدقيق يعتمد على نسخة API لديك — تحقق منه في لوحة RedotPay
    # عند أول اختبار فعلي وعدّل المسار التالي إذا لزم.
    payment_url = data.get("data", {}).get("payUrl") or data.get("payUrl")
    if not payment_url:
        raise RuntimeError(f"لم يُرجع RedotPay رابط دفع صالح: {data}")

    return payment_url


def verify_webhook(headers: dict, raw_body: bytes) -> dict | None:
    """
    يتحقق من صحة توقيع ويبهوك RedotPay ويرجع الـ body كـ dict إذا كان صالحًا،
    أو None إذا فشل التحقق (توقيع مزوّر أو غير متطابق).
    """
    timestamp = headers.get("x-r-ts")
    signature = headers.get("x-r-signature")
    key_version = headers.get("x-r-key-version", REDOTPAY_PUBLIC_KEY_VERSION)

    if not timestamp or not signature:
        return None

    public_key_pem = REDOTPAY_PLATFORM_PUBLIC_KEYS.get((REDOTPAY_ENV, key_version))
    if not public_key_pem:
        return None  # لا يوجد مفتاح مطابق للبيئة/النسخة المستلمة — ارفض الطلب

    body_str = raw_body.decode("utf-8")

    is_valid = verify_callback_signature(
        app_key=REDOTPAY_APP_KEY,
        timestamp=timestamp,
        request_body=body_str,
        signature_b64=signature,
        redotpay_public_key_pem=public_key_pem,
    )

    if not is_valid:
        return None

    return json.loads(body_str)

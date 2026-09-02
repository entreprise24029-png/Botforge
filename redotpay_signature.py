"""
توقيع/تحقق طلبات RedotPay Connect حسب توثيقهم الرسمي.
RedotPay يستخدم توقيع SHA256withRSA (غير Stripe اللي يستخدم HMAC بسيط).

مرجع رسمي:
https://redotpay.readme.io/docs/redotpay-api-request-signature-and-verification-guide

نقاط مهمة يجب فهمها قبل الاستخدام:
- عندك زوج مفاتيح خاص بك (مفتاح خاص تولّده أنت + مفتاح عام ترفعه للوحة تاجر RedotPay)
  تستخدمه لتوقيع طلباتك أنت المرسلة لـ RedotPay.
- RedotPay عندهم مفتاح عام خاص بهم (منشور في توثيقهم، يختلف بين Sandbox و Production)
  تستخدمه أنت للتحقق من توقيع الويبهوكات (Callbacks) القادمة منهم.
  لا تخلط بين المفتاحين إطلاقًا.
"""
import base64
import time

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend


def load_private_key(pem_str: str):
    return serialization.load_pem_private_key(
        pem_str.encode(), password=None, backend=default_backend()
    )


def load_public_key(pem_str: str):
    return serialization.load_pem_public_key(pem_str.encode(), backend=default_backend())


def sign_request(http_method: str, http_uri: str, app_key: str,
                  private_key_pem: str, request_body: str) -> tuple[int, str]:
    """
    يولّد توقيع الطلب المرسل إلى RedotPay.
    يرجع (timestamp_ms, signature_base64) لوضعهما في هيدرز X-R-Ts و X-R-Signature.
    """
    timestamp = int(time.time() * 1000)
    string_to_sign = f"{http_method.upper()} {http_uri}\n{app_key}.{timestamp}.{request_body}"

    private_key = load_private_key(private_key_pem)
    signature_bytes = private_key.sign(
        string_to_sign.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    signature_b64 = base64.b64encode(signature_bytes).decode("utf-8")
    return timestamp, signature_b64


def verify_callback_signature(app_key: str, timestamp: str, request_body: str,
                               signature_b64: str, redotpay_public_key_pem: str) -> bool:
    """
    يتحقق من توقيع ويبهوك قادم من RedotPay.
    استخدم مفتاح RedotPay العام (وليس مفتاحك أنت) حسب X-R-Key-Version في هيدرز الطلب.
    """
    try:
        string_to_verify = f"{app_key}.{timestamp}.{request_body}"
        signature_bytes = base64.b64decode(signature_b64)
        public_key = load_public_key(redotpay_public_key_pem)

        public_key.verify(
            signature_bytes,
            string_to_verify.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False

"""
تشفير توكنات بوتات العملاء قبل تخزينها في قاعدة البيانات.
يستخدم Fernet (تشفير متماثل من مكتبة cryptography) — سريع وآمن كفاية لهذا الاستخدام.

مهم جدًا:
- المفتاح ENCRYPTION_KEY يجب أن يبقى سريًا تمامًا (لا يُرفع لـ Git إطلاقًا).
- إذا ضاع المفتاح، تضيع القدرة على فك تشفير كل التوكنات المخزّنة سابقًا.
- خذ نسخة احتياطية آمنة من المفتاح بمكان منفصل عن قاعدة البيانات نفسها.
"""
import os
import hashlib
from cryptography.fernet import Fernet

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    raise RuntimeError(
        "ENCRYPTION_KEY غير موجود في متغيرات البيئة.\n"
        "ولّد مفتاحًا جديدًا بتشغيل: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
        "وضعه في ملف .env تحت اسم ENCRYPTION_KEY"
    )

_fernet = Fernet(ENCRYPTION_KEY.encode())


def encrypt_token(plain_token: str) -> str:
    """تشفير توكن قبل حفظه في القاعدة"""
    return _fernet.encrypt(plain_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """فك تشفير توكن عند الحاجة لاستخدامه فعليًا (تشغيل البوت مثلًا)"""
    return _fernet.decrypt(encrypted_token.encode()).decode()


def hash_token(plain_token: str) -> str:
    """بصمة ثابتة غير قابلة للعكس لاستخدامها في منع تكرار التوكن"""
    return hashlib.sha256(plain_token.encode("utf-8")).hexdigest()

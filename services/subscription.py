import os
import requests
from datetime import datetime, timezone

FREE_TRIAL_MAX_CHANNELS = 3

def check_user_access(user):
    """
    فحص صلاحية المستخدم (تجريبية أم اشتراك مدفوع ساري)
    """
    now = datetime.now(timezone.utc)
    
    sub_end = user.subscription_end_date
    if sub_end and sub_end.tzinfo is None:
        sub_end = sub_end.replace(tzinfo=timezone.utc)

    # 1. اشتراك مدفوع وساري المفعول
    if getattr(user, 'is_paid', False) and sub_end and sub_end > now:
        return {
            "allowed": True, 
            "reason": "paid_active", 
            "max_channels": getattr(user, 'paid_channel_limit', 199) or 199
        }

    # 2. التجربة المجانية (أول مرة)
    if getattr(user, 'trials_used', 0) == 0:
        return {
            "allowed": True, 
            "reason": "trial_active", 
            "max_channels": FREE_TRIAL_MAX_CHANNELS
        }

    # 3. انتهاء التجربة أو الاشتراك
    rip = os.getenv("BARIDIMOB_CCP_RIP", "00799999002581351014")
    ccp = os.getenv("CCP_NUMBER", "0025813510 Clè 14")
    account_name = os.getenv("BARIDIMOB_ACCOUNT_NAME", "بوراس إكرام")

    return {
        "allowed": False, 
        "reason": "payment_required", 
        "message": (
            "⚠️ **انتهت الفترة التجريبية المجانية!**\n\n"
            f"لقد استهلكت تجربتك المتاحة ({FREE_TRIAL_MAX_CHANNELS} قنوات).\n"
            "للاستمرار في إضافة القنوات وتجديد الخدمات، يرجى الاشتراك الشهري عبر:\n\n"
            f"📱 **BaridiMob (RIP):** `{rip}`\n"
            f"📮 **CCP:** `{ccp}`\n"
            f"👤 **الاسم:** {account_name}\n\n"
            "📌 **بعد التحويل:** يرجى إرسال صورة الوصل أو رقم المعاملة هنا لتفعيل حسابك."
        )
    }

def add_channel_request(user, current_channels_count, telegram_user_obj=None):
    """
    التحقق عند إضافة قناة جديدة
    """
    access = check_user_access(user)
    
    if not access["allowed"]:
        return False, access["message"]
        
    if current_channels_count >= access["max_channels"]:
        if access["reason"] == "trial_active":
            user.trials_used = 1  # تسجيل استهلاك التجربة
            return False, access["message"]
        else:
            return False, "❌ تجاوزت الحد الأقصى للقنوات المسموح بها في اشتراكك الحالي."

    return True, "Success"

from datetime import datetime, timezone

# الإعدادات المرجعية للاشتراك والتجربة المجانية
FREE_TRIAL_MAX_CHANNELS = 3
SUBSCRIPTION_DAYS = 30

def check_user_access(user):
    """
    دالة التحقق الهندسي من صلاحية المستخدم (تجريبية أم اشتراك مدفوع)
    """
    now = datetime.now(timezone.utc)
    
    # تحويل تاريخ انقضاء الاشتراك إلى timezone aware إذا كان naive
    sub_end = user.subscription_end_date
    if sub_end and sub_end.tzinfo is None:
        sub_end = sub_end.replace(tzinfo=timezone.utc)

    # 1. إذا كان لديه اشتراك مدفوع وساري المفعول
    if getattr(user, 'is_paid', False) and sub_end and sub_end > now:
        return {
            "allowed": True, 
            "reason": "paid_active", 
            "max_channels": getattr(user, 'paid_channel_limit', 99) or 99
        }

    # 2. إذا كان ينوي استخدام التجربة المجانية لأول مرة
    if getattr(user, 'trials_used', 0) == 0:
        return {
            "allowed": True, 
            "reason": "trial_active", 
            "max_channels": FREE_TRIAL_MAX_CHANNELS
        }

    # 3. إذا انتهت التجربة أو انتهى الاشتراك الشهري
    return {
        "allowed": False, 
        "reason": "payment_required", 
        "message": (
            "⚠️ **انتهت الفترة التجريبية المجانية!**\n\n"
            "لقد استهلكت تجربتك المتاحة (3 قنوات).\n"
            "للاستمرار في استخدام البوت وتجديد الخدمات، يرجى الاشتراك الشهري عبر BaridiMob."
        )
    }

def add_channel_request(user, current_channels_count):
    """
    التحقق عند طلب إضافة قناة جديدة
    """
    access = check_user_access(user)
    
    if not access["allowed"]:
        return False, access["message"]
        
    if current_channels_count >= access["max_channels"]:
        if access["reason"] == "trial_active":
            return False, (
                f"❌ **تجاوزت حد التجربة المجانية!**\n\n"
                f"تسمح الفترة التجريبية بإضافة {FREE_TRIAL_MAX_CHANNELS} قنوات فقط.\n"
                f"لتستطيع إضافة المزيد من القنوات، يرجى ترقية حسابك والدفع لمدة شهر."
            )
        else:
            return False, "❌ تجاوزت الحد الأقصى للقنوات المسموح بها في اشتراكك الحالي."

    return True, "Success"

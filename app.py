import os
from datetime import datetime

from fastapi import FastAPI, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
import stripe as stripe_lib
import bcrypt
from sqlalchemy import select

from database.db import (
    async_session,
    activate_subscription,
    deactivate_bot,
    get_bot_by_stripe_subscription,
    set_stripe_subscription_id,
)
from database.models import Client, SupportBot, BotChannel, PublishOperation, User, Channel
from core.payments import verify_webhook
from services.subscription import add_channel_request

load_dotenv()
from core.bot_manager import manager
import main as main_runtime

app = FastAPI(title="ChannelForge | مطوّر القنوات")
templates = Jinja2Templates(directory="dashboard/templates")
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASSWORD_HASH = os.getenv("DASHBOARD_PASSWORD_HASH")
DASHBOARD_SESSION_SECRET = os.getenv("DASHBOARD_SESSION_SECRET")
DASHBOARD_COOKIE_SECURE = os.getenv("DASHBOARD_COOKIE_SECURE", "false").lower() in {
    "1",
    "true",
    "yes",
}

if not DASHBOARD_PASSWORD_HASH:
    raise RuntimeError(
        "DASHBOARD_PASSWORD_HASH غير موجود. "
        "ولّد قيمة bcrypt واحفظها في Replit Secrets أو ملف .env."
    )
if not DASHBOARD_SESSION_SECRET:
    raise RuntimeError(
        "DASHBOARD_SESSION_SECRET غير موجود. "
        "استخدم سرًا عشوائيًا طويلًا في Replit Secrets أو ملف .env."
    )

app.add_middleware(
    SessionMiddleware,
    secret_key=DASHBOARD_SESSION_SECRET,
    session_cookie="dashboard_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=DASHBOARD_COOKIE_SECURE,
)


def check_admin(request: Request):
    """يتحقق من جلسة الأدمن الموقعة بدل إرسال كلمة المرور مع كل طلب"""
    username = request.session.get("admin_user")
    if username != DASHBOARD_USER:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return username


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("admin_user") == DASHBOARD_USER:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    valid_password = bcrypt.checkpw(
        password.encode("utf-8"),
        DASHBOARD_PASSWORD_HASH.encode("utf-8"),
    )
    if username != DASHBOARD_USER or not valid_password:
        raise HTTPException(status_code=401, detail="بيانات دخول غير صحيحة")

    request.session.clear()
    request.session["admin_user"] = username
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ---------- معالجة أوامر تليجرام البوت المباشرة ----------
def handle_add_channel(bot, db, message, process_channel_addition_func):
    """
    دالة معالجة أمر إضافة القنوات المحدثة والمربوطة بالـ Freemium + BaridiMob/CCP
    """
    telegram_id = str(message.from_user.id)
    
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    current_channels_count = db.query(Channel).filter(Channel.user_id == user.id).count()

    can_add, response_msg = add_channel_request(
        user=user, 
        current_channels_count=current_channels_count, 
        telegram_user_obj=message.from_user
    )

    if not can_add:
        bot.reply_to(message, response_msg, parse_mode="Markdown")
        return

    msg = bot.reply_to(
        message, 
        "✅ **يمكنك إضافة قناة جديدة.**\n\nيرجى إرسال معرف القناة (مثال: `@my_channel`) أو أعد توجيه رسالة منها إلى هنا:"
    )
    bot.register_next_step_handler(msg, process_channel_addition_func, user_id=user.id)


@app.post("/telegram/webhook/{bot_id}")
async def telegram_webhook_proxy(bot_id: int, request: Request):
    """يستقبل Webhook كل بوت فرعي مباشرة داخل FastAPI."""
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"detail": "invalid webhook payload"}, status_code=400)
    status, response = await manager.handle_webhook_update(
        bot_id,
        payload,
        request.headers.get("X-Telegram-Bot-Api-Secret-Token"),
    )
    return JSONResponse(response, status_code=status)


@app.post("/telegram/webhook/main")
async def main_telegram_webhook(request: Request):
    """يستقبل Webhook البوت الرئيسي على نفس منفذ لوحة التحكم."""
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"detail": "invalid webhook payload"}, status_code=400)
    status, response = await main_runtime.handle_main_webhook(
        payload,
        request.headers.get("X-Telegram-Bot-Api-Secret-Token"),
    )
    return JSONResponse(response, status_code=status)


def _subscription_metadata(payload: dict) -> dict:
    """يقرأ metadata من أشكال كائنات Stripe المختلفة"""
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    parent = payload.get("parent")
    if isinstance(parent, dict):
        details = parent.get("subscription_details")
        if isinstance(details, dict) and isinstance(details.get("metadata"), dict):
            return details["metadata"]
    return {}


async def _find_subscription_bot_id(payload: dict) -> int | None:
    metadata = _subscription_metadata(payload)
    bot_id = metadata.get("bot_id")
    if bot_id:
        try:
            return int(bot_id)
        except (TypeError, ValueError):
            return None

    subscription_id = payload.get("subscription") or payload.get("id")
    if not subscription_id:
        return None
    support_bot = await get_bot_by_stripe_subscription(subscription_id)
    return support_bot.id if support_bot else None


@app.on_event("startup")
async def on_startup():
    await main_runtime.start_runtime()


@app.on_event("shutdown")
async def on_shutdown():
    await main_runtime.stop_runtime()


# ---------- لوحة التحكم ----------
@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request, admin: str = Depends(check_admin)):
    async with async_session() as session:
        clients_result = await session.execute(select(Client))
        clients = clients_result.scalars().all()

        bots_result = await session.execute(select(SupportBot))
        bots = bots_result.scalars().all()
        channels_result = await session.execute(select(BotChannel))
        channels = channels_result.scalars().all()
        operations_result = await session.execute(select(PublishOperation))
        operations = operations_result.scalars().all()

    stats = {
        "total_clients": len(clients),
        "total_bots": len(bots),
        "active_bots": len([b for b in bots if b.is_active]),
        "expired_bots": len([
            b for b in bots
            if b.subscription_expires_at and b.subscription_expires_at < datetime.utcnow()
        ]),
        "channels": len(channels),
        "support_groups": len([b for b in bots if b.support_group_id]),
        "published": len([
            item for item in operations
            if item.action == "publish" and item.status == "success"
        ]),
        "failed_publications": len([
            item for item in operations
            if item.action == "publish" and item.status == "failed"
        ]),
    }

    clients_by_id = {c.id: c for c in clients}
    bots_view = []
    for b in bots:
        owner = clients_by_id.get(b.owner_id)
        bots_view.append({
            "id": b.id,
            "username": b.bot_username,
            "company_name": b.company_name,
            "owner_name": owner.full_name if owner else "غير معروف",
            "is_active": b.is_active,
            "subscription_active": b.subscription_active,
            "expires_at": b.subscription_expires_at,
            "language": b.language or "ar",
            "channel_count": len([c for c in channels if c.bot_id == b.id]),
            "published": len([
                item for item in operations
                if item.bot_id == b.id and item.action == "publish"
                and item.status == "success"
            ]),
            "failed_publications": len([
                item for item in operations
                if item.bot_id == b.id and item.action == "publish"
                and item.status == "failed"
            ]),
        })

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "stats": stats, "bots": bots_view},
    )


@app.post("/bots/{bot_id}/activate")
async def manual_activate(bot_id: int, days: int = Form(30), admin: str = Depends(check_admin)):
    """تفعيل يدوي احتياطي من واجهة اللوحة (بدون المرور بـ Stripe)"""
    await activate_subscription(bot_id, days)
    return RedirectResponse(url="/", status_code=303)


# ---------- صفحات نتيجة الدفع (بعد Stripe Checkout) ----------
@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(request: Request, bot_id: int):
    return templates.TemplateResponse(
        "payment_result.html",
        {"request": request, "success": True, "bot_id": bot_id},
    )


@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel(request: Request, bot_id: int):
    return templates.TemplateResponse(
        "payment_result.html",
        {"request": request, "success": False, "bot_id": bot_id},
    )


# ---------- ويبهوك Stripe ----------
@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = verify_webhook(payload, sig_header)
    except (stripe_lib.error.SignatureVerificationError, ValueError):
        raise HTTPException(status_code=400, detail="توقيع الويبهوك غير صالح")

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        metadata = session_obj.get("metadata", {})
        bot_id = metadata.get("bot_id")

        if bot_id:
            subscription_id = session_obj.get("subscription")
            if subscription_id:
                await set_stripe_subscription_id(int(bot_id), subscription_id)
            await activate_subscription(int(bot_id), days=30)

    elif event["type"] == "invoice.paid":
        invoice = event["data"]["object"]
        bot_id = await _find_subscription_bot_id(invoice)
        if bot_id:
            subscription_id = invoice.get("subscription")
            if subscription_id:
                await set_stripe_subscription_id(bot_id, subscription_id)
            await activate_subscription(bot_id, days=30)

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        bot_id = await _find_subscription_bot_id(subscription)
        if bot_id:
            await deactivate_bot(bot_id)

    return {"status": "ok"}

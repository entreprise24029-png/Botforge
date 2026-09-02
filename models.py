"""
نماذج قاعدة البيانات لمشروع "مصنع بوتات الدعم"
"""
from datetime import datetime
from sqlalchemy import (
    String,
    Integer,
    BigInteger,
    DateTime,
    Boolean,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Client(Base):
    """العميل الذي اشترى خدمة إنشاء بوت دعم"""
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bots: Mapped[list["SupportBot"]] = relationship(back_populates="owner")


class SupportBot(Base):
    """بوت الدعم الفرعي الذي تم إنشاؤه لعميل معيّن"""
    __tablename__ = "support_bots"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))

    bot_token: Mapped[str] = mapped_column(String(255))  # التوكن محفوظ مشفّرًا بـ Fernet
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    stripe_subscription_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=True
    )
    bot_username: Mapped[str] = mapped_column(String(255), nullable=True)

    company_name: Mapped[str] = mapped_column(String(255), default="شركتي")
    welcome_message: Mapped[str] = mapped_column(Text, default="أهلاً بك! كيف يمكننا مساعدتك؟")
    support_group_id: Mapped[int] = mapped_column(BigInteger, nullable=True)  # جروب فريق الدعم البشري
    language: Mapped[str] = mapped_column(
        String(10), default="ar", nullable=False
    )  # ar / en / fr / tr / es

    is_active: Mapped[bool] = mapped_column(Boolean, default=False)  # هل البوت شغّال فعليًا الآن
    subscription_active: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["Client"] = relationship(back_populates="bots")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="bot")
    commands: Mapped[list["BotCommand"]] = relationship(back_populates="bot")
    buttons: Mapped[list["BotButton"]] = relationship(back_populates="bot")
    auto_replies: Mapped[list["BotAutoReply"]] = relationship(back_populates="bot")
    channels: Mapped[list["BotChannel"]] = relationship(back_populates="bot")
    publication_logs: Mapped[list["PublishOperation"]] = relationship(
        back_populates="bot"
    )
    baridimob_payments: Mapped[list["BaridiMobPayment"]] = relationship(
        back_populates="bot"
    )


class Ticket(Base):
    """تذكرة/محادثة دعم واحدة داخل أحد بوتات الدعم الفرعية"""
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("support_bots.id"))

    end_user_telegram_id: Mapped[int] = mapped_column(BigInteger)  # الشخص اللي بيسأل الدعم
    end_user_name: Mapped[str] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="open")  # open / closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    bot: Mapped["SupportBot"] = relationship(back_populates="tickets")
    messages: Mapped[list["TicketMessage"]] = relationship(back_populates="ticket")


class TicketMessage(Base):
    """ربط رسالة التذكرة المُحوّلة برسالة المستخدم النهائي"""
    __tablename__ = "ticket_messages"
    __table_args__ = (
        UniqueConstraint(
            "support_group_id",
            "forwarded_message_id",
            name="uq_ticket_messages_group_forwarded_message",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    forwarded_message_id: Mapped[int] = mapped_column(BigInteger)
    support_group_id: Mapped[int] = mapped_column(BigInteger)
    end_user_telegram_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    ticket: Mapped["Ticket"] = relationship(back_populates="messages")


class BotCommand(Base):
    """أمر مخصص يعرّفه مالك البوت"""
    __tablename__ = "bot_commands"
    __table_args__ = (
        UniqueConstraint("bot_id", "command", name="uq_bot_commands_bot_command"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("support_bots.id"), index=True)
    command: Mapped[str] = mapped_column(String(64))
    response_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bot: Mapped["SupportBot"] = relationship(back_populates="commands")


class BotButton(Base):
    """زر Inline مخصص يظهر لمستخدمي البوت"""
    __tablename__ = "bot_buttons"
    __table_args__ = (
        UniqueConstraint("bot_id", "label", name="uq_bot_buttons_bot_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("support_bots.id"), index=True)
    label: Mapped[str] = mapped_column(String(128))
    response_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bot: Mapped["SupportBot"] = relationship(back_populates="buttons")


class BotAutoReply(Base):
    """رد تلقائي عند احتواء رسالة المستخدم على trigger"""
    __tablename__ = "bot_auto_replies"
    __table_args__ = (
        UniqueConstraint("bot_id", "trigger", name="uq_bot_auto_replies_bot_trigger"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("support_bots.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(255))
    response_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bot: Mapped["SupportBot"] = relationship(back_populates="auto_replies")


class BotChannel(Base):
    """قناة ينشر فيها البوت المنشورات الغنية"""
    __tablename__ = "bot_channels"
    __table_args__ = (
        UniqueConstraint("bot_id", "chat_id", name="uq_bot_channels_bot_chat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("support_bots.id"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bot: Mapped["SupportBot"] = relationship(back_populates="channels")


class PublishOperation(Base):
    """نتيجة نشر/حذف منشور لكل قناة أو مجموعة على حدة"""

    __tablename__ = "publish_operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("support_bots.id"), index=True)
    post_number: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(20))  # publish / delete
    destination_chat_id: Mapped[int] = mapped_column(BigInteger)
    destination_title: Mapped[str] = mapped_column(String(255), nullable=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True)  # success / failed
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bot: Mapped["SupportBot"] = relationship(back_populates="publication_logs")


class BaridiMobPayment(Base):
    """طلب دفع BaridiMob بالدينار مع إثبات يراجعه الأدمن"""
    __tablename__ = "baridimob_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("support_bots.id"), index=True)
    client_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount_dzd: Mapped[int] = mapped_column(Integer)
    proof_file_id: Mapped[str] = mapped_column(String(255))
    proof_type: Mapped[str] = mapped_column(String(30))  # photo / document
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    bot: Mapped["SupportBot"] = relationship(back_populates="baridimob_payments")

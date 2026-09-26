from sqlalchemy import Column, Integer, String, Boolean, DateTime
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String, unique=True, index=True)
    is_paid = Column(Boolean, default=False)
    trials_used = Column(Integer, default=0)
    paid_channel_limit = Column(Integer, default=199)  # حد 199 قناة للمدفوع
    subscription_end_date = Column(DateTime, nullable=True)

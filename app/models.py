from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Member(Base):
    """家庭成员。aliases 为别名（逗号分隔），如：妈妈,我妈,母亲。"""

    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    aliases: Mapped[str] = mapped_column(String(255), default="")
    relation: Mapped[str] = mapped_column(String(32), default="")
    note: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[int] = mapped_column(default=1)

    readings: Mapped[list["Reading"]] = relationship(
        back_populates="member", cascade="all, delete-orphan"
    )


class Reading(Base):
    """测量记录。kind=bp 时使用血压字段，kind=weight 时使用体重字段。"""

    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    kind: Mapped[str] = mapped_column(String(8))  # bp / weight
    systolic: Mapped[float] = mapped_column(Float, default=0)  # 收缩压
    diastolic: Mapped[float] = mapped_column(Float, default=0)  # 舒张压
    heart_rate: Mapped[float] = mapped_column(Float, default=0)
    weight_kg: Mapped[float] = mapped_column(Float, default=0)
    body_fat_pct: Mapped[float] = mapped_column(Float, default=0)
    measured_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(8), default="text")  # text/photo/manual/api
    raw_text: Mapped[str] = mapped_column(String(500), default="")
    chat: Mapped[str] = mapped_column(String(64), default="")
    sender: Mapped[str] = mapped_column(String(64), default="")

    member: Mapped[Member] = relationship(back_populates="readings")


class Outbox(Base):
    """待发送消息队列：定时提醒、周报由微信桥取走发送。"""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_chat: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProcessedMsg(Base):
    """已处理消息（用于去重）。"""

    __tablename__ = "processed_msgs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    reply: Mapped[str] = mapped_column(String(2000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

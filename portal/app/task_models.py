"""Native tasks; business-module work remains in its owning tables."""
from datetime import datetime
from sqlalchemy import CheckConstraint, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base, User, utcnow


class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default='')
    creator_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    external_name: Mapped[str] = mapped_column(String(255), default='')
    external_email: Mapped[str] = mapped_column(String(255), default='')
    group_id: Mapped[int | None] = mapped_column(ForeignKey('groups.id', ondelete='SET NULL'), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='open', index=True)
    priority: Mapped[str] = mapped_column(String(16), default='normal')
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    due_has_time: Mapped[bool] = mapped_column(Boolean, default=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[str] = mapped_column(String(500), default='')
    seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), default='')
    source_id: Mapped[str] = mapped_column(String(100), default='')
    source_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey('task_series.id'), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {'version_id_col': version}
    __table_args__ = (CheckConstraint("(assignee_id IS NOT NULL AND external_email = '') OR (assignee_id IS NULL AND external_email <> '')", name='task_one_responsible'),)

    @property
    def responsible_name(self):
        return self.assignee.name if self.assignee else self.external_name

    creator: Mapped[User] = relationship(foreign_keys=[creator_id])
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])


class TaskParticipant(Base):
    __tablename__ = 'task_participants'
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    user: Mapped[User] = relationship()


class TaskActivity(Base):
    __tablename__ = 'task_activity'
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(255), default='System')
    kind: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaskComment(Base):
    __tablename__ = 'task_comments'
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    external_author: Mapped[str] = mapped_column(String(300), default='')
    body: Mapped[str] = mapped_column(Text)
    external_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    author: Mapped[User | None] = relationship()

    @property
    def author_display(self):
        return self.author.name if self.author else self.external_author


class TaskCheck(Base):
    __tablename__ = 'task_checks'
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), index=True)
    title: Mapped[str] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskAttachment(Base):
    __tablename__ = 'task_attachments'
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(80), default='')
    mime: Mapped[str] = mapped_column(String(100), default='application/octet-stream')
    size: Mapped[int] = mapped_column(Integer, default=0)
    dms_file_id: Mapped[int | None] = mapped_column(ForeignKey('dms_files.id', ondelete='SET NULL'), nullable=True)
    is_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    external_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskDependency(Base):
    __tablename__ = 'task_dependencies'
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True)
    blocker_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True)


class TaskSeries(Base):
    __tablename__ = 'task_series'
    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    rule: Mapped[str] = mapped_column(String(500))
    anchor_local: Mapped[str] = mapped_column(String(40))
    timezone: Mapped[str] = mapped_column(String(100))
    template_json: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaskReminder(Base):
    __tablename__ = 'task_reminders'
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), index=True)
    offset_minutes: Mapped[int] = mapped_column(Integer, default=0)
    recipient_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    sent_for: Mapped[str] = mapped_column(String(80), default='')
    __table_args__ = (UniqueConstraint('task_id', 'offset_minutes', 'recipient_id'),)


class TaskOccurrence(Base):
    __tablename__ = 'task_occurrences'
    series_id: Mapped[int] = mapped_column(ForeignKey('task_series.id'), primary_key=True)
    local_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), unique=True)


class TaskExternal(Base):
    __tablename__ = 'task_external'
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comments_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskRule(Base):
    __tablename__ = 'task_rules'
    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(200))
    trigger: Mapped[str] = mapped_column(String(40))
    conditions_json: Mapped[str] = mapped_column(Text, default='{}')
    action_json: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __mapper_args__ = {'version_id_col': version}


class TaskRuleRun(Base):
    __tablename__ = 'task_rule_runs'
    rule_id: Mapped[int] = mapped_column(ForeignKey('task_rules.id'), primary_key=True)
    event_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'))
    version: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(500), default='Ausgeführt')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

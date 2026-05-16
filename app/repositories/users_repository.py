from uuid import UUID
from sqlalchemy.orm import Session

from app.models.user_profile import UserProfile


class UsersRepository:

    @staticmethod
    def list_all(db: Session, limit: int = 200) -> list[UserProfile]:
        return (
            db.query(UserProfile)
            .order_by(UserProfile.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def list_by_role(db: Session, role: str, limit: int = 200) -> list[UserProfile]:
        return (
            db.query(UserProfile)
            .filter(UserProfile.role == role)
            .order_by(UserProfile.full_name)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_by_id(db: Session, user_id: UUID) -> UserProfile | None:
        return db.query(UserProfile).filter(UserProfile.id == user_id).first()

    @staticmethod
    def update(
        db: Session,
        user_id: UUID,
        role: str | None = None,
        full_name: str | None = None,
    ) -> UserProfile | None:
        user = db.query(UserProfile).filter(UserProfile.id == user_id).first()
        if not user:
            return None
        if role is not None:
            user.role = role
        if full_name is not None:
            user.full_name = full_name
        db.commit()
        db.refresh(user)
        return user

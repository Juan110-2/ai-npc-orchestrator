from sqlalchemy.orm import Session
from app.models.profile import Profile
from app.models.sessions import Session as SessionModel
from app.models.conversation_message import ConversationMessage
from app.schemas.profile import ProfileCreate, ProfileUpdate

class ProfileRepository:

    @staticmethod
    def create(db: Session, payload: ProfileCreate) -> Profile:
        profile = Profile(
            name=payload.name,
            description=payload.description,
            traits=payload.traits
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile
    
    @staticmethod
    def update(db: Session, profile_id: str, payload: ProfileUpdate) -> Profile:

        profile = ProfileRepository.get_by_id(db, profile_id)

        if not profile: 
            return None

        if payload.name is not None:    
            profile.name = payload.name

        if payload.description is not None:    
            profile.description = payload.description

        if payload.traits is not None:    
            profile.traits = payload.traits

        db.commit()
        db.refresh(profile)
        return profile
    
    @staticmethod
    def delete(db: Session, profile_id: str) -> bool:
        profile = ProfileRepository.get_by_id(db, profile_id)

        if not profile:
            return False

        linked_session_ids = [
            row[0]
            for row in db.query(SessionModel.id)
            .filter(SessionModel.profile_id == profile.id)
            .all()
        ]

        if linked_session_ids:
            db.query(ConversationMessage).filter(
                ConversationMessage.session_id.in_(linked_session_ids)
            ).delete(synchronize_session=False)
            db.query(SessionModel).filter(
                SessionModel.id.in_(linked_session_ids)
            ).delete(synchronize_session=False)

        db.delete(profile)
        db.commit()
        return True
    
    @staticmethod
    def get_by_id(db: Session, profile_id: str) -> Profile | None:
        return db.query(Profile).filter(Profile.id == profile_id).first() 

    @staticmethod
    def get_all(db: Session) -> list[Profile]:
        return db.query(Profile).all()
    
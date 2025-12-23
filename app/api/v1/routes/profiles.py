from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.schemas.profile import ProfileCreate, ProfileUpdate, ProfileResponse
from app.api.v1.deps import get_db
from app.repositories.profile_repository import ProfileRepository
from fastapi import HTTPException, status

router = APIRouter(prefix="/profiles", tags=["profiles"])

@router.post("/create", response_model=ProfileResponse)
def create_profile(
    payload: ProfileCreate,
    db: Session = Depends(get_db)
):
    return ProfileRepository.create(db, payload)

@router.patch("/{profile_id}/update", response_model=ProfileResponse)
def update_profile(
    profile_id: str,
    payload: ProfileUpdate,
    db: Session = Depends(get_db)
):
    return ProfileRepository.update(db, profile_id, payload)

@router.delete("/{profile_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db)
):
    deleted = ProfileRepository.delete(db, profile_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")

@router.get("/", response_model=list[ProfileResponse])
def get_profiles(
    db: Session = Depends(get_db)
):
    return ProfileRepository.get_all(db)

@router.get("/{profile_id}", response_model=ProfileResponse)
def get_profile(
    profile_id: str,
    db: Session = Depends(get_db)
):
    return ProfileRepository.get_by_id(db, profile_id)


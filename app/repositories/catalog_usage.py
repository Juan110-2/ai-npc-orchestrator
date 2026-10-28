"""
Uso y borrado seguro de perfiles y escenarios (casos).

Regla de negocio:
  - "Sesion con actividad": tiene al menos un registro en `conversation_messages`,
    en `session_evaluations` o en `ai_call_logs` (columna `session_id`).
  - "Sesion sin uso": no tiene ninguno de los tres. No se usa el estado ni el tiempo,
    porque el cronometro corre con solo abrir el chat.
  - Un caso con alguna sesion con actividad no se borra (conserva la trazabilidad de las
    practicas). Si todas sus sesiones estan sin uso, se borran junto con el caso.

Cascadas en el ORM: los modelos no declaran `relationship(..., cascade=...)`, asi que el ORM
no borra mensajes ni evaluaciones por su cuenta. Aun asi, las sesiones se borran con DELETE a
nivel SQL (Core), nunca con `db.delete(obj)`, para que ninguna cascada futura del ORM pueda
arrastrar historial. En la base, la migracion 014 deja las FK de mensajes y evaluaciones en
`ON DELETE RESTRICT` como segunda barrera.
"""
from dataclasses import dataclass

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.ai_call_log import AICallLog
from app.models.conversation_message import ConversationMessage
from app.models.session_evaluation import SessionEvaluation
from app.models.sessions import Session as SessionModel

DELETED = "deleted"
NOT_FOUND = "not_found"
BLOCKED = "blocked"


@dataclass(frozen=True)
class DeleteResult:
    """Resultado de `delete_case_if_unused`: `status` y sesiones involucradas."""

    status: str
    sessions_with_activity: int = 0
    deleted_sessions: int = 0


@dataclass(frozen=True)
class CaseUsage:
    total_sessions: int
    sessions_with_activity: int

    @property
    def unused_sessions(self) -> int:
        return self.total_sessions - self.sessions_with_activity

    @property
    def can_delete(self) -> bool:
        return self.sessions_with_activity == 0


def _has_activity():
    """Condicion SQL (EXISTS en las tres tablas) para filtrar sesiones con actividad."""
    return or_(
        exists().where(ConversationMessage.session_id == SessionModel.id),
        exists().where(SessionEvaluation.session_id == SessionModel.id),
        exists().where(AICallLog.session_id == SessionModel.id),
    )


def _count_with_activity(db: Session, session_ids: list) -> int:
    if not session_ids:
        return 0
    stmt = (
        select(func.count())
        .select_from(SessionModel)
        .where(SessionModel.id.in_(session_ids), _has_activity())
    )
    return db.execute(stmt).scalar_one()


def get_case_usage(db: Session, case_model, fk_column, case_id) -> CaseUsage | None:
    """
    Conteo de sesiones del caso, sin bloqueos (consulta informativa).

    Devuelve None si el caso no existe.
    """
    exists_case = db.execute(select(case_model.id).where(case_model.id == case_id)).first()
    if exists_case is None:
        return None
    total = db.execute(
        select(func.count()).select_from(SessionModel).where(fk_column == case_id)
    ).scalar_one()
    with_activity = db.execute(
        select(func.count()).select_from(SessionModel).where(fk_column == case_id, _has_activity())
    ).scalar_one()
    return CaseUsage(total_sessions=total, sessions_with_activity=with_activity)


def delete_case_if_unused(db: Session, case_model, fk_column, case_id) -> DeleteResult:
    """
    Borra un perfil/escenario y sus sesiones sin uso en UNA transaccion, a prueba de carreras.

    Orden obligatorio:
      1. SELECT ... FOR UPDATE de la fila del caso: impide crear sesiones nuevas que lo referencien.
      2. SELECT id FROM sessions WHERE <fk> = :id FOR UPDATE: impide insertar el primer mensaje,
         evaluacion o log en esas sesiones (el INSERT con FK pide FOR KEY SHARE sobre la sesion).
      3. Solo entonces se cuenta la actividad de esas sesiones.
      4. Con actividad: rollback y resultado BLOCKED. Sin actividad: DELETE de las sesiones y del
         caso, y commit.

    Cualquier excepcion (p. ej. IntegrityError) deja la transaccion deshecha y se propaga al caller.
    """
    try:
        locked = db.execute(
            select(case_model.id).where(case_model.id == case_id).with_for_update()
        ).first()
        if locked is None:
            db.rollback()
            return DeleteResult(NOT_FOUND)

        session_ids = list(
            db.execute(select(SessionModel.id).where(fk_column == case_id).with_for_update())
            .scalars()
            .all()
        )

        with_activity = _count_with_activity(db, session_ids)
        if with_activity:
            db.rollback()
            return DeleteResult(BLOCKED, sessions_with_activity=with_activity)

        if session_ids:
            db.execute(
                delete(SessionModel)
                .where(SessionModel.id.in_(session_ids))
                .execution_options(synchronize_session=False)
            )
        db.execute(
            delete(case_model)
            .where(case_model.id == case_id)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return DeleteResult(DELETED, deleted_sessions=len(session_ids))
    except Exception:
        db.rollback()
        raise

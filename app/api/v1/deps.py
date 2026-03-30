from app.core.database import SessionLocal

def get_db():
    """
    Provee una sesión de base de datos por solicitud HTTP.

    - Centraliza la gestión de sesiones en un único punto.
    - Usa inyección de dependencias (FastAPI) para desacoplar infraestructura y rutas.
    - Garantiza liberación de recursos con `finally`, incluso ante errores.
    """   
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

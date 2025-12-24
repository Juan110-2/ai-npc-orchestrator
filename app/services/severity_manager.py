def adjust_severity(current_severity: int, impact: int) -> int:
    """
    Ajusta la severidad según el impacto evaluado.
    """

    new_severity = current_severity + impact

    return max(1, min(5, new_severity))

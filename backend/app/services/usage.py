"""Compteurs d'utilisation (ApiUsage) incrémentés de façon atomique : deux requêtes simultanées ne peuvent plus
créer deux fois la même ligne du jour (contrainte unique provider + jour)."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from ..models import ApiUsage


def bump_usage(db: Session, provider: str, n: int = 1, day: Optional[str] = None, commit: bool = True) -> None:
    if n <= 0:
        return
    day = day or date.today().isoformat()
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # autre base : chemin classique
        row = db.get(ApiUsage, (provider, day))
        if row is None:
            db.add(ApiUsage(provider=provider, day=day, requests=n))
        else:
            row.requests += n
        if commit:
            db.commit()
        return
    stmt = insert(ApiUsage).values(provider=provider[:40], day=day, requests=n)
    stmt = stmt.on_conflict_do_update(index_elements=[ApiUsage.provider, ApiUsage.day],
                                      set_={"requests": ApiUsage.requests + n})
    db.execute(stmt)
    if commit:
        db.commit()

"""Owner-scoped application pages from one consistent database statement."""
from typing import Literal

from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.orm import Session, aliased

from models import Application

SortField = Literal['app_id_str', 'applicant_name', 'loan_type', 'amount',
                    'status', 'validation_comments', 'submitted_date']
SortDirection = Literal['asc', 'desc']


def list_application_page(db: Session, owner_id: int, page: int, page_size: int,
                          sort_by: SortField, sort_direction: SortDirection):
    columns = {name: getattr(Application, name) for name in SortField.__args__}
    value = columns[sort_by]
    if sort_by not in ('amount', 'submitted_date'):
        value = func.nullif(func.lower(func.trim(value)), '')
    order = value.asc() if sort_direction == 'asc' else value.desc()
    owned = select(
        Application,
        func.row_number().over(order_by=[order.nulls_last(), Application.id.desc()]).label('position'),
    ).where(Application.owner_id == owner_id).cte('owned')
    metadata = select(
        func.count().label('total'),
        func.coalesce(func.max(case(
            (func.lower(func.trim(owned.c.status)).in_(['pending', 'processing', 'retrying']), 1),
            else_=0)), 0).label('active'),
    ).select_from(owned).cte('metadata')
    # Integer division must truncate on both SQLite and PostgreSQL.
    pages = cast(func.floor((metadata.c.total + page_size - 1) / page_size), Integer)
    current = case((metadata.c.total == 0, 1), (pages < page, pages), else_=page)
    bounds = select(metadata, pages.label('pages'), current.label('page')).cte('bounds')
    application = aliased(Application, owned)
    statement = select(application, bounds).select_from(bounds).outerjoin(
        owned, (owned.c.position > (bounds.c.page - 1) * page_size)
        & (owned.c.position <= bounds.c.page * page_size),
    ).order_by(owned.c.position)
    rows = db.execute(statement).all()
    first = rows[0]._mapping
    return dict(items=[row[0] for row in rows if row[0] is not None],
                total=first['total'], page=first['page'], page_size=page_size,
                total_pages=first['pages'], sort_by=sort_by, sort_direction=sort_direction,
                has_active_applications=bool(first['active']))

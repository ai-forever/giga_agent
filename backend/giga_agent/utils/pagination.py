"""
Утилиты для пагинации.
"""

from math import ceil
from typing import TypeVar, Generic, Sequence

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class PaginationMeta(BaseModel):
    """Метаданные пагинации"""
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_items: int = Field(..., description="Общее количество элементов")
    total_pages: int = Field(..., description="Общее количество страниц")
    has_next: bool = Field(..., description="Есть ли следующая страница")
    has_prev: bool = Field(..., description="Есть ли предыдущая страница")


class PaginatedResponse(BaseModel, Generic[T]):
    """Обёртка для пагинированного ответа"""
    items: list[T]
    meta: PaginationMeta


class PaginationParams(BaseModel):
    """Параметры пагинации"""
    page: int = Field(1, ge=1, description="Номер страницы")
    page_size: int = Field(20, ge=1, le=100, description="Размер страницы")
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
    
    @property
    def limit(self) -> int:
        return self.page_size


def get_pagination_params(
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(20, ge=1, le=100, description="Размер страницы"),
) -> PaginationParams:
    """FastAPI dependency для получения параметров пагинации"""
    return PaginationParams(page=page, page_size=page_size)


def calculate_pagination_meta(
    page: int,
    page_size: int,
    total_items: int,
) -> PaginationMeta:
    """Вычислить метаданные пагинации"""
    total_pages = ceil(total_items / page_size) if page_size > 0 else 0
    return PaginationMeta(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


async def paginate(
    db: AsyncSession,
    query: Select,
    params: PaginationParams,
) -> tuple[Sequence, PaginationMeta]:
    """
    Выполнить пагинированный запрос.
    
    Args:
        db: AsyncSession
        query: SQLAlchemy Select запрос
        params: Параметры пагинации
        
    Returns:
        Tuple[items, meta] - список элементов и метаданные пагинации
    """
    # Подсчёт общего количества
    # Извлекаем модель из запроса для подсчёта
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total_items = total_result.scalar() or 0
    
    # Применяем пагинацию
    paginated_query = query.offset(params.offset).limit(params.limit)
    result = await db.execute(paginated_query)
    items = result.scalars().all()
    
    meta = calculate_pagination_meta(params.page, params.page_size, total_items)
    
    return items, meta

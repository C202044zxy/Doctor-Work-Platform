from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request


def get_redis(request: Request):
    if request.app.state.cache is None:
        raise HTTPException(503, "Redis unavailable")
    return request.app.state.cache


Cache = Annotated[object, Depends(get_redis)]


class Pagination:
    def __init__(
        self,
        page: int = Query(1, ge=1, description="页码，从 1 开始 / Page number, starting at 1"),
        size: int = Query(20, ge=1, le=100, description="每页条数 / Page size"),
    ):
        self.page, self.size = page, size
        self.offset = (page - 1) * size

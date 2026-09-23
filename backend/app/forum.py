"""M7: shared professional discussions, with no patient record associations."""

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from app.audit import mark_audit
from app.auth import CurrentUser, ok
from app.forum_schemas import (
    Category,
    ForumPostCreate,
    ForumPostListResponse,
    ForumPostResponse,
    ForumReplyCreate,
    ForumReplyListResponse,
    ForumReplyResponse,
)
from app.models import ForumPost, ForumReply, User


def enabled(request: Request):
    if not request.app.state.settings.forum_enabled:
        raise HTTPException(404, "Forum is disabled")


router = APIRouter(prefix="/api/forum", tags=["Forum"], dependencies=[Depends(enabled)])


def read(db, row):
    data = {
        "id": row.id,
        "author": db.get(User, row.author_id).name,
        "body": row.body,
        "created_at": row.created_at.replace(tzinfo=UTC),
        "is_sample": row.seed_key is not None,
    }
    if isinstance(row, ForumPost):
        data.update(
            title=row.title,
            category=row.category,
            reply_count=db.scalar(
                select(func.count()).select_from(ForumReply).where(ForumReply.post_id == row.id)
            ),
        )
    return data


def find_post(db, post_id):
    row = db.get(ForumPost, post_id)
    if row is None:
        raise HTTPException(404, "Discussion not found")
    return row


@router.get("/posts", response_model=ForumPostListResponse)
def list_posts(
    request: Request,
    user: CurrentUser,
    q: str = Query("", max_length=200),
    category: Category | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    with request.app.state.sessions() as db:
        query = select(ForumPost)
        if q.strip():
            query = query.where(
                or_(
                    ForumPost.title.icontains(q.strip(), autoescape=True),
                    ForumPost.body.icontains(q.strip(), autoescape=True),
                )
            )
        if category:
            query = query.where(ForumPost.category == category)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(
            query.order_by(ForumPost.created_at.desc(), ForumPost.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return ok(
            {"items": [read(db, row) for row in rows], "total": total, "page": page, "size": size}
        )


@router.post("/posts", response_model=ForumPostResponse)
def create_post(request: Request, user: CurrentUser, body: ForumPostCreate):
    with request.app.state.sessions() as db:
        row = ForumPost(author_id=user.id, **body.model_dump())
        db.add(row)
        db.commit()
        mark_audit(request, "forum.post.create", "forum_post", row.id)
        return ok(read(db, row))


@router.get("/posts/{post_id}", response_model=ForumPostResponse)
def get_post(request: Request, user: CurrentUser, post_id: int):
    with request.app.state.sessions() as db:
        return ok(read(db, find_post(db, post_id)))


@router.get("/posts/{post_id}/replies", response_model=ForumReplyListResponse)
def list_replies(
    request: Request,
    user: CurrentUser,
    post_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    with request.app.state.sessions() as db:
        find_post(db, post_id)
        query = select(ForumReply).where(ForumReply.post_id == post_id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(
            query.order_by(ForumReply.created_at, ForumReply.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        return ok(
            {"items": [read(db, row) for row in rows], "total": total, "page": page, "size": size}
        )


@router.post("/posts/{post_id}/replies", response_model=ForumReplyResponse)
def create_reply(request: Request, user: CurrentUser, post_id: int, body: ForumReplyCreate):
    with request.app.state.sessions() as db:
        find_post(db, post_id)
        row = ForumReply(post_id=post_id, author_id=user.id, body=body.body)
        db.add(row)
        db.commit()
        mark_audit(request, "forum.reply.create", "forum_post", post_id)
        return ok(read(db, row))

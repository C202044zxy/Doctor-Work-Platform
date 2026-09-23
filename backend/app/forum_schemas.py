"""M7 forum contract models; plain text content only."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Category = Literal[
    "General discussion", "Clinical practice", "Patient communication", "Research & learning"
]


class ForumReplyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class ForumPostCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    category: Category


class ForumReply(BaseModel):
    id: int
    author: str
    body: str
    created_at: datetime
    is_sample: bool


class ForumPost(ForumReply):
    title: str
    category: Category
    reply_count: int


class ForumPostResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "ok"
    data: ForumPost


class ForumReplyResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "ok"
    data: ForumReply


class PostPage(BaseModel):
    items: list[ForumPost]
    total: int
    page: int
    size: int


class ReplyPage(BaseModel):
    items: list[ForumReply]
    total: int
    page: int
    size: int


class ForumPostListResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "ok"
    data: PostPage


class ForumReplyListResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "ok"
    data: ReplyPage

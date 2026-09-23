"""Idempotent fictional M7 discussions, called by the startup demo seeder."""

from sqlalchemy import select

from app.models import ForumPost, ForumReply, User

SAMPLES = [
    (
        "welcome",
        "General discussion",
        "Welcome to the medical forum",
        "A space to exchange ideas with colleagues across departments. Introduce yourself and share a topic you would like to discuss. This is a fictional starter discussion; do not include patient identifiers.",
        "I would enjoy a regular discussion about lessons learned in team communication.",
    ),
    (
        "handover",
        "Clinical practice",
        "What makes a useful clinical handover?",
        "Fictional discussion prompt: our teaching team is reviewing how to make handovers clearer. What structure helps your colleagues ask questions and understand outstanding tasks?",
        "For a teaching exercise, we could compare two fictional handovers and discuss what information is missing.",
    ),
    (
        "communication",
        "Patient communication",
        "Making room for questions in a busy appointment",
        "Fictional discussion prompt: how do you invite questions and explain unfamiliar terminology? Share communication approaches without real patient stories or identifying details.",
        "A useful workshop topic would be practising explanations in plain language with a colleague.",
    ),
    (
        "journal",
        "Research & learning",
        "Starting a cross-department journal club",
        "We are planning a fictional journal club. Which topics would you like to explore, and how should we structure discussion of study limitations? Please link original research when sharing a paper.",
        "Could each session include time to discuss the study population and questions the paper leaves unanswered?",
    ),
]


def seed_forum(db):
    authors = list(
        db.scalars(
            select(User)
            .where(User.username.in_(["dr_li", "dr_wang", "admin_zhang", "admin"]))
            .order_by(User.id)
        )
    )
    if not authors:
        return
    for index, (key, category, title, body, reply) in enumerate(SAMPLES):
        post_key = f"m7-{key}"
        post = db.scalar(select(ForumPost).where(ForumPost.seed_key == post_key))
        if post is None:
            post = ForumPost(
                author_id=authors[index % len(authors)].id,
                title=title,
                body=body,
                category=category,
                seed_key=post_key,
            )
            db.add(post)
            db.flush()
        if db.scalar(select(ForumReply.id).where(ForumReply.seed_key == post_key)) is None:
            db.add(
                ForumReply(
                    post_id=post.id,
                    author_id=authors[(index + 1) % len(authors)].id,
                    body=reply,
                    seed_key=post_key,
                )
            )

"""Conversations router: create, append messages, and read history (Req 8.1-8.4).

All responses use typed Pydantic models and render errors through the existing uniform
error envelope. ``POST /conversations`` creates a conversation; ``POST
/conversations/{id}/messages`` appends a message (auto-creating an unknown id, Req 8.4);
``GET /conversations/{id}`` returns the history ordered by position, or ``404`` via the
envelope when the conversation is unknown (Req 8.3).

The Conversation_Store is synchronous, so its calls run in a worker thread to avoid
blocking the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import get_conversation_store, require_permission
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    AppendMessageRequest,
    ConversationHistoryResponse,
    ConversationSummaryResponse,
    CreateConversationResponse,
    MessageModel,
)
from agentforge.conversation.base import Conversation_Store
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission

router = APIRouter(tags=["conversations"])


@router.post(
    "/conversations",
    response_model=CreateConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    store: Conversation_Store = Depends(get_conversation_store),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> CreateConversationResponse:
    """Create a conversation owned by the caller's org (Req 8.1, 4.4)."""
    conversation_id = await run_in_threadpool(store.create, principal.org_id)
    return CreateConversationResponse(conversation_id=conversation_id)


@router.get("/conversations", response_model=list[ConversationSummaryResponse])
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    store: Conversation_Store = Depends(get_conversation_store),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> list[ConversationSummaryResponse]:
    """Return the caller org's conversations, most recent first (Req 8.1, 4.2).

    Creation returned an id once and there was no way to enumerate threads afterwards, so
    a conversation became unreachable as soon as its id was lost. Scoped to
    ``principal.org_id`` at the data-access layer, so no other tenant's thread can appear.
    """
    summaries = await run_in_threadpool(
        lambda: store.list_conversations(principal.org_id, limit=limit)
    )
    return [
        ConversationSummaryResponse(
            conversation_id=summary.id,
            created_at=summary.created_at,
            message_count=summary.message_count,
            preview=summary.preview,
        )
        for summary in summaries
    ]


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageModel,
    status_code=status.HTTP_201_CREATED,
)
async def append_message(
    conversation_id: str,
    payload: AppendMessageRequest,
    store: Conversation_Store = Depends(get_conversation_store),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> MessageModel:
    """Append a message with the next ordinal, auto-creating an unknown id (Req 8.2, 8.4)."""
    message = await run_in_threadpool(
        store.append, principal.org_id, conversation_id, payload.role, payload.content
    )
    return MessageModel(
        role=message.role, content=message.content, position=message.position
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationHistoryResponse,
)
async def get_conversation(
    conversation_id: str,
    store: Conversation_Store = Depends(get_conversation_store),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> ConversationHistoryResponse:
    """Return the conversation history ordered by position; 404 when unknown/cross-tenant (Req 8.3, 4.3)."""
    exists = await run_in_threadpool(store.exists, principal.org_id, conversation_id)
    if not exists:
        raise AppError(
            "not_found",
            f"conversation {conversation_id!r} was not found",
            status.HTTP_404_NOT_FOUND,
        )
    messages = await run_in_threadpool(store.history, principal.org_id, conversation_id)
    return ConversationHistoryResponse(
        conversation_id=conversation_id,
        messages=[
            MessageModel(role=m.role, content=m.content, position=m.position)
            for m in messages
        ],
    )

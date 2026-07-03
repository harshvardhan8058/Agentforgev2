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

from fastapi import APIRouter, Depends, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import get_conversation_store
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    AppendMessageRequest,
    ConversationHistoryResponse,
    CreateConversationResponse,
    MessageModel,
)
from agentforge.conversation.base import Conversation_Store

router = APIRouter(tags=["conversations"])


@router.post(
    "/conversations",
    response_model=CreateConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    store: Conversation_Store = Depends(get_conversation_store),
) -> CreateConversationResponse:
    """Create a conversation with a unique id (Req 8.1)."""
    conversation_id = await run_in_threadpool(store.create)
    return CreateConversationResponse(conversation_id=conversation_id)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageModel,
    status_code=status.HTTP_201_CREATED,
)
async def append_message(
    conversation_id: str,
    payload: AppendMessageRequest,
    store: Conversation_Store = Depends(get_conversation_store),
) -> MessageModel:
    """Append a message with the next ordinal, auto-creating an unknown id (Req 8.2, 8.4)."""
    message = await run_in_threadpool(
        store.append, conversation_id, payload.role, payload.content
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
) -> ConversationHistoryResponse:
    """Return the conversation history ordered by position; 404 when unknown (Req 8.3)."""
    exists = await run_in_threadpool(store.exists, conversation_id)
    if not exists:
        raise AppError(
            "not_found",
            f"conversation {conversation_id!r} was not found",
            status.HTTP_404_NOT_FOUND,
        )
    messages = await run_in_threadpool(store.history, conversation_id)
    return ConversationHistoryResponse(
        conversation_id=conversation_id,
        messages=[
            MessageModel(role=m.role, content=m.content, position=m.position)
            for m in messages
        ],
    )

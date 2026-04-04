"""FastAPI web application for CRM."""
from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

# Use relative imports for running directly
try:
    from crm import crud, search
    from crm.database import get_db
    from crm.schemas import CRMEntryCreate, CRMEntryUpdate, EntryFilterParams
    from crm.websocket import handle_websocket, manager, broadcast_entry_update
except ImportError:
    import crud
    import search
    from database import get_db
    from schemas import CRMEntryCreate, CRMEntryUpdate, EntryFilterParams
    from websocket import handle_websocket, manager, broadcast_entry_update


# Setup templates and static files
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"

TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}


def _safe_filename(filename: str) -> str:
    """Return a filesystem-safe filename stem."""
    stem = Path(filename).stem or "image"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", stem)[:80]


async def _save_upload_file(upload_file: UploadFile) -> str | None:
    """Save one uploaded image and return public URL path."""
    original_name = upload_file.filename or ""
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None

    safe_stem = _safe_filename(original_name)
    unique_name = f"{uuid.uuid4().hex}_{safe_stem}{ext}"
    output_path = UPLOAD_DIR / unique_name

    content = await upload_file.read()
    if not content:
        return None

    output_path.write_bytes(content)
    return f"/static/uploads/{unique_name}"


async def _save_uploaded_images(files: list[UploadFile] | None) -> list[str]:
    """Save uploaded images and return their URL paths."""
    if not files:
        return []

    saved_paths: list[str] = []
    for file in files:
        saved_path = await _save_upload_file(file)
        if saved_path:
            saved_paths.append(saved_path)
    return saved_paths


def _split_existing_attachments(raw_attachments: str | None) -> list[str]:
    """Parse textarea attachments into list."""
    if not raw_attachments:
        return []
    return [line.strip() for line in raw_attachments.splitlines() if line.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # FIX: use try/except for import compatibility (package vs direct run)
    try:
        from crm.database import get_engine, init_db
    except ImportError:
        from database import get_engine, init_db

    engine = get_engine()
    init_db(engine)
    yield
    # Shutdown


app = FastAPI(title="IceWhale CRM", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Dashboard page."""
    stats = crud.get_stats(db)
    filter_options = search.get_filter_options(db)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "filter_options": filter_options,
        },
    )


@app.get("/entries", response_class=HTMLResponse)
async def list_entries(
    request: Request,
    q: str | None = None,
    type_tag: str | None = None,
    status_tag: str | None = None,
    feature_module: str | None = None,
    assignee: str | None = None,
    user_name: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List entries with filters."""
    filters = EntryFilterParams(
        q=q,
        type_tag=type_tag,
        status_tag=status_tag,
        feature_module=feature_module,
        assignee=assignee,
        user_name=user_name,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )

    entries, total = search.get_filtered_entries(db, filters)
    filter_options = search.get_filter_options(db)

    # Calculate pagination
    total_pages = (total + page_size - 1) // page_size

    return templates.TemplateResponse(
        request,
        "list.html",
        {
            "entries": entries,
            "filters": filters,
            "filter_options": filter_options,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        },
    )


@app.get("/entries/new", response_class=HTMLResponse)
async def new_entry_form(request: Request, db: Session = Depends(get_db)):
    """New entry form."""
    filter_options = search.get_filter_options(db)
    return templates.TemplateResponse(
        request,
        "form.html",
        {
            "entry": None,
            "filter_options": filter_options,
            "is_edit": False,
        },
    )


@app.post("/entries")
async def create_entry(
    request: Request,
    title: str = Form(...),
    analysis_todo: str | None = Form(default=None),
    community_todo: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    assignee: str | None = Form(default=None),
    status_tag: str = Form(default="已定位/知晓"),
    feature_module: str | None = Form(default=None),
    user_name: str | None = Form(default=None),
    volume: int = Form(default=1),
    notes: str | None = Form(default=None),
    parent_record: str | None = Form(default=None),
    type_tag: str = Form(default="S"),
    knowledge_base_url: str | None = Form(default=None),
    github_issue_url: str | None = Form(default=None),
    source_type: str | None = Form(default=None),
    created_by: str | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
):
    """Create new entry."""
    attachment_paths = await _save_uploaded_images(files)

    entry_create = CRMEntryCreate(
        title=title,
        analysis_todo=analysis_todo or None,
        community_todo=community_todo or None,
        source_url=source_url or None,
        assignee=assignee or None,
        status_tag=status_tag,
        feature_module=feature_module or None,
        user_name=user_name or None,
        volume=volume,
        notes=notes or None,
        parent_record=parent_record or None,
        type_tag=type_tag,
        attachments=attachment_paths,
        knowledge_base_url=knowledge_base_url or None,
        github_issue_url=github_issue_url or None,
        source_type=source_type or None,
        created_by=created_by,
    )

    entry = crud.create_entry(db, entry_create, created_by=created_by)

    # Trigger webhooks for new entry
    try:
        from webhook_handlers import notify_new_issue, notify_high_priority

        # Notify new issue
        await notify_new_issue(
            entry_id=entry.id,
            title=entry.title,
            type_tag=entry.type_tag,
            status_tag=entry.status_tag,
            feature_module=entry.feature_module,
            user_name=entry.user_name,
            source_type=entry.source_type,
            source_url=entry.source_url,
            priority=getattr(entry, 'priority', '中'),
        )

        # Notify if high priority
        if getattr(entry, 'priority', '中') in ['高', '紧急']:
            await notify_high_priority(
                entry_id=entry.id,
                title=entry.title,
                type_tag=entry.type_tag,
                status_tag=entry.status_tag,
                feature_module=entry.feature_module,
                user_name=entry.user_name,
                source_type=entry.source_type,
                source_url=entry.source_url,
                priority=entry.priority,
            )
    except Exception as e:
        # Log error but don't fail the request
        print(f"Webhook notification error: {e}")

    return RedirectResponse(url=f"/entries/{entry.id}", status_code=303)


# FIX: batch-delete must be registered BEFORE /{entry_id} routes to avoid route conflict
@app.post("/entries/batch-delete")
async def batch_delete_entries(
    request: Request,
    entry_ids: str = Form(...),
    db: Session = Depends(get_db),
):
    """Batch delete entries."""
    ids = [id.strip() for id in entry_ids.split(",") if id.strip()]
    deleted_count = crud.delete_entries_batch(db, ids)

    return RedirectResponse(url="/entries", status_code=303)


@app.get("/entries/{entry_id}", response_class=HTMLResponse)
async def view_entry(entry_id: str, request: Request, db: Session = Depends(get_db)):
    """View entry details."""
    entry = crud.get_entry(db, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    filter_options = search.get_filter_options(db)

    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "entry": entry,
            "filter_options": filter_options,
        },
    )


@app.get("/entries/{entry_id}/edit", response_class=HTMLResponse)
async def edit_entry_form(
    entry_id: str, request: Request, db: Session = Depends(get_db)
):
    """Edit entry form."""
    entry = crud.get_entry(db, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    filter_options = search.get_filter_options(db)

    return templates.TemplateResponse(
        request,
        "form.html",
        {
            "entry": entry,
            "filter_options": filter_options,
            "is_edit": True,
        },
    )


@app.post("/entries/{entry_id}")
async def update_entry(
    entry_id: str,
    request: Request,
    title: str | None = Form(default=None),
    analysis_todo: str | None = Form(default=None),
    community_todo: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    assignee: str | None = Form(default=None),
    status_tag: str | None = Form(default=None),
    feature_module: str | None = Form(default=None),
    user_name: str | None = Form(default=None),
    volume: int | None = Form(default=None),
    notes: str | None = Form(default=None),
    parent_record: str | None = Form(default=None),
    type_tag: str | None = Form(default=None),
    existing_attachments: str | None = Form(default=None),
    knowledge_base_url: str | None = Form(default=None),
    github_issue_url: str | None = Form(default=None),
    source_type: str | None = Form(default=None),
    version: int | None = Form(default=None),
    edited_by: str | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
):
    """Update entry with optimistic locking."""
    db_entry = crud.get_entry(db, entry_id)
    if not db_entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    form = await request.form()
    kept_attachments = _split_existing_attachments(existing_attachments)
    new_attachments = await _save_uploaded_images(files)

    update_payload: dict[str, object | None] = {
        "version": version,
        "edited_by": edited_by,
    }

    if "title" in form:
        update_payload["title"] = title
    if "analysis_todo" in form:
        update_payload["analysis_todo"] = analysis_todo
    if "community_todo" in form:
        update_payload["community_todo"] = community_todo
    if "source_url" in form:
        update_payload["source_url"] = source_url or None
    if "assignee" in form:
        update_payload["assignee"] = assignee or None
    if "status_tag" in form:
        update_payload["status_tag"] = status_tag
    if "feature_module" in form:
        update_payload["feature_module"] = feature_module or None
    if "user_name" in form:
        update_payload["user_name"] = user_name or None
    if "volume" in form:
        update_payload["volume"] = volume
    if "notes" in form:
        update_payload["notes"] = notes
    if "parent_record" in form:
        update_payload["parent_record"] = parent_record or None
    if "type_tag" in form:
        update_payload["type_tag"] = type_tag
    if "knowledge_base_url" in form:
        update_payload["knowledge_base_url"] = knowledge_base_url or None
    if "github_issue_url" in form:
        update_payload["github_issue_url"] = github_issue_url or None
    if "source_type" in form:
        update_payload["source_type"] = source_type or None
    if "existing_attachments" in form or new_attachments:
        update_payload["attachments"] = kept_attachments + new_attachments

    entry_update = CRMEntryUpdate(**update_payload)

    try:
        entry = crud.update_entry(db, entry_id, entry_update, edited_by=edited_by)
    except crud.ConflictError as e:
        # Return conflict error with current data
        return JSONResponse(
            status_code=409,
            content={
                "error": "Conflict detected",
                "message": str(e),
                "current_version": e.current_version,
                "your_version": e.your_version,
                "current_data": {
                    "id": e.current_entry.id,
                    "title": e.current_entry.title,
                    "version": e.current_entry.version,
                    "last_edited_by": e.current_entry.last_edited_by,
                    "last_edited_at": e.current_entry.last_edited_at.isoformat() if e.current_entry.last_edited_at else None,
                },
            },
        )

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Broadcast update to other connected clients
    updated_fields = entry_update.model_dump(exclude_unset=True, exclude={"version", "edited_by"})
    await broadcast_entry_update(
        entry_id=entry_id,
        updated_fields=updated_fields,
        version=entry.version,
        edited_by=edited_by or "unknown",
    )

    return RedirectResponse(url=f"/entries/{entry.id}", status_code=303)


@app.post("/entries/{entry_id}/delete")
async def delete_entry(entry_id: str, db: Session = Depends(get_db)):
    """Delete entry."""
    success = crud.delete_entry(db, entry_id)
    if not success:
        raise HTTPException(status_code=404, detail="Entry not found")

    return RedirectResponse(url="/entries", status_code=303)


# API Endpoints
@app.get("/api/entries")
async def api_list_entries(
    q: str | None = None,
    type_tag: str | None = None,
    status_tag: str | None = None,
    feature_module: str | None = None,
    assignee: str | None = None,
    user_name: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """API: List entries with filters."""
    filters = EntryFilterParams(
        q=q,
        type_tag=type_tag,
        status_tag=status_tag,
        feature_module=feature_module,
        assignee=assignee,
        user_name=user_name,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )

    entries, total = search.get_filtered_entries(db, filters)

    return {
        "items": entries,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/entries/{entry_id}")
async def api_get_entry(entry_id: str, db: Session = Depends(get_db)):
    """API: Get entry details."""
    entry = crud.get_entry(db, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@app.patch("/api/entries/{entry_id}")
async def api_patch_entry(
    entry_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """API: Partial update of an entry."""
    entry = crud.get_entry(db, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    data = await request.json()

    # Build update payload with only provided fields
    update_data = {"version": entry.version}
    allowed_fields = [
        "title", "analysis_todo", "community_todo", "source_url",
        "assignee", "status_tag", "feature_module", "user_name",
        "volume", "notes", "parent_record", "type_tag",
        "knowledge_base_url", "github_issue_url", "source_type"
    ]

    for field in allowed_fields:
        if field in data:
            update_data[field] = data[field]

    entry_update = CRMEntryUpdate(**update_data)
    updated_entry = crud.update_entry(db, entry_id, entry_update, edited_by="system")

    if not updated_entry:
        raise HTTPException(status_code=409, detail="Update failed due to conflict")

    return updated_entry


@app.get("/api/stats")
async def api_get_stats(db: Session = Depends(get_db)):
    """API: Get dashboard statistics."""
    return crud.get_stats(db)


# Collaboration API Endpoints

@app.get("/api/entries/{entry_id}/version")
async def api_get_entry_version(entry_id: str, db: Session = Depends(get_db)):
    """API: Get entry version for optimistic locking."""
    entry = crud.get_entry(db, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    return {
        "id": entry.id,
        "version": entry.version,
        "last_edited_by": entry.last_edited_by,
        "last_edited_at": entry.last_edited_at,
        "is_being_edited": entry.is_being_edited,
        "edited_by_session": entry.edited_by_session,
    }


@app.get("/api/entries/{entry_id}/history")
async def api_get_entry_history(
    entry_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """API: Get edit history for an entry."""
    entry = crud.get_entry(db, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    history = crud.get_entry_history(db, entry_id, limit)
    return {
        "entry_id": entry_id,
        "history": [
            {
                "id": h.id,
                "field_name": h.field_name,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "created_at": h.created_at,
                "username": h.user.username if h.user else None,
            }
            for h in history
        ],
    }


@app.post("/api/entries/{entry_id}/edit-session/start")
async def api_start_edit_session(
    entry_id: str,
    username: str = Form(...),
    session_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """API: Start an edit session for an entry."""
    entry = crud.start_edit_session(db, entry_id, session_id, username)
    if not entry:
        raise HTTPException(status_code=409, detail="Entry is being edited by another user")

    return {
        "success": True,
        "entry_id": entry_id,
        "session_id": session_id,
        "expires_at": entry.edit_session_expires,
    }


@app.post("/api/entries/{entry_id}/edit-session/end")
async def api_end_edit_session(
    entry_id: str,
    session_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """API: End an edit session for an entry."""
    entry = crud.end_edit_session(db, entry_id, session_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    return {"success": True, "entry_id": entry_id}


# WebSocket endpoint for real-time collaboration
@app.websocket("/ws/entries/{entry_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    entry_id: str,
    username: str = Query(...),
    session_id: str = Query(...),
    db: Session = Depends(get_db),
):
    """WebSocket endpoint for real-time collaboration on an entry."""
    await handle_websocket(websocket, entry_id, username, session_id, db)


# User management endpoints
@app.post("/api/users")
async def api_create_user(
    username: str = Form(...),
    display_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """API: Create or get a user."""
    user = crud.get_or_create_user(db, username, display_name)
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "created_at": user.created_at,
    }


@app.get("/api/users/{username}")
async def api_get_user(username: str, db: Session = Depends(get_db)):
    """API: Get user by username."""
    user = crud.get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "created_at": user.created_at,
    }


# AI Assistant API Endpoints

@app.post("/api/ai/parse")
async def api_ai_parse_issue(request: Request):
    """API: Parse raw issue text using AI."""
    try:
        from ai_assistant import get_ai_assistant

        data = await request.json()
        text = data.get("text", "")

        if not text:
            raise HTTPException(status_code=400, detail="Text is required")

        ai = get_ai_assistant()
        result = ai.parse_issue(text)

        if result is None:
            raise HTTPException(status_code=500, detail="AI parsing failed")

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/suggest-kb")
async def api_ai_suggest_kb(
    request: Request,
    db: Session = Depends(get_db),
):
    """API: Suggest knowledge base articles for an issue."""
    try:
        from ai_assistant import get_ai_assistant
        from vector_search import get_vector_search

        data = await request.json()
        title = data.get("title", "")
        content = data.get("content", "")

        if not title:
            raise HTTPException(status_code=400, detail="Title is required")

        # Search vector DB
        vector_search = get_vector_search()
        kb_results = vector_search.search(f"{title} {content}", limit=3)

        # AI rerank
        ai = get_ai_assistant()
        result = ai.suggest_knowledge_base(title, content, kb_results)

        return {
            "suggestions": kb_results,
            "ai_recommendation": result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/generate-response")
async def api_ai_generate_response(request: Request):
    """API: Generate response to an issue."""
    try:
        from ai_assistant import get_ai_assistant

        data = await request.json()
        title = data.get("title", "")
        content = data.get("content", "")
        kb_article = data.get("kb_article")

        if not title:
            raise HTTPException(status_code=400, detail="Title is required")

        ai = get_ai_assistant()
        response = ai.generate_response(title, content, kb_article)

        if response is None:
            raise HTTPException(status_code=500, detail="Generation failed")

        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)

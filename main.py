import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Column as ColumnSchema, Task as TaskSchema

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def to_str_id(doc: Dict[str, Any]):
    if doc and doc.get("_id"):
        doc["id"] = str(doc.pop("_id"))
    return doc


@app.get("/")
def read_root():
    return {"message": "Kanban API is running"}


# Columns Endpoints
class ColumnCreate(BaseModel):
    name: str
    position: Optional[int] = 0


class ColumnUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None


@app.get("/api/columns")
def list_columns():
    cols = get_documents("column", {})
    cols.sort(key=lambda c: c.get("position", 0))
    return [to_str_id(c) for c in cols]


@app.post("/api/columns")
def create_column(payload: ColumnCreate):
    col = ColumnSchema(name=payload.name, position=payload.position or 0)
    new_id = create_document("column", col)
    doc = db["column"].find_one({"_id": ObjectId(new_id)})
    return to_str_id(doc)


@app.patch("/api/columns/{column_id}")
def update_column(column_id: str, payload: ColumnUpdate):
    try:
        oid = ObjectId(column_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid column id")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        return {"updated": False}
    db["column"].update_one({"_id": oid}, {"$set": updates})
    doc = db["column"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Column not found")
    return to_str_id(doc)


@app.delete("/api/columns/{column_id}")
def delete_column(column_id: str):
    try:
        oid = ObjectId(column_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid column id")
    res = db["column"].delete_one({"_id": oid})
    # Also optionally delete tasks in that column
    db["task"].delete_many({"column_id": column_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Column not found")
    return {"deleted": True}


# Tasks Endpoints
class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    column_id: str
    position: Optional[int] = 0
    priority: Optional[str] = "normal"
    tags: Optional[List[str]] = []


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column_id: Optional[str] = None
    position: Optional[int] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None


@app.get("/api/tasks")
def list_tasks(column_id: Optional[str] = Query(default=None)):
    query: Dict[str, Any] = {}
    if column_id:
        query["column_id"] = column_id
    tasks = get_documents("task", query)
    tasks.sort(key=lambda t: t.get("position", 0))
    return [to_str_id(t) for t in tasks]


@app.post("/api/tasks")
def create_task(payload: TaskCreate):
    # Determine position as end of column
    last = db["task"].find({"column_id": payload.column_id}).sort("position", -1).limit(1)
    last_pos = 0
    for d in last:
        last_pos = int(d.get("position", 0)) + 1
    t = TaskSchema(
        title=payload.title,
        description=payload.description,
        column_id=payload.column_id,
        position=last_pos,
        priority=payload.priority or "normal",
        tags=payload.tags or [],
    )
    new_id = create_document("task", t)
    doc = db["task"].find_one({"_id": ObjectId(new_id)})
    return to_str_id(doc)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdate):
    try:
        oid = ObjectId(task_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid task id")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}

    # If moving to a new column without position, append to end
    if "column_id" in updates and updates.get("position") is None:
        last = db["task"].find({"column_id": updates["column_id"]}).sort("position", -1).limit(1)
        last_pos = 0
        for d in last:
            last_pos = int(d.get("position", 0)) + 1
        updates["position"] = last_pos

    db["task"].update_one({"_id": oid}, {"$set": updates})
    doc = db["task"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Task not found")
    return to_str_id(doc)


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str):
    try:
        oid = ObjectId(task_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid task id")
    res = db["task"].delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

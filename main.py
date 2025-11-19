import os
from datetime import date, datetime, timezone, timedelta
from typing import Optional, List, Any, Dict

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import User as UserSchema, Plan as PlanSchema, Checkin as CheckinSchema, Tip as TipSchema

try:
    from bson import ObjectId  # type: ignore
except Exception:
    # Fallback simple ObjectId converter if bson isn't available (should be with pymongo)
    class ObjectId(str):
        pass

app = FastAPI(title="SnusQuit API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in doc.items():
        if k == "_id":
            out["id"] = str(v)
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


@app.get("/")
def read_root():
    return {"message": "SnusQuit Backend is running"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


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
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = getattr(db, "name", "?")
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


# ---------------------------
# SnusQuit core endpoints
# ---------------------------

class CreateUserRequest(UserSchema):
    pass


@app.post("/api/users")
def create_user(payload: CreateUserRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    user_id = create_document("user", payload)
    return {"id": user_id}


class CreatePlanRequest(PlanSchema):
    pass


@app.post("/api/plans")
def create_plan(payload: CreatePlanRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    # ensure user exists
    try:
        uid = ObjectId(payload.user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if db["user"].count_documents({"_id": uid}) == 0:
        raise HTTPException(status_code=404, detail="User not found")
    plan_id = create_document("plan", payload)
    return {"id": plan_id}


class CreateCheckinRequest(CheckinSchema):
    pass


@app.post("/api/checkins")
def create_or_update_checkin(payload: CreateCheckinRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    # Upsert per user_id + date
    try:
        uid = ObjectId(payload.user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    d = datetime.fromisoformat(str(payload.date)).date()
    existing = db["checkin"].find_one({"user_id": payload.user_id, "date": d})
    doc = payload.model_dump()
    doc["date"] = d
    doc["updated_at"] = datetime.now(timezone.utc)
    if existing:
        db["checkin"].update_one({"_id": existing["_id"]}, {"$set": doc})
        cid = str(existing["_id"])
    else:
        doc["created_at"] = datetime.now(timezone.utc)
        res = db["checkin"].insert_one(doc)
        cid = str(res.inserted_id)
    return {"id": cid}


@app.get("/api/checkins/{user_id}")
def get_checkins(user_id: str, limit: int = Query(default=30, ge=1, le=365)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        _ = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    items = db["checkin"].find({"user_id": user_id}).sort("date", -1).limit(limit)
    return [serialize_doc({**i, "date": i.get("date")}) for i in items]


@app.get("/api/plan/{user_id}")
def get_plan(user_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        _ = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    plan = db["plan"].find_one({"user_id": user_id}, sort=[("created_at", -1)])
    if not plan:
        return None
    return serialize_doc(plan)


@app.get("/api/summary/{user_id}")
def get_summary(user_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        _ = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    today = date.today()
    checkins = list(db["checkin"].find({"user_id": user_id}).sort("date", 1))

    total = len(checkins)
    nicotine_free = sum(1 for c in checkins if c.get("nicotine_free"))
    portions = [c.get("portions_used", 0) or 0 for c in checkins]
    avg_portions = round(sum(portions) / len(portions), 2) if portions else 0.0

    # Streak (consecutive nicotine_free days up to today)
    streak = 0
    c_map = {c.get("date"): c for c in checkins}
    day = today
    while True:
        c = c_map.get(day)
        if c and c.get("nicotine_free"):
            streak += 1
            day = day - timedelta(days=1)
        else:
            break

    # Last 7 days
    last7_start = today - timedelta(days=6)
    last7 = [c for c in checkins if last7_start <= c.get("date", today - timedelta(days=1000)) <= today]
    last7_nf = sum(1 for c in last7 if c.get("nicotine_free"))

    # Adherence vs plan if exists
    plan = db["plan"].find_one({"user_id": user_id}, sort=[("created_at", -1)])
    adherence = None
    if plan and plan.get("goal_type") == "reduce" and plan.get("target_portions_per_day") is not None:
        # Compare last 7 days average to target
        last7_portions = [c.get("portions_used", 0) or 0 for c in last7]
        last7_avg = (sum(last7_portions) / len(last7_portions)) if last7_portions else 0
        target = float(plan.get("target_portions_per_day") or 0)
        adherence = max(0.0, round((1 - (last7_avg / target)) * 100, 1)) if target > 0 else None

    return {
        "total_checkins": total,
        "nicotine_free_days": nicotine_free,
        "current_streak": streak,
        "avg_portions": avg_portions,
        "last7": {"days": len(last7), "nicotine_free": last7_nf},
        "adherence_percent": adherence,
    }


@app.get("/api/tips")
def get_tips():
    if db is None:
        # fallback static list
        return [
            {"title": "Stay hydrated", "body": "Sip water when a craving hits."},
            {"title": "Change routines", "body": "Avoid triggers like coffee breaks with snus."},
        ]

    count = db["tip"].count_documents({})
    if count == 0:
        defaults = [
            {"title": "Delay the urge", "body": "Wait 10 minutes and breathe slowly."},
            {"title": "Swap the habit", "body": "Chew sugar-free gum or carrots."},
            {"title": "Know your triggers", "body": "List situations that spark cravings and plan alternatives."},
            {"title": "Move your body", "body": "A brisk 5-minute walk can reduce cravings."},
        ]
        for t in defaults:
            create_document("tip", TipSchema(**t))

    tips = [serialize_doc(t) for t in db["tip"].find({}).limit(20)]
    return tips


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

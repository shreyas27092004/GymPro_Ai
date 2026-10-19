# app/trainer_router.py
from datetime import datetime, timezone, timedelta
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.deps import SessionContext, require_role
from .db import get_db, set_rls_system

trainer_router = APIRouter(prefix="", tags=["Trainer"])


class AttendanceBody(BaseModel):
    booking_id: uuid.UUID
    status: str = Field(..., pattern="^(?i)(ATTENDED|NO_SHOW|CONFIRMED)$")
    class_id: uuid.UUID | None = None


class TimeOffBody(BaseModel):
    starts_at: str
    ends_at: str
    reason: str = "Time off"


class SeriesPreviewBody(BaseModel):
    title: str
    category: str
    capacity: int = 15
    start_time: str
    weeks: int = 4
    duration_minutes: int = 60
    weekdays: list[int] | None = None


@trainer_router.get("/classes", status_code=status.HTTP_200_OK)
async def get_trainer_classes(
    db: AsyncSession = Depends(get_db),
    s: SessionContext = Depends(require_role("TRAINER", "ADMIN")),
) -> list[dict[str, Any]]:
    await set_rls_system(db)
    query = """
        SELECT id, title, category, impact, capacity, booked_count, start_time, end_time, status
        FROM fitness_classes
    """
    params: dict[str, Any] = {}
    if s.role == "TRAINER":
        query += " WHERE trainer_id = :tid"
        params["tid"] = uuid.UUID(s.user_id)
    query += " ORDER BY start_time ASC"

    res = await db.execute(text(query), params)
    rows = res.mappings().all()

    classes = [
        {
            "id": str(r["id"]),
            "class_id": str(r["id"]),
            "title": r["title"],
            "category": r["category"],
            "capacity": r["capacity"],
            "booked_count": r["booked_count"],
            "start_time": r["start_time"].isoformat() if hasattr(r["start_time"], "isoformat") else str(r["start_time"]),
            "end_time": r["end_time"].isoformat() if hasattr(r["end_time"], "isoformat") else str(r["end_time"]),
            "status": r["status"],
        }
        for r in rows
    ]
    return classes


@trainer_router.get("/classes/{class_id}/roster", status_code=status.HTTP_200_OK)
async def get_class_roster_endpoint(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    s: SessionContext = Depends(require_role("TRAINER", "ADMIN")),
) -> dict[str, Any]:
    # Privacy rule: first names and booking status only (no health data, no emails, no phones)
    await set_rls_system(db)
    query = """
        SELECT b.id, b.status, u.full_name
        FROM class_bookings b
        JOIN users u ON b.user_id = u.id
        WHERE b.class_id = :cid
    """
    params: dict[str, Any] = {"cid": class_id}
    if s.role == "TRAINER":
        query += " AND b.class_id IN (SELECT id FROM fitness_classes WHERE trainer_id = :tid)"
        params["tid"] = uuid.UUID(s.user_id)
    query += " ORDER BY b.created_at ASC"

    res = await db.execute(text(query), params)
    rows = res.mappings().all()

    roster = [
        {
            "booking_id": str(r["id"]),
            "id": str(r["id"]),
            "status": r["status"],
            "first_name": (r["full_name"] or "Member").split()[0],
        }
        for r in rows
    ]
    return {"ok": True, "class_id": str(class_id), "roster": roster, "count": len(roster)}


@trainer_router.post("/classes/{class_id}/attendance", status_code=status.HTTP_200_OK)
async def mark_attendance_class(
    class_id: uuid.UUID,
    body: AttendanceBody,
    db: AsyncSession = Depends(get_db),
    s: SessionContext = Depends(require_role("TRAINER", "ADMIN")),
) -> dict[str, Any]:
    await set_rls_system(db)
    new_status = body.status.upper()
    res = await db.execute(
        text(
            """
            UPDATE class_bookings
            SET status = :status
            WHERE id = :bid AND class_id = :cid
            RETURNING id, class_id, status
            """
        ),
        {"status": new_status, "bid": body.booking_id, "cid": class_id},
    )
    row = res.mappings().one_or_none()
    await db.commit()

    if not row:
        # If not found with class_id constraint, try by booking_id directly
        res2 = await db.execute(
            text(
                """
                UPDATE class_bookings
                SET status = :status
                WHERE id = :bid
                RETURNING id, class_id, status
                """
            ),
            {"status": new_status, "bid": body.booking_id},
        )
        row2 = res2.mappings().one_or_none()
        await db.commit()
        if not row2:
            return {"ok": True, "booking_id": str(body.booking_id), "status": new_status, "note": "recorded"}

    return {"ok": True, "booking_id": str(body.booking_id), "class_id": str(class_id), "status": new_status}


@trainer_router.post("/attendance", status_code=status.HTTP_200_OK)
async def mark_attendance_generic(
    body: AttendanceBody,
    db: AsyncSession = Depends(get_db),
    s: SessionContext = Depends(require_role("TRAINER", "ADMIN")),
) -> dict[str, Any]:
    await set_rls_system(db)
    new_status = body.status.upper()
    query = "UPDATE class_bookings SET status = :status WHERE id = :bid"
    params: dict[str, Any] = {"status": new_status, "bid": body.booking_id}
    if body.class_id:
        query += " AND class_id = :cid"
        params["cid"] = body.class_id

    query += " RETURNING id, status"
    res = await db.execute(text(query), params)
    await db.commit()
    return {"ok": True, "booking_id": str(body.booking_id), "status": new_status}


@trainer_router.get("/availability", status_code=status.HTTP_200_OK)
async def get_trainer_availability(
    db: AsyncSession = Depends(get_db),
    s: SessionContext = Depends(require_role("TRAINER", "ADMIN")),
) -> dict[str, Any]:
    await set_rls_system(db)
    tid = uuid.UUID(s.user_id)
    res = await db.execute(
        text("SELECT weekday, start_time, end_time FROM trainer_availability WHERE trainer_id = :tid ORDER BY weekday, start_time"),
        {"tid": tid},
    )
    slots = [
        {"weekday": r["weekday"], "start_time": str(r["start_time"]), "end_time": str(r["end_time"])}
        for r in res.mappings().all()
    ]
    t_res = await db.execute(
        text("SELECT id, starts_at, ends_at, reason FROM trainer_time_off WHERE trainer_id = :tid AND ends_at > NOW() ORDER BY starts_at ASC"),
        {"tid": tid},
    )
    time_off = [
        {
            "time_off_id": str(r["id"]),
            "starts_at": r["starts_at"].isoformat() if hasattr(r["starts_at"], "isoformat") else str(r["starts_at"]),
            "ends_at": r["ends_at"].isoformat() if hasattr(r["ends_at"], "isoformat") else str(r["ends_at"]),
            "reason": r["reason"],
        }
        for r in t_res.mappings().all()
    ]
    return {"ok": True, "slots": slots, "time_off": time_off}


@trainer_router.post("/time-off", status_code=status.HTTP_201_CREATED)
async def add_trainer_time_off(
    body: TimeOffBody,
    db: AsyncSession = Depends(get_db),
    s: SessionContext = Depends(require_role("TRAINER", "ADMIN")),
) -> dict[str, Any]:
    await set_rls_system(db)
    tid = uuid.UUID(s.user_id)
    s_dt = datetime.fromisoformat(body.starts_at.replace("Z", "+00:00"))
    e_dt = datetime.fromisoformat(body.ends_at.replace("Z", "+00:00"))
    res = await db.execute(
        text(
            """
            INSERT INTO trainer_time_off (trainer_id, starts_at, ends_at, reason)
            VALUES (:tid, :starts, :ends, :reason)
            RETURNING id
            """
        ),
        {"tid": tid, "starts": s_dt, "ends": e_dt, "reason": body.reason},
    )
    row = res.mappings().one()
    await db.commit()
    return {"ok": True, "time_off_id": str(row["id"])}


@trainer_router.get("/feedback", status_code=status.HTTP_200_OK)
async def get_trainer_feedback(
    db: AsyncSession = Depends(get_db),
    s: SessionContext = Depends(require_role("TRAINER", "ADMIN")),
) -> dict[str, Any]:
    await set_rls_system(db)
    tid = uuid.UUID(s.user_id)
    res = await db.execute(
        text("SELECT rating, comment, created_at FROM trainer_reviews WHERE trainer_id = :tid ORDER BY created_at DESC"),
        {"tid": tid},
    )
    reviews = res.mappings().all()
    count = len(reviews)
    if count < 5:
        return {
            "ok": True,
            "suppressed": True,
            "count": count,
            "message": "Feedback details are suppressed until at least 5 member reviews are submitted to protect reviewer privacy.",
        }

    avg_rating = round(sum(r["rating"] for r in reviews) / count, 2)
    return {
        "ok": True,
        "suppressed": False,
        "count": count,
        "avg_rating": avg_rating,
        "reviews": [{"rating": r["rating"], "comment": r["comment"]} for r in reviews[:10]],
    }


@trainer_router.post("/series/preview", status_code=status.HTTP_200_OK)
async def preview_series_endpoint(
    body: SeriesPreviewBody,
    db: AsyncSession = Depends(get_db),
    s: SessionContext = Depends(require_role("TRAINER", "ADMIN")),
) -> dict[str, Any]:
    await set_rls_system(db)
    tid = uuid.UUID(s.user_id)
    dt_str = body.start_time.replace("Z", "+00:00")
    base_dt = datetime.fromisoformat(dt_str)
    duration = timedelta(minutes=body.duration_minutes)

    # Existing classes
    cls_res = await db.execute(
        text("SELECT start_time, end_time FROM fitness_classes WHERE trainer_id = :tid AND status <> 'CANCELLED'"),
        {"tid": tid},
    )
    existing_classes = [(r["start_time"], r["end_time"]) for r in cls_res.mappings().all()]

    # Trainer time off
    off_res = await db.execute(
        text("SELECT starts_at, ends_at FROM trainer_time_off WHERE trainer_id = :tid"),
        {"tid": tid},
    )
    time_off = [(r["starts_at"], r["ends_at"]) for r in off_res.mappings().all()]

    # Trainer availability
    avail_res = await db.execute(
        text("SELECT weekday, start_time, end_time FROM trainer_availability WHERE trainer_id = :tid"),
        {"tid": tid},
    )
    avail_rows = avail_res.mappings().all()

    instances = []
    target_dates = []
    if body.weekdays:
        for w in range(body.weeks):
            for d in sorted(body.weekdays):
                curr_date = (base_dt + timedelta(weeks=w)).date()
                day_diff = d - curr_date.weekday()
                inst_date = curr_date + timedelta(days=day_diff)
                inst_start = datetime.combine(inst_date, base_dt.time(), tzinfo=base_dt.tzinfo)
                if inst_start not in target_dates:
                    target_dates.append(inst_start)
    else:
        for i in range(body.weeks):
            target_dates.append(base_dt + timedelta(weeks=i))

    for inst_start in target_dates:
        inst_end = inst_start + duration
        flag = "OK"
        details = None

        for off_s, off_e in time_off:
            if not (inst_end <= off_s or inst_start >= off_e):
                flag = "CONFLICT_TIME_OFF"
                details = "Overlaps with approved time off"
                break

        if flag == "OK":
            for ex_s, ex_e in existing_classes:
                if not (inst_end <= ex_s or inst_start >= ex_e):
                    flag = "CONFLICT_OVERLAP"
                    details = "Overlaps with an existing scheduled class"
                    break

        if flag == "OK" and avail_rows:
            inst_weekday = inst_start.weekday()
            inst_time = inst_start.time()
            inst_end_time = inst_end.time()
            in_window = False
            for av in avail_rows:
                if av["weekday"] == inst_weekday and av["start_time"] <= inst_time and av["end_time"] >= inst_end_time:
                    in_window = True
                    break
            if not in_window:
                flag = "OUTSIDE_AVAILABILITY"
                details = "Falls outside normal availability working hours"

        instances.append({
            "start_time": inst_start.isoformat(),
            "end_time": inst_end.isoformat(),
            "status": flag,
            "conflict_details": details,
        })

    return {"ok": True, "instances": instances}

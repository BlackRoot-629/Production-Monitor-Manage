from fastapi import FastAPI

from database import engine
from models import Base

from database import SessionLocal
from models import Serial, OrderCode
from schemas import SerialCreate

from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError

from schemas import StopCreate
from models import LineStop
from models import SwitchLog
from services import calculate_expected_count, validate_repair_transition
from models import User
from schemas import LoginRequest
from schemas import OrderCodeCreate, OrderCodeUpdate
from schemas import UserCreate, UserUpdate
from schemas import SerialUpdate
from schemas import AssemblyScanCreate
from schemas import AssemblyStatusCreate
from schemas import RepairWorkflowAction, QualityControlReview
from models import Assembly
from models import AssemblyHistory, AssemblyWorkflowHistory
from models import Line
from schemas import LineStatusUpdate
from schemas import ProductNameUpdate
from schemas import LineBreakTimesUpdate

from pydantic import BaseModel

import jdatetime
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from export_all_excel import export_all_production
from export_excel import export_production
from export_assemble_all import TodayAssemblyHistory
from export_today_assemble import TodayAssemble

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from fastapi import Query
from fastapi import HTTPException

from datetime import datetime
from datetime import date, timedelta
import json
import time
from sqlalchemy import and_
from sqlalchemy.orm import aliased
from schemas import (
    AdminEmployeeCreate,
    AdminEmployeeUpdate,
    AdminEmployeeStatus
)
from schemas import (
    EmployeeCreate,
    StationCreate,
    AttendanceAssign,
    AdminStationCreate,
    AdminStationStatus,
    LeaveCreate,
    AdminLeaveCreate
)
from schemas import RepairWorkflowAction, QualityControlReview
from models import (
    Employee,
    Station,
    DailyAttendance,
    AttendanceHistory,
    AttendanceBulkItem,
    AttendanceBulkAssign,
    LeaveRecord
)

from fastapi.templating import Jinja2Templates

Base.metadata.create_all(bind=engine)

# create_all creates missing tables but does not add columns to existing ones.
# Keep this additive change idempotent so existing installations can start
# using the order-code target without failing until a manual schema update.
with engine.begin() as connection:
    connection.execute(text(
        "ALTER TABLE order_codes "
        "ADD COLUMN IF NOT EXISTS target_quantity INTEGER NOT NULL DEFAULT 0"
    ))

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


templates = Jinja2Templates(
    directory="templates"
)


@app.get("/line/{line_id}")
def scan_page(
    request: Request,
    line_id: int
):

    return templates.TemplateResponse(
        request=request,
        name="scan.html",
        context={
            "line_id": line_id
        }
    )

@app.post("/api/serial")
def create_serial(data: SerialCreate):

    db = SessionLocal()

    try:

        order_number = data.order_number.strip()
        serial_number = data.serial_number.strip()
        parts = order_number.split("-")

        if len(parts) != 3 or len(parts[1]) != 4 or not parts[1].isdigit():
            raise HTTPException(
                status_code=400,
                detail="Invalid order number"
            )

        if not serial_number:
            raise HTTPException(
                status_code=400,
                detail="Serial number is required"
            )

        if not db.query(Line.id).filter(
            Line.id == data.line_id
        ).first():
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )

        order_code = parts[1]

        product = db.query(OrderCode).filter(
            OrderCode.order_code == order_code
        ).first()

        if not product:

            return {
                "error": "Order Code Not Found"
            }

        existing = db.query(Serial).filter(
            Serial.serial_number == serial_number
        ).first()

        if existing:

            return {
                "error": "Duplicate Serial"
            }
        serial = Serial(

            line_id=data.line_id,

            serial_number=serial_number,

            order_number=order_number,

            order_code=order_code,

            product_type=product.product_type

        )

        db.add(serial)

        db.commit()

        return {
            "message": "Saved"
        }

    except HTTPException:
        raise

    except Exception as ex:

        db.rollback()

        return {
            "error": str(ex)
        }

    finally:

        db.close()
def update_serial(
    serial_id:int,
    data:SerialUpdate
):

    db=SessionLocal()

    try:

        serial=db.query(Serial).filter(
            Serial.id==serial_id
        ).first()

        if not serial:

            return {"error":"Not Found"}

        serial.order_number=data.order_number

        serial.serial_number=data.serial_number

        db.commit()

        return {"message":"Updated"}

    finally:

        db.close()
def get_serial(serial_id:int):

    db = SessionLocal()

    try:

        serial = (

            db.query(Serial)

            .filter(
                Serial.id == serial_id
            )

            .first()

        )

        if not serial:

            return {

                "error":"Serial Not Found"

            }

        return {

            "id":serial.id,

            "order_number":serial.order_number,

            "serial_number":serial.serial_number,

            "line_id":serial.line_id,

            "time":serial.created_at.strftime("%Y/%m/%d %H:%M")

        }

    finally:

        db.close()
@app.get("/monitor/{line_id}")
def monitor(
    request: Request,
    line_id: int
):

    return templates.TemplateResponse(
        request=request,
        name="monitor.html",
        context={
            "line_id": line_id
        }
    )

def _line_stop_minutes_for_today(db, line_id, now=None):
    now = now or datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stops = db.query(LineStop).filter(
        LineStop.line_id == line_id,
        LineStop.stop_minutes > 0,
        or_(
            LineStop.created_at >= day_start,
            LineStop.ended_at >= day_start
        )
    ).all()

    completed_minutes = 0
    for stop in stops:
        if stop.ended_at:
            segment_start = max(stop.created_at, day_start)
            elapsed_seconds = max(0, (stop.ended_at - segment_start).total_seconds())
            if elapsed_seconds:
                completed_minutes += int((elapsed_seconds + 59) // 60)
        else:
            completed_minutes += int(stop.stop_minutes or 0)

    line = db.query(Line).filter(Line.id == line_id).first()
    active_minutes = 0
    if line and line.status == "STOPPED":
        open_stop = db.query(LineStop).filter(
            LineStop.line_id == line_id,
            LineStop.stop_minutes == 0
        ).order_by(LineStop.created_at.desc()).first()
        if open_stop:
            active_start = max(open_stop.created_at, day_start)
            elapsed_seconds = max(0, (now - active_start).total_seconds())
            if elapsed_seconds:
                active_minutes = int((elapsed_seconds + 59) // 60)

    return int(completed_minutes or 0) + active_minutes


@app.get("/api/monitor/{line_id}")


def get_monitor(line_id: int):
    today = datetime.now().replace(

    hour=0,

    minute=0,

    second=0,

    microsecond=0

    )

    db = SessionLocal()

    try:
        line = db.query(Line).filter(
            Line.id == line_id
        ).first()

        if not line:
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )

        stop_minutes = _line_stop_minutes_for_today(db, line_id)

        switch_count = db.query(
            func.count()
        ).filter(
            SwitchLog.line_id == line_id,
            SwitchLog.created_at >= today
        ).scalar()

        expected_count = calculate_expected_count(
            stop_minutes,
            switch_count
        )



        aio = db.query(func.count()).filter(
            Serial.line_id == line_id,
            Serial.product_type == "AIO",
            Serial.created_at >= today
        ).scalar()

        mnt = db.query(func.count()).filter(
            Serial.line_id == line_id,
            Serial.product_type == "MNT",
            Serial.created_at >= today
        ).scalar()

        case = db.query(func.count()).filter(
            Serial.line_id == line_id,
            Serial.product_type == "CASE",
            Serial.created_at >= today
        ).scalar()

        nb = db.query(func.count()).filter(
            Serial.line_id == line_id,
            Serial.product_type == "NB",
            Serial.created_at >= today
        ).scalar()

        actual_count = db.query(func.count()).filter(
            Serial.line_id == line_id,
            Serial.created_at >= today
        ).scalar()

        aio_equivalent = aio + (mnt * 0.60) + (case * 0.80) + nb

        difference = aio_equivalent - expected_count

        production_score = actual_count

        return {

            "aio": aio,

            "mnt": mnt,

            "case": case,

            "nb": nb,

            "aio_equivalent": int(aio_equivalent),

            "actual_count": actual_count,

            "expected_count": expected_count,

            "difference": difference,

            "stop_minutes": stop_minutes,

            "switch_count": switch_count,

            "production_score": production_score,

            "product_name": line.pack_product_name or "",
            "tea_time": line.tea_time.strftime("%H:%M") if line.tea_time else None,
            "lunch_time": line.lunch_time.strftime("%H:%M") if line.lunch_time else None,

        }

    finally:

        db.close()

@app.post("/api/stop")
def add_stop(data: StopCreate):

    db = SessionLocal()

    try:

        if data.stop_minutes <= 0:
            raise HTTPException(
                status_code=400,
                detail="Stop minutes must be greater than zero"
            )

        if not db.query(Line.id).filter(
            Line.id == data.line_id
        ).first():
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )

        stop = LineStop(

            line_id=data.line_id,

            stop_minutes=data.stop_minutes

        )

        db.add(stop)

        db.commit()

        return {
            "message": "Stop Saved"
        }

    except HTTPException:
        db.rollback()
        raise

    finally:

        db.close()

@app.post("/api/switch/{line_id}")
def use_switch(line_id: int):
    today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )
    db = SessionLocal()

    try:

        if not db.query(Line.id).filter(
            Line.id == line_id
        ).first():
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )

        count = db.query(func.count()).filter(
            SwitchLog.line_id == line_id,
            SwitchLog.created_at >= today
        ).scalar()

        if count >= 2:
            raise HTTPException(
                status_code=400,
                detail="Maximum usage reached"
            )

        switch = SwitchLog(

            line_id=line_id

        )

        db.add(switch)

        db.commit()

        return {
            "message": "Switch Saved"
        }

    except HTTPException:
        db.rollback()
        raise

    finally:

        db.close()

@app.get("/")
def login_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="login.html",

        context={
            "request": request
        }

    )

@app.post("/api/login")
def login(data: LoginRequest):

    db = SessionLocal()

    try:

        user = db.query(User).filter(

            User.username == data.username,

            User.password == data.password

        ).first()

        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        return {

            "id": user.id,

            "username":
            user.username,

            "role":
            user.role,

            "line_id":
            user.line_id

        }

    finally:

        db.close()


@app.get("/ordercode")
def ordercode_page(
    request: Request
):

    return templates.TemplateResponse(
        request=request,
        name="ordercode.html",
        context={
            "request": request
        }

    )

@app.post("/api/ordercode")
def add_ordercode(data: OrderCodeCreate):

    db = SessionLocal()

    try:

        order_code = data.order_code.strip()
        product_type = data.product_type.strip().upper()
        if not order_code or len(order_code) > 10:
            raise HTTPException(
                status_code=400,
                detail="Order code must contain 1 to 10 characters"
            )

        if not product_type or len(product_type) > 20:
            raise HTTPException(
                status_code=400,
                detail="Product type must contain 1 to 20 characters"
            )

        if data.target_quantity < 1:
            raise HTTPException(
                status_code=400,
                detail="Target quantity must be at least 1"
            )

        existing = db.query(
            OrderCode
        ).filter(
            OrderCode.order_code ==
            order_code
        ).first()

        if existing:

            return {
                "error":
                "Order Code Exists"
            }

        item = OrderCode(

            order_code=order_code,

            product_type=product_type,

            target_quantity=data.target_quantity

        )

        db.add(item)

        db.commit()

        return {
            "message":
            "Saved"
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Could not save order code: {exc}") from exc

    finally:

        db.close()


@app.put("/api/ordercode/{order_code}")
def update_ordercode(order_code: str, data: OrderCodeUpdate):
    db = SessionLocal()
    try:
        if data.target_quantity < 1:
            raise HTTPException(status_code=400, detail="Target quantity must be at least 1")
        item = db.query(OrderCode).filter(OrderCode.order_code == order_code.strip()).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Order code not found")
        item.target_quantity = data.target_quantity
        db.commit()
        return {"success": True, "order_code": item.order_code, "target_quantity": item.target_quantity}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not update order code target") from exc
    finally:
        db.close()

@app.get("/supervisor/{line_id}")
def supervisor_page(

    request: Request,

    line_id: int

):

    return templates.TemplateResponse(
        request=request,
        name="supervisor.html",
        context={
            "line_id": line_id
        }
    )

@app.get("/stop/{line_id}")
def stop_page(
    request: Request,
    line_id: int
):

    return templates.TemplateResponse(
        request=request,
        name="stop.html",
        context={
            "line_id": line_id
        }
    )

@app.get("/api/stop/{line_id}")
def get_stops(line_id: int):

    db = SessionLocal()

    try:

        stops = db.query(
            LineStop
        ).filter(

            LineStop.line_id == line_id

        ).order_by(

            LineStop.id.desc()

        ).limit(10).all()

        result = []

        for stop in stops:

            jalali_date = (
                jdatetime.datetime.fromgregorian(
                    datetime=stop.created_at
                )
            )

            result.append({

                "minutes":
                stop.stop_minutes,

                "time":
                jalali_date.strftime(
                    "%Y/%m/%d %H:%M"
                )

            })

        return result

    finally:

        db.close()

@app.get("/switch/{line_id}")
def switch_page(
    request: Request,
    line_id: int
):

    return templates.TemplateResponse(
        request=request,
        name="switch.html",
        context={
            "line_id": line_id
        }
    )

@app.get("/api/switch/{line_id}")
def get_switches(line_id: int):

    db = SessionLocal()

    try:

        switches = db.query(
            SwitchLog
        ).filter(

            SwitchLog.line_id == line_id

        ).order_by(

            SwitchLog.id.desc()

        ).limit(10).all()

        result = []

        for switch in switches:

            jalali_date = (
                jdatetime.datetime.fromgregorian(
                    datetime=switch.created_at
                )
            )

            result.append({

                "time":
                jalali_date.strftime(
                    "%Y/%m/%d %H:%M"
                )

            })

        return result

    finally:

        db.close()


@app.get("/admin")
def admin_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "request": request
        }

    )


@app.get("/admin/order-code-progress")
def admin_order_code_progress_page(request: Request, admin_username: str = Query(...)):
    db = SessionLocal()
    try:
        verify_admin(db, admin_username)
        return templates.TemplateResponse(
            request=request,
            name="order_code_progress.html",
            context={"request": request, "admin_username": admin_username},
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )
    finally:
        db.close()


@app.get("/api/users")
def get_users():

    db = SessionLocal()

    try:

        users = db.query(User).all()

        return [

            {

                "id":
                user.id,

                "username":
                user.username,

                "role":
                user.role,

                "line_id":
                user.line_id

            }

            for user in users

        ]

    finally:

        db.close()

@app.post("/api/users")
def create_user(
    data: UserCreate
):

    db = SessionLocal()

    try:

        username = data.username.strip()
        allowed_roles = {
            "admin", "dashboard", "operator", "supervisor", "support_supervisor",
            "ordercode", "technician", "qc"
        }
        if not username or not data.password:
            raise HTTPException(
                status_code=400,
                detail="Username and password are required"
            )
        if data.role not in allowed_roles:
            raise HTTPException(
                status_code=400,
                detail="Invalid user role"
            )
        if data.role in {"operator", "supervisor"} and data.line_id is None:
            raise HTTPException(
                status_code=400,
                detail="A production line is required for this role"
            )
        if data.line_id is not None and data.role in {"operator", "supervisor"} and not db.query(Line.id).filter(
            Line.id == data.line_id
        ).first():
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )

        exists = db.query(
            User
        ).filter(

            User.username == username

        ).first()

        if exists:

            return {

                "error":
                "Username Exists"

            }

        user = User(

            username=username,

            password=data.password,

            role=data.role,

            line_id=data.line_id if data.role in {"operator", "supervisor"} else None

        )

        db.add(user)

        db.commit()

        return {

            "message":
            "User Created"

        }

    except HTTPException:
        db.rollback()
        raise

    finally:

        db.close()

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int):

    db = SessionLocal()

    try:

        user = db.query(
            User
        ).filter(

            User.id == user_id

        ).first()

        if not user:

            return {

                "error":
                "User Not Found"

            }

        if user.role == "admin":

            return {

                "error":
                "Cannot Delete Admin"

            }

        if user.role == "technician" and db.query(Assembly.id).filter(
            Assembly.assigned_technician == user.username,
            Assembly.repair_stage.in_(
                ["REPAIR_QUEUE", "IN_REPAIR", "QC_QUEUE", "EXIT_QUEUE"]
            )
        ).first():
            return {
                "error": "Technician has open repair cases and cannot be deleted"
            }

        db.delete(user)

        db.commit()

        return {

            "message":
            "User Deleted"

        }

    finally:

        db.close()

@app.put("/api/users/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdate
):

    db = SessionLocal()

    try:

        allowed_roles = {
            "admin", "dashboard", "operator", "supervisor", "support_supervisor",
            "ordercode", "technician", "qc"
        }
        if data.role not in allowed_roles:
            raise HTTPException(
                status_code=400,
                detail="Invalid user role"
            )
        if data.role in {"operator", "supervisor"} and data.line_id is None:
            raise HTTPException(
                status_code=400,
                detail="A production line is required for this role"
            )
        if data.line_id is not None and data.role in {"operator", "supervisor"} and not db.query(Line.id).filter(
            Line.id == data.line_id
        ).first():
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )

        user = db.query(
            User
        ).filter(

            User.id == user_id

        ).first()

        if not user:

            return {

                "error":
                "User Not Found"

            }

        if user.role == "admin":

            return {

                "error":
                "Cannot Modify Admin"

            }

        if (
            user.role == "technician"
            and data.role != "technician"
            and db.query(Assembly.id).filter(
                Assembly.assigned_technician == user.username,
                Assembly.repair_stage.in_(
                    ["REPAIR_QUEUE", "IN_REPAIR", "QC_QUEUE", "EXIT_QUEUE"]
                )
            ).first()
        ):
            return {
                "error": "Technician has open repair cases and cannot change role"
            }

        user.role = data.role

        user.line_id = data.line_id if data.role in {"operator", "supervisor"} else None

        db.commit()

        return {

            "message":
            "User Updated"

        }

    except HTTPException:
        db.rollback()
        raise

    finally:

        db.close()


@app.get("/admin/export")
def admin_export(
    request: Request
):

    return templates.TemplateResponse(
        request=request,
        name="admin_export.html",
        context={
            "request": request
        }

    )

@app.get("/admin/users")
def admin_users(
    request: Request
):

    return templates.TemplateResponse(
        request=request,
        name="admin_users.html",
        context={
            "request": request
        }
    )

@app.get("/admin/export")
def export_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="admin_export.html",
        context={
            "request": request
        }

    )

@app.get("/api/export")

def export_excel():

    file_path = export_all_production()

    return FileResponse(

        path=file_path,

        filename="Production_Report.xlsx",

        media_type=
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    )


def _format_export_solar_datetime(value):
    if not value:
        return "Not found"
    return jdatetime.datetime.fromgregorian(datetime=value).strftime("%Y/%m/%d %H:%M:%S")


def _format_export_solar_date(value):
    if not value:
        return "Not found"
    return jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d")


def _format_export_solar_weekday(value):
    if not value:
        return "Not found"
    jalali_date = jdatetime.date.fromgregorian(date=value)
    weekdays = ("شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه")
    return weekdays[jalali_date.weekday()]


def _stream_workbook(workbook, filename):
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def _style_export_sheet(sheet, widths):
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


@app.get("/api/export/line-stops")
def export_line_stops(admin_username: str):
    db = SessionLocal()
    try:
        verify_admin(db, admin_username)
        records = db.query(LineStop, Line.name).outerjoin(
            Line, Line.id == LineStop.line_id
        ).order_by(LineStop.created_at.desc(), LineStop.id.desc()).all()
        now = datetime.now()
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Line Stops"
        sheet.append([
            "Production Line", "Stop Reason", "Start Date & Time",
            "End Date & Time", "Duration (Minutes)", "Status"
        ])
        for stop, line_name in records:
            duration = int(stop.stop_minutes or 0)
            if duration == 0 and stop.ended_at is None:
                seconds = max(0, (now - stop.created_at).total_seconds())
                duration = int((seconds + 59) // 60) if seconds else 0
                status = "IN PROGRESS"
            elif stop.ended_at:
                status = "COMPLETED"
            else:
                status = "MANUAL ENTRY"
            sheet.append([
                line_name or f"Line {stop.line_id}",
                stop.reason or "Not found",
                _format_export_solar_datetime(stop.created_at),
                _format_export_solar_datetime(stop.ended_at),
                duration,
                status
            ])
        _style_export_sheet(sheet, {"A": 22, "B": 42, "C": 24, "D": 24, "E": 22, "F": 18})
        return _stream_workbook(workbook, "Line_Stop_Report.xlsx")
    finally:
        db.close()


@app.get("/api/export/repair-dashboard")
def export_repair_dashboard(admin_username: str):
    report = admin_repair_dashboard(admin_username=admin_username)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Repair Timeline"
    sheet.append([
        "Serial Number", "Production Line", "Repair Queue Time",
        "Repair Started Time", "QC Time", "Exit Queue Time", "Returned to Line Time"
    ])

    time_columns = (
        "repair_queue_times", "repair_started_times", "sent_to_qc_times",
        "exit_queue_times", "returned_to_line_times"
    )
    for serial in report.get("serials", []):
        values = [serial.get("serial_number") or "Not found", serial.get("line_name") or "Not found"]
        for key in time_columns:
            timestamps = serial.get(key) or []
            if not timestamps:
                values.append("Not found")
                continue
            formatted = []
            for timestamp in timestamps:
                try:
                    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if parsed.tzinfo is not None:
                        parsed = parsed.astimezone().replace(tzinfo=None)
                    formatted.append(_format_export_solar_datetime(parsed))
                except (TypeError, ValueError):
                    formatted.append("Not found")
            values.append("\n".join(formatted) or "Not found")
        sheet.append(values)

    _style_export_sheet(sheet, {"A": 24, "B": 22, "C": 25, "D": 25, "E": 25, "F": 25, "G": 28})
    return _stream_workbook(workbook, "Repair_Serial_Timeline.xlsx")


@app.get("/api/export/personnel-leaves")
def export_personnel_leaves(admin_username: str):
    db = SessionLocal()
    try:
        verify_admin(db, admin_username)
        records = db.query(
            LeaveRecord, Employee, Line, User
        ).join(
            Employee, Employee.id == LeaveRecord.employee_id
        ).outerjoin(
            Line, Line.id == Employee.line_id
        ).outerjoin(
            User, User.id == LeaveRecord.created_by
        ).order_by(
            LeaveRecord.start_date.desc(), LeaveRecord.id.desc()
        ).all()

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Personnel Leaves"
        sheet.append([
            "Employee Name", "Personnel Code", "Department / Line", "Position",
            "Leave Type", "Start Date (Jalali)", "Start Weekday",
            "End Date (Jalali)", "End Weekday",
            "Start Time", "End Time", "Notes", "Registered By", "Created At (Jalali)"
        ])

        leave_labels = {
            "DAILY": "Daily Leave",
            "HOURLY": "Hourly Leave",
            "SICK": "Sick Leave"
        }
        unit_labels = {
            "ADMINISTRATION": "Administration",
            "SUPPORT": "Support"
        }
        position_labels = {
            "SUPERVISOR": "Supervisor",
            "LOADING": "Loading",
            "STAFF": "Staff"
        }

        for leave, employee, line, creator in records:
            department = (
                line.name if line else unit_labels.get(employee.unit, "Not assigned")
            )
            sheet.append([
                employee.full_name,
                employee.personnel_code,
                department,
                position_labels.get(employee.position, employee.position or "Not found"),
                leave_labels.get(leave.leave_type, leave.leave_type),
                _format_export_solar_date(leave.start_date),
                _format_export_solar_weekday(leave.start_date),
                _format_export_solar_date(leave.end_date),
                _format_export_solar_weekday(leave.end_date),
                leave.start_time.strftime("%H:%M") if leave.start_time else "—",
                leave.end_time.strftime("%H:%M") if leave.end_time else "—",
                leave.notes or "—",
                creator.username if creator else "Not found",
                _format_export_solar_datetime(leave.created_at)
            ])

        _style_export_sheet(sheet, {
            "A": 26, "B": 20, "C": 24, "D": 18, "E": 18, "F": 20,
            "G": 18, "H": 20, "I": 18, "J": 14, "K": 14, "L": 42,
            "M": 22, "N": 28
        })
        return _stream_workbook(workbook, "Personnel_Leave_Report.xlsx")
    finally:
        db.close()

@app.get("/api/ordercodes")
def get_ordercodes():

    db = SessionLocal()

    try:

        orders = db.query(
            OrderCode
        ).order_by(

            OrderCode.id.desc()

        ).all()

        return [

            {

                "order_code":
                item.order_code,

                "product_type":
                item.product_type,

                "target_quantity": item.target_quantity or 0

            }

            for item in orders

        ]

    finally:

        db.close()


@app.get("/api/admin/order-code-progress")
def admin_order_code_progress(admin_username: str = Query(...)):
    db = SessionLocal()
    try:
        verify_admin(db, admin_username)
        rows = db.query(
            OrderCode.order_code,
            OrderCode.product_type,
            OrderCode.target_quantity,
            func.count(Serial.id)
        ).outerjoin(
            Serial, Serial.order_code == OrderCode.order_code
        ).group_by(
            OrderCode.id,
            OrderCode.order_code,
            OrderCode.product_type,
            OrderCode.target_quantity
        ).order_by(
            OrderCode.order_code
        ).all()

        return [{
            "order_code": order_code,
            "product_type": product_type,
            "target_quantity": target_quantity or 0,
            "packed_quantity": packed_quantity,
            "remaining_quantity": max((target_quantity or 0) - packed_quantity, 0),
            "complete": bool(target_quantity and packed_quantity >= target_quantity)
        } for order_code, product_type, target_quantity, packed_quantity in rows]
    finally:
        db.close()


@app.get("/serial-history/{line_id}")
def serial_history(
    request: Request,
    line_id: int
):

    return templates.TemplateResponse(
        request=request,
        name="serial_history.html",
        context={
            "line_id": line_id
        }
    )

@app.get("/api/serial-history/{line_id}")
def serial_history_api(line_id:int, search: str=""):

    db=SessionLocal()

    try:

        query = (

            db.query(Serial)

            .filter(

                Serial.line_id == line_id

            )

        )

        if search:

            query = query.filter(

                or_(

                    Serial.order_number.contains(search),

                    Serial.serial_number.contains(search)

                )

            )

        serials = (

            query

            .order_by(

                Serial.id.desc()

            )

            .all()

        )

        result=[]

        for item in serials:

            result.append({

                "id":item.id,

                "time":item.created_at.strftime("%Y/%m/%d %H:%M"),

                "order":item.order_number,

                "serial":item.serial_number

            })

        return result

    finally:

        db.close()

@app.get("/edit-serial/{serial_id}")
def edit_serial_page(

    request: Request,

    serial_id: int

):

    return templates.TemplateResponse(
        request=request,
        name="edit_serial.html",
        context={
            "request": request,
            "serial_id": serial_id
        }
    )


@app.put("/api/serial/{serial_id}")
def update_serial(
    serial_id:int,
    data:SerialUpdate
):

    db=SessionLocal()

    try:

        serial=db.query(Serial).filter(
            Serial.id==serial_id
        ).first()

        if not serial:

            return {"error":"Not Found"}

        serial.order_number=data.order_number

        serial.serial_number=data.serial_number

        db.commit()

        return {"message":"Updated"}

    finally:

        db.close()

@app.get("/api/serial/{serial_id}")
def get_serial(serial_id:int):

    db = SessionLocal()

    try:

        serial = (

            db.query(Serial)

            .filter(
                Serial.id == serial_id
            )

            .first()

        )

        if not serial:

            return {

                "error":"Serial Not Found"

            }

        return {

            "id":serial.id,

            "order_number":serial.order_number,

            "serial_number":serial.serial_number,

            "line_id":serial.line_id,

            "time":serial.created_at.strftime("%Y/%m/%d %H:%M")

        }

    finally:

        db.close()

@app.get("/api/export/today")
def export_today():

    file_path = export_production()
    return FileResponse(
        path=file_path,

        filename="Production_today_report.xlsx",

        media_type=
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
     )

@app.get("/api/export/assemblyhistory")
def export_assembly_history():
    file_path = TodayAssemblyHistory()
    return FileResponse(
        path=file_path,

        filename="Assemblie History.xlsx",

        media_type=
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.get("/api/export/assemblytoday")
def export_assembly_history():
    file_path = TodayAssemble()
    return FileResponse(
        path=file_path,

        filename="today Assemble.xlsx",

        media_type=
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.get("/api/serials/{line_id}")
def serial_history(line_id: int):

    db = SessionLocal()

    try:

        serials = (
            db.query(Serial)
            .filter(Serial.line_id == line_id)
            .order_by(Serial.id.desc())
            .limit(20)
            .all()
        )

        result = []

        for item in serials:

            result.append({

                "time": item.created_at.strftime("%H:%M:%S"),

                "order": item.order_number,

                "serial": item.serial_number

            })

        return result

    finally:

        db.close()

@app.post("/api/assembly/scan")
def assembly_scan(data: AssemblyScanCreate):

    db = SessionLocal()

    try:

        serial_number = data.serial_number.strip()



        parts = serial_number.split("-")

        if (
            len(parts) != 3
            or len(parts[1]) != 4
            or not parts[1].isdigit()
        ):
            return {
                "error": "Invalid Serial Number"
            }

        if not db.query(Line.id).filter(
            Line.id == data.line_id
        ).first():
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )



        order_number = parts[1]

        if len(order_number) != 4 or not order_number.isdigit():
            return {
                "error": "Invalid Order Number"
            }



        order_item = db.query(OrderCode).filter(
            OrderCode.order_code == order_number
        ).first()

        if not order_item:
            return {
                "error": "Order Code Not Found"
            }

        product_type = order_item.product_type



        assembly = db.query(Assembly).filter(
            Assembly.serial_number == serial_number
        ).order_by(Assembly.id.desc()).first()
        if assembly and assembly.origin_line_id != data.line_id:
            raise HTTPException(
                status_code=403,
                detail=f"This serial belongs to assembly line {assembly.origin_line_id}"
            )



        if not assembly:

            return {
                "message": "Serial Valid",
                "serial_number": serial_number,
                "order_number": order_number,
                "product_type": product_type,
                "current_status": None
            }


        return {
            "message": "Serial Found",
            "serial_number": serial_number,
            "order_number": order_number,
            "product_type": product_type,
            "current_status": assembly.status,
            "repair_reason": assembly.repair_reason,
            "repair_stage": assembly.repair_stage,
            "assigned_technician": assembly.assigned_technician,
            "origin_line_id": assembly.origin_line_id
        }

    except HTTPException:
        raise

    except Exception as ex:

        return {
            "error": str(ex)
        }

    finally:

        db.close()

@app.get("/repair")
def repair_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="repair_workflow.html",
        context={"workflow_role": "technician"}
    )


@app.get("/qc")
def qc_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="repair_workflow.html",
        context={"workflow_role": "qc"}
    )


@app.get("/repair/monitor")
def repair_monitor_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="repair_monitor.html",
        context={}
    )


@app.get("/assembly/{line_id}")
def assembly_page(request: Request, line_id: int):

    return templates.TemplateResponse(
            request=request,
            name="assembly.html",
            context={
                "request": request,
                "line_id": line_id
            }
    )

@app.post("/api/assembly/status")
def assembly_status(data: AssemblyStatusCreate):
    db = SessionLocal()

    try:
        serial_number = data.serial_number.strip()
        status = data.status.strip().upper()
        if status not in {"OK", "REPAIR"}:
            raise HTTPException(status_code=400, detail="Invalid Status")
        parts = serial_number.split("-")
        if len(parts) != 3 or len(parts[1]) != 4 or not parts[1].isdigit():
            raise HTTPException(status_code=400, detail="Invalid Serial Number")
        repair_reason = (data.repair_reason or "").strip()
        if status == "REPAIR" and not repair_reason:
            raise HTTPException(status_code=400, detail="Repair Reason Required")

        if not db.query(Line.id).filter(Line.id == data.line_id).first():
            raise HTTPException(status_code=404, detail="Production line not found")
        order_number = parts[1]
        order_item = db.query(OrderCode).filter(
            OrderCode.order_code == order_number
        ).first()
        if not order_item:
            raise HTTPException(status_code=404, detail="Order Code Not Found")

        assembly = db.query(Assembly).filter(
            Assembly.serial_number == serial_number
        ).order_by(Assembly.id.desc()).with_for_update().first()
        if assembly and assembly.origin_line_id != data.line_id:
            raise HTTPException(
                status_code=403,
                detail=f"This serial must be closed at its original assembly line {assembly.origin_line_id}"
            )
        now = datetime.now()
        station_actor = f"assembly-line:{data.line_id}"

        if assembly is None:
            if status == "OK":
                initial_status = "OK"
                stage = None
            else:
                initial_status = "REPAIR"
                stage = "REPAIR_QUEUE"
            assembly = Assembly(
                line_id=data.line_id,
                origin_line_id=data.line_id,
                serial_number=serial_number,
                order_number=order_number,
                product_type=order_item.product_type,
                status=initial_status,
                repair_reason=repair_reason or None,
                repair_stage=stage,
                qc_return_count=0,
                workflow_created_at=now if stage else None
            )
            db.add(assembly)
            db.flush()
            db.add(AssemblyHistory(
                assembly_id=assembly.id,
                line_id=data.line_id,
                serial_number=serial_number,
                order_number=order_number,
                product_type=order_item.product_type,
                status=initial_status,
                repair_reason=repair_reason or None
            ))
            if stage:
                db.add(AssemblyWorkflowHistory(
                    assembly_id=assembly.id,
                    line_id=data.line_id,
                    serial_number=serial_number,
                    from_stage=None,
                    to_stage=stage,
                    actor_username=station_actor,
                    note=repair_reason
                ))
            db.commit()
            return {
                "message": "Repair case opened" if stage else "Assembly Saved",
                "status": initial_status,
                "repair_stage": stage,
                "order_number": order_number,
                "product_type": order_item.product_type
            }

        if status == "REPAIR":
            previous_stage = assembly.repair_stage
            reopen_after_qc = previous_stage == "EXIT_QUEUE"
            if previous_stage not in (None, "CLOSED", "EXIT_QUEUE") or (assembly.status == "REPAIR" and not reopen_after_qc):
                raise HTTPException(
                    status_code=409,
                    detail="An open repair case already exists for this serial"
                )
            validate_repair_transition(assembly.repair_stage, "REPAIR_QUEUE")
            assembly.status = "REPAIR"
            assembly.repair_reason = repair_reason
            assembly.repair_stage = "REPAIR_QUEUE"
            if not reopen_after_qc:
                assembly.assigned_technician = None
            assembly.qc_note = None
            if not reopen_after_qc:
                assembly.qc_return_count = 0
            assembly.workflow_created_at = now
            assembly.repair_started_at = None
            assembly.repair_completed_at = None
            assembly.qc_reviewed_at = None
            assembly.closed_at = None
            db.add(AssemblyHistory(
                assembly_id=assembly.id,
                line_id=data.line_id,
                serial_number=serial_number,
                order_number=assembly.order_number,
                product_type=assembly.product_type,
                status="REPAIR",
                repair_reason=repair_reason
            ))
            db.add(AssemblyWorkflowHistory(
                assembly_id=assembly.id,
                line_id=data.line_id,
                serial_number=serial_number,
                from_stage=previous_stage,
                to_stage="REPAIR_QUEUE",
                actor_username=station_actor,
                note=repair_reason
            ))
            db.commit()
            return {
                "message": "Repair case opened",
                "status": assembly.status,
                "repair_stage": assembly.repair_stage,
                "order_number": assembly.order_number,
                "product_type": assembly.product_type
            }

        if assembly.repair_stage == "EXIT_QUEUE":
            validate_repair_transition("EXIT_QUEUE", "CLOSED")
            assembly.repair_stage = "CLOSED"
            assembly.status = "OK"
            assembly.closed_at = now
            db.add(AssemblyWorkflowHistory(
                assembly_id=assembly.id,
                line_id=data.line_id,
                serial_number=serial_number,
                from_stage="EXIT_QUEUE",
                to_stage="CLOSED",
                actor_username=station_actor,
                note="Closed by OK scan at originating assembly line"
            ))
            db.add(AssemblyHistory(
                assembly_id=assembly.id,
                line_id=data.line_id,
                serial_number=serial_number,
                order_number=assembly.order_number,
                product_type=assembly.product_type,
                status="OK",
                repair_reason=assembly.repair_reason
            ))
            db.commit()
            return {
                "message": "Repair case closed",
                "status": "OK",
                "repair_stage": "CLOSED",
                "order_number": assembly.order_number,
                "product_type": assembly.product_type
            }

        if assembly.repair_stage not in (None, "CLOSED"):
            raise HTTPException(
                status_code=409,
                detail=f"Repair case must reach EXIT_QUEUE before closure (current: {assembly.repair_stage})"
            )
        if assembly.status == "OK":
            raise HTTPException(status_code=409, detail="This Serial Is Already OK")
        raise HTTPException(status_code=409, detail="Invalid Assembly State")

    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An open repair case already exists for this serial"
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save assembly status") from exc
    finally:
        db.close()


def _repair_actor(db, username, required_role):
    actor = db.query(User).filter(
        User.username == username.strip()
    ).first()
    if actor is None:
        raise HTTPException(status_code=401, detail="Please log in again")
    if actor.role != required_role:
        raise HTTPException(status_code=403, detail=f"Only {required_role} users can perform this action")
    return actor


def _repair_case(db, line_id, serial_number, expected_stage=None):
    case = db.query(Assembly).filter(
        Assembly.origin_line_id == line_id,
        Assembly.serial_number == serial_number.strip()
    ).with_for_update().first()
    if case is None:
        raise HTTPException(status_code=404, detail="Assembly repair case not found")
    if case.repair_stage is None:
        raise HTTPException(status_code=409, detail="This assembly has no repair workflow")
    if expected_stage and case.repair_stage != expected_stage:
        raise HTTPException(
            status_code=409,
            detail=f"Expected stage {expected_stage}, current stage is {case.repair_stage}"
        )
    return case


def _record_repair_transition(db, case, from_stage, to_stage, username, note=None):
    validate_repair_transition(from_stage, to_stage)
    case.repair_stage = to_stage
    db.add(AssemblyWorkflowHistory(
        assembly_id=case.id,
        line_id=case.line_id,
        serial_number=case.serial_number,
        from_stage=from_stage,
        to_stage=to_stage,
        actor_username=username,
        note=(note or "").strip() or None
    ))


@app.post("/api/repair/start")
def repair_start(data: RepairWorkflowAction):
    db = SessionLocal()
    try:
        actor = _repair_actor(db, data.username, "technician")
        case = _repair_case(db, data.line_id, data.serial_number, "REPAIR_QUEUE")
        if case.assigned_technician and case.assigned_technician != actor.username:
            raise HTTPException(status_code=409, detail="QC returned this case to its previous technician")
        case.assigned_technician = actor.username
        case.repair_started_at = datetime.now()
        _record_repair_transition(db, case, "REPAIR_QUEUE", "IN_REPAIR", actor.username)
        db.commit()
        return {"success": True, "repair_stage": case.repair_stage, "assigned_technician": case.assigned_technician}
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not start repair") from exc
    finally:
        db.close()


@app.post("/api/repair/complete")
def repair_complete(data: RepairWorkflowAction):
    db = SessionLocal()
    try:
        actor = _repair_actor(db, data.username, "technician")
        case = _repair_case(db, data.line_id, data.serial_number, "IN_REPAIR")
        if case.assigned_technician != actor.username:
            raise HTTPException(status_code=403, detail="Only the assigned technician can submit this repair for QC")
        case.repair_completed_at = datetime.now()
        case.qc_note = None
        _record_repair_transition(db, case, "IN_REPAIR", "QC_QUEUE", actor.username)
        db.commit()
        return {"success": True, "repair_stage": case.repair_stage}
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not submit repair for QC") from exc
    finally:
        db.close()


@app.post("/api/repair/qc-review")
def repair_qc_review(data: QualityControlReview):
    db = SessionLocal()
    try:
        actor = _repair_actor(db, data.username, "qc")
        case = _repair_case(db, data.line_id, data.serial_number, "QC_QUEUE")
        note = (data.note or "").strip()
        if not data.approved and not note:
            raise HTTPException(status_code=400, detail="QC rejection reason is required")
        now = datetime.now()
        case.qc_reviewed_at = now
        case.qc_note = note or None
        if data.approved:
            _record_repair_transition(db, case, "QC_QUEUE", "EXIT_QUEUE", actor.username, note)
        else:
            case.qc_return_count = (case.qc_return_count or 0) + 1
            _record_repair_transition(db, case, "QC_QUEUE", "REPAIR_QUEUE", actor.username, note)
        db.commit()
        return {
            "success": True,
            "repair_stage": case.repair_stage,
            "assigned_technician": case.assigned_technician,
            "qc_return_count": case.qc_return_count
        }
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save QC result") from exc
    finally:
        db.close()


@app.get("/api/repair/monitor")
def repair_monitor(line_id: int | None = None, work_date: date | None = None, username: str | None = None):
    db = SessionLocal()
    try:
        selected_date = work_date or date.today()
        query = db.query(Assembly)
        if line_id is not None:
            query = query.filter(Assembly.origin_line_id == line_id)
        open_cases = query.filter(
            Assembly.repair_stage.in_(["REPAIR_QUEUE", "IN_REPAIR", "QC_QUEUE", "EXIT_QUEUE"])
        ).order_by(Assembly.workflow_created_at, Assembly.id).all()
        stages = {name: [] for name in ("REPAIR_QUEUE", "IN_REPAIR", "QC_QUEUE", "EXIT_QUEUE")}
        for case in open_cases:
            stages[case.repair_stage].append({
                "id": case.id,
                "line_id": case.line_id,
                "serial_number": case.serial_number,
                "order_number": case.order_number,
                "product_type": case.product_type,
                "repair_reason": case.repair_reason,
                "assigned_technician": case.assigned_technician,
                "qc_note": case.qc_note,
                "qc_return_count": case.qc_return_count or 0,
                "repair_stage": case.repair_stage,
                "workflow_created_at": case.workflow_created_at.isoformat() if case.workflow_created_at else None,
                "repair_started_at": case.repair_started_at.isoformat() if case.repair_started_at else None,
                "repair_completed_at": case.repair_completed_at.isoformat() if case.repair_completed_at else None
            })
        if username:
            actor = db.query(User).filter(User.username == username.strip()).first()
            if actor is None or actor.role not in ("qc", "technician"):
                raise HTTPException(status_code=403, detail="A QC or Technician account is required")
            if actor.role == "qc":
                stages = {name: items if name == "QC_QUEUE" else [] for name, items in stages.items()}
            else:
                stages = {name: items if name in ("REPAIR_QUEUE", "IN_REPAIR") else [] for name, items in stages.items()}
        daily = db.query(AssemblyWorkflowHistory).filter(
            AssemblyWorkflowHistory.created_at >= datetime.combine(selected_date, datetime.min.time()),
            AssemblyWorkflowHistory.created_at < datetime.combine(selected_date + timedelta(days=1), datetime.min.time())
        )
        if line_id is not None:
            daily = daily.filter(AssemblyWorkflowHistory.line_id == line_id)
        events = daily.all()
        return {
            "work_date": str(selected_date),
            "queues": stages,
            "counts": {stage: len(items) for stage, items in stages.items()},
            "daily": {
                "opened": sum(1 for event in events if event.to_stage == "REPAIR_QUEUE" and event.from_stage in (None, "CLOSED")),
                "repairs_started": sum(1 for event in events if event.to_stage == "IN_REPAIR"),
                "sent_to_qc": sum(1 for event in events if event.to_stage == "QC_QUEUE"),
                "qc_approved": sum(1 for event in events if event.to_stage == "EXIT_QUEUE"),
                "qc_returned": sum(1 for event in events if event.from_stage == "QC_QUEUE" and event.to_stage == "REPAIR_QUEUE"),
                "closed": sum(1 for event in events if event.to_stage == "CLOSED")
            }
        }
    finally:
        db.close()


@app.get("/api/repair/monitor/overview")
def repair_monitor_overview():
    db = SessionLocal()
    try:
        stages = ("REPAIR_QUEUE", "IN_REPAIR", "QC_QUEUE", "EXIT_QUEUE")
        lines = db.query(Line).order_by(Line.id).all()
        line_rows = {
            line.id: {
                "line_id": line.id,
                "line_name": line.name or f"Line {line.id}",
                "counts": {stage: 0 for stage in stages}
            }
            for line in lines
        }
        grouped = db.query(
            Assembly.origin_line_id,
            Assembly.repair_stage,
            func.count(Assembly.id)
        ).filter(
            Assembly.repair_stage.in_(stages)
        ).group_by(Assembly.origin_line_id, Assembly.repair_stage).all()
        totals = {stage: 0 for stage in stages}
        for line_id, stage, count in grouped:
            if line_id not in line_rows:
                line_rows[line_id] = {
                    "line_id": line_id,
                    "line_name": f"Line {line_id}",
                    "counts": {name: 0 for name in stages}
                }
            line_rows[line_id]["counts"][stage] = count
            totals[stage] += count
        return {
            "updated_at": datetime.now().isoformat(),
            "stages": list(stages),
            "totals": totals,
            "lines": list(line_rows.values())
        }
    finally:
        db.close()


@app.get("/api/assembly/exit-queue/{line_id}")
def assembly_exit_queue_count(line_id: int):
    """Return live exit-queue counts for the requested line and all lines."""
    db = SessionLocal()
    try:
        if not db.query(Line.id).filter(Line.id == line_id).first():
            raise HTTPException(status_code=404, detail="Production line not found")

        per_line = db.query(
            Assembly.origin_line_id,
            func.count(Assembly.id)
        ).filter(
            Assembly.repair_stage == "EXIT_QUEUE"
        ).group_by(Assembly.origin_line_id).all()
        counts = {origin_line_id: count for origin_line_id, count in per_line}
        return {
            "line_id": line_id,
            "line_name": db.query(Line.name).filter(Line.id == line_id).scalar() or f"Line {line_id}",
            "line_count": counts.get(line_id, 0),
            "total_count": sum(counts.values()),
            "updated_at": datetime.now().isoformat()
        }
    finally:
        db.close()


@app.get("/api/repair/monitor/stream")
def repair_monitor_stream():
    def events():
        previous_snapshot = None
        last_heartbeat = time.monotonic()
        while True:
            try:
                payload = repair_monitor_overview()
                snapshot = {key: value for key, value in payload.items() if key != "updated_at"}
                signature = json.dumps(snapshot, sort_keys=True)
                if signature != previous_snapshot:
                    previous_snapshot = signature
                    payload["updated_at"] = datetime.now().isoformat()
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_heartbeat = time.monotonic()
                elif time.monotonic() - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
            except Exception:
                yield ": monitor refresh failed\n\n"
            time.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.get("/api/admin/repair-dashboard")
def admin_repair_dashboard(
    admin_username: str = Query(...),
    serial_number: str | None = None,
    line_id: int | None = None
):
    db = SessionLocal()
    try:
        verify_personnel_dashboard_access(db, admin_username)
        labels = {
            "REPAIR_QUEUE": "repair_queue_times",
            "IN_REPAIR": "repair_started_times",
            "QC_QUEUE": "sent_to_qc_times",
            "EXIT_QUEUE": "exit_queue_times",
            "CLOSED": "returned_to_line_times"
        }
        query = db.query(AssemblyWorkflowHistory, Line.name).outerjoin(
            Line, Line.id == AssemblyWorkflowHistory.line_id
        ).filter(
            AssemblyWorkflowHistory.to_stage.in_(labels.keys())
        )
        if serial_number and serial_number.strip():
            query = query.filter(
                AssemblyWorkflowHistory.serial_number.ilike(f"%{serial_number.strip()}%")
            )
        if line_id is not None:
            query = query.filter(AssemblyWorkflowHistory.line_id == line_id)
        records = query.order_by(
            AssemblyWorkflowHistory.created_at.desc(),
            AssemblyWorkflowHistory.id.desc()
        ).limit(2000).all()
        serials = {}
        for event, line_name in records:
            row = serials.setdefault(event.serial_number, {
                "serial_number": event.serial_number,
                "line_id": event.line_id,
                "line_name": line_name or f"Line {event.line_id}",
                **{field: [] for field in labels.values()}
            })
            if event.created_at:
                row[labels[event.to_stage]].append(event.created_at.isoformat())
        return {
            "updated_at": datetime.now().isoformat(),
            "lines": [{"line_id": item.id, "line_name": item.name or f"Line {item.id}"}
                      for item in db.query(Line).order_by(Line.id).all()],
            "serials": list(serials.values())
        }
    finally:
        db.close()


@app.get("/api/repair/history/{line_id}/{serial_number}")
def repair_history(line_id: int, serial_number: str):
    db = SessionLocal()
    try:
        records = db.query(AssemblyWorkflowHistory).filter(
            AssemblyWorkflowHistory.line_id == line_id,
            AssemblyWorkflowHistory.serial_number == serial_number
        ).order_by(AssemblyWorkflowHistory.created_at, AssemblyWorkflowHistory.id).all()
        return [{
            "from_stage": item.from_stage,
            "to_stage": item.to_stage,
            "actor_username": item.actor_username,
            "note": item.note,
            "created_at": item.created_at.isoformat()
        } for item in records]
    finally:
        db.close()


@app.get("/api/assembly/history/{line_id}")
def get_assembly_history(line_id: int):

    db = SessionLocal()

    try:

        items = (
            db.query(Assembly)
            .filter(
                Assembly.line_id == line_id
            )
            .order_by(
                Assembly.id.desc()
            )
            .limit(100)
            .all()
        )

        return [
            {
                "id": item.id,
                "time": item.created_at.strftime("%H:%M:%S"),
                "serial_number": item.serial_number,
                "order_number": item.order_number,
                "product_type": item.product_type,
                "status": item.status,
                "repair_reason": item.repair_reason
            }
            for item in items
        ]

    finally:

        db.close()

@app.get("/api/assembly/monitor/{line_id}")
def get_assembly_monitor(line_id: int):

    today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    db = SessionLocal()

    try:

        if not db.query(Line.id).filter(
            Line.id == line_id
        ).first():
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )



        stop_minutes = _line_stop_minutes_for_today(db, line_id)




        switch_count = db.query(
            func.count()
        ).filter(
            SwitchLog.line_id == line_id,
            SwitchLog.created_at >= today
        ).scalar()




        expected_count = calculate_expected_count(
            stop_minutes,
            switch_count
        )




        aio = db.query(
            func.count()
        ).filter(
            Assembly.line_id == line_id,
            Assembly.product_type == "AIO",
            Assembly.created_at >= today
        ).scalar()


        mnt = db.query(
            func.count()
        ).filter(
            Assembly.line_id == line_id,
            Assembly.product_type == "MNT",
            Assembly.created_at >= today
        ).scalar()


        case = db.query(
            func.count()
        ).filter(
            Assembly.line_id == line_id,
            Assembly.product_type == "CASE",
            Assembly.created_at >= today
        ).scalar()


        nb = db.query(
            func.count()
        ).filter(
            Assembly.line_id == line_id,
            Assembly.product_type == "NB",
            Assembly.created_at >= today
        ).scalar()




        ok_count = db.query(
            func.count()
        ).filter(
            Assembly.line_id == line_id,
            Assembly.status == "OK",
            Assembly.created_at >= today
        ).scalar()


        repair_count = db.query(
            func.count()
        ).filter(
            Assembly.line_id == line_id,
            Assembly.status == "REPAIR",
            Assembly.created_at >= today
        ).scalar()



        actual_count = ok_count + repair_count


        aio_equivalent = (
            aio
            + (mnt * 0.60)
            + (case * 0.80)
            + nb
        )

        aio_equivalent = int(aio_equivalent)




        difference = aio_equivalent - expected_count

        line = db.query(Line).filter(
            Line.id == line_id
        ).first()


        return {

            "ok": ok_count,

            "repair": repair_count,

            "actual_count": actual_count,

            "expected_count": expected_count,

            "difference": difference,

            "stop_minutes": stop_minutes,

            "switch_count": switch_count,

            "aio_equivalent": aio_equivalent,

            "aio": aio,
            "mnt": mnt,
            "case": case,
            "nb": nb,

            "product_name": line.assembly_product_name or "",
            "tea_time": line.tea_time.strftime("%H:%M") if line.tea_time else None,
            "lunch_time": line.lunch_time.strftime("%H:%M") if line.lunch_time else None,

        }


    finally:

        db.close()

@app.get("/assembly-monitor/{line_id}")
def assembly_monitor(request: Request, line_id: int):

    return templates.TemplateResponse(
                request=request,
                name="assembly_monitor.html",
                context={
                    "request": request,
                    "line_id": line_id
                }
        )

@app.get("/api/supervisor/assembly/today/{line_id}")
def supervisor_today_assembly(line_id: int):

    today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    db = SessionLocal()

    try:

        items = (
            db.query(Assembly)
            .filter(
                Assembly.line_id == line_id,
                Assembly.created_at >= today
            )
            .order_by(
                Assembly.id.desc()
            )
            .all()
        )

        return [
            {
                "id": item.id,
                "time": item.created_at.strftime("%H:%M:%S"),
                "serial_number": item.serial_number,
                "order_number": item.order_number,
                "product_type": item.product_type,
                "status": item.status,
                "repair_reason": item.repair_reason or ""
            }
            for item in items
        ]

    finally:

        db.close()

@app.get("/supervisor/assembly/{line_id}")
def supervisor_assembly_page(
    request: Request,
    line_id: int
):
    return templates.TemplateResponse(
        request=request,
        name="supervisor_assembly.html",
        context={
            "line_id": line_id
        }
    )

@app.get("/api/supervisor/assembly/history/{line_id}")
def supervisor_assembly_history(line_id: int):
    db = SessionLocal()

    try:
        items = (
            db.query(AssemblyHistory)
            .filter(
                AssemblyHistory.line_id == line_id
            )
            .order_by(
                AssemblyHistory.id.desc()
            )
            .all()
        )

        return [
            {
                "id": item.id,
                "time": item.created_at.strftime("%H:%M:%S"),
                "serial_number": item.serial_number,
                "order_number": item.order_number,
                "product_type": item.product_type,
                "status": item.status,
                "repair_reason": item.repair_reason or ""
            }
            for item in items
        ]

    finally:
        db.close()

@app.get("/supervisor/assembly-history/{line_id}")
def supervisor_assembly_history_page(
    request: Request,
    line_id: int
):
    return templates.TemplateResponse(
        request=request,
        name="supervisor_assembly_history.html",
        context={
            "line_id": line_id
        }
    )

@app.get("/api/supervisor/pack/today/{line_id}")
def supervisor_today_pack(line_id: int):

    today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    db = SessionLocal()

    try:

        items = (
            db.query(Serial)
            .filter(
                Serial.line_id == line_id,
                Serial.created_at >= today
            )
            .order_by(
                Serial.id.desc()
            )
            .all()
        )

        return [
            {
                "id": item.id,
                "time": item.created_at.strftime("%H:%M:%S"),
                "serial_number": item.serial_number,
                "order_number": item.order_number,
                "order_code": item.order_code,
                "product_type": item.product_type
            }
            for item in items
        ]

    finally:
        db.close()

@app.get("/supervisor/pack/{line_id}")
def supervisor_pack_page(
    request: Request,
    line_id: int
):

    return templates.TemplateResponse(
        request=request,
        name="supervisor_pack.html",
        context={
            "line_id": line_id
        }
    )

@app.put("/api/supervisor/pack/{serial_id}")
def update_supervisor_pack(
    serial_id: int,
    data: SerialUpdate
):
    db = SessionLocal()

    try:

        item = db.query(Serial).filter(
            Serial.id == serial_id
        ).first()

        if not item:
            return {
                "error": "Serial Not Found"
            }

        order_number = data.order_number.strip()
        serial_number = data.serial_number.strip()

        if not order_number:
            return {
                "error": "Order Number Required"
            }

        if not serial_number:
            return {
                "error": "Serial Number Required"
            }



        duplicate = db.query(Serial).filter(
            Serial.serial_number == serial_number,
            Serial.id != serial_id
        ).first()

        if duplicate:
            return {
                "error": "Serial Already Exists"
            }



        order_code = None

        parts = order_number.split("-")

        if len(parts) == 3:

            order_code = parts[1]

        else:

            # اگر خود کاربر فقط Order Code وارد کرد
            order_code = order_number




        order_item = db.query(OrderCode).filter(
            OrderCode.order_code == order_code
        ).first()


        if not order_item:

            return {
                "error": f"Order Code Not Found: {order_code}"
            }




        product_type = order_item.product_type




        item.order_number = order_number

        item.serial_number = serial_number

        item.order_code = order_code

        item.product_type = product_type


        db.commit()


        return {

            "message": "Pack Updated",

            "id": item.id,

            "order_number": item.order_number,

            "serial_number": item.serial_number,

            "order_code": item.order_code,

            "product_type": item.product_type

        }


    except Exception as ex:

        db.rollback()

        return {
            "error": str(ex)
        }


    finally:

        db.close()

@app.delete("/api/supervisor/pack/{serial_id}")
def delete_supervisor_pack(
    serial_id: int
):
    db = SessionLocal()

    try:

        item = db.query(Serial).filter(
            Serial.id == serial_id
        ).first()

        if not item:
            return {
                "error": "Serial Not Found"
            }

        db.delete(item)

        db.commit()

        return {
            "message": "Pack Deleted"
        }

    except Exception as ex:

        db.rollback()

        return {
            "error": str(ex)
        }

    finally:
        db.close()

@app.put("/api/supervisor/assembly/{assembly_id}")
def update_supervisor_assembly(
    assembly_id: int,
    data: AssemblyStatusCreate
):
    db = SessionLocal()

    try:

        item = db.query(Assembly).filter(
            Assembly.id == assembly_id
        ).first()

        if not item:
            return {
                "error": "Assembly Not Found"
            }

        if item.repair_stage is not None:
            return {
                "error": "Assembly records with a repair workflow cannot be edited"
            }

        serial_number = data.serial_number.strip()

        if not serial_number:
            return {
                "error": "Serial Number Required"
            }



        parts = serial_number.split("-")

        if len(parts) != 3:
            return {
                "error": "Invalid Serial Number"
            }

        order_number = parts[1]

        if len(order_number) != 4 or not order_number.isdigit():
            return {
                "error": "Invalid Order Number"
            }


        duplicate = db.query(Assembly).filter(
            Assembly.serial_number == serial_number,
            Assembly.id != assembly_id
        ).first()

        if duplicate:
            return {
                "error": "Serial Already Exists"
            }



        order_item = db.query(OrderCode).filter(
            OrderCode.order_code == order_number
        ).first()

        if not order_item:
            return {
                "error": f"Order Code Not Found: {order_number}"
            }

        product_type = order_item.product_type



        status = data.status.strip().upper()

        if status not in ["OK", "REPAIR"]:
            return {
                "error": "Invalid Status"
            }

        repair_reason = data.repair_reason

        if status == "REPAIR":

            if not repair_reason or not repair_reason.strip():
                return {
                    "error": "Repair Reason Required"
                }

            repair_reason = repair_reason.strip()

        else:

            repair_reason = None



        item.serial_number = serial_number
        item.order_number = order_number
        item.product_type = product_type
        item.status = status
        item.repair_reason = repair_reason

        db.commit()

        return {
            "message": "Assembly Updated",
            "id": item.id,
            "serial_number": item.serial_number,
            "order_number": item.order_number,
            "product_type": item.product_type,
            "status": item.status,
            "repair_reason": item.repair_reason
        }

    except Exception as ex:

        db.rollback()

        return {
            "error": str(ex)
        }

    finally:

        db.close()

@app.delete("/api/supervisor/assembly/{assembly_id}")
def delete_supervisor_assembly(
    assembly_id: int
):
    db = SessionLocal()

    try:

        item = db.query(Assembly).filter(
            Assembly.id == assembly_id
        ).first()

        if not item:
            return {
                "error": "Assembly Not Found"
            }

        if item.repair_stage not in (None, "CLOSED"):
            return {
                "error": "An open repair case cannot be deleted"
            }

        db.delete(item)

        db.commit()

        return {
            "message": "Assembly Deleted"
        }

    except Exception as ex:

        db.rollback()

        return {
            "error": str(ex)
        }

    finally:

        db.close()

@app.get("/api/dashboard")
def get_dashboard():

    today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    db = SessionLocal()

    try:

        result = []


        for line_id in range(1, 7):



            line = db.query(Line).filter(
                Line.id == line_id
            ).first()

            line_status = (
                line.status
                if line
                else "RUNNING"
            )
            assembly_product = (
                line.assembly_product_name
                if line
                else ""
            )

            pack_product = (
                line.pack_product_name
                if line
                else ""
            )




            stop_minutes = _line_stop_minutes_for_today(db, line_id)




            switch_count = db.query(
                func.count()
            ).filter(
                SwitchLog.line_id == line_id,
                SwitchLog.created_at >= today
            ).scalar()

            switch_count = int(
                switch_count or 0
            )




            expected_count = calculate_expected_count(
                stop_minutes,
                switch_count
            )




            pack_aio = db.query(
                func.count()
            ).filter(
                Serial.line_id == line_id,
                Serial.product_type == "AIO",
                Serial.created_at >= today
            ).scalar()

            pack_mnt = db.query(
                func.count()
            ).filter(
                Serial.line_id == line_id,
                Serial.product_type == "MNT",
                Serial.created_at >= today
            ).scalar()

            pack_case = db.query(
                func.count()
            ).filter(
                Serial.line_id == line_id,
                Serial.product_type == "CASE",
                Serial.created_at >= today
            ).scalar()

            pack_nb = db.query(
                func.count()
            ).filter(
                Serial.line_id == line_id,
                Serial.product_type == "NB",
                Serial.created_at >= today
            ).scalar()


            pack_actual = db.query(func.count()).filter(
                Serial.line_id == line_id,
                Serial.created_at >= today
            ).scalar()


            pack_aio_equivalent = int(
                pack_aio +
                (pack_mnt * 0.60) +
                (pack_case * 0.80) +
                pack_nb
            )




            assembly_aio = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.product_type == "AIO",
                Assembly.created_at >= today
            ).scalar()

            assembly_mnt = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.product_type == "MNT",
                Assembly.created_at >= today
            ).scalar()

            assembly_case = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.product_type == "CASE",
                Assembly.created_at >= today
            ).scalar()

            assembly_nb = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.product_type == "NB",
                Assembly.created_at >= today
            ).scalar()


            assembly_actual = db.query(func.count()).filter(
                Assembly.line_id == line_id,
                Assembly.created_at >= today
            ).scalar()


            assembly_aio_equivalent = int(
                assembly_aio +
                (assembly_mnt * 0.60) +
                (assembly_case * 0.80) +
                assembly_nb
            )


            repair_aio = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.status == "REPAIR",
                Assembly.product_type == "AIO"
            ).scalar()

            repair_mnt = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.status == "REPAIR",
                Assembly.product_type == "MNT"
            ).scalar()

            repair_case = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.status == "REPAIR",
                Assembly.product_type == "CASE"
            ).scalar()

            repair_nb = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.status == "REPAIR",
                Assembly.product_type == "NB"
            ).scalar()

            repair_actual = (
                repair_aio +
                repair_mnt +
                repair_case +
                repair_nb
            )



            repair_count = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.status == "REPAIR"
            ).scalar()

            repair_count = int(
                repair_count or 0
            )



            difference = (
                pack_aio_equivalent -
                expected_count
            )



            result.append({

                "line_id": line_id,

                "status": line_status,

                "assembly_product": assembly_product,

                "pack_product": pack_product,

                "tea_time": line.tea_time.strftime("%H:%M") if line and line.tea_time else None,

                "lunch_time": line.lunch_time.strftime("%H:%M") if line and line.lunch_time else None,


                "pack": {

                    "aio": pack_aio,

                    "mnt": pack_mnt,

                    "case": pack_case,

                    "nb": pack_nb,

                    "actual": pack_actual,

                    "aio_equivalent":
                        pack_aio_equivalent
                },



                "assembly": {

                    "aio": assembly_aio,

                    "mnt": assembly_mnt,

                    "case": assembly_case,

                    "nb": assembly_nb,

                    "actual": assembly_actual,

                    "aio_equivalent":
                        assembly_aio_equivalent
                },

                "repair": {

                    "aio": repair_aio,

                    "mnt": repair_mnt,

                    "case": repair_case,

                    "nb": repair_nb,

                    "actual": repair_actual
                },



                "expected":
                    expected_count,

                "difference":
                    difference,



                "stop_minutes":
                    stop_minutes,

                "switch_count":
                    switch_count,

                "repair_count":
                    repair_count,
            })




        return result


    finally:

        db.close()

@app.get("/dashboard")
def dashboard(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html"
    )

@app.put("/api/supervisor/line-status/{line_id}")
def update_line_status(
    line_id: int,
    data: LineStatusUpdate
):
    db = SessionLocal()

    try:

        status = data.status.strip().upper()

        if status not in ["RUNNING", "STOPPED"]:
            return {
                "error": "Invalid Status"
            }

        line = db.query(Line).filter(
            Line.id == line_id
        ).with_for_update().first()

        if not line:
            return {
                "error": "Line Not Found"
            }

        now = datetime.now()
        reason = (data.reason or "").strip()
        open_stop = db.query(LineStop).filter(
            LineStop.line_id == line_id,
            LineStop.stop_minutes == 0
        ).order_by(LineStop.created_at.desc()).with_for_update().first()

        if status == "STOPPED" and not open_stop:
            if not reason:
                return {"error": "Stop reason is required"}
            db.add(LineStop(
                line_id=line_id,
                stop_minutes=0,
                created_at=now,
                reason=reason
            ))
        elif status == "STOPPED" and open_stop and reason:
            open_stop.reason = reason
        elif status == "RUNNING" and line.status == "STOPPED" and open_stop:
            elapsed_seconds = max(0, (now - open_stop.created_at).total_seconds())
            open_stop.stop_minutes = max(1, int((elapsed_seconds + 59) // 60))
            open_stop.ended_at = now

        line.status = status

        db.commit()

        db.refresh(line)

        return {
            "message": "Line Status Updated",
            "line_id": line.id,
            "status": line.status
        }

    except Exception as ex:

        db.rollback()

        return {
            "error": str(ex)
        }

    finally:

        db.close()

@app.get("/api/line-status")
def get_line_status():

    db = SessionLocal()

    try:

        lines = (
            db.query(Line)
            .order_by(Line.id)
            .all()
        )

        result = []
        for line in lines:
            active_stop = db.query(LineStop).filter(
                LineStop.line_id == line.id,
                LineStop.stop_minutes == 0
            ).order_by(LineStop.created_at.desc()).first()
            result.append({
                "line_id": line.id,
                "name": line.name,
                "status": line.status,
                "stop_reason": active_stop.reason if active_stop else None,
                "stop_started_at": active_stop.created_at.isoformat() if active_stop else None
            })
        return result

    finally:

        db.close()

@app.get("/supervisor/line-status/{line_id}")
def supervisor_line_status_page(
    request: Request,
    line_id: int
):

    return templates.TemplateResponse(
        request=request,
        name="supervisor_line_status.html",
        context={
            "line_id": line_id
        }
    )

@app.put("/api/supervisor/assembly-product/{line_id}")
def update_assembly_product(
    line_id: int,
    data: ProductNameUpdate
):
    db = SessionLocal()

    try:
        line = db.query(Line).filter(
            Line.id == line_id
        ).first()

        if not line:
            return {"error": "Line Not Found"}

        product_name = data.product_name.strip()

        if not product_name:
            return {"error": "Product Name Required"}

        line.assembly_product_name = product_name

        db.commit()
        db.refresh(line)

        return {
            "message": "Assembly Product Updated",
            "product_name": line.assembly_product_name
        }

    except Exception as ex:
        db.rollback()
        return {"error": str(ex)}

    finally:
        db.close()

@app.put("/api/supervisor/pack-product/{line_id}")
def update_pack_product(
    line_id: int,
    data: ProductNameUpdate
):
    db = SessionLocal()

    try:
        line = db.query(Line).filter(
            Line.id == line_id
        ).first()

        if not line:
            return {"error": "Line Not Found"}

        product_name = data.product_name.strip()

        if not product_name:
            return {"error": "Product Name Required"}

        line.pack_product_name = product_name

        db.commit()
        db.refresh(line)

        return {
            "message": "Pack Product Updated",
            "product_name": line.pack_product_name
        }

    except Exception as ex:
        db.rollback()
        return {"error": str(ex)}

    finally:
        db.close()

@app.get("/api/supervisor/products/{line_id}")
def get_supervisor_products(line_id: int):
    db = SessionLocal()

    try:
        line = db.query(Line).filter(
            Line.id == line_id
        ).first()

        if not line:
            return {"error": "Line Not Found"}

        return {
            "assembly_product_name": line.assembly_product_name or "",
            "pack_product_name": line.pack_product_name or ""
        }

    finally:
        db.close()


@app.get("/api/supervisor/break-times/{line_id}")
def supervisor_get_break_times(line_id: int, username: str):
    db = SessionLocal()
    try:
        verify_supervisor_line(db, username, line_id)
        line = db.query(Line).filter(Line.id == line_id).first()
        if line is None:
            raise HTTPException(status_code=404, detail="Production line not found")
        return {
            "line_id": line.id,
            "tea_time": line.tea_time.strftime("%H:%M") if line.tea_time else None,
            "lunch_time": line.lunch_time.strftime("%H:%M") if line.lunch_time else None
        }
    finally:
        db.close()


@app.put("/api/supervisor/break-times/{line_id}")
def supervisor_update_break_times(line_id: int, data: LineBreakTimesUpdate):
    db = SessionLocal()
    try:
        verify_supervisor_line(db, data.username, line_id)
        line = db.query(Line).filter(Line.id == line_id).first()
        if line is None:
            raise HTTPException(status_code=404, detail="Production line not found")
        line.tea_time = data.tea_time
        line.lunch_time = data.lunch_time
        db.commit()
        return {
            "success": True,
            "line_id": line.id,
            "tea_time": line.tea_time.strftime("%H:%M") if line.tea_time else None,
            "lunch_time": line.lunch_time.strftime("%H:%M") if line.lunch_time else None
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save line break times") from exc
    finally:
        db.close()

@app.post("/api/attendance/employees")
def create_employee(data: EmployeeCreate):

    db = SessionLocal()

    try:
        line = db.query(Line).filter(
            Line.id == data.line_id
        ).first()

        if not line:
            return {"error": "Line Not Found"}

        existing = db.query(Employee).filter(
            Employee.personnel_code == data.personnel_code
        ).first()

        if existing:
            return {"error": "Employee Already Exists"}

        employee = Employee(
            personnel_code=data.personnel_code,
            full_name=data.full_name,
            line_id=data.line_id
        )

        db.add(employee)
        db.commit()
        db.refresh(employee)

        return {
            "message": "Employee Created",
            "id": employee.id,
            "full_name": employee.full_name,
            "line_id": employee.line_id
        }

    finally:
        db.close()

@app.get("/api/attendance/employees/{line_id}")
def get_employees(line_id: int):

    db = SessionLocal()

    try:
        employees = db.query(Employee).filter(
            Employee.line_id == line_id,
            Employee.is_active == 1
        ).all()

        return [
            {
                "id": emp.id,
                "personnel_code": emp.personnel_code,
                "full_name": emp.full_name,
                "line_id": emp.line_id
            }
            for emp in employees
        ]

    finally:
        db.close()

@app.post("/api/attendance/stations")
def create_station(data: StationCreate):

    db = SessionLocal()

    try:
        line = db.query(Line).filter(
            Line.id == data.line_id
        ).first()

        if not line:
            return {"error": "Line Not Found"}

        existing = db.query(Station).filter(
            Station.line_id == data.line_id,
            Station.station_name == data.station_name
        ).first()

        if existing:
            return {"error": "Station Already Exists"}

        station = Station(
            station_name=data.station_name,
            line_id=data.line_id
        )

        db.add(station)
        db.commit()
        db.refresh(station)

        return {
            "message": "Station Created",
            "id": station.id,
            "station_name": station.station_name,
            "line_id": station.line_id
        }

    finally:
        db.close()

@app.get("/api/attendance/stations/{line_id}")
def get_stations(line_id: int):

    db = SessionLocal()

    try:
        stations = db.query(Station).filter(
            Station.line_id == line_id,
            Station.is_active == 1
        ).all()

        return [
            {
                "id": station.id,
                "station_name": station.station_name,
                "line_id": station.line_id
            }
            for station in stations
        ]

    finally:
        db.close()

@app.post("/api/attendance/assign")
def assign_station(data: AttendanceAssign):

    db = SessionLocal()

    try:
        user = db.query(User).filter(
            User.id == data.user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if user.role != "supervisor":
            raise HTTPException(
                status_code=403,
                detail="Only supervisors can assign stations"
            )

        employee = db.query(Employee).filter(
            Employee.id == data.employee_id,
            Employee.is_active == 1
        ).first()

        if not employee:
            raise HTTPException(
                status_code=404,
                detail="Employee not found or inactive"
            )

        if user.line_id != employee.line_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot manage employees of another line"
            )

        full_day_leave = db.query(LeaveRecord).filter(
            LeaveRecord.employee_id == data.employee_id,
            LeaveRecord.start_date <= data.attendance_date,
            LeaveRecord.end_date >= data.attendance_date,
            LeaveRecord.leave_type.in_(["DAILY", "SICK"])
        ).first()

        if full_day_leave:
            raise HTTPException(
                status_code=400,
                detail="Employee is on leave and cannot be assigned to a station"
            )

        station = db.query(Station).filter(
            Station.id == data.station_id,
            Station.is_active == 1
        ).first()

        if not station:
            raise HTTPException(
                status_code=404,
                detail="Station not found or inactive"
            )

        if station.line_id != employee.line_id:
            raise HTTPException(
                status_code=400,
                detail="Station does not belong to employee line"
            )

        attendance = db.query(DailyAttendance).filter(
            DailyAttendance.employee_id == data.employee_id,
            DailyAttendance.attendance_date == data.attendance_date
        ).first()

        if attendance:

            old_station_id = attendance.station_id

            attendance.station_id = data.station_id
            attendance.status = "PRESENT"
            attendance.updated_by = user.id

        else:

            old_station_id = None

            attendance = DailyAttendance(
                employee_id=data.employee_id,
                attendance_date=data.attendance_date,
                station_id=data.station_id,
                status="PRESENT",
                updated_by=user.id
            )

            db.add(attendance)

        if old_station_id != data.station_id:

            history = AttendanceHistory(
                employee_id=data.employee_id,
                attendance_date=data.attendance_date,
                old_station_id=old_station_id,
                new_station_id=data.station_id,
                changed_by=user.id
            )

            db.add(history)

        db.commit()

        return {
            "success": True,
            "message": "Station assigned successfully",
            "employee_id": employee.id,
            "station_id": station.id,
            "line_id": employee.line_id,
            "attendance_date": str(data.attendance_date),
            "changed_by": user.username
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()

@app.get("/api/attendance/daily/{line_id}")
def get_daily_attendance(
    line_id: int,
    user_id: int,
    attendance_date: date
):
    db = SessionLocal()

    try:
        user = db.query(User).filter(
            User.id == user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if user.role != "supervisor":
            raise HTTPException(
                status_code=403,
                detail="Only supervisors can view attendance"
            )

        if user.line_id != line_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot view another line"
            )

        results = (
            db.query(Employee, DailyAttendance, Station)
            .outerjoin(
                DailyAttendance,
                and_(
                    DailyAttendance.employee_id == Employee.id,
                    DailyAttendance.attendance_date == attendance_date
                )
            )
            .outerjoin(
                Station,
                DailyAttendance.station_id == Station.id
            )
            .filter(
                Employee.line_id == line_id,
                Employee.is_active == 1
            )
            .order_by(Employee.full_name)
            .all()
        )

        employees = []

        for employee, attendance, station in results:

            leaves = db.query(LeaveRecord).filter(
                LeaveRecord.employee_id == employee.id,
                LeaveRecord.start_date <= attendance_date,
                LeaveRecord.end_date >= attendance_date
            ).order_by(
                LeaveRecord.created_at.desc()
            ).all()

            leave = None

            if leaves:
                leave = next(
                    (
                        item for item in leaves
                        if item.leave_type == "SICK"
                    ),
                    None
                )

                if leave is None:
                    leave = next(
                        (
                            item for item in leaves
                            if item.leave_type == "DAILY"
                        ),
                        None
                    )

                if leave is None:
                    leave = next(
                        (
                            item for item in leaves
                            if item.leave_type == "HOURLY"
                        ),
                        None
                    )

            if leave:
                if leave.leave_type == "DAILY":
                    status = "LEAVE_DAILY"

                elif leave.leave_type == "SICK":
                    status = "SICK_LEAVE"

                elif leave.leave_type == "HOURLY":
                    status = "LEAVE_HOURLY"

                else:
                    status = (
                        attendance.status
                        if attendance
                        else "NOT_REGISTERED"
                    )

            elif attendance is None:
                status = "NOT_REGISTERED"

            else:
                status = attendance.status

            employees.append({
                "employee_id": employee.id,
                "personnel_code": employee.personnel_code,
                "full_name": employee.full_name,
                "line_id": employee.line_id,

                "station_id": station.id if station else None,
                "station_name": (
                    station.station_name
                    if station else None
                ),

                "status": status,
                "attendance_registered": attendance is not None,

                "updated_at": (
                    attendance.updated_at.isoformat()
                    if attendance and attendance.updated_at
                    else None
                ),

                "leave_id": leave.id if leave else None,

                "leave_type": (
                    leave.leave_type
                    if leave else None
                ),

                "leave_start_date": (
                    str(leave.start_date)
                    if leave else None
                ),

                "leave_end_date": (
                    str(leave.end_date)
                    if leave else None
                ),

                "leave_start_time": (
                    leave.start_time.strftime("%H:%M")
                    if leave and leave.start_time
                    else None
                ),

                "leave_end_time": (
                    leave.end_time.strftime("%H:%M")
                    if leave and leave.end_time
                    else None
                ),

                "leave_notes": (
                    leave.notes
                    if leave else None
                )
            })

        return {
            "success": True,
            "line_id": line_id,
            "attendance_date": str(attendance_date),
            "total_employees": len(employees),
            "employees": employees
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()


@app.get("/api/attendance/history/{line_id}")
def get_attendance_history(
    line_id: int,
    user_id: int,
    attendance_date: date
):
    db = SessionLocal()

    try:
        user = db.query(User).filter(
            User.id == user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if user.role != "supervisor":
            raise HTTPException(
                status_code=403,
                detail="Only supervisors can view history"
            )

        if user.line_id != line_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot view another line"
            )

        OldStation = aliased(Station)
        NewStation = aliased(Station)

        results = (
            db.query(
                AttendanceHistory,
                Employee,
                OldStation,
                NewStation,
                User
            )
            .join(
                Employee,
                AttendanceHistory.employee_id == Employee.id
            )
            .outerjoin(
                OldStation,
                AttendanceHistory.old_station_id == OldStation.id
            )
            .outerjoin(
                NewStation,
                AttendanceHistory.new_station_id == NewStation.id
            )
            .join(
                User,
                AttendanceHistory.changed_by == User.id
            )
            .filter(
                Employee.line_id == line_id,
                AttendanceHistory.attendance_date == attendance_date
            )
            .order_by(
                AttendanceHistory.changed_at.desc()
            )
            .all()
        )

        history = []

        for record, employee, old_station, new_station, changed_user in results:

            history.append({
                "employee_id": employee.id,
                "personnel_code": employee.personnel_code,
                "employee_name": employee.full_name,

                "old_station_id": record.old_station_id,
                "old_station_name": (
                    old_station.station_name
                    if old_station else None
                ),

                "new_station_id": record.new_station_id,
                "new_station_name": (
                    new_station.station_name
                    if new_station else None
                ),

                "changed_by": changed_user.username,
                "changed_at": (
                    record.changed_at.isoformat()
                    if record.changed_at else None
                )
            })

        return {
            "success": True,
            "line_id": line_id,
            "attendance_date": str(attendance_date),
            "total_changes": len(history),
            "history": history
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()

@app.get("/supervisor/attendance/{line_id}")
def supervisor_attendance_page(
    request: Request,
    line_id: int
):
    return templates.TemplateResponse(
        request=request,
        name="supervisor_attendance.html",
        context={
            "line_id": line_id
        }
    )

@app.post("/api/attendance/assign-bulk")
def assign_station_bulk(data: AttendanceBulkAssign):

    db = SessionLocal()

    try:
        user = db.query(User).filter(
            User.id == data.user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if user.role != "supervisor":
            raise HTTPException(
                status_code=403,
                detail="Only supervisors can assign stations"
            )

        if not data.assignments:
            raise HTTPException(
                status_code=400,
                detail="No assignments provided"
            )

        employee_ids = [
            item.employee_id for item in data.assignments
        ]

        if len(employee_ids) != len(set(employee_ids)):
            raise HTTPException(
                status_code=400,
                detail="Duplicate employee IDs are not allowed"
            )

        prepared_assignments = []

        for item in data.assignments:

            employee = db.query(Employee).filter(
                Employee.id == item.employee_id,
                Employee.is_active == 1
            ).first()

            if not employee:
                raise HTTPException(
                    status_code=404,
                    detail=f"Employee {item.employee_id} not found or inactive"
                )

            if employee.line_id != user.line_id:
                raise HTTPException(
                    status_code=403,
                    detail=f"Employee {item.employee_id} belongs to another line"
                )

            station = db.query(Station).filter(
                Station.id == item.station_id,
                Station.is_active == 1
            ).first()

            if not station:
                raise HTTPException(
                    status_code=404,
                    detail=f"Station {item.station_id} not found or inactive"
                )

            if station.line_id != user.line_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Station {item.station_id} belongs to another line"
                )

            prepared_assignments.append(
                (item, employee, station)
            )

        changed_count = 0
        unchanged_count = 0

        for item, employee, station in prepared_assignments:

            attendance = db.query(DailyAttendance).filter(
                DailyAttendance.employee_id == employee.id,
                DailyAttendance.attendance_date == data.attendance_date
            ).first()

            if attendance:

                old_station_id = attendance.station_id

                attendance.station_id = station.id
                attendance.status = "PRESENT"
                attendance.updated_by = user.id

            else:

                old_station_id = None

                attendance = DailyAttendance(
                    employee_id=employee.id,
                    attendance_date=data.attendance_date,
                    station_id=station.id,
                    status="PRESENT",
                    updated_by=user.id
                )

                db.add(attendance)

            # تاریخچه فقط در صورت تغییر واقعی ایستگاه
            if old_station_id != station.id:

                history = AttendanceHistory(
                    employee_id=employee.id,
                    attendance_date=data.attendance_date,
                    old_station_id=old_station_id,
                    new_station_id=station.id,
                    changed_by=user.id
                )

                db.add(history)
                changed_count += 1

            else:
                unchanged_count += 1

        db.commit()

        return {
            "success": True,
            "message": "All assignments saved successfully",
            "line_id": user.line_id,
            "attendance_date": str(data.attendance_date),
            "total_assignments": len(data.assignments),
            "changed_count": changed_count,
            "unchanged_count": unchanged_count
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()


def verify_admin(db, admin_username):

    admin = db.query(User).filter(
        User.username == admin_username
    ).first()

    if not admin:
        raise HTTPException(
            status_code=404,
            detail="Admin not found"
        )

    if admin.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only administrators can manage employees"
        )

    return admin


def verify_personnel_dashboard_access(db, admin_username):
    user = db.query(User).filter(
        User.username == admin_username
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if user.role not in ("admin", "dashboard"):
        raise HTTPException(
            status_code=403,
            detail="Only administrators and dashboard users can access this dashboard"
        )

    return user


def verify_supervisor_line(db, username, line_id):
    user = db.query(User).filter(User.username == username.strip()).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in again")
    if user.role != "supervisor" or user.line_id != line_id:
        raise HTTPException(status_code=403, detail="This supervisor can only manage their assigned line")
    return user


@app.get("/api/admin/employees")
def admin_get_employees(
    admin_username: str,
    line_id: int | None = None,
    unit: str | None = None
):

    db = SessionLocal()

    try:

        verify_admin(db, admin_username)

        query = db.query(Employee)

        if line_id is not None:
            query = query.filter(
                Employee.line_id == line_id
            )
        if unit is not None:
            query = query.filter(Employee.unit == unit.strip().upper())

        employees = query.order_by(
            Employee.line_id,
            Employee.full_name
        ).all()

        return {
            "success": True,
            "total": len(employees),
            "employees": [
                {
                    "id": emp.id,
                    "personnel_code": emp.personnel_code,
                    "full_name": emp.full_name,
                    "line_id": emp.line_id,
                    "unit": emp.unit,
                    "position": emp.position,
                    "is_active": emp.is_active
                }
                for emp in employees
            ]
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()


@app.post("/api/admin/employees")
def admin_create_employee(data: AdminEmployeeCreate):

    db = SessionLocal()

    try:

        verify_admin(db, data.admin_username)

        unit = (data.unit or "").strip().upper() or None
        if (data.line_id is None) == (unit is None):
            raise HTTPException(
                status_code=400,
                detail="Select exactly one production line or personnel unit"
            )
        if unit not in (None, "ADMINISTRATION", "SUPPORT"):
            raise HTTPException(status_code=400, detail="Invalid personnel unit")
        position = (data.position or "STAFF").strip().upper()
        if position not in {"SUPERVISOR", "LOADING", "STAFF"}:
            raise HTTPException(status_code=400, detail="Invalid employee position")
        if data.line_id is not None and not db.query(Line).filter(Line.id == data.line_id).first():
            raise HTTPException(status_code=404, detail="Production line not found")

        existing = db.query(Employee).filter(
            Employee.personnel_code == data.personnel_code
        ).first()

        if existing:
            raise HTTPException(
                status_code=400,
                detail="Personnel code already exists"
            )

        employee = Employee(
            personnel_code=data.personnel_code,
            full_name=data.full_name,
            line_id=data.line_id,
            unit=unit,
            position=position,
            is_active=1
        )

        db.add(employee)
        db.commit()
        db.refresh(employee)

        return {
            "success": True,
            "message": "Employee created successfully",
            "employee": {
                "id": employee.id,
                "personnel_code": employee.personnel_code,
                "full_name": employee.full_name,
                "line_id": employee.line_id,
                "unit": employee.unit,
                "position": employee.position,
                "is_active": employee.is_active
            }
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()



@app.put("/api/admin/employees/{employee_id}")
def admin_update_employee(
    employee_id: int,
    data: AdminEmployeeUpdate
):

    db = SessionLocal()

    try:

        verify_admin(db, data.admin_username)

        employee = db.query(Employee).filter(
            Employee.id == employee_id
        ).first()

        if not employee:
            raise HTTPException(
                status_code=404,
                detail="Employee not found"
            )

        unit = (data.unit or "").strip().upper() or None
        if (data.line_id is None) == (unit is None):
            raise HTTPException(
                status_code=400,
                detail="Select exactly one production line or personnel unit"
            )
        if unit not in (None, "ADMINISTRATION", "SUPPORT"):
            raise HTTPException(status_code=400, detail="Invalid personnel unit")
        position = (data.position or "STAFF").strip().upper()
        if position not in {"SUPERVISOR", "LOADING", "STAFF"}:
            raise HTTPException(status_code=400, detail="Invalid employee position")
        if data.line_id is not None and not db.query(Line).filter(Line.id == data.line_id).first():
            raise HTTPException(status_code=404, detail="Production line not found")

        duplicate = db.query(Employee).filter(
            Employee.personnel_code == data.personnel_code,
            Employee.id != employee_id
        ).first()

        if duplicate:
            raise HTTPException(
                status_code=400,
                detail="Personnel code already exists"
            )

        employee.personnel_code = data.personnel_code
        employee.full_name = data.full_name
        employee.line_id = data.line_id
        employee.unit = unit
        employee.position = position

        db.commit()

        return {
            "success": True,
            "message": "Employee updated successfully"
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()


@app.patch("/api/admin/employees/{employee_id}/status")
def admin_update_employee_status(
    employee_id: int,
    data: AdminEmployeeStatus
):

    db = SessionLocal()

    try:

        verify_admin(db, data.admin_username)

        if data.is_active not in [0, 1]:
            raise HTTPException(
                status_code=400,
                detail="is_active must be 0 or 1"
            )

        employee = db.query(Employee).filter(
            Employee.id == employee_id
        ).first()

        if not employee:
            raise HTTPException(
                status_code=404,
                detail="Employee not found"
            )

        employee.is_active = data.is_active

        if data.is_active == 0:
            assignments = db.query(DailyAttendance).filter(
                DailyAttendance.employee_id == employee.id,
                DailyAttendance.attendance_date == date.today()
            ).all()
            for attendance in assignments:
                attendance.station_id = None
                attendance.status = "INACTIVE"

        db.commit()

        return {
            "success": True,
            "message": "Employee status updated",
            "is_active": employee.is_active
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()

@app.get("/admin/personnel")
def admin_personnel_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="admin_personnel.html",
        context={}
    )

@app.get("/api/admin/stations")
def admin_get_stations(admin_username: str):
    db = SessionLocal()

    try:
        verify_admin(db, admin_username)

        stations = db.query(Station).order_by(
            Station.line_id,
            Station.station_name
        ).all()

        return {
            "success": True,
            "stations": [
                {
                    "id": s.id,
                    "station_name": s.station_name,
                    "line_id": s.line_id,
                    "is_active": s.is_active
                }
                for s in stations
            ]
        }

    finally:
        db.close()


@app.post("/api/admin/stations")
def admin_create_station(data: AdminStationCreate):
    db = SessionLocal()

    try:
        verify_admin(db, data.admin_username)

        station_name = data.station_name.strip()

        if not station_name:
            raise HTTPException(
                status_code=400,
                detail="Station name is required"
            )

        line = db.query(Line).filter(
            Line.id == data.line_id
        ).first()

        if not line:
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )

        existing = db.query(Station).filter(
            Station.line_id == data.line_id,
            Station.station_name == station_name
        ).first()

        if existing:
            if existing.is_active == 1:
                raise HTTPException(
                    status_code=400,
                    detail="This station already exists"
                )

            # اگر قبلاً غیرفعال شده، دوباره فعال شود
            existing.is_active = 1
            db.commit()

            return {
                "success": True,
                "message": "Station reactivated",
                "id": existing.id
            }

        station = Station(
            station_name=station_name,
            line_id=data.line_id,
            is_active=1
        )

        db.add(station)
        db.commit()
        db.refresh(station)

        return {
            "success": True,
            "message": "Station created",
            "id": station.id
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()


@app.patch("/api/admin/stations/{station_id}/status")
def admin_update_station_status(
    station_id: int,
    data: AdminStationStatus
):
    db = SessionLocal()

    try:
        verify_admin(db, data.admin_username)

        if data.is_active not in [0, 1]:
            raise HTTPException(
                status_code=400,
                detail="Invalid station status"
            )

        station = db.query(Station).filter(
            Station.id == station_id
        ).first()

        if not station:
            raise HTTPException(
                status_code=404,
                detail="Station not found"
            )

        station.is_active = data.is_active
        db.commit()

        return {
            "success": True,
            "message": "Station status updated",
            "is_active": station.is_active
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()

@app.post("/api/attendance/leaves")
def create_leave(data: LeaveCreate):

    db = SessionLocal()

    try:

        # بررسی سرپرست
        user = db.query(User).filter(
            User.id == data.user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if user.role not in {"supervisor", "support_supervisor"}:
            raise HTTPException(
                status_code=403,
                detail="Only supervisors can register leave"
            )

        # بررسی پرسنل
        employee = db.query(Employee).filter(
            Employee.id == data.employee_id,
            Employee.is_active == 1
        ).first()

        if not employee:
            raise HTTPException(
                status_code=404,
                detail="Employee not found"
            )

        # Line supervisors can manage only their line; the support supervisor
        # can manage only employees in the SUPPORT unit.
        employee_is_in_scope = (
            employee.unit == "SUPPORT" and employee.line_id is None
            if user.role == "support_supervisor"
            else employee.line_id == user.line_id and employee.unit is None
        )
        if not employee_is_in_scope:
            raise HTTPException(
                status_code=403,
                detail="You cannot manage leave for this employee"
            )

        leave_type = data.leave_type.upper().strip()

        if leave_type not in {"DAILY", "HOURLY", "SICK"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid leave type"
            )

        start_date = data.start_date
        end_date = data.end_date or start_date

        if end_date < start_date:
            raise HTTPException(
                status_code=400,
                detail="Invalid date range"
            )

        start_time = data.start_time
        end_time = data.end_time

        # مرخصی ساعتی
        if leave_type == "HOURLY":

            if end_date != start_date:
                raise HTTPException(
                    status_code=400,
                    detail="Hourly leave must be on one date"
                )

            if (
                not start_time
                or not end_time
                or start_time >= end_time
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid time range"
                )

        else:

            start_time = None
            end_time = None

            if leave_type == "DAILY" and end_date != start_date:
                raise HTTPException(
                    status_code=400,
                    detail="Daily leave is limited to one date"
                )

            if leave_type == "SICK" and (data.start_time or data.end_time):
                raise HTTPException(
                    status_code=400,
                    detail="Sick leave must cover full days"
                )

        # بررسی تداخل مرخصی‌ها
        overlaps = db.query(LeaveRecord).filter(
            LeaveRecord.employee_id == employee.id,
            LeaveRecord.start_date <= end_date,
            LeaveRecord.end_date >= start_date
        ).all()

        for existing in overlaps:

            # دو مرخصی ساعتی در یک روز می‌توانند جدا باشند
            if (
                leave_type == "HOURLY"
                and existing.leave_type == "HOURLY"
                and existing.start_date == start_date
            ):

                if (
                    existing.end_time
                    and existing.start_time
                    and (
                        start_time >= existing.end_time
                        or end_time <= existing.start_time
                    )
                ):
                    continue

            raise HTTPException(
                status_code=409,
                detail="This leave overlaps an existing leave"
            )

        # ذخیره مرخصی
        leave = LeaveRecord(
            employee_id=employee.id,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            notes=(data.notes or "").strip() or None,
            created_by=user.id
        )

        db.add(leave)
        db.commit()
        db.refresh(leave)

        return {
            "success": True,
            "leave_id": leave.id,
            "employee_id": employee.id,
            "employee_name": employee.full_name,
            "leave_type": leave.leave_type,
            "start_date": str(leave.start_date),
            "end_date": str(leave.end_date),
            "start_time": (
                leave.start_time.strftime("%H:%M")
                if leave.start_time else None
            ),
            "end_time": (
                leave.end_time.strftime("%H:%M")
                if leave.end_time else None
            )
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()

@app.get("/api/attendance/leaves/{line_id}")
def get_leaves(
    line_id: int,
    user_id: int,
    start_date: date,
    end_date: date | None = None
):

    db = SessionLocal()

    try:

        user = db.query(User).filter(
            User.id == user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if user.role != "supervisor" or user.line_id != line_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot view another line"
            )

        until_date = end_date or start_date

        if until_date < start_date:
            raise HTTPException(
                status_code=400,
                detail="Invalid date range"
            )

        rows = db.query(
            LeaveRecord,
            Employee
        ).join(
            Employee,
            LeaveRecord.employee_id == Employee.id
        ).filter(
            Employee.line_id == line_id,
            LeaveRecord.start_date <= until_date,
            LeaveRecord.end_date >= start_date
        ).order_by(
            LeaveRecord.start_date,
            Employee.full_name
        ).all()

        return {
            "success": True,
            "leaves": [
                {
                    "id": leave.id,
                    "employee_id": employee.id,
                    "employee_name": employee.full_name,
                    "personnel_code": employee.personnel_code,
                    "leave_type": leave.leave_type,
                    "start_date": str(leave.start_date),
                    "end_date": str(leave.end_date),
                    "start_time": (
                        leave.start_time.strftime("%H:%M")
                        if leave.start_time else None
                    ),
                    "end_time": (
                        leave.end_time.strftime("%H:%M")
                        if leave.end_time else None
                    ),
                    "notes": leave.notes
                }
                for leave, employee in rows
            ]
        }

    finally:
        db.close()


@app.get("/supervisor/support/leave")
def support_leave_page(request: Request, username: str = Query(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username.strip()).first()
        if user is None or user.role != "support_supervisor":
            raise HTTPException(status_code=403, detail="Support supervisor access required")
        return templates.TemplateResponse(
            request=request,
            name="supervisor_support_leave.html",
            context={
                "username": user.username,
                "persian_today": jdatetime.date.fromgregorian(
                    date=date.today()
                ).strftime("%Y/%m/%d").translate(
                    str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
                )
            },
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    finally:
        db.close()


@app.get("/api/support/leave/employees")
def support_leave_employees(username: str = Query(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username.strip()).first()
        if user is None or user.role != "support_supervisor":
            raise HTTPException(status_code=403, detail="Support supervisor access required")
        employees = db.query(Employee).filter(
            Employee.unit == "SUPPORT",
            Employee.line_id.is_(None),
            Employee.is_active == 1
        ).order_by(Employee.full_name).all()
        return [{
            "id": employee.id,
            "personnel_code": employee.personnel_code,
            "full_name": employee.full_name
        } for employee in employees]
    finally:
        db.close()


@app.get("/api/support/leave/records")
def support_leave_records(username: str = Query(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username.strip()).first()
        if user is None or user.role != "support_supervisor":
            raise HTTPException(status_code=403, detail="Support supervisor access required")
        rows = db.query(LeaveRecord, Employee).join(
            Employee, Employee.id == LeaveRecord.employee_id
        ).filter(
            Employee.unit == "SUPPORT",
            Employee.line_id.is_(None)
        ).order_by(LeaveRecord.start_date.desc(), LeaveRecord.id.desc()).limit(500).all()
        return [{
            "id": leave.id,
            "employee_id": employee.id,
            "employee_name": employee.full_name,
            "personnel_code": employee.personnel_code,
            "leave_type": leave.leave_type,
            "start_date": str(leave.start_date),
            "end_date": str(leave.end_date),
            "start_time": leave.start_time.strftime("%H:%M") if leave.start_time else None,
            "end_time": leave.end_time.strftime("%H:%M") if leave.end_time else None,
            "notes": leave.notes
        } for leave, employee in rows]
    finally:
        db.close()

@app.post("/api/admin/personnel-leaves")
def admin_create_personnel_leave(data: AdminLeaveCreate):
    db = SessionLocal()
    try:
        admin = verify_admin(db, data.admin_username)
        employee = db.query(Employee).filter(
            Employee.id == data.employee_id,
            Employee.is_active == 1,
            Employee.unit.in_(["ADMINISTRATION", "SUPPORT"])
        ).first()
        if not employee:
            raise HTTPException(
                status_code=404,
                detail="Active administration or support employee not found"
            )

        leave_type = data.leave_type.upper().strip()
        if leave_type not in {"DAILY", "HOURLY", "SICK"}:
            raise HTTPException(status_code=400, detail="Invalid leave type")
        start_date = data.start_date
        end_date = data.end_date or start_date
        if end_date < start_date:
            raise HTTPException(status_code=400, detail="Invalid date range")
        start_time, end_time = data.start_time, data.end_time
        if leave_type == "HOURLY":
            if end_date != start_date or not start_time or not end_time or start_time >= end_time:
                raise HTTPException(status_code=400, detail="Invalid hourly leave time range")
        else:
            start_time = end_time = None
            if leave_type == "DAILY" and end_date != start_date:
                raise HTTPException(status_code=400, detail="Daily leave is limited to one date")
            if leave_type == "SICK" and (data.start_time or data.end_time):
                raise HTTPException(status_code=400, detail="Sick leave must cover full days")

        overlaps = db.query(LeaveRecord).filter(
            LeaveRecord.employee_id == employee.id,
            LeaveRecord.start_date <= end_date,
            LeaveRecord.end_date >= start_date
        ).all()
        for existing in overlaps:
            if (
                leave_type == "HOURLY" and existing.leave_type == "HOURLY"
                and existing.start_date == start_date and existing.start_time and existing.end_time
                and (start_time >= existing.end_time or end_time <= existing.start_time)
            ):
                continue
            raise HTTPException(status_code=409, detail="This leave overlaps an existing leave")

        leave = LeaveRecord(
            employee_id=employee.id,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            notes=(data.notes or "").strip() or None,
            created_by=admin.id
        )
        db.add(leave)
        db.commit()
        db.refresh(leave)
        return {"success": True, "leave_id": leave.id}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


@app.get("/api/admin/personnel-dashboard")
def admin_personnel_dashboard(
    admin_username: str,
    start_date: date | None = None,
    end_date: date | None = None
):
    db = SessionLocal()

    try:
        # فقط ادمین اجازه مشاهده دارد
        verify_personnel_dashboard_access(db, admin_username)

        today = date.today()
        start_date = start_date or today
        end_date = end_date or today

        if start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail="Invalid date range"
            )

        # دریافت همه پرسنل و ایستگاه تخصیص‌یافته امروز
        employee_rows = (
            db.query(Employee, Line, Station)
            .outerjoin(Line, Employee.line_id == Line.id)
            .outerjoin(
                DailyAttendance,
                and_(
                    DailyAttendance.employee_id == Employee.id,
                    DailyAttendance.attendance_date == today
                )
            )
            .outerjoin(
                Station,
                DailyAttendance.station_id == Station.id
            )
            .order_by(Employee.line_id, Employee.full_name)
            .all()
        )

        employees = []

        for employee, line, station in employee_rows:
            employees.append({
                "id": employee.id,
                "personnel_code": employee.personnel_code,
                "full_name": employee.full_name,
                "line_id": employee.line_id,
                "unit": employee.unit,
                "position": employee.position,
                "line_name": line.name if line else (
                    "Administration" if employee.unit == "ADMINISTRATION"
                    else "Support" if employee.unit == "SUPPORT"
                    else "Not assigned"
                ),
                "is_active": employee.is_active,
                "station_name": (
                    station.station_name if station else None
                )
            })

        # دریافت مرخصی‌های بازه انتخابی
        leave_rows = (
            db.query(LeaveRecord, Employee, Line)
            .join(
                Employee,
                LeaveRecord.employee_id == Employee.id
            )
            .join(
                Line,
                Employee.line_id == Line.id,
                isouter=True
            )
            .filter(
                LeaveRecord.start_date <= end_date,
                LeaveRecord.end_date >= start_date
            )
            .order_by(
                Employee.line_id,
                LeaveRecord.start_date
            )
            .all()
        )

        leaves = []

        for leave, employee, line in leave_rows:
            leaves.append({
                "id": leave.id,
                "employee_id": employee.id,
                "personnel_code": employee.personnel_code,
                "employee_name": employee.full_name,
                "line_id": employee.line_id,
                "unit": employee.unit,
                "line_name": line.name if line else (
                    "Administration" if employee.unit == "ADMINISTRATION"
                    else "Support" if employee.unit == "SUPPORT"
                    else "Not assigned"
                ),
                "leave_type": leave.leave_type,
                "start_date": str(leave.start_date),
                "end_date": str(leave.end_date),
                "start_time": (
                    leave.start_time.isoformat()
                    if leave.start_time else None
                ),
                "end_time": (
                    leave.end_time.isoformat()
                    if leave.end_time else None
                ),
                "notes": leave.notes
            })

        return {
            "success": True,
            "today": str(today),
            "total_employees": len(employees),
            "active_employees": sum(
                1 for e in employees if e["is_active"] == 1
            ),
            "inactive_employees": sum(
                1 for e in employees if e["is_active"] != 1
            ),
            "employees": employees,
            "leave_total": len(leaves),
            "leaves": leaves
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        db.close()

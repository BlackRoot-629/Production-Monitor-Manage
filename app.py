from fastapi import FastAPI

from database import engine
from models import Base

from database import SessionLocal
from models import Serial, OrderCode
from schemas import SerialCreate

from sqlalchemy import func, or_

from schemas import StopCreate
from models import LineStop
from models import SwitchLog
from services import calculate_expected_count
from models import User
from schemas import LoginRequest
from schemas import OrderCodeCreate
from schemas import UserCreate, UserUpdate
from schemas import SerialUpdate
from schemas import AssemblyScanCreate
from schemas import AssemblyStatusCreate
from models import Assembly
from models import AssemblyHistory
from models import Line
from schemas import LineStatusUpdate
from schemas import ProductNameUpdate

from pydantic import BaseModel

import jdatetime
from fastapi.responses import FileResponse
from export_all_excel import export_all_production
from export_excel import export_production
from export_assemble_all import TodayAssemblyHistory
from export_today_assemble import TodayAssemble

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi import Query
from fastapi import HTTPException

from datetime import datetime
from datetime import date
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
    LeaveCreate
)
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

app = FastAPI()


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

        order_code = data.order_number.split("-")[1]

        product = db.query(OrderCode).filter(
            OrderCode.order_code == order_code
        ).first()

        if not product:

            return {
                "error": "Order Code Not Found"
            }

        existing = db.query(Serial).filter(
            Serial.serial_number == data.serial_number
        ).first()

        if existing:

            return {
                "error": "Duplicate Serial"
            }
        serial = Serial(

            line_id=data.line_id,

            serial_number=data.serial_number,

            order_number=data.order_number,

            order_code=order_code,

            product_type=product.product_type

        )

        db.add(serial)

        db.commit()

        return {
            "message": "Saved"
        }

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
        stop_minutes = db.query(
        func.coalesce(
            func.sum(LineStop.stop_minutes),
            0
        )
        ).filter(
            LineStop.line_id == line_id,
            LineStop.created_at >= today
        ).scalar()

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

        aio_equivalent = (

            aio

            + (mnt * 0.60)

            + (case * 0.80)

            + nb

        )

        difference = aio_equivalent - expected_count

        production_score = actual_count

        line = db.query(Line).filter(
            Line.id == line_id
        ).first()

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

        }

    finally:

        db.close()

@app.post("/api/stop")
def add_stop(data: StopCreate):

    db = SessionLocal()

    try:

        stop = LineStop(

            line_id=data.line_id,

            stop_minutes=data.stop_minutes

        )

        db.add(stop)

        db.commit()

        return {
            "message": "Stop Saved"
        }

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

        count = db.query(func.count()).filter(
            SwitchLog.line_id == line_id,
            SwitchLog.created_at >= today
        ).scalar()

        if count >= 2:

            return {
                "error": "Maximum usage reached"
            }

        switch = SwitchLog(

            line_id=line_id

        )

        db.add(switch)

        db.commit()

        return {
            "message": "Switch Saved"
        }

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

            return {
                "error":
                "Invalid Username Or Password"
            }

        return {

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

        existing = db.query(
            OrderCode
        ).filter(
            OrderCode.order_code ==
            data.order_code
        ).first()

        if existing:

            return {
                "error":
                "Order Code Exists"
            }

        item = OrderCode(

            order_code=data.order_code,

            product_type=data.product_type

        )

        db.add(item)

        db.commit()

        return {
            "message":
            "Saved"
        }

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

        exists = db.query(
            User
        ).filter(

            User.username ==
            data.username

        ).first()

        if exists:

            return {

                "error":
                "Username Exists"

            }

        user = User(

            username=data.username,

            password=data.password,

            role=data.role,

            line_id=data.line_id

        )

        db.add(user)

        db.commit()

        return {

            "message":
            "User Created"

        }

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

        user.role = data.role

        user.line_id = data.line_id

        db.commit()

        return {

            "message":
            "User Updated"

        }

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

@app.get("/api/ordercodes")
def get_ordercodes():

    db = SessionLocal()

    try:

        orders = db.query(
            OrderCode
        ).order_by(

            OrderCode.id.desc()

        ).limit(20).all()

        return [

            {

                "order_code":
                item.order_code,

                "product_type":
                item.product_type

            }

            for item in orders

        ]

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

        # -----------------------------
        # Check Serial Format
        # -----------------------------

        parts = serial_number.split("-")

        if len(parts) != 3:
            return {
                "error": "Invalid Serial Number"
            }

        # -----------------------------
        # Extract Order Number
        # -----------------------------

        order_number = parts[1]

        if len(order_number) != 4 or not order_number.isdigit():
            return {
                "error": "Invalid Order Number"
            }

        # -----------------------------
        # Find Product Type
        # -----------------------------

        order_item = db.query(OrderCode).filter(
            OrderCode.order_code == order_number
        ).first()

        if not order_item:
            return {
                "error": "Order Code Not Found"
            }

        product_type = order_item.product_type

        # -----------------------------
        # Find Existing Assembly
        # -----------------------------

        assembly = db.query(Assembly).filter(
            Assembly.line_id == data.line_id,
            Assembly.serial_number == serial_number
        ).first()

        # -----------------------------
        # New Serial
        # -----------------------------

        if not assembly:

            return {
                "message": "Serial Valid",
                "serial_number": serial_number,
                "order_number": order_number,
                "product_type": product_type,
                "current_status": None
            }

        # -----------------------------
        # Existing Serial
        # -----------------------------

        return {
            "message": "Serial Found",
            "serial_number": serial_number,
            "order_number": order_number,
            "product_type": product_type,
            "current_status": assembly.status,
            "repair_reason": assembly.repair_reason
        }

    except Exception as ex:

        return {
            "error": str(ex)
        }

    finally:

        db.close()

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

        # فقط دو وضعیت مجاز هستند
        if status not in ["OK", "REPAIR"]:
            return {
                "error": "Invalid Status"
            }

        # پیدا کردن Order Code از روی Serial
        parts = serial_number.split("-")

        if len(parts) != 3:
            return {
                "error": "Invalid Serial Number"
            }

        order_number = parts[1]

        # پیدا کردن Product Type
        order_item = db.query(OrderCode).filter(
            OrderCode.order_code == order_number
        ).first()

        if not order_item:
            return {
                "error": "Order Code Not Found"
            }

        product_type = order_item.product_type

        # پیدا کردن رکورد قبلی همین سریال در همین خط
        assembly = db.query(Assembly).filter(
            Assembly.line_id == data.line_id,
            Assembly.serial_number == serial_number
        ).first()

        # اگر محصول قبلاً وجود ندارد
        if not assembly:

            # برای REPAIR باید علت وارد شود
            if status == "REPAIR" and not data.repair_reason:
                return {
                    "error": "Repair Reason Required"
                }

            assembly = Assembly(
                line_id=data.line_id,
                serial_number=serial_number,
                order_number=order_number,
                product_type=product_type,
                status=status,
                repair_reason=data.repair_reason
            )

            db.add(assembly)
            db.commit()
            db.refresh(assembly)

            history = AssemblyHistory(
                assembly_id=assembly.id,
                line_id=data.line_id,
                serial_number=serial_number,
                order_number=order_number,
                product_type=product_type,
                status=status,
                repair_reason=data.repair_reason
            )

            db.add(history)
            db.commit()

            return {
                "message": "Assembly Saved",
                "status": status,
                "order_number": order_number,
                "product_type": product_type
            }


        # --------------------------------
        # محصول قبلاً ثبت شده
        # --------------------------------

        # اگر الان REPAIR است
        if assembly.status == "REPAIR":

            # فقط OK اجازه دارد
            if status != "OK":
                return {
                    "error": "This Order Is Already In Repair"
                }

            # تغییر وضعیت به OK
            assembly.status = "OK"
            assembly.repair_reason = None

            db.commit()

            history = AssemblyHistory(
                assembly_id=assembly.id,
                line_id=data.line_id,
                serial_number=serial_number,
                order_number=order_number,
                product_type=product_type,
                status="OK",
                repair_reason=None
            )

            db.add(history)
            db.commit()

            return {
                "message": "Assembly Returned From Repair",
                "status": "OK",
                "order_number": order_number,
                "product_type": product_type
            }


        # --------------------------------
        # محصول الان OK است
        # --------------------------------

        if assembly.status == "OK":

            if status == "OK":
                return {
                    "error": "This Serial Is Already OK"
                }

            if status == "REPAIR":

                if not data.repair_reason:
                    return {
                        "error": "Repair Reason Required"
                    }

                assembly.status = "REPAIR"
                assembly.repair_reason = data.repair_reason

                db.commit()

                history = AssemblyHistory(
                    assembly_id=assembly.id,
                    line_id=data.line_id,
                    serial_number=serial_number,
                    order_number=order_number,
                    product_type=product_type,
                    status="REPAIR",
                    repair_reason=data.repair_reason
                )

                db.add(history)
                db.commit()

                return {
                    "message": "Assembly Sent To Repair",
                    "status": "REPAIR",
                    "order_number": order_number,
                    "product_type": product_type
                }

        return {
            "error": "Invalid Assembly State"
        }

    except Exception as ex:

        db.rollback()

        return {
            "error": str(ex)
        }

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

        # -----------------------------
        # STOP
        # -----------------------------

        stop_minutes = db.query(
            func.coalesce(
                func.sum(LineStop.stop_minutes),
                0
            )
        ).filter(
            LineStop.line_id == line_id,
            LineStop.created_at >= today
        ).scalar()


        # -----------------------------
        # SWITCH
        # -----------------------------

        switch_count = db.query(
            func.count()
        ).filter(
            SwitchLog.line_id == line_id,
            SwitchLog.created_at >= today
        ).scalar()


        # -----------------------------
        # EXPECTED
        # Same as Packing
        # -----------------------------

        expected_count = calculate_expected_count(
            stop_minutes,
            switch_count
        )


        # -----------------------------
        # PRODUCT TYPES
        # -----------------------------

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


        # -----------------------------
        # STATUS
        # -----------------------------

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


        # -----------------------------
        # ACTUAL
        # -----------------------------

        actual_count = ok_count + repair_count


        aio_equivalent = (
            aio
            + (mnt * 0.60)
            + (case * 0.80)
            + nb
        )

        aio_equivalent = int(aio_equivalent)


        # -----------------------------
        # DIFFERENCE
        # -----------------------------

        difference = aio_equivalent - expected_count

        line = db.query(Line).filter(
            Line.id == line_id
        ).first()


        return {

            "aio": aio,

            "mnt": mnt,

            "case": case,

            "nb": nb,

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

        # --------------------------------
        # Duplicate Serial Check
        # --------------------------------

        duplicate = db.query(Serial).filter(
            Serial.serial_number == serial_number,
            Serial.id != serial_id
        ).first()

        if duplicate:
            return {
                "error": "Serial Already Exists"
            }

        # --------------------------------
        # Extract Order Code
        # --------------------------------

        order_code = None

        parts = order_number.split("-")

        if len(parts) == 3:

            order_code = parts[1]

        else:

            # اگر خود کاربر فقط Order Code وارد کرد
            order_code = order_number


        # --------------------------------
        # Find Order Code
        # --------------------------------

        order_item = db.query(OrderCode).filter(
            OrderCode.order_code == order_code
        ).first()


        if not order_item:

            return {
                "error": f"Order Code Not Found: {order_code}"
            }


        # --------------------------------
        # Product Type
        # --------------------------------

        product_type = order_item.product_type


        # --------------------------------
        # Update Serial
        # --------------------------------

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

        serial_number = data.serial_number.strip()

        if not serial_number:
            return {
                "error": "Serial Number Required"
            }

        # -----------------------------
        # Validate Serial Format
        # -----------------------------

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

        # -----------------------------
        # Check Duplicate Serial
        # -----------------------------

        duplicate = db.query(Assembly).filter(
            Assembly.serial_number == serial_number,
            Assembly.id != assembly_id
        ).first()

        if duplicate:
            return {
                "error": "Serial Already Exists"
            }

        # -----------------------------
        # Find Order Code
        # -----------------------------

        order_item = db.query(OrderCode).filter(
            OrderCode.order_code == order_number
        ).first()

        if not order_item:
            return {
                "error": f"Order Code Not Found: {order_number}"
            }

        product_type = order_item.product_type

        # -----------------------------
        # Validate Status
        # -----------------------------

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

        # -----------------------------
        # Update Assembly
        # -----------------------------

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

        # ==========================================
        # 6 PRODUCTION LINES
        # ==========================================

        for line_id in range(1, 7):

            # ======================================
            # LINE STATUS
            # ======================================

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


            # ======================================
            # STOP
            # ======================================

            stop_minutes = db.query(
                func.coalesce(
                    func.sum(LineStop.stop_minutes),
                    0
                )
            ).filter(
                LineStop.line_id == line_id,
                LineStop.created_at >= today
            ).scalar()

            stop_minutes = int(
                stop_minutes or 0
            )


            # ======================================
            # SWITCH
            # ======================================

            switch_count = db.query(
                func.count()
            ).filter(
                SwitchLog.line_id == line_id,
                SwitchLog.created_at >= today
            ).scalar()

            switch_count = int(
                switch_count or 0
            )


            # ======================================
            # EXPECTED
            # ======================================

            expected_count = calculate_expected_count(
                stop_minutes,
                switch_count
            )


            # ======================================
            # PACK
            # ======================================

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


            pack_actual = (
                pack_aio +
                pack_mnt +
                pack_case +
                pack_nb
            )


            pack_aio_equivalent = int(
                pack_aio +
                (pack_mnt * 0.60) +
                (pack_case * 0.80) +
                pack_nb
            )


            # ======================================
            # ASSEMBLY
            # ======================================

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


            assembly_actual = (
                assembly_aio +
                assembly_mnt +
                assembly_case +
                assembly_nb
            )


            assembly_aio_equivalent = int(
                assembly_aio +
                (assembly_mnt * 0.60) +
                (assembly_case * 0.80) +
                assembly_nb
            )
            # ======================================
            # REPAIR BY PRODUCT
            # ======================================

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

            # ======================================
            # REPAIR
            # ======================================

            repair_count = db.query(
                func.count()
            ).filter(
                Assembly.line_id == line_id,
                Assembly.status == "REPAIR"
            ).scalar()

            repair_count = int(
                repair_count or 0
            )


            # ======================================
            # DIFFERENCE
            # ======================================

            difference = (
                pack_aio_equivalent -
                expected_count
            )


            # ======================================
            # RESULT
            # ======================================

            result.append({

                "line_id": line_id,

                "status": line_status,

                "assembly_product": assembly_product,

                "pack_product": pack_product,

                # ------------------------------
                # PACK
                # ------------------------------

                "pack": {

                    "aio": pack_aio,

                    "mnt": pack_mnt,

                    "case": pack_case,

                    "nb": pack_nb,

                    "actual": pack_actual,

                    "aio_equivalent":
                        pack_aio_equivalent
                },


                # ------------------------------
                # ASSEMBLY
                # ------------------------------

                "assembly": {

                    "aio": assembly_aio,

                    "mnt": assembly_mnt,

                    "case": assembly_case,

                    "nb": assembly_nb,

                    "actual": assembly_actual,

                    "aio_equivalent":
                        assembly_aio_equivalent
                },
                # ------------------------------
                # REPAIR
                # ------------------------------

                "repair": {

                    "aio": repair_aio,

                    "mnt": repair_mnt,

                    "case": repair_case,

                    "nb": repair_nb,

                    "actual": repair_actual
                },


                # ------------------------------
                # PRODUCTION
                # ------------------------------

                "expected":
                    expected_count,

                "difference":
                    difference,


                # ------------------------------
                # STOP / SWITCH
                # ------------------------------

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
        ).first()

        if not line:
            return {
                "error": "Line Not Found"
            }

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

        return [
            {
                "line_id": line.id,
                "name": line.name,
                "status": line.status
            }
            for line in lines
        ]

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
        # 1. بررسی وجود کاربر درخواست‌دهنده
        user = db.query(User).filter(
            User.id == data.user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # 2. فقط سرپرست مجاز است
        if user.role != "supervisor":
            raise HTTPException(
                status_code=403,
                detail="Only supervisors can assign stations"
            )

        # 3. بررسی وجود کارمند فعال
        employee = db.query(Employee).filter(
            Employee.id == data.employee_id,
            Employee.is_active == 1
        ).first()

        if not employee:
            raise HTTPException(
                status_code=404,
                detail="Employee not found or inactive"
            )

        # 4. سرپرست فقط به کارکنان خط خودش دسترسی دارد
        if user.line_id != employee.line_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot manage employees of another line"
            )

        # 5. بررسی مرخصی روزانه یا استعلاجی
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

        # 6. بررسی ایستگاه فعال
        station = db.query(Station).filter(
            Station.id == data.station_id,
            Station.is_active == 1
        ).first()

        if not station:
            raise HTTPException(
                status_code=404,
                detail="Station not found or inactive"
            )

        # 7. ایستگاه باید متعلق به خط کارمند باشد
        if station.line_id != employee.line_id:
            raise HTTPException(
                status_code=400,
                detail="Station does not belong to employee line"
            )

        # 8. بررسی رکورد حضور روزانه
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

        # 9. ثبت تاریخچه فقط در صورت تغییر ایستگاه
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
        # 1. بررسی کاربر درخواست‌دهنده
        user = db.query(User).filter(
            User.id == user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # 2. فقط سرپرست مجاز است
        if user.role != "supervisor":
            raise HTTPException(
                status_code=403,
                detail="Only supervisors can view attendance"
            )

        # 3. سرپرست فقط خط خودش را مشاهده می‌کند
        if user.line_id != line_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot view another line"
            )

        # 4. دریافت همه کارکنان فعال خط
        # حتی افرادی که هنوز رکورد حضور ندارند
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

            # 5. دریافت مرخصی‌های معتبر کارمند در تاریخ انتخاب‌شده
            leaves = db.query(LeaveRecord).filter(
                LeaveRecord.employee_id == employee.id,
                LeaveRecord.start_date <= attendance_date,
                LeaveRecord.end_date >= attendance_date
            ).order_by(
                LeaveRecord.created_at.desc()
            ).all()

            # 6. تعیین مرخصی دارای اولویت
            # اولویت: استعلاجی، روزانه، ساعتی
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

            # 7. تعیین وضعیت نهایی کارمند
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

            # 8. اضافه کردن اطلاعات کارمند به خروجی
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

                # اطلاعات مرخصی
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

        # 9. خروجی نهایی
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
        # بررسی کاربر
        user = db.query(User).filter(
            User.id == user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # فقط سرپرست مجاز است
        if user.role != "supervisor":
            raise HTTPException(
                status_code=403,
                detail="Only supervisors can view history"
            )

        # محدودیت مشاهده به خط خود سرپرست
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
        # 1. بررسی سرپرست
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

        # 2. جلوگیری از ارسال چندباره یک کارمند
        employee_ids = [
            item.employee_id for item in data.assignments
        ]

        if len(employee_ids) != len(set(employee_ids)):
            raise HTTPException(
                status_code=400,
                detail="Duplicate employee IDs are not allowed"
            )

        # 3. بررسی همه تخصیص‌ها قبل از ثبت
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

        # 4. ثبت همه تخصیص‌ها در یک تراکنش
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

        # فقط یک بار Commit
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


@app.get("/api/admin/employees")
def admin_get_employees(
    admin_username: str,
    line_id: int | None = None
):

    db = SessionLocal()

    try:

        verify_admin(db, admin_username)

        query = db.query(Employee)

        if line_id is not None:
            query = query.filter(
                Employee.line_id == line_id
            )

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

        line = db.query(Line).filter(
            Line.id == data.line_id
        ).first()

        if not line:
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )

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

        line = db.query(Line).filter(
            Line.id == data.line_id
        ).first()

        if not line:
            raise HTTPException(
                status_code=404,
                detail="Production line not found"
            )

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

        if user.role != "supervisor":
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

        # سرپرست فقط خط خودش
        if employee.line_id != user.line_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot manage another line"
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

@app.get("/api/admin/personnel-dashboard")
def admin_personnel_dashboard(
    admin_username: str,
    start_date: date | None = None,
    end_date: date | None = None
):
    db = SessionLocal()

    try:
        # فقط ادمین اجازه مشاهده دارد
        verify_admin(db, admin_username)

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
            .join(Line, Employee.line_id == Line.id)
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
                "line_name": line.name,
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
                Employee.line_id == Line.id
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
                "line_name": line.name,
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
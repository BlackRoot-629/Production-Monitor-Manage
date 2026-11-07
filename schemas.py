from pydantic import BaseModel
from datetime import date
from datetime import time

class SerialCreate(BaseModel):

    line_id: int

    order_number: str

    serial_number: str

class StopCreate(BaseModel):

    line_id: int

    stop_minutes: int

class LoginRequest(BaseModel):

    username: str

    password: str

class OrderCodeCreate(BaseModel):

    order_code: str

    product_type: str

    target_quantity: int


class OrderCodeUpdate(BaseModel):
    target_quantity: int

class UserCreate(BaseModel):

    username: str

    password: str

    role: str

    line_id: int | None = None

class UserUpdate(
    BaseModel
):

    role: str

    line_id: int | None = None

class SerialUpdate(BaseModel):

    order_number:str

    serial_number:str

class AssemblyScanCreate(BaseModel):
    line_id: int
    serial_number: str

class AssemblyStatusCreate(BaseModel):
    line_id: int
    serial_number: str
    status: str
    repair_reason: str | None = None


class RepairWorkflowAction(BaseModel):
    line_id: int
    serial_number: str
    username: str


class QualityControlReview(BaseModel):
    line_id: int
    serial_number: str
    username: str
    approved: bool
    note: str | None = None

class LineStatusUpdate(BaseModel):
    status: str
    reason: str | None = None

class ProductNameUpdate(BaseModel):
    product_name: str

class LineBreakTimesUpdate(BaseModel):
    username: str
    tea_time: time | None = None
    lunch_time: time | None = None

from datetime import date
from pydantic import BaseModel


class EmployeeCreate(BaseModel):

    personnel_code: str
    full_name: str
    line_id: int


class StationCreate(BaseModel):

    station_name: str
    line_id: int


class AttendanceAssign(BaseModel):
    employee_id: int
    station_id: int
    attendance_date: date
    user_id: int


class AttendanceStatusUpdate(BaseModel):

    employee_id: int
    attendance_date: date
    status: str

class AdminEmployeeCreate(BaseModel):
    admin_username: str
    personnel_code: str
    full_name: str
    line_id: int | None = None
    unit: str | None = None
    position: str = "STAFF"


class AdminEmployeeUpdate(BaseModel):
    admin_username: str
    personnel_code: str
    full_name: str
    line_id: int | None = None
    unit: str | None = None
    position: str = "STAFF"


class AdminEmployeeStatus(BaseModel):
    admin_username: str
    is_active: int

class AdminStationCreate(BaseModel):
    admin_username: str
    station_name: str
    line_id: int


class AdminStationStatus(BaseModel):
    admin_username: str
    is_active: int

class LeaveCreate(BaseModel):

    user_id: int
    employee_id: int

    leave_type: str

    start_date: date
    end_date: date | None = None

    start_time: time | None = None
    end_time: time | None = None

    notes: str | None = None


class AdminLeaveCreate(BaseModel):
    admin_username: str
    employee_id: int
    leave_type: str
    start_date: date
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    notes: str | None = None



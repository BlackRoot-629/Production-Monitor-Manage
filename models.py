from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Integer, String
from sqlalchemy import DateTime
from datetime import datetime
from sqlalchemy import ForeignKey
from sqlalchemy import DateTime
from datetime import datetime
from sqlalchemy import Date, Time, UniqueConstraint, Index, text, CheckConstraint
from pydantic import BaseModel
from typing import List
from datetime import date

class Base(DeclarativeBase):
    pass


class Line(Base):
    __tablename__ = "lines"

    id = Column(Integer, primary_key=True)

    name = Column(String)

    status = Column(
        String(20),
        default="RUNNING",
        nullable=False
    )

    assembly_product_name = Column(String(200), nullable=True)
    pack_product_name = Column(String(200), nullable=True)
    tea_time = Column(Time, nullable=True)
    lunch_time = Column(Time, nullable=True)

class OrderCode(Base):

    __tablename__ = "order_codes"

    id = Column(Integer, primary_key=True)

    order_code = Column(String(10), unique=True)

    product_type = Column(String(20))   
    target_quantity = Column(Integer, nullable=False, default=0, server_default=text("0"))

class Serial(Base):

    __tablename__ = "serials"

    id = Column(Integer, primary_key=True)

    line_id = Column(Integer, ForeignKey("lines.id"))

    serial_number = Column(String(100), unique=True)

    order_number = Column(String(50))

    order_code = Column(String(10))

    product_type = Column(String(20))

    created_at = Column(DateTime, default=datetime.now)

class LineStop(Base):

    __tablename__ = "line_stops"

    id = Column(Integer, primary_key=True)

    line_id = Column(Integer, ForeignKey("lines.id"))

    stop_minutes = Column(Integer)

    created_at = Column(DateTime, default=datetime.now)
    ended_at = Column(DateTime, nullable=True)
    reason = Column(String(500), nullable=True)

class SwitchLog(Base):

    __tablename__ = "switch_logs"

    id = Column(Integer, primary_key=True)

    line_id = Column(Integer, ForeignKey("lines.id"))

    created_at = Column(DateTime, default=datetime.now)

class User(Base):

    __tablename__ = "users"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    username = Column(
        String,
        unique=True
    )

    password = Column(
        String
    )

    role = Column(
        String
    )

    line_id = Column(
        Integer,
        nullable=True
    )

class Assembly(Base):
    __tablename__ = "assemblies"
    __table_args__ = (
        CheckConstraint(
            "repair_stage IS NULL OR repair_stage IN "
            "('REPAIR_QUEUE', 'IN_REPAIR', 'QC_QUEUE', 'EXIT_QUEUE', 'CLOSED')",
            name="ck_assemblies_repair_stage"
        ),
        Index(
            "uq_assemblies_open_repair_serial",
            "serial_number",
            unique=True,
            postgresql_where=text(
                "repair_stage IN ('REPAIR_QUEUE', 'IN_REPAIR', 'QC_QUEUE', 'EXIT_QUEUE')"
            )
        ),
    )

    id = Column(Integer, primary_key=True)
    line_id = Column(Integer, ForeignKey("lines.id"), nullable=False)

    serial_number = Column(String(100), nullable=False)
    order_number = Column(String(10), nullable=False)
    product_type = Column(String(20), nullable=True)

    status = Column(String(20), nullable=False)

    repair_reason = Column(String(500), nullable=True)

    repair_stage = Column(String(20), nullable=True)
    origin_line_id = Column(Integer, ForeignKey("lines.id"), nullable=False)
    assigned_technician = Column(String(100), nullable=True)
    qc_note = Column(String(500), nullable=True)
    qc_return_count = Column(Integer, default=0, nullable=False)
    workflow_created_at = Column(DateTime, nullable=True)
    repair_started_at = Column(DateTime, nullable=True)
    repair_completed_at = Column(DateTime, nullable=True)
    qc_reviewed_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.now)


class AssemblyHistory(Base):
    __tablename__ = "assembly_history"

    id = Column(Integer, primary_key=True)

    assembly_id = Column(
        Integer,
        ForeignKey("assemblies.id", ondelete="SET NULL"),
        nullable=True
    )

    line_id = Column(Integer, ForeignKey("lines.id"), nullable=False)
    serial_number = Column(String(100), nullable=False)
    order_number = Column(String(10), nullable=False)
    product_type = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False)
    repair_reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class AssemblyWorkflowHistory(Base):
    __tablename__ = "assembly_workflow_history"

    id = Column(Integer, primary_key=True)
    assembly_id = Column(
        Integer,
        ForeignKey("assemblies.id", ondelete="SET NULL"),
        nullable=True
    )
    line_id = Column(Integer, ForeignKey("lines.id"), nullable=False)
    serial_number = Column(String(100), nullable=False)
    from_stage = Column(String(20), nullable=True)
    to_stage = Column(String(20), nullable=False)
    actor_username = Column(String(100), nullable=False)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)


class Employee(Base):

    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            "(line_id IS NOT NULL AND unit IS NULL) OR "
            "(line_id IS NULL AND unit IN ('ADMINISTRATION', 'SUPPORT'))",
            name="ck_employees_line_or_personnel_unit"
        ),
        CheckConstraint(
            "position IN ('SUPERVISOR', 'LOADING', 'STAFF')",
            name="ck_employees_position"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    personnel_code = Column(String(50), unique=True, nullable=False)

    full_name = Column(String(150), nullable=False)

    line_id = Column(
        Integer,
        ForeignKey("lines.id"),
        nullable=True
    )

    # Non-production personnel belong to an administrative unit instead of a line.
    unit = Column(String(30), nullable=True)
    position = Column(String(30), nullable=False, default="STAFF")

    is_active = Column(
        Integer,
        default=1,
        nullable=False
    )


class Station(Base):

    __tablename__ = "stations"

    id = Column(Integer, primary_key=True, index=True)

    station_name = Column(String(150), nullable=False)

    line_id = Column(
        Integer,
        ForeignKey("lines.id"),
        nullable=False
    )

    is_active = Column(
        Integer,
        default=1,
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "line_id",
            "station_name",
            name="uq_station_line_name"
        ),
    )


class DailyAttendance(Base):

    __tablename__ = "daily_attendance"

    id = Column(Integer, primary_key=True, index=True)

    employee_id = Column(
        Integer,
        ForeignKey("employees.id"),
        nullable=False
    )

    attendance_date = Column(Date, nullable=False)

    station_id = Column(
        Integer,
        ForeignKey("stations.id"),
        nullable=True
    )

    status = Column(
        String(30),
        default="PRESENT",
        nullable=False
    )

    updated_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True
    )

    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now
    )

    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "attendance_date",
            name="uq_employee_daily_attendance"
        ),
    )


class AttendanceHistory(Base):

    __tablename__ = "attendance_history"

    id = Column(Integer, primary_key=True, index=True)

    employee_id = Column(
        Integer,
        ForeignKey("employees.id"),
        nullable=False
    )

    attendance_date = Column(Date, nullable=False)

    old_station_id = Column(
        Integer,
        ForeignKey("stations.id"),
        nullable=True
    )

    new_station_id = Column(
        Integer,
        ForeignKey("stations.id"),
        nullable=True
    )

    changed_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    changed_at = Column(
        DateTime,
        default=datetime.now,
        nullable=False
    )

class AttendanceBulkItem(BaseModel):
    employee_id: int
    station_id: int


class AttendanceBulkAssign(BaseModel):
    user_id: int
    attendance_date: date
    assignments: List[AttendanceBulkItem]

class LeaveRecord(Base):

    __tablename__ = "leave_records"

    id = Column(Integer, primary_key=True, index=True)

    employee_id = Column(
        Integer,
        ForeignKey("employees.id"),
        nullable=False
    )

    # DAILY, HOURLY, SICK
    leave_type = Column(
        String(20),
        nullable=False
    )

    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)

    notes = Column(String(500), nullable=True)

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.now,
        nullable=False
    )

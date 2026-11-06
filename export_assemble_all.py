from datetime import datetime
from openpyxl import Workbook

from database import SessionLocal
from models import AssemblyHistory

import os


EXPORT_PATH = r"P:\ProductionReports"


def TodayAssemblyHistory():

    db = SessionLocal()

    try:

        serials = db.query(
           AssemblyHistory
        ).order_by(
            AssemblyHistory.created_at.desc()
        ).all()

        workbook = Workbook()

        sheet = workbook.active

        sheet.title = "Production"

        sheet.append([

            "Date Time",

            "Line",

            "Serial Number",

            "status",

            "Order Number",

            "Product Type"


        ])

        for item in serials:

            sheet.append([

                item.created_at.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),

                item.line_id,

                item.serial_number,

                item.status,

                item.order_number,

                item.product_type

            ])

        summary = workbook.create_sheet(
            "Summary"
        )

        summary.append([
            "Line",
            "Count"
        ])

        total = 0

        for line_id in range(1, 7):

            count = len([

                s for s in serials

                if s.line_id == line_id

            ])

            total += count

            summary.append([

                line_id,

                count

            ])

        summary.append([])

        summary.append([

            "Total Production",

            total

        ])

        os.makedirs(
            EXPORT_PATH,
            exist_ok=True
        )

        filename = (

            f"{EXPORT_PATH}\\"

            f"AssemblyHistory_"

            f"{datetime.now():%Y_%m_%d_%H_%M_%S}.xlsx"

        )

        workbook.save(
            filename
        )

        return filename

    finally:

        db.close()


if __name__ == "__main__":

    TodayAssemblyHistory()
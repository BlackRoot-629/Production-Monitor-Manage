from datetime import datetime
from openpyxl import Workbook

from database import SessionLocal
from models import Serial

import os


EXPORT_PATH = r"P:\ProductionReports"


def export_production():

    db = SessionLocal()

    try:

        today = datetime.now().date()

        serials = db.query(
            Serial
        ).filter(

            Serial.created_at >= today

        ).all()

        workbook = Workbook()

        sheet = workbook.active

        sheet.title = "Production"

        sheet.append([

            "Date Time",

            "Line",

            "Serial Number",

            "Order Number",

            "Order Code",

            "Product Type"

        ])

        for item in serials:

            sheet.append([

                item.created_at.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),

                item.line_id,

                item.serial_number,

                item.order_number,

                item.order_code,

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

        filename = (

            f"{EXPORT_PATH}\\"

            f"Production_"

            f"{datetime.now():%Y_%m_%d}.xlsx"

        )

        os.makedirs(EXPORT_PATH, exist_ok=True)
        
        workbook.save(filename)

        print(

            f"Excel Exported : {filename}"

        )
        return filename

    finally:

        db.close()

    

if __name__ == "__main__":

    export_production()

    
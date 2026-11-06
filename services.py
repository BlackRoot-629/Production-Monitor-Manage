from datetime import datetime, time


def calculate_expected_count(
    stop_minutes: int,
    switch_count: int
):

    now = datetime.now()

    start_time = datetime.combine(
        now.date(),
        time(8, 15)
    )

    end_time = datetime.combine(
        now.date(),
        time(16, 30)
    )

    lunch_start = datetime.combine(
        now.date(),
        time(12, 15)
    )

    lunch_end = datetime.combine(
        now.date(),
        time(13, 0)
    )

    if now < start_time:
        worked_seconds = 0

    elif now > end_time:
        worked_seconds = int(
            (end_time - start_time).total_seconds()
        )

    else:
        worked_seconds = int(
            (now - start_time).total_seconds()
        )

    if now > lunch_start:

        if now < lunch_end:

            worked_seconds -= int(
                (now - lunch_start).total_seconds()
            )

        else:

            worked_seconds -= 2700

    worked_seconds -= stop_minutes * 60

    expected = int(worked_seconds / 225)

    expected -= switch_count * 12

    if expected < 0:
        expected = 0

    return expected
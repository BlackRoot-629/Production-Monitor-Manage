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

    worked_seconds = max(0, worked_seconds - max(0, stop_minutes or 0) * 60)

    expected = worked_seconds // 225

    expected -= max(0, switch_count or 0) * 12

    if expected < 0:
        expected = 0

    return expected


REPAIR_WORKFLOW_TRANSITIONS = {
    None: {"REPAIR_QUEUE"},
    "REPAIR_QUEUE": {"IN_REPAIR"},
    "IN_REPAIR": {"QC_QUEUE"},
    "QC_QUEUE": {"REPAIR_QUEUE", "EXIT_QUEUE"},
    "EXIT_QUEUE": {"CLOSED", "REPAIR_QUEUE"},
    "CLOSED": {"REPAIR_QUEUE"},
}


def validate_repair_transition(current_stage, next_stage):
    allowed = REPAIR_WORKFLOW_TRANSITIONS.get(current_stage, set())
    if next_stage not in allowed:
        raise ValueError(
            f"Invalid repair workflow transition: {current_stage!r} -> {next_stage!r}"
        )

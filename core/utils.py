
import datetime


def time_desc(h=None):
    """返回中文时段：深夜/清晨/上午/中午/下午/晚上"""
    h = (h or datetime.datetime.now().hour) % 24
    return (
        "深夜"
        if h < 6
        else "清晨"
        if h < 9
        else "上午"
        if h < 12
        else "中午"
        if h < 14
        else "下午"
        if h < 18
        else "晚上"
        if h < 22
        else "深夜"
    )

def parse_schedule_time(schedule_time: str | None) -> tuple[int, int]:
    schedule_time = str(schedule_time or "00:00")
    try:
        hour, minute = map(int, schedule_time.split(":", 1))
    except Exception:
        return 0, 0
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return 0, 0


def resolve_business_now(
    schedule_time: str | None,
    now: datetime.datetime | None = None,
) -> datetime.datetime:
    now = now or datetime.datetime.now()
    hour, minute = parse_schedule_time(schedule_time)
    boundary = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < boundary:
        return now - datetime.timedelta(days=1)
    return now


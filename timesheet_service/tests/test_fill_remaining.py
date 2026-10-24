import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from time_manager import TimeManager


def make_timer():
    config = {
        "schedule": {
            "work_start": "07:30",
            "work_end": "16:30",
            "lunch_start": "11:30",
            "lunch_end": "12:30",
            "target_hours": 8,
            "fill_block_minutes": 60,
        }
    }
    return TimeManager(config, None)


def to_min(t):
    return t.hour * 60 + t.minute


def test_full_day_when_empty():
    tm = make_timer()
    slots = tm.calculate_remaining_slots([], target_date=datetime(2026, 9, 22))
    assert slots, "Debe generar bloques para un día vacío"
    assert sum(s["duration_min"] for s in slots) == 480, "Debe sumar 8h"
    for s in slots:
        st = to_min(datetime.strptime(s["start_time"], "%d.%m.%Y %H:%M"))
        et = to_min(datetime.strptime(s["end_time"], "%d.%m.%Y %H:%M"))
        assert not (st < 750 and et > 690), "Cruza el almuerzo"
    print(f"OK test_full_day_when_empty: {len(slots)} bloques, total {sum(s['duration_min'] for s in slots)} min")


def test_no_overlap_and_bounds():
    tm = make_timer()
    registered = [("08:00", "10:00")]
    slots = tm.calculate_remaining_slots(registered, target_date=datetime(2026, 9, 22))

    assert slots, "Debe generar bloques de relleno"

    intervals = []
    for s in slots:
        st = to_min(datetime.strptime(s["start_time"], "%d.%m.%Y %H:%M"))
        et = to_min(datetime.strptime(s["end_time"], "%d.%m.%Y %H:%M"))
        assert et > st
        assert to_min(datetime(2000, 1, 1, 7, 30)) <= st < et <= to_min(datetime(2000, 1, 1, 16, 30)), "Fuera de jornada"
        # No cruzar el almuerzo (11:30-12:30) ni el registro existente
        assert not (st < to_min(datetime(2000, 1, 1, 12, 30)) and et > to_min(datetime(2000, 1, 1, 11, 30))), "Cruza almuerzo"
        assert not (st < 600 and et > 480), "Solapa con registro existente"
        intervals.append((st, et))

    intervals.sort()
    for a, b in zip(intervals, intervals[1:]):
        assert a[1] <= b[0], "Bloques solapados"
    assert sum(e - s for s, e in intervals) <= 360, "No debe superar lo faltante"

    print(f"OK test_no_overlap_and_bounds: {len(slots)} bloques, total {sum(e - s for s, e in intervals)} min")


def test_already_complete():
    tm = make_timer()
    registered = [("07:30", "11:30"), ("12:30", "16:30")]
    slots = tm.calculate_remaining_slots(registered, target_date=datetime(2026, 9, 22))
    assert slots == [], "No debe generar bloques si ya está completo"
    print("OK test_already_complete")


if __name__ == "__main__":
    test_full_day_when_empty()
    test_no_overlap_and_bounds()
    test_already_complete()
    print("TODOS LOS CHECKS PASARON")

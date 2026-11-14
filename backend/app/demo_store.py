"""Process-local stores shared by the demo API routers."""

from threading import Lock

feed_items: list[dict] = []
profiles: dict[str, dict] = {}
calendar_events: dict[tuple[str, str], dict] = {}
seed_lock = Lock()

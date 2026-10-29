"""The manager's planning worker (whole-tree review, 2026-10-29)."""


from ghostcursor import manager


def test_a_finished_planner_counts_as_running_until_its_result_is_taken(monkeypatch):
    import ghostcursor.reasoning.planner as planner

    monkeypatch.setattr(planner, "plan_compiled_goal", lambda goal, **k: "plan")
    worker = manager._PlanningWorker()
    worker.start(manager.LaunchRequest("open the deck", 0))
    worker._thread.join(5)
    assert worker.running  # finished, but its result is unread
    taken = worker.take()
    assert taken.result == "plan" and not worker.running

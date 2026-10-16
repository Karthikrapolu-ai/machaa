"""Task ids, history, and stop."""

from machaa.core.tasks import TaskStore, new_task_id


def test_task_ids_are_unique_and_prefixed():
    first = new_task_id()
    second = new_task_id()
    assert first.startswith("task_")
    assert first != second
    assert len(first) == len("task_") + 32


def test_history_is_reopened_from_the_same_database(settings):
    store = TaskStore(settings.database_path)
    created = store.create("Open Google and search for chairs")
    store.finish(created.id, status="completed", summary="Done.", agent="research", page_url="https://www.google.com/search?q=chairs")
    store.close()

    again = TaskStore(settings.database_path)
    loaded = again.list_recent()
    assert len(loaded) == 1
    assert loaded[0].id == created.id
    assert loaded[0].status == "completed"
    assert loaded[0].page_url.startswith("https://www.google.com/search")
    public = loaded[0].to_public()
    assert "report_path" not in public
    assert "screenshot_path" not in public
    again.close()


def test_stop_on_a_queued_task_finishes_it(settings):
    store = TaskStore(settings.database_path)
    created = store.create("Open Google and search for chairs")
    stopped = store.request_stop(created.id)
    assert stopped is not None
    assert stopped.status == "stopped"
    assert stopped.stop_requested is True
    again = store.request_stop(created.id)
    assert again.status == "stopped"
    store.close()


def test_a_finished_task_is_not_overwritten(settings):
    store = TaskStore(settings.database_path)
    created = store.create("Open Google and search for chairs")
    store.finish(created.id, status="blocked", summary="Blocked.", block_reason="Blocked.")
    store.finish(created.id, status="completed", summary="Should not replace the block.")
    loaded = store.get(created.id)
    assert loaded.status == "blocked"
    assert loaded.summary == "Blocked."
    store.close()


def test_steps_are_kept_in_order(settings):
    store = TaskStore(settings.database_path)
    created = store.create("Visit https://example.com")
    first = store.add_step(created.id, tool="browser.visit_public_page", label="Open the public page", arguments={"url": "https://example.com"}, status="running")
    store.finish_step(first, "completed", "https://example.com")
    second = store.add_step(created.id, tool="browser.screenshot", label="Take a screenshot", arguments={}, status="completed")
    loaded = store.get(created.id)
    assert [step.position for step in loaded.steps] == [1, 2]
    assert loaded.steps[0].id == first
    assert loaded.steps[1].id == second
    store.close()

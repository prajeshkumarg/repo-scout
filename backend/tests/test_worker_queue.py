"""Worker queue wiring. No network: RQ builds a Queue lazily."""

from worker.queue import INDEXING_QUEUE, get_indexing_queue


def test_indexing_queue_has_the_expected_name():
    assert get_indexing_queue().name == INDEXING_QUEUE

from fakeredis import FakeStrictRedis

from worker.app import get_queue
from worker.jobs import ping


def test_worker_executes_job_synchronously():
    queue = get_queue(connection=FakeStrictRedis(), is_async=False)

    job = queue.enqueue(ping)

    assert job.is_finished
    assert job.return_value() == "pong"

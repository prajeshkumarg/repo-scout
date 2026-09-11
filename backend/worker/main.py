"""Worker entrypoint: `python -m worker.main`.

No jobs are defined yet. The process exists so the three-process layout in
`make dev` is real from M0 onward; indexing jobs land in M4.
"""

import logging
import os
import sys

# macOS aborts a forked child that touches the Obj-C runtime, which RQ's
# work-horse does through our native deps (ONNX, psycopg): the job dies
# with signal 6 before it runs a line of our code. The opt-out only
# takes effect if it is set before the process starts, so setting it
# from here means re-execing once. Linux (CI, deploys) is unaffected.
_FORK_SAFETY = "OBJC_DISABLE_INITIALIZE_FORK_SAFETY"
if sys.platform == "darwin" and os.environ.get(_FORK_SAFETY) != "YES":
    os.environ[_FORK_SAFETY] = "YES"
    os.execv(sys.executable, [sys.executable, "-m", "worker.main"])

from rq import Worker  # noqa: E402

from db.conn import connect  # noqa: E402
from db.schema import ensure_schema  # noqa: E402
from worker.queue import EMBEDDING_QUEUE, INDEXING_QUEUE, get_redis  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    """Run an RQ worker against the indexing queue until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # A worker can be the first thing to touch a new database.
    with connect() as conn:
        conn.autocommit = True
        ensure_schema(conn)

    connection = get_redis()
    # Order is priority: RQ takes the first queue with work, checking
    # between jobs. Embedding yields after each batch, so a freshly
    # pasted repo starts cloning one batch later at worst instead of
    # waiting out another repo's whole vector backlog.
    queues = [INDEXING_QUEUE, EMBEDDING_QUEUE]
    logger.info("worker starting, listening on queues %r", queues)
    worker = Worker(queues, connection=connection)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()

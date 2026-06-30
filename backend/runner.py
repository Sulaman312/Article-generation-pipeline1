from datetime import datetime
import logging

from . import artifacts
from . import pipeline

logger = logging.getLogger(__name__)


def run_pipeline(client_id: str, topic: str, verbose: bool = True) -> str:
    from .context_summary import generate_context_summary

    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logger.info(
        "pipeline start client=%s run_id=%s topic=%s",
        client_id,
        run_id,
        topic[:80] + ("…" if len(topic) > 80 else ""),
    )

    context_summary = generate_context_summary(client_id)
    if verbose:
        logger.info("context summary (%s chars)\n%s", len(context_summary), context_summary)

    statuses = {name: "pending" for name in pipeline.STEP_ORDER}
    artifacts.save_run_manifest(client_id, run_id, topic, statuses)

    previous = topic
    for step_name in pipeline.STEP_ORDER:
        run_step = pipeline.STEP_RUNNERS[step_name]
        timings = artifacts.record_step_started(client_id, run_id, step_name)
        statuses[step_name] = "running"
        artifacts.save_run_manifest(
            client_id, run_id, topic, statuses, step_timings=timings
        )
        try:
            previous = run_step(client_id, run_id, previous)
            logger.info(
                "pipeline step done name=%s out_len=%s preview=%s",
                step_name,
                len(previous),
                previous[:120].replace("\n", " "),
            )
            statuses[step_name] = "done"
            timings = artifacts.record_step_finished(
                client_id, run_id, step_name, "done"
            )
            artifacts.save_run_manifest(
                client_id, run_id, topic, statuses, step_timings=timings
            )
        except Exception as e:
            statuses[step_name] = "error"
            timings = artifacts.record_step_finished(
                client_id, run_id, step_name, "error"
            )
            logger.exception("pipeline stopped in step=%s: %s", step_name, e)
            artifacts.save_run_manifest(
                client_id, run_id, topic, statuses, step_timings=timings
            )
            raise

    logger.info(
        "pipeline complete client=%s run_id=%s path=clients/%s/runs/%s/",
        client_id,
        run_id,
        client_id,
        run_id,
    )
    return run_id


if __name__ == "__main__":
    run_pipeline(
        client_id="arsuno",
        topic="how AI improves patient intake in healthcare",
    )

from .processor import process_job


def process_queued_job(job_id: str) -> None:
    """Run one task without retaining business data in the RQ result record."""
    process_job(job_id)

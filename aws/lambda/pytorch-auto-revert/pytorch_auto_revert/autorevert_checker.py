"""
Autorevert pattern detection for PyTorch CI workflows.

Detects pattern where 2 recent commits have same failure and 1 older doesn't.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from .clickhouse_client_helper import CHCliFactory


@dataclass
class JobResult:
    """Job execution result with classification."""

    head_sha: str
    name: str
    conclusion: str
    status: str
    classification_rule: str
    workflow_created_at: datetime


@dataclass
class CommitJobs:
    """All jobs for a single commit."""

    head_sha: str
    created_at: datetime
    jobs: List[JobResult]

    @property
    def failed_jobs(self) -> List[JobResult]:
        """Jobs with failure conclusion and classification rule."""
        return [
            j for j in self.jobs if j.conclusion == "failure" and j.classification_rule
        ]

    @property
    def has_pending_jobs(self) -> bool:
        """Check if any jobs are still pending."""
        return any(j.status == "pending" for j in self.jobs)

    @property
    def job_base_names(self) -> Set[str]:
        if not hasattr(self, "_job_base_names"):
            self._job_base_names = self._get_job_base_names()
        return self._job_base_names

    def normalize_job_name(self, name: str) -> str:
        """Strip shard suffix from job name for matching."""
        # Remove patterns like ", 1, 1, " or ", 2, 3, " from job names
        return re.sub(r", \d+, \d+, ", ", ", name)

    def _get_job_base_names(self) -> Set[str]:
        """Get normalized job names (without shard info)."""
        return {self.normalize_job_name(j.name) for j in self.jobs}


class AutorevertPatternChecker:
    """Detects autorevert patterns in workflow job failures."""

    def __init__(self, workflow_names: List[str] = None, lookback_hours: int = 48):
        self.workflow_names = workflow_names or []
        self.lookback_hours = lookback_hours
        self._workflow_commits_cache: Dict[str, List[CommitJobs]] = {}
        self._commit_history = None

    def get_workflow_commits(self, workflow_name: str) -> List[CommitJobs]:
        """Get workflow commits for a specific workflow, fetching if needed."""
        if workflow_name not in self._workflow_commits_cache:
            self._fetch_workflow_data()
        return self._workflow_commits_cache.get(workflow_name, [])

    @property
    def workflow_commits(self) -> List[CommitJobs]:
        """Get workflow commits for the first workflow (backward compatibility)."""
        if self.workflow_names:
            return self.get_workflow_commits(self.workflow_names[0])
        return []

    @property
    def commit_history(self) -> List[Dict]:
        """Get commit history, fetching if needed."""
        if self._commit_history is None:
            self._fetch_commit_history()
        return self._commit_history or []

    def _fetch_workflow_data(self):
        """Fetch workflow job data from ClickHouse for all workflows in batch."""
        if not self.workflow_names:
            return

        lookback_time = datetime.now() - timedelta(hours=self.lookback_hours)

        print(
            f"Fetching workflow data for {len(self.workflow_names)} workflows since {lookback_time.isoformat()}..."
        )

        query = """
        SELECT
            workflow_name,
            head_sha,
            name,
            conclusion,
            status,
            torchci_classification.rule as classification_rule,
            workflow_created_at
        FROM workflow_job FINAL
        WHERE workflow_name IN {workflow_names:Array(String)}
          AND head_branch = 'main'
          AND workflow_created_at >= {lookback_time:DateTime}
        ORDER BY workflow_name, workflow_created_at DESC, head_sha, name
        """

        result = CHCliFactory().client.query(
            query,
            parameters={
                "workflow_names": self.workflow_names,
                "lookback_time": lookback_time,
            },
        )

        # Group by workflow and commit SHA
        workflow_commits_data = {}
        for row in result.result_rows:
            (
                workflow_name,
                head_sha,
                name,
                conclusion,
                status,
                classification_rule,
                created_at,
            ) = row

            if workflow_name not in workflow_commits_data:
                workflow_commits_data[workflow_name] = {}

            if head_sha not in workflow_commits_data[workflow_name]:
                workflow_commits_data[workflow_name][head_sha] = CommitJobs(
                    head_sha=head_sha, created_at=created_at, jobs=[]
                )

            workflow_commits_data[workflow_name][head_sha].jobs.append(
                JobResult(
                    head_sha=head_sha,
                    name=name,
                    conclusion=conclusion,
                    status=status,
                    classification_rule=classification_rule or "",
                    workflow_created_at=created_at,
                )
            )

        # Sort and cache results per workflow
        for workflow_name, commits_data in workflow_commits_data.items():
            print(
                f"Found {len(commits_data)} commits with job data for workflow '{workflow_name}'"
            )
            self._workflow_commits_cache[workflow_name] = sorted(
                commits_data.values(), key=lambda c: c.created_at, reverse=True
            )

        # Initialize empty lists for workflows with no data
        for workflow_name in self.workflow_names:
            if workflow_name not in self._workflow_commits_cache:
                self._workflow_commits_cache[workflow_name] = []

    def _fetch_commit_history(self):
        """Fetch commit history from push table."""
        lookback_time = datetime.now() - timedelta(hours=self.lookback_hours)

        query = """
        SELECT DISTINCT
            head_commit.id as sha,
            head_commit.message as message,
            head_commit.timestamp as timestamp
        FROM default.push
        WHERE head_commit.timestamp >= {lookback_time:DateTime}
          AND ref = 'refs/heads/main'
        ORDER BY head_commit.timestamp DESC
        """

        result = CHCliFactory().client.query(
            query, parameters={"lookback_time": lookback_time}
        )

        self._commit_history = [
            {"sha": row[0], "message": row[1], "timestamp": row[2]}
            for row in result.result_rows
        ]

    def detect_autorevert_pattern_workflow(self, workflow_name: str) -> List[Dict]:
        """
        Detect all autorevert patterns in commit job data for a specific workflow.

        Pattern: 3 consecutive commits where:
        - 2 newer commits have same exact failure classification
        - 1 older commit doesn't have this failure but has matching jobs
        - All commits have signal (jobs present) and no pending jobs in oldest

        Args:
            workflow_name: The workflow to analyze

        Returns:
            List of all detected patterns
        """
        commits = self.get_workflow_commits(workflow_name)
        if len(commits) < 3:
            return []

        patterns = []

        for i in range(len(commits) - 2):
            newer_commit1 = commits[i]  # Most recent
            newer_commit2 = commits[i + 1]  # Second most recent
            older_commit = commits[i + 2]  # Third most recent

            # All commits must have jobs (signal)
            if not all(c.jobs for c in [newer_commit1, newer_commit2, older_commit]):
                continue

            # Oldest commit cannot have pending jobs
            if older_commit.has_pending_jobs:
                continue

            # Find common failure classifications between the 2 newer commits
            newer1_failures = {j.classification_rule for j in newer_commit1.failed_jobs}
            newer2_failures = {j.classification_rule for j in newer_commit2.failed_jobs}
            common_failures = newer1_failures & newer2_failures

            if not common_failures:
                continue

            # Check if older commit lacks these failures but has overlapping job coverage
            older_failures = {j.classification_rule for j in older_commit.failed_jobs}
            older_job_names = older_commit.get_job_base_names()

            for failure_rule in common_failures:
                if failure_rule in older_failures:
                    continue  # Older commit also has this failure

                # Get job names that had this failure in newer commits
                failed_job_names = set()
                for commit in [newer_commit1, newer_commit2]:
                    for job in commit.failed_jobs:
                        if job.classification_rule == failure_rule:
                            failed_job_names.add(commit.normalize_job_name(job.name))

                # Check if older commit has overlapping job coverage
                if failed_job_names & older_job_names:
                    patterns.append(
                        {
                            "pattern_detected": True,
                            "workflow_name": workflow_name,
                            "failure_rule": failure_rule,
                            "newer_commits": [
                                newer_commit1.head_sha,
                                newer_commit2.head_sha,
                            ],
                            "older_commit": older_commit.head_sha,
                            "failed_job_names": list(failed_job_names),
                            "older_job_coverage": list(
                                older_job_names & failed_job_names
                            ),
                        }
                    )

        return patterns

    def detect_autorevert_pattern(self) -> List[Dict]:
        """
        Detect all autorevert patterns across all configured workflows.

        When the same commits are detected across multiple workflows, the pattern
        is kept once with the first workflow, and other workflows are added to
        an 'additional_workflows' field.

        Returns:
            List of all detected patterns from all workflows (deduplicated)
        """
        all_patterns = []
        seen_commit_pairs = {}  # Map of (commit1, commit2) -> pattern index

        for workflow_name in self.workflow_names:
            patterns = self.detect_autorevert_pattern_workflow(workflow_name)

            for pattern in patterns:
                # Create a key from the two newer commits (order-independent)
                commit_pair = tuple(sorted(pattern["newer_commits"]))

                if commit_pair in seen_commit_pairs:
                    # Add this workflow to the existing pattern's additional_workflows
                    pattern_idx = seen_commit_pairs[commit_pair]
                    existing_pattern = all_patterns[pattern_idx]

                    if "additional_workflows" not in existing_pattern:
                        existing_pattern["additional_workflows"] = []

                    existing_pattern["additional_workflows"].append(
                        {
                            "workflow_name": workflow_name,
                            "failure_rule": pattern["failure_rule"],
                        }
                    )
                else:
                    # First time seeing this commit pair
                    seen_commit_pairs[commit_pair] = len(all_patterns)
                    all_patterns.append(pattern)

        return all_patterns

    def is_commit_reverted(self, target_commit_sha: str) -> Optional[Dict]:
        """
        Check if a commit was reverted within the lookback window.

        Args:
            target_commit_sha: The commit to check for reverting

        Returns:
            Dict with revert information if found, None otherwise
        """
        commits = self.commit_history
        target_time = None

        # Find target commit timestamp
        for commit in commits:
            if commit["sha"] == target_commit_sha:
                target_time = commit["timestamp"]
                break

        if not target_time:
            return None  # Target commit not found

        # Look for revert commits after target commit
        for commit in commits:
            commit_time = commit["timestamp"]

            # Only consider commits after target
            if commit_time <= target_time:
                continue

            message = commit["message"]

            # Check for revert pattern
            if (
                message.startswith('Revert "')
                and f"This reverts commit {target_commit_sha}" in message
            ):
                return {
                    "reverted": True,
                    "revert_sha": commit["sha"],
                    "revert_message": message,
                    "revert_timestamp": commit_time,
                    "hours_after_target": (commit_time - target_time).total_seconds()
                    / 3600,
                }

        return None  # No revert found

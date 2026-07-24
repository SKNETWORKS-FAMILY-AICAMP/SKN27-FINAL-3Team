import json

from django.core.management.base import BaseCommand, CommandError

from chatbot.repositories import get_analysis_job_provenance


class Command(BaseCommand):
    help = "Show operator-safe model, prompt, Agent, and retrieval versions for a job."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", required=True)
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
        )

    def handle(self, *args, **options):
        result = get_analysis_job_provenance(options["job_id"])
        if result is None:
            raise CommandError("analysis_job_not_found")

        if options["format"] == "json":
            self.stdout.write(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
            )
            return

        self.stdout.write(f"job_id: {result['job_id']}")
        self.stdout.write(f"status: {result['status']}")
        self.stdout.write(f"analysis_plan_id: {result['analysis_plan_id']}")
        conversation = result["supervisor"]["conversation"]
        planner = result["supervisor"]["planner"]
        self.stdout.write(
            "supervisor_conversation: "
            f"{conversation['provider']}/{conversation['model']} "
            f"{conversation['prompt_version']}"
        )
        self.stdout.write(
            "supervisor_planner: "
            f"{planner['provider']}/{planner['model']} "
            f"{planner['prompt_version']}"
        )
        for execution in result["executions"]:
            provenance = execution["provenance"]
            self.stdout.write(
                "execution: "
                f"{execution['execution_id']} {execution['node_code']} "
                f"{execution['status']} {provenance['agent_version']} "
                f"{provenance['release_version']}"
            )
        for retrieval in result["retrievals"]:
            provenance = retrieval["data_provenance"]
            embedding = retrieval["embedding"]
            self.stdout.write(
                "retrieval: "
                f"{retrieval['retrieval_event_id']} {retrieval['status']} "
                f"{embedding['provider']}/{embedding['model']}/{embedding['dimensions']} "
                f"{provenance['dataset_version']} "
                f"{provenance['effective_at']} {provenance['retrieved_at']}"
            )

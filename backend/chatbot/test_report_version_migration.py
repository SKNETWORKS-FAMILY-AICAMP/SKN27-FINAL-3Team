from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ReportVersionMigrationTests(TransactionTestCase):
    migrate_from = ("chatbot", "0009_consultation_case_v2")
    migrate_to = ("chatbot", "0010_report_case_version_constraint")

    def setUp(self) -> None:
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        case_model = old_apps.get_model("chatbot", "Case")
        report_model = old_apps.get_model("chatbot", "Report")
        case = case_model.objects.create(
            case_id="case_version_migration",
            owner_id="usr_version_migration",
        )
        for report_id, version_no in (
            ("rep_keep_3", 3),
            ("rep_keep_5", 5),
            ("rep_duplicate_5", 5),
        ):
            report_model.objects.create(
                report_id=report_id,
                owner_id="usr_version_migration",
                case=case,
                version_no=version_no,
            )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self) -> None:
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        super().tearDown()

    def test_migration_preserves_unique_versions_and_audits_only_duplicate_repair(self) -> None:
        case_model = self.apps.get_model("chatbot", "Case")
        report_model = self.apps.get_model("chatbot", "Report")

        versions = dict(
            report_model.objects.filter(case__case_id="case_version_migration")
            .values_list("report_id", "version_no")
        )
        self.assertEqual(
            versions,
            {"rep_keep_3": 3, "rep_keep_5": 5, "rep_duplicate_5": 6},
        )
        changed = report_model.objects.get(report_id="rep_duplicate_5")
        self.assertEqual(
            changed.metadata["version_migration_0010"],
            {"old_version": 5, "new_version": 6},
        )
        self.assertEqual(
            case_model.objects.get(case_id="case_version_migration").current_report_version,
            6,
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        reverted_apps = executor.loader.project_state([self.migrate_from]).apps
        reverted_report_model = reverted_apps.get_model("chatbot", "Report")
        reverted_case_model = reverted_apps.get_model("chatbot", "Case")
        reverted = dict(
            reverted_report_model.objects.filter(case__case_id="case_version_migration")
            .values_list("report_id", "version_no")
        )
        self.assertEqual(
            reverted,
            {"rep_keep_3": 3, "rep_keep_5": 5, "rep_duplicate_5": 5},
        )
        self.assertEqual(
            reverted_case_model.objects.get(
                case_id="case_version_migration"
            ).current_report_version,
            5,
        )

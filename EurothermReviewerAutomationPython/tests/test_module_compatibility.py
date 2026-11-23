"""Preserve imports used by existing scripts after moving implementations."""
from importlib import import_module
from unittest import TestCase


class ModuleCompatibilityTests(TestCase):
    def test_existing_imports_reference_the_domain_implementations(self):
        exports = {
            "workflow": {"application.workflow": ["execute"], "application.run": ["run_command"]},
            "core": {"common.errors": ["WorkflowError"], "common.locking": ["run_lock"],
                     "common.time": ["utc_time", "iso", "now_iso"], "common.logging": ["create_logger"],
                     "application.commands": ["should_import", "should_download"]},
            "uhh": {"instrument.validation": ["hash_file", "validate_file"],
                    "instrument.metadata": ["read_interval"], "instrument.identity": ["select_group"],
                    "instrument.duplicates": ["archived_file", "check_duplicate", "import_evidence"],
                    "instrument.importer": ["assert_import_authorized", "import_single_file"]},
            "diagnostics": {"ui.status": ["reviewer_status", "assert_reviewer_ready"],
                            "health.preflight": ["run_preflight"], "health.readiness": ["readiness_issues"],
                            "health.host": ["disk_and_service_status", "parse_services"]},
            "reporting": {"reports.settings": ["configure_print", "set_custom_check"],
                          "reports.validation": ["verify_text", "verify_boundaries"],
                          "reports.preview": ["validate_preview"], "reports.pdf": ["download_pdf"]},
            "browser": {"ui.browser": ["open_reviewer"]},
            "groups": {"ui.groups": ["all_groups", "group_card"], "ui.batches": ["inspect_batches"]},
            "chart": {"ui.chart": ["select_date", "open_chart"]},
        }
        for facade, modules in exports.items():
            public = import_module(f"reviewer.{facade}")
            for module, names in modules.items():
                implementation = import_module(f"reviewer.{module}")
                for name in names:
                    with self.subTest(module=facade, export=name):
                        self.assertIs(getattr(public, name), getattr(implementation, name))

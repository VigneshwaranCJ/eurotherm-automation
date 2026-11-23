"""Supported commands and import/download policy."""
COMMANDS = ("discover", "diagnostics", "datasources", "file:check", "report:dry", "report", "import:test", "full", "workflow:preview", "workflow:run", "workflow:channels", "workflow:pen", "workflow:messages")


def should_import(command, status):
    return status != "already-imported" and command in {"import:test", "full"}


def should_download(command, dry_run):
    return command == "report" or (command == "full" and not dry_run)

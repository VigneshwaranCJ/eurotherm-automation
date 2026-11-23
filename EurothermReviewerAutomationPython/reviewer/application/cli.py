import argparse
import sys
from ..config import Settings
from .commands import COMMANDS


def main():
    parser = argparse.ArgumentParser(description="Eurotherm Reviewer Python Playwright automation")
    parser.add_argument("command", nargs="?", default="discover", choices=(*COMMANDS, "check-config", "check-env", "workflow:plan", 'batch:scan', 'batch:organize', 'batch:run', 'batch:recover'))
    parser.add_argument("--authorize-import", help="Explicit single-file SHA-256 authorization; never needed for reporting")
    args = parser.parse_args()
    try:
        if args.command == "check-env":
            from ..health.environment import print_environment_report
            return 0 if print_environment_report() else 1
        settings = Settings.load()
        if args.command == 'batch:recover':
            import json
            from ..pipeline.recovery import recover
            print(json.dumps(recover(settings), indent=2))
        elif args.command.startswith('batch:'):
            from ..pipeline.batch import run_batch
            result = run_batch(settings, args.command)
            return 2 if result['status'] == 'Stopped' else 1 if result['failedFiles'] else 0
        elif args.command == 'workflow:plan':
            import json
            from ..pipeline.runner import prepare_pipeline
            config, configured = prepare_pipeline(settings)
            print(json.dumps(dict(config.summary(), selectedInput=str(configured.file)), indent=2))
        elif args.command == "check-config":
            print("Configuration is valid.")
        else:
            from .run import run_command
            run_command(args.command, settings, args.authorize_import)
        return 0
    except Exception as error:
        print(f"{getattr(error, 'code', 'ERROR')}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

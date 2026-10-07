"""Desktop app backend; run with python -m nam2zoom."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .bank import build_bank, load_models, prepare_bank
from .hybrid import classify


def main() -> int:
    parser = argparse.ArgumentParser(prog="nam2zoom")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect-hybrid", help="classify a NAM import")
    inspect.add_argument("model", type=Path)
    inspect.add_argument("--profile", choices=("compact", "lite"), default="compact")

    adapt = sub.add_parser("adapt", help="train a compact 44.1 kHz student")
    adapt.add_argument("model", type=Path)
    adapt.add_argument("--training-di", type=Path, required=True)
    adapt.add_argument("--cache", type=Path, required=True)
    adapt.add_argument("--epochs", type=int, default=100)
    adapt.add_argument("--profile", choices=("compact", "lite"), default="compact")
    adapt.add_argument("--max-esr", type=float, default=0.05)
    adapt.add_argument("--review-quality", action="store_true",
                       help="return quality results for review before using the conversion")
    adapt.add_argument("--prepare-only", action="store_true")
    adapt.add_argument("--ir", type=Path, help="mono WAV cab IR to bake into the student")

    bank = sub.add_parser("build-bank", help="build an offline 1-10 model effect")
    bank.add_argument("models", nargs="+", type=Path)
    bank.add_argument("--label", action="append", dest="labels")
    bank.add_argument("--output", type=Path, required=True)
    bank.add_argument("--profile", choices=("compact", "lite"), default="compact")
    bank.add_argument("--prepare-only", action="store_true")

    install = sub.add_parser("install-bank", help="guarded MS Plus bank replacement")
    install.add_argument("effect", type=Path)
    install.add_argument("--session", type=Path, required=True)
    install.add_argument("--no-backup", action="store_true")
    install.add_argument("--approved-zd2-sha256", required=True)
    install.add_argument("--approved-zic-sha256", required=True)
    install.add_argument("--ack-risk", action="store_true")

    uninstall = sub.add_parser("uninstall-bank", help="guarded MS Plus bank removal")
    uninstall.add_argument("--session", type=Path, required=True)
    uninstall.add_argument("--no-backup", action="store_true")
    uninstall.add_argument("--ack-risk", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "inspect-hybrid":
            print(json.dumps(classify(args.model, args.profile)))
        elif args.command == "adapt":
            from .adapt import adapt as run_adapt

            result = run_adapt(args.model, args.training_di, args.cache,
                               epochs=args.epochs, max_esr=args.max_esr,
                               prepare_only=args.prepare_only,
                               review_quality=args.review_quality, ir=args.ir, profile=args.profile)
            print(f"READY_MODEL={result}")
        elif args.command == "build-bank":
            models = load_models(args.models, args.labels, profile=args.profile)
            manifest = prepare_bank(models, args.output, profile=args.profile)
            print(f"Prepared {len(models)} model(s) in {args.output}")
            if not args.prepare_only:
                effect = build_bank(manifest)
                for artifact in (effect, effect.with_suffix(".ZIC")):
                    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                    print(f"{artifact}: SHA-256 {digest}")
            print("Offline build only; no pedal upload was attempted")
        elif args.command == "install-bank":
            if not args.ack_risk:
                parser.error("install requires --ack-risk")
            from .deploy import install_bank

            install_bank(args.effect, args.session, args.approved_zd2_sha256,
                         args.approved_zic_sha256, full_backup=not args.no_backup)
        elif args.command == "uninstall-bank":
            if not args.ack_risk:
                parser.error("uninstall requires --ack-risk")
            from .deploy import uninstall_bank

            uninstall_bank(args.session, full_backup=not args.no_backup)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"nam2zoom: {args.command} failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

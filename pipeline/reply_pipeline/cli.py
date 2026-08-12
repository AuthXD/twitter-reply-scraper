import argparse
import logging
import sys
from .config import Config
from .adapters import REGISTRY
from . import pipeline, export


def _log():
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")


def cmd_run(args):
    cfg = Config.load(args.config)
    adapter_cls = REGISTRY[args.adapter]
    adapter = adapter_cls(input_path=args.input) if args.adapter == "manual" else adapter_cls()
    stats = pipeline.run(cfg, adapter)
    vetoed = stats.get("vetoed") or {}
    summary = "".join(f" {k}={v}" for k, v in sorted(vetoed.items()))
    print(f"fetched={stats['fetched']} qualified={stats['matched']} "
          f"vetoed={sum(vetoed.values())}{summary} db={stats['db']}")
    if args.out:
        n = export.to_csv(cfg, args.out)
        print(f"exported {n} rows -> {args.out}")


def cmd_export(args):
    cfg = Config.load(args.config)
    n = export.to_csv(cfg, args.out)
    print(f"exported {n} rows -> {args.out}")


def main(argv=None):
    _log()
    p = argparse.ArgumentParser(prog="reply-pipeline",
                                description="Accounts x keyword themes -> qualified targets (authorized sources only)")
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="fetch + filter + score")
    pr.add_argument("--adapter", choices=list(REGISTRY), required=True)
    pr.add_argument("--input", help="input file for the manual adapter (CSV/JSON)")
    pr.add_argument("--out", help="also export qualified rows to this CSV")
    pr.set_defaults(func=cmd_run)

    pe = sub.add_parser("export", help="export qualified rows from the DB")
    pe.add_argument("--out", required=True)
    pe.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

"""steamshelf command line."""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any

from . import auth, cm, credentials, engine, rules, session, store
from . import config as config_mod
from .cache import Cache
from .collections import CollectionSet
from .hltb import HltbClient
from .steamapi import OwnedGame, SteamClient

# Failures a user can act on. Anything else is a bug and deserves its traceback.
EXPECTED = (session.SessionError, store.StoreError, auth.AuthError, cm.CMError,
            credentials.CredentialError)


def _err(message: str) -> int:
    print(f"steamshelf: {message}", file=sys.stderr)
    return 1


def _prompt_guard_code(guard_type: int, hint: str) -> str:
    what = auth.GUARD_NAMES.get(guard_type, "your Steam Guard code")
    suffix = f" ({hint})" if hint else ""
    return input(f"Enter {what}{suffix}: ")


# -- commands ----------------------------------------------------------------


def cmd_login(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    item = args.item or cfg.op_item
    try:
        creds = credentials.load(item, args.vault or cfg.op_vault)
    except credentials.CredentialError as exc:
        return _err(str(exc))

    print(f"Logging in to Steam as {creds.account_name} (credentials from 1Password item {item!r})")
    try:
        result = auth.login(
            creds.account_name,
            creds.password,
            code_provider=_prompt_guard_code,
            on_status=lambda msg: print(f"  {msg}"),
        )
    except auth.AuthError as exc:
        return _err(str(exc))

    saved = session.store(result)
    print(f"Logged in as {saved.account_name} (SteamID {saved.steamid}).")
    print(f"Token saved to {session.TOKEN_PATH}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        current = session.load()
    except session.SessionError as exc:
        return _err(str(exc))
    print(f"Account:  {current.account_name} (SteamID {current.steamid})")
    print(f"Token:    {session.TOKEN_PATH}")
    print(f"Config:   {session.CONFIG_PATH}{'' if session.CONFIG_PATH.exists() else ' (using defaults)'}")

    cache = Cache()
    stats = cache.stats()
    print("Cache:    " + (", ".join(f"{scope}={count}" for scope, count in stats) or "empty"))

    path = store.local_namespace_path(current.steamid3)
    print(f"Steam:    {'running' if store.steam_is_running() else 'not running'}"
          f"{f', mirror at {path}' if path else ''}")
    return 0


def _load_collections(current: session.Session, args: argparse.Namespace) -> CollectionSet:
    if args.source == "local":
        return store.read_local(current.steamid3)
    with store.CloudStore.connect(
        current.account_name, current.refresh_token, current.steamid
    ) as cloud:
        return cloud.read()


def cmd_collections(args: argparse.Namespace) -> int:
    try:
        current = session.load()
        collection_set = _load_collections(current, args)
    except EXPECTED as exc:
        return _err(str(exc))

    rule_config = config_mod.load().rules()
    live = sorted(collection_set.live(), key=lambda c: c.name)
    if args.json:
        print(json.dumps(
            [
                {"id": c.id, "name": c.name, "games": len(c.added),
                 "dynamic": c.is_dynamic, "managed": rule_config.owns(c.name)}
                for c in live
            ],
            indent=2,
        ))
        return 0

    print(f"{len(live)} collections (namespace version {collection_set.namespace_version})\n")
    for collection in live:
        marks = []
        if collection.is_dynamic:
            marks.append("dynamic")
        if collection.is_builtin:
            marks.append("built-in")
        if rule_config.owns(collection.name):
            marks.append("managed")
        note = f"  [{', '.join(marks)}]" if marks else ""
        print(f"  {collection.name:<42} {len(collection.added):>5} games{note}")
    return 0


def _gather(args: argparse.Namespace) -> tuple[Any, ...]:
    """Shared setup for `plan` and `apply`: session, library, collections, plan."""
    current = session.load()
    rule_config = config_mod.load().rules()
    cache = Cache()
    steam = SteamClient(cache, request_delay=args.store_delay)
    hltb = HltbClient(cache, request_delay=args.hltb_delay)

    collection_set = _load_collections(current, args)
    owned = steam.owned_games(current.steamid, current.web_token())
    note = ""
    if args.include_client_apps:
        known = {g.appid for g in owned}
        # Family-shared and never-launched free-to-play titles show in the
        # library but are not "owned", so Steam's API never reports them.
        extra = [OwnedGame(appid=a, name="") for a in sorted(
            store.client_known_appids(current.steamid3) - known)]
        owned.extend(extra)
        note = f" (+{len(extra)} known only to the local client)"
    print(f"Library: {len(owned)} apps{note}; {len(collection_set.live())} collections.")

    targets, membership = engine.select_targets(
        owned, collection_set, rule_config, force_all=args.all
    )
    if args.app:
        wanted = set(args.app)
        targets = [g for g in owned if g.appid in wanted]
    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("Nothing to do - every game already has all its categories.")
        return current, rule_config, collection_set, None

    print(f"Looking up {len(targets)} game(s). This is rate-limited; first runs are slow.\n")

    def progress(index: int, total: int, game: OwnedGame) -> None:
        print(f"  [{index:>4}/{total}] {game.name[:52]}", flush=True)

    plan = engine.build_plan(
        targets, membership, steam, hltb, rule_config,
        progress=None if args.quiet else progress,
    )
    return current, rule_config, collection_set, plan


def _print_plan(plan: engine.Plan, rule_config: rules.RuleConfig, *, verbose: bool) -> None:
    changes = plan.changes(rule_config)
    print(f"\n{len(changes)} game(s) would change; {len(plan.skipped)} skipped.")

    if verbose:
        for item in changes:
            print(f"\n  {item.game.name}  (appid {item.game.appid})")
            if item.hltb:
                print(f"    HLTB {item.hltb.name} - {item.hltb.hours(rule_config.hltb_style)}h "
                      f"(match {item.hltb.confidence:.0%})")
            for name in sorted(item.additions):
                print(f"    + {name}")
            for name in sorted(item.removals(rule_config)):
                print(f"    - {name}")

    deltas = plan.collection_deltas(rule_config)
    if deltas:
        print("\nCollection changes:")
        for name in sorted(deltas):
            add, remove = deltas[name]
            bits = []
            if add:
                bits.append(f"+{len(add)}")
            if remove:
                bits.append(f"-{len(remove)}")
            print(f"  {name:<42} {' '.join(bits)}")

    if plan.retry_later:
        reasons = Counter(reason.split(":")[0] for _game, reason in plan.retry_later)
        print(f"\n{len(plan.retry_later)} game(s) left as they are and worth a re-run: "
              + ", ".join(f"{count} {reason}" for reason, count in reasons.most_common()))

    if plan.skipped:
        reasons = Counter(reason for _game, reason in plan.skipped)
        print("\nSkipped: " + ", ".join(f"{count} {reason}" for reason, count in reasons.most_common()))


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        _current, rule_config, _collections, plan = _gather(args)
    except EXPECTED as exc:
        return _err(str(exc))
    if plan is None:
        return 0
    _print_plan(plan, rule_config, verbose=not args.quiet)
    print("\nThis was a dry run. Use `steamshelf apply` to write these collections.")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        current, rule_config, collection_set, plan = _gather(args)
    except EXPECTED as exc:
        return _err(str(exc))
    if plan is None:
        return 0

    _print_plan(plan, rule_config, verbose=args.verbose)
    if not plan.changes(rule_config):
        print("\nNothing to write.")
        return 0

    if not args.yes:
        answer = input("\nWrite these changes to your Steam account? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    touched = engine.apply_plan(plan, collection_set, rule_config)
    print(f"\nUploading {len(touched)} collection(s)...")
    try:
        with store.CloudStore.connect(
            current.account_name, current.refresh_token, current.steamid
        ) as cloud:
            # Re-read first: the running client may have moved on since we
            # planned, and an upload replaces whole collections.
            raw = cloud.read_raw()
            saved = store.write_snapshot(raw, store.snapshot_path(current.steamid))
            print(f"Backed up current collections to {saved}")

            fresh = CollectionSet.from_entries(
                raw.get("entries", []), namespace_version=int(raw.get("version", 0))
            )
            merged = engine.apply_plan(plan, fresh, rule_config)
            version = cloud.write(merged, fresh.namespace_version)
    except EXPECTED as exc:
        return _err(f"upload failed: {exc}")

    print(f"Done. Namespace is now at version {version}.")
    print("Steam picks the change up on its next sync; restart the client if you "
          "want to see it immediately.")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    try:
        current = session.load()
        with store.CloudStore.connect(
            current.account_name, current.refresh_token, current.steamid
        ) as cloud:
            raw = cloud.read_raw()
    except EXPECTED as exc:
        return _err(str(exc))

    target = Path(args.output) if args.output else store.snapshot_path(current.steamid)
    saved = store.write_snapshot(raw, target)
    collections = sum(1 for e in raw.get("entries", []) if e["key"].startswith("user-collections."))
    print(f"Saved {collections} collections (namespace version {raw.get('version', 0)}) to {saved}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    if args.show:
        print(session.CONFIG_PATH.read_text() if session.CONFIG_PATH.exists()
              else config_mod.DEFAULT_TOML)
        return 0
    created = config_mod.write_default(force=args.force)
    if created:
        print(f"Wrote {session.CONFIG_PATH}")
    else:
        print(f"{session.CONFIG_PATH} already exists; pass --force to overwrite.")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    cache = Cache()
    if args.clear:
        removed = cache.clear(args.scope)
        print(f"Cleared {removed} cached entries" + (f" in {args.scope}" if args.scope else ""))
        return 0
    for scope, count in cache.stats():
        print(f"  {scope:<12} {count}")
    return 0


# -- argument parsing --------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steamshelf",
        description="File uncategorized Steam games into collections by how long "
                    "they take to beat, what they run on, and how they review.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            typical use:
              steamshelf login          # reads your Steam password from 1Password
              steamshelf plan           # dry run: show what would change
              steamshelf apply          # write the collections to your account
            """),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="log in to Steam using credentials from 1Password")
    login.add_argument("--item", help="1Password item name, UUID or op:// reference")
    login.add_argument("--vault", help="1Password vault to search")
    login.set_defaults(func=cmd_login)

    status = sub.add_parser("status", help="show the stored session, config and cache")
    status.set_defaults(func=cmd_status)

    for name, help_text, func in (
        ("plan", "show what would change without writing anything", cmd_plan),
        ("apply", "write category collections to your Steam account", cmd_apply),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--all", action="store_true",
                         help="re-categorize every owned game, not just uncategorized ones")
        cmd.add_argument("--app", type=int, action="append", metavar="APPID",
                         help="only consider this app id (repeatable)")
        cmd.add_argument("--limit", type=int, help="stop after this many games")
        cmd.add_argument("--include-client-apps", action="store_true",
                         help="also consider apps the installed Steam client knows about "
                              "but the account does not own - family-shared titles and "
                              "never-launched free-to-play games")
        cmd.add_argument("--source", choices=("cloud", "local"), default="cloud",
                         help="read existing collections from Steam's cloud (default) "
                              "or the local client mirror")
        cmd.add_argument("--store-delay", type=float, default=1.4, metavar="SECONDS",
                         help="pause between Steam storefront requests (default: 1.4)")
        cmd.add_argument("--hltb-delay", type=float, default=0.6, metavar="SECONDS",
                         help="pause between HowLongToBeat requests (default: 0.6)")
        cmd.add_argument("-q", "--quiet", action="store_true", help="less output")
        if name == "apply":
            cmd.add_argument("-y", "--yes", action="store_true", help="do not ask before writing")
            cmd.add_argument("-v", "--verbose", action="store_true",
                             help="list every game's changes")
        cmd.set_defaults(func=func)

    collections = sub.add_parser("collections", help="list your Steam collections")
    collections.add_argument("--source", choices=("cloud", "local"), default="local")
    collections.add_argument("--json", action="store_true")
    collections.set_defaults(func=cmd_collections)

    backup = sub.add_parser("backup", help="save a raw copy of your collections")
    backup.add_argument("-o", "--output", help="file to write (default: under the cache dir)")
    backup.set_defaults(func=cmd_backup)

    conf = sub.add_parser("config", help="create or show the configuration file")
    conf.add_argument("--show", action="store_true", help="print the active configuration")
    conf.add_argument("--force", action="store_true", help="overwrite an existing config")
    conf.set_defaults(func=cmd_config)

    cache = sub.add_parser("cache", help="inspect or clear the metadata cache")
    cache.add_argument("--clear", action="store_true")
    cache.add_argument("--scope", choices=("appdetails", "reviews", "deck", "hltb"))
    cache.set_defaults(func=cmd_cache)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

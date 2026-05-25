import argparse

from app.database.db import init_db, get_session
from app.services.wishlist import WishlistService


def parse_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None

    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed or None


def print_entry(entry) -> None:
    print(f"{entry.id}: {entry.title} [{entry.platform}]")
    print(f"  URL: {entry.source_url}")
    print(f"  Status: {'active' if entry.is_active else 'inactive'}")
    print(f"  Sizes: {WishlistService.get_size_scope(entry)}")
    print(f"  Platforms: {WishlistService.get_platforms_to_track(entry)}")
    if entry.notes:
        print(f"  Notes: {entry.notes}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage wishlist entries")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add a new wishlist entry")
    add_parser.add_argument("--url", required=True)
    add_parser.add_argument("--brand", required=True)
    add_parser.add_argument("--model", required=True, dest="model_name")
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--platforms", help="Comma-separated platforms to track")
    add_parser.add_argument("--sizes", help="Comma-separated sizes to track")
    add_parser.add_argument("--notes")

    list_parser = subparsers.add_parser("list", help="List all wishlist entries")
    list_parser.add_argument("--include-inactive", action="store_true")

    disable_parser = subparsers.add_parser("disable", help="Disable a wishlist entry")
    disable_parser.add_argument("--url", required=True)

    enable_parser = subparsers.add_parser("enable", help="Enable a wishlist entry")
    enable_parser.add_argument("--url", required=True)

    delete_parser = subparsers.add_parser("delete", help="Delete a wishlist entry")
    delete_parser.add_argument("--url", required=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    init_db()
    session = get_session()

    try:
        if args.command == "add":
            entry = WishlistService.add_from_url(
                session,
                url=args.url,
                brand=args.brand,
                model_name=args.model_name,
                title=args.title,
                platforms_to_track=parse_csv(args.platforms),
                size_scope=parse_csv(args.sizes),
                notes=args.notes,
            )
            print(f"Added wishlist entry {entry.id}: {entry.title}")
            return

        if args.command == "list":
            entries = WishlistService.get_all(session)
            if not entries:
                print("No wishlist entries found.")
                return

            for entry in entries:
                if entry.is_active or args.include_inactive:
                    print_entry(entry)
                    print()
            return

        if args.command == "disable":
            updated = WishlistService.set_active(session, args.url, False)
            if updated is None:
                print(f"No wishlist entry found for {args.url}")
                return

            print(f"Disabled wishlist entry {updated.id}: {updated.title}")
            return

        if args.command == "enable":
            updated = WishlistService.set_active(session, args.url, True)
            if updated is None:
                print(f"No wishlist entry found for {args.url}")
                return

            print(f"Enabled wishlist entry {updated.id}: {updated.title}")
            return

        if args.command == "delete":
            deleted = WishlistService.delete(session, args.url)
            if not deleted:
                print(f"No wishlist entry found for {args.url}")
                return

            print(f"Deleted wishlist entry for {args.url}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
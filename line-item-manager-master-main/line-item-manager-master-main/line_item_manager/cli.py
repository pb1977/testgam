"""Console script for line_item_manager."""
from functools import partial
import sys

import click

from . import version as VERSION
from .app_runner import CreateOptions, LineItemManagerUsageError, create_line_items, list_bidders, read_resource

# 🛠️ GLOBAL TWEAK: This makes the help menu automatically show default values for all options.
click.option = partial(click.option, show_default=True)

# ==========================================================
# 🌳 THE TRUNK: The main "Group" command
# ==========================================================
@click.group(invoke_without_command=True)  # @click.group(...) makes cli the top-level command group, like: line_item_manager create, invoke_without_command=True means: If the user runs just line_item_manager with no subcommand, Click still calls cli().
@click.option('--version', is_flag=True, help='Print version information and exit.')
@click.pass_context # <--- Gives this function a "Passport" (ctx) to see its own subcommands
def cli(ctx: click.core.Context, version: bool) -> None:
    if version:
        print(f'line-item-manager version {VERSION}')
        return
    # 📋 If user didn't type 'create' or 'show', just show the Help manual
    if not ctx.invoked_subcommand:
        click.echo(cli.get_help(ctx))

# ==========================================================
# 🚀 THE 'CREATE' BRANCH: This does the heavy lifting
# ==========================================================
@cli.command() # this creates a subcommand to cli
# 📄 Required: The YAML file with your ad settings
@click.argument('configfile', type=click.Path(exists=True))
# 🏢 Optional: Network settings (can also be inside the YAML)
@click.option('--network-code', type=int, help='GAM network code...')
@click.option('--network-name', help='GAM network name...')
# 🔑 Required: The JSON file that acts as your login key
@click.option('--private-key-file', '-k', required=True, default='gam_creds.json',
              type=click.Path(exists=True), help='Path to json GAM credentials file.')
# 🧬 Advanced: Custom templates/schemas
@click.option('--template', type=click.Path(exists=True), help='Path to custom line item template.')
@click.option('--settings', type=click.Path(exists=True), help='Path to settings file.')
@click.option('--schema', type=click.Path(exists=True), help='Path to schema file.')
# 🔀 Logic Flags: How should the orders be structured?
@click.option('--single-order', '-s', is_flag=True, help='One order for ALL bidders.')
@click.option('--bidder-code', '-b', multiple=True, help='Specific bidder (can use multiple times).')
# 🧪 Safety Flags: Run without actually changing anything in GAM
@click.option('--test-run', '-t', is_flag=True, help='Creates limited items with "Test:" prefix.')
@click.option('--dry-run', '-n', is_flag=True, help='Print what WOULD happen, but do nothing.')
# 🔊 Logging Flags: How much info to print in the terminal
@click.option('--quiet', '-q', is_flag=True, help='Only show errors.')
@click.option('--verbose', '-v', multiple=True, is_flag=True, help='Show more detail (-vv for even more).')
@click.option('--skip-auto-archive', is_flag=True, help='Do NOT delete progress if script fails.')
@click.pass_context
def create(ctx: click.core.Context, configfile: str, **kwargs):
    """Create line items"""
    try:
        create_line_items(
            CreateOptions(
                configfile=configfile,
                network_code=kwargs.get("network_code"),
                network_name=kwargs.get("network_name"),
                private_key_file=kwargs.get("private_key_file"),
                template=kwargs.get("template"),
                settings=kwargs.get("settings"),
                schema=kwargs.get("schema"),
                single_order=kwargs.get("single_order", False),
                bidder_codes=kwargs.get("bidder_code"),
                test_run=kwargs.get("test_run", False),
                dry_run=kwargs.get("dry_run", False),
                quiet=kwargs.get("quiet", False),
                verbose=kwargs.get("verbose"),
                skip_auto_archive=kwargs.get("skip_auto_archive", False),
            )
        )
    except LineItemManagerUsageError as exc:
        raise click.UsageError(str(exc), ctx=ctx)

# ==========================================================
# 🔍 THE 'SHOW' BRANCH: Peek at internal default files
# ==========================================================
@cli.command()
@click.argument('resource', type=click.Choice(['config', 'bidders', 'template', 'settings', 'schema']))
def show(resource: str) -> None:
    """Show resources"""
    if resource == 'bidders':
        print("%-25s%s" % ('Code', 'Name'))
        print("%-25s%s" % ('----', '----'))
        for row in list_bidders():
            print("%-25s%s" % (row['bidder-code'], row['bidder-name']))
        return
    print(read_resource(resource))

# ==========================================================
# 🚦 ENTRY POINT: Where Python starts the engine
# ==========================================================
def main():
    cli() # Start the Root command

if __name__ == "__main__":
    sys.exit(main())

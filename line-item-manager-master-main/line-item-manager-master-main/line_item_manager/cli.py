"""Console script for line_item_manager."""
from functools import partial
import json
import pkg_resources
import sys

import click
from googleads.errors import GoogleAdsError
import yaml

from . import version as VERSION
from .config import config
from .exceptions import ResourceNotActive, ResourceNotFound
from .gam_config import GAMConfig
from .gam_operations import client as gam_client
from .prebid import prebid, PrebidBidder
from .validate import Validator

# 🛠️ GLOBAL TWEAK: This makes the help menu automatically show default values for all options.
click.option = partial(click.option, show_default=True)

logger = config.getLogger(__name__)

# ==========================================================
# 🌳 THE TRUNK: The main "Group" command
# ==========================================================
@click.group(invoke_without_command=True)
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
@cli.command()
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
    # 📥 DATA HANDOFF: Move all terminal flags into our central Config "Brain"
    config.cli = kwargs

    # 1️⃣ LOAD YAML: Parse your settings file
    try:
        config.set_user_configfile(configfile)
    except yaml.YAMLError as e:
        raise click.UsageError(f'Check your configfile. {e}', ctx=ctx)

    gam = GAMConfig()

    # 2️⃣ LOGIC CHECK: Ensure user didn't pick conflicting options
    if not kwargs['single_order'] and not kwargs['bidder_code']:
        raise click.UsageError('You must use --single-order or provide at least one --bidder-code', ctx=ctx)

    if kwargs['single_order'] and kwargs['bidder_code']:
        raise click.UsageError('Use of --single-order and --bidder-code is not allowed.', ctx=ctx)

    # 3️⃣ LOGIN CHECK: Try to connect to Google
    config.set_client_factory(gam_client)
    try:
        config.client # This triggers the JSON key read and OAuth login
    except Exception:
        raise click.UsageError('Check your private key file. Access failed.', ctx=ctx)

    # 4️⃣ NETWORK CHECK: Does the ID you gave match the name Google has?
    try:
        if not gam.network['displayName'] == config.network_name:
            raise click.UsageError(f"Network name mismatch!", ctx=ctx)
    except GoogleAdsError as _e:
        logger.error(f'GoogleAdsError, {_e}')
        raise click.UsageError('Access denied to Google account.', ctx=ctx)

    # 5️⃣ SCHEMA CHECK: Does your YAML follow the required structure rules?
    user_cfg = Validator(config.schema, config.user)
    if not user_cfg.is_valid():
        err_str = '\n'.join([f'  - {user_cfg.fmt(_e)}' for _e in user_cfg.errors()])
        raise click.UsageError(f'Validation errors:\n{err_str}', ctx=ctx)

    # 6️⃣ PRE-CREATE: Calculate dates and expand price buckets
    try:
        config.pre_create()
    except ValueError as e:
        raise click.UsageError(f'{e}', ctx=ctx)

    # 7️⃣ EXECUTION: Talk to the Google API and build the items
    try:
        gam.create_line_items()
        gam.success = True
    except (ResourceNotActive, ResourceNotFound, GoogleAdsError) as _e:
        logger.error('Failed to create resources: %s', _e)
    except KeyboardInterrupt:
        logger.warning('User stopped the script.')
    finally:
        # 🧹 CLEANUP: If things broke, archive the messy half-finished orders
        try:
            gam.cleanup()
        except GoogleAdsError as _e:
            logger.error('Cleanup failed: %s', _e)

# ==========================================================
# 🔍 THE 'SHOW' BRANCH: Peek at internal default files
# ==========================================================
def show_resource(filename: str) -> None:
    """Helper to find and print files hidden inside the package."""
    rsrc_name = pkg_resources.resource_filename('line_item_manager', filename)
    with open(rsrc_name) as fp:
        print(fp.read())

@cli.command()
@click.argument('resource', type=click.Choice(['config', 'bidders', 'template', 'settings', 'schema']))
def show(resource: str) -> None:
    """Show internal resources for reference."""
    if resource == 'config':
        show_resource('conf.d/line_item_manager.yml')
    elif resource == 'bidders':
        # Lists all Prebid bidders the tool knows about
        print("%-25s%s" % ('Code', 'Name'))
        for row in sorted(prebid.bidders.values(), key=lambda x: x['bidder-code']):
            print("%-25s%s" % (row['bidder-code'], row['bidder-name']))
    else:
        show_resource(f'conf.d/{resource}.yml')

# ==========================================================
# 🚦 ENTRY POINT: Where Python starts the engine
# ==========================================================
def main():
    cli() # Start the Root command

if __name__ == "__main__":
    sys.exit(main())

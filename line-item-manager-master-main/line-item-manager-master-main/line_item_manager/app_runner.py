from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Union

import yaml
from googleads.errors import GoogleAdsError

from .config import config
from .exceptions import ResourceNotActive, ResourceNotFound
from .gam_config import GAMConfig
from .gam_operations import client as gam_client
from .prebid import prebid, PrebidBidder
from .utils import read_package_file
from .validate import Validator

logger = config.getLogger(__name__)

RESOURCE_MAP = {
    "config": "line_item_manager.yml",
    "template": "line_item_template.yml",
    "settings": "settings.yml",
    "schema": "schema.yml",
}


class LineItemManagerUsageError(Exception):
    """User-facing error for invalid input or access issues."""


@dataclass
class CreateOptions:
    configfile: str
    network_code: Optional[int] = None
    network_name: Optional[str] = None
    private_key_file: str = "gam_creds.json"
    template: Optional[str] = None
    settings: Optional[str] = None
    schema: Optional[str] = None
    single_order: bool = False
    bidder_codes: Sequence[str] = field(default_factory=list)
    test_run: bool = False
    dry_run: bool = False
    quiet: bool = False
    verbose: Union[int, Sequence[bool], None] = field(default_factory=list)
    skip_auto_archive: bool = False

    def normalized_cli(self) -> dict:
        return {
            "network_code": self.network_code,
            "network_name": self.network_name,
            "private_key_file": self.private_key_file,
            "template": self.template,
            "settings": self.settings,
            "schema": self.schema,
            "single_order": self.single_order,
            "bidder_code": list(self.bidder_codes or []),
            "test_run": self.test_run,
            "dry_run": self.dry_run,
            "quiet": self.quiet,
            "verbose": _normalize_verbose(self.verbose),
            "skip_auto_archive": self.skip_auto_archive,
        }


@dataclass
class CreateResult:
    success: bool
    errors: List[str]
    line_item_count: int
    lica_count: int
    line_items: List[dict] = field(default_factory=list)
    licas: List[List[dict]] = field(default_factory=list)


def _normalize_verbose(verbose: Union[int, Sequence[bool], None]) -> List[bool]:
    if isinstance(verbose, int):
        return [True] * verbose
    if not verbose:
        return []
    return list(verbose)


def _reset_config_cache() -> None:
    config._schema = None
    config._cpm_names = None
    config._app = None
    config._client = None
    config._user = None


def create_line_items(options: CreateOptions, include_details: bool = False) -> CreateResult:
    _reset_config_cache()
    config.cli = options.normalized_cli()

    try:
        config.set_user_configfile(options.configfile)
    except yaml.YAMLError as exc:
        raise LineItemManagerUsageError(f"Check your configfile. {exc}") from exc

    gam = GAMConfig()

    if not config.cli["single_order"] and not config.cli["bidder_code"]:
        raise LineItemManagerUsageError(
            "You must use --single-order or provide at least one --bidder-code"
        )

    if config.cli["single_order"] and config.cli["bidder_code"]:
        raise LineItemManagerUsageError(
            "Use of --single-order and --bidder-code is not allowed."
        )

    config.set_client_factory(gam_client)
    try:
        _ = config.client
    except Exception as exc:
        raise LineItemManagerUsageError("Check your private key file. Access failed.") from exc

    try:
        if not gam.network["displayName"] == config.network_name:
            raise LineItemManagerUsageError("Network name mismatch!")
    except GoogleAdsError as exc:
        logger.error("GoogleAdsError, %s", exc)
        raise LineItemManagerUsageError("Access denied to Google account.") from exc

    user_cfg = Validator(config.schema, config.user)
    if not user_cfg.is_valid():
        err_str = "\n".join([f"  - {user_cfg.fmt(_e)}" for _e in user_cfg.errors()])
        raise LineItemManagerUsageError(f"Validation errors:\n{err_str}")

    try:
        PrebidBidder.validate_override_map(config.user.get("bidder_key_map"))
    except ValueError as exc:
        raise LineItemManagerUsageError(f"{exc}") from exc

    try:
        config.pre_create()
    except ValueError as exc:
        raise LineItemManagerUsageError(f"{exc}") from exc

    errors: List[str] = []
    try:
        gam.create_line_items()
        gam.success = True
    except ResourceNotActive as exc:
        logger.error("Resource is not active:\n  - %s", exc)
        errors.append(f"Resource is not active: {exc}")
    except ResourceNotFound as exc:
        logger.error("Not able to find the following resource:\n  - %s", exc)
        errors.append(f"Resource not found: {exc}")
    except GoogleAdsError as exc:
        logger.error("Google Ads Error, %s", exc)
        errors.append(f"Google Ads Error: {exc}")
    except ValueError as exc:
        logger.error("Unexpected result, %s", exc)
        errors.append(f"Unexpected result: {exc}")
    except KeyboardInterrupt:
        logger.warning("User Interrupt")
        errors.append("User Interrupt")
    finally:
        try:
            gam.cleanup()
        except GoogleAdsError as exc:
            logger.error("Cleanup: Google Ads Error, %s", exc)
            errors.append(f"Cleanup: Google Ads Error: {exc}")

    line_items: List[dict] = []
    line_item_count = 0
    for li_obj in gam.li_objs:
        items = getattr(li_obj, "_line_items", None) or []
        line_item_count += len(items)
        if include_details:
            line_items.extend(items)

    lica_count = sum(len(licas) for licas in gam.lica_objs)
    licas = list(gam.lica_objs) if include_details else []

    return CreateResult(
        success=gam.success and not errors,
        errors=errors,
        line_item_count=line_item_count,
        lica_count=lica_count,
        line_items=line_items,
        licas=licas,
    )


def read_resource(resource: str) -> str:
    if resource not in RESOURCE_MAP:
        raise ValueError(f"Unknown resource '{resource}'")
    return read_package_file(RESOURCE_MAP[resource])


def list_bidders() -> List[dict]:
    return sorted(prebid.bidders.values(), key=lambda x: x["bidder-code"])

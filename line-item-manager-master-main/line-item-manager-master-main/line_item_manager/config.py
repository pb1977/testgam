from datetime import datetime
import logging
from typing import Callable, Dict, List, Iterable, Optional, Union
import pytz

from googleads import ad_manager

# 🛠️ UTILS: These are helper functions imported from other files in the package.
# They handle things like loading files and calculating price buckets.
from .yaml_date import date_from_string
from .utils import values_from_bucket, ichunk, load_file, load_package_file, read_package_file

logging.basicConfig()

# 🔊 CUSTOM LOG LEVELS: Defining "extra loud" logging levels for troubleshooting.
VERBOSE1: int = logging.INFO - 1
VERBOSE2: int = logging.INFO - 2

class Config:
    """
    THE BRAIN: This class stores the 'state' of the application. 
    It holds your settings, your login credentials, and your pricing logic.
    """

    def __init__(self):
        self._schema = None
        self._cpm_names = None
        self._app = None
        self._start_time = datetime.now()
        self.set_logger()

    # ==========================================================
    # 📢 LOGGING SETUP: Controls how much the script "talks"
    # ==========================================================
    def isLoggingEnabled(self, level: int) -> bool:
        return self._logger.getEffectiveLevel() <= level

    def set_logger(self) -> None:
        self._logger = logging.getLogger(__package__)
        self._logger.setLevel(logging.INFO)
        logging.addLevelName(VERBOSE1, 'VERBOSE1')
        logging.addLevelName(VERBOSE2, 'VERBOSE2')

    def getLogger(self, name: str) -> logging.Logger:
        return self._logger.getChild(name.split('.')[-1])

    def set_log_level(self) -> None:
        """Translates terminal flags like -v or -q into actual logging levels."""
        if self.cli.get('verbose'):
            self._logger.setLevel(logging.INFO - len(self.cli['verbose']))
        if self.cli.get('quiet'):
            self._logger.setLevel(logging.WARNING)

    # ==========================================================
    # 🔑 AUTH & CLI: Handling inputs from the user
    # ==========================================================
    @property
    def app(self) -> dict:
        """Loads internal tool settings (settings.yml)."""
        if self._app is None:
            self._app = self.settings_obj()
        return self._app

    @property
    def cli(self) -> dict:
        """The dictionary of flags passed from cli.py."""
        return self._cli

    @cli.setter
    def cli(self, obj) -> None:
        """When CLI flags are set, we reset the client to ensure fresh login settings."""
        self._cli = obj
        self._client = None
        self.set_log_level()

    @property
    def client(self) -> Optional[ad_manager.AdManagerClient]:
        """🌐 THE API CONNECTION: Creates the actual link to Google Ad Manager."""
        if self._client is None:
            self._client = self._client_factory(self.network_code, self.cli['private_key_file'])
        return self._client

    @property
    def user(self) -> dict:
        """The data loaded from your user config YAML file."""
        return self._user

    def set_client_factory(self, factory: Callable) -> None:
        self._client = None
        self._client_factory = factory

    def set_user_configfile(self, filename: str) -> None:
        """Loads your specific ad setup YAML file into memory."""
        self._user = load_file(filename)
        self._client = None
        self._cpm_names = None

    # ==========================================================
    # 🎯 TARGETING & PRICING: The logic for the line items
    # ==========================================================
    @property
    def network_code(self) -> int:
        """Checks the terminal flag first, then falls back to the YAML file."""
        return self.cli['network_code'] or self.user.get('publisher', {}).get('network_code')

    @property
    def network_name(self) -> str:
        return self.cli['network_name'] or self.user.get('publisher', {}).get('network_name')

    @property
    def schema(self) -> dict:
        """The rules used to validate if your YAML file is formatted correctly."""
        if self._schema is None:
            self._schema = load_file(self.cli['schema']) if self.cli.get('schema') else \
              load_package_file('schema.yml')
        return self._schema

    def bidder_codes(self) -> List[str]:
        """Decides if we are making items for one bidder or many."""
        if self.cli['single_order']:
            return [self.app['prebid']['bidders']['single_order']['code']]
        return self.cli['bidder_code']

    def cpm_buckets(self) -> List[Dict[str, float]]:
        """Determines the pricing intervals (e.g., $0.10, $0.50)."""
        _type = self.user['rate']['granularity']['type']
        if _type == "custom":
            return self.user['rate']['granularity']['custom']
        return self.app['prebid']['price_granularity'][_type]

    def cpm_names(self) -> List[str]:
        """Generates the text names for price points (e.g., '1.50', '1.60')."""
        if self._cpm_names is None:
            values = set()
            for bucket in self.cpm_buckets():
                values.update(values_from_bucket(bucket))
            self._cpm_names = ['%.2f' % v_ for v_ in sorted(values)]
        
        # 🧪 TEST LIMIT: If --test-run is on, only generate a few items.
        if self.cli['test_run']:
            return self._cpm_names[:self.app['mgr']['test_run']['line_item_limit']]
        return self._cpm_names

    def micro_amount(self, cpm: Union[str, float]) -> int:
        """💰 GOOGLE CONVERSION: Converts $1.50 into 1,500,000 (micros) for the API."""
        return int(float(cpm) * self.app['googleads']['line_items']['micro_cent_factor'])

    # ==========================================================
    # 🏗️ PRE-CREATE: The final data transformation
    # ==========================================================
    def pre_create(self) -> None:
        """
        MASSAGING THE DATA: This function runs just before we talk to Google.
        It converts dates, sets timezones, and handles 'Test:' prefixes.
        """
        li_ = self.user['line_item']
        is_standard = li_['item_type'].upper() == "STANDARD"
        is_sponsorship = li_['item_type'].upper() == "SPONSORSHIP"
        end_str = li_.get('end_datetime')
        start_str = li_.get('start_datetime')
        fmt = self.app['mgr']['date_fmt']
        vcpm = self.user['rate'].get('vcpm')

        # 🕒 TIMEZONE CHECK: Ensure the timezone provided is valid (like 'America/New_York').
        try:
            tz_str = li_.get('timezone', self.app['mgr']['timezone'])
            _ = pytz.timezone(tz_str)
        except pytz.exceptions.UnknownTimeZoneError as e:
            raise ValueError(f'Unknown Time Zone, {e}') from e

        # 🏷️ NAMING: Add a placeholder so we can prepend 'Test: ' later if needed.
        for i_ in ('line_item', 'order'):
            self.user[i_]['name'] = ''.join(['{{ run_mode }}', self.user[i_]['name']])

        # 📅 DATE CONVERSION: Turn text strings into real Google-friendly date objects.
        li_.update(dict(
            start_dt=date_from_string(start_str, fmt, tz_str) if start_str else "IMMEDIATELY",
            start_dt_type="USE_START_DATE_TIME" if start_str else "IMMEDIATELY",
            end_dt=date_from_string(end_str, fmt, tz_str),
            unlimited_end_dt=not end_str,
        ))

        # 🚩 TYPE SPECIFIC LOGIC: Handle goals for Standard vs Sponsorship items.
        if not is_sponsorship:
            li_.update({'goal': dict(goalType="NONE")})

        if vcpm:
            if not is_standard:
                raise ValueError("Specifying 'vcpm' requires using line item type 'standard'")
            li_.update({'goal': dict(
                goalType="LIFETIME",
                unitType="VIEWABLE_IMPRESSIONS",
                units=vcpm,
            )})

        self.user['rate'].update(dict(
            cost_type="VCPM" if vcpm else "CPM"
        ))

# 🌟 THE SINGLETON: This creates the one-and-only Config object used by the whole app.
config = Config()

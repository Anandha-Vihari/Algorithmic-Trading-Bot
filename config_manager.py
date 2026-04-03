"""
CONFIG MANAGER - Clean dependency injection for bot-specific configuration

Replaces sys.modules hacks with a clean ConfigManager class.
Validates configuration on startup.
"""

import sys
from typing import Dict, Any


class ConfigManager:
    """Load and validate bot-specific configuration without sys.modules hacks."""

    def __init__(self, bot_id: int):
        """
        Initialize ConfigManager with bot ID.

        Args:
            bot_id: Bot identifier (1, 2, or 3)

        Raises:
            ValueError if bot_id is invalid
            AssertionError if validation fails
        """
        if bot_id not in (1, 2, 3):
            raise ValueError(f"Invalid bot_id: {bot_id}. Must be 1, 2, or 3.")

        self.bot_id = bot_id
        self.config = self._load_bot_config(bot_id)
        self._validate()

    def _load_bot_config(self, bot_id: int) -> Dict[str, Any]:
        """
        Load bot-specific configuration from config_botX.py.

        Args:
            bot_id: Bot identifier (1, 2, or 3)

        Returns:
            Dictionary with bot configuration
        """
        if bot_id == 1:
            from config_bot1 import (
                BOT_ID, BOT_NAME, TRADE_VOLUME, MT5_LOGIN, MT5_PASSWORD,
                USE_SIGNAL_INVERTER, FOLLOW_HOURS_IST_START, FOLLOW_HOURS_IST_END,
                STRATEGY
            )
            return {
                'BOT_ID': BOT_ID,
                'BOT_NAME': BOT_NAME,
                'TRADE_VOLUME': TRADE_VOLUME,
                'MT5_LOGIN': MT5_LOGIN,
                'MT5_PASSWORD': MT5_PASSWORD,
                'USE_SIGNAL_INVERTER': USE_SIGNAL_INVERTER,
                'FOLLOW_HOURS_IST_START': FOLLOW_HOURS_IST_START,
                'FOLLOW_HOURS_IST_END': FOLLOW_HOURS_IST_END,
                'STRATEGY': STRATEGY,
            }

        elif bot_id == 2:
            from config_bot2 import (
                BOT_ID, BOT_NAME, TRADE_VOLUME, MT5_LOGIN, MT5_PASSWORD,
                USE_SIGNAL_INVERTER, STRATEGY
            )
            return {
                'BOT_ID': BOT_ID,
                'BOT_NAME': BOT_NAME,
                'TRADE_VOLUME': TRADE_VOLUME,
                'MT5_LOGIN': MT5_LOGIN,
                'MT5_PASSWORD': MT5_PASSWORD,
                'USE_SIGNAL_INVERTER': USE_SIGNAL_INVERTER,
                'FOLLOW_HOURS_IST_START': None,
                'FOLLOW_HOURS_IST_END': None,
                'STRATEGY': STRATEGY,
            }

        else:  # bot_id == 3
            from config_bot3 import (
                BOT_ID, BOT_NAME, TRADE_VOLUME, MT5_LOGIN, MT5_PASSWORD,
                USE_SIGNAL_INVERTER, STRATEGY
            )
            return {
                'BOT_ID': BOT_ID,
                'BOT_NAME': BOT_NAME,
                'TRADE_VOLUME': TRADE_VOLUME,
                'MT5_LOGIN': MT5_LOGIN,
                'MT5_PASSWORD': MT5_PASSWORD,
                'USE_SIGNAL_INVERTER': USE_SIGNAL_INVERTER,
                'FOLLOW_HOURS_IST_START': None,
                'FOLLOW_HOURS_IST_END': None,
                'STRATEGY': STRATEGY,
            }

    def _validate(self):
        """
        Validate configuration on startup.

        Raises:
            AssertionError if validation fails
        """
        required_fields = ['BOT_ID', 'BOT_NAME', 'TRADE_VOLUME', 'MT5_LOGIN', 'MT5_PASSWORD']

        for field in required_fields:
            assert field in self.config, f"Missing required config field: {field}"

        assert self.config['BOT_ID'] == self.bot_id, "BOT_ID mismatch in config"
        assert self.config['TRADE_VOLUME'] > 0, "TRADE_VOLUME must be > 0"
        assert len(str(self.config['MT5_LOGIN'])) > 0, "MT5_LOGIN must not be empty"
        assert len(str(self.config['MT5_PASSWORD'])) > 0, "MT5_PASSWORD must not be empty"

        print(f"[CONFIG] Bot {self.bot_id} configuration validated ✓")

    def __getitem__(self, key: str) -> Any:
        """
        Dict-like access to configuration.

        Args:
            key: Configuration key

        Returns:
            Configuration value

        Raises:
            KeyError if key not found
        """
        return self.config[key]

    def get(self, key: str, default=None) -> Any:
        """
        Get configuration value with default.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self.config.get(key, default)

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"ConfigManager(bot_id={self.bot_id}, name={self.config['BOT_NAME']}, volume={self.config['TRADE_VOLUME']})"

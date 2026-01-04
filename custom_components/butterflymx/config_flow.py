import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD

# Import the library (assuming it's installed via requirements)
from butterflymx import ButterflyMXClient

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ButterflyMX."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                await self._validate_input(user_input)
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL], 
                    data=user_input
                )
            except Exception:
                errors["base"] = "auth_error"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )

    async def _validate_input(self, data):
        """Validate the user input allows us to connect."""
        client = ButterflyMXClient(data[CONF_EMAIL], data[CONF_PASSWORD], token_file=None)
        
        # Run async login directly
        success = await client.login()
        
        if not success:
            raise Exception("Invalid credentials")

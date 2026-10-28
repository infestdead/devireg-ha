"""Tests for the config flow and entity setup inside Home Assistant."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.devireg.api import InvalidOtp, PairingResult, Room
from custom_components.devireg.const import DOMAIN
from custom_components.devireg.dominion import Code, ControlState
from custom_components.devireg.sdg import generate_private_key

from .fake_sdg import FakeGrid, FakeThermostat
from .test_protocol import _packet


async def test_config_flow_creates_house(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    pairing = PairingResult(
        private_key=generate_private_key().hex(),
        house_name="My Flat",
        rooms=[Room("ab" * 32, "Bathroom"), Room("cd" * 32, "Kitchen")],
    )
    with (
        patch("custom_components.devireg.config_flow.pair", return_value=pairing),
        patch("custom_components.devireg.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp": "123-456-789", "user_name": "HA"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "My Flat"
    assert [room["name"] for room in result["data"]["rooms"]] == ["Bathroom", "Kitchen"]


async def test_config_flow_bad_otp(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch("custom_components.devireg.config_flow.pair", side_effect=InvalidOtp):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp": "1", "user_name": "HA"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_otp"}


async def test_setup_creates_entities(hass: HomeAssistant, socket_enabled) -> None:
    initial = (
        _packet(Code.HEATING_TEMPERATURE_ROOM, (2150).to_bytes(2, "little"))
        + _packet(Code.HEATING_TEMPERATURE_FLOOR, (2300).to_bytes(2, "little"))
        + _packet(Code.SCHEDULER_CONTROL_INFO, bytes([ControlState.MANUAL]))
        + _packet(Code.SCHEDULER_SETPOINT_MANUAL, (2250).to_bytes(2, "little"))
        + _packet(Code.SYSTEM_HEATING_INFO, b"\x01")
        + _packet(Code.SYSTEM_WINDOW_OPEN, b"\x01")
        + _packet(Code.GLOBAL_SOFTWAREREVISION, bytes([0x7F, 0x01]))
        + _packet(Code.GLOBAL_SERIALNUMBER, (10175249).to_bytes(4, "little"))
        # Installer setup with a 375 W heater (15 x 25 W), 10 h heater on-time
        + _packet(Code.SYSTEM_WIZARD_INFO, bytes([6, 1, 1, 0, 0, 15, 1]))
        + _packet(Code.SYSTEM_RUNTIME_INFO_RELAY_ON_TIME, (36000).to_bytes(4, "little"))
    )
    thermostat = FakeThermostat(initial)
    grid = FakeGrid(thermostat)
    servers = await grid.start()

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="My Flat",
        data={
            "private_key": generate_private_key().hex(),
            "house_name": "My Flat",
            "rooms": [{"peer_id": thermostat.peer_id, "name": "Bathroom"}],
        },
    )
    entry.add_to_hass(hass)
    with patch("custom_components.devireg.sdg.grid.DANFOSS_SERVERS", servers):
        assert await hass.config_entries.async_setup(entry.entry_id)
        for _ in range(50):
            await hass.async_block_till_done()
            state = hass.states.get("climate.bathroom")
            if state and state.state != "unavailable":
                break
            await asyncio.sleep(0.1)

        state = hass.states.get("climate.bathroom")
        assert state.state == "heat"
        # Wizard says floor regulation, so the floor reading is the current temperature
        assert state.attributes["current_temperature"] == 23.0
        assert state.attributes["temperature"] == 22.5
        assert state.attributes["hvac_action"] == "heating"
        assert hass.states.get("sensor.bathroom_floor_temperature").state == "23.0"
        assert hass.states.get("binary_sensor.bathroom_heating").state == STATE_ON
        assert hass.states.get("sensor.bathroom_heater_power").state == "375"
        assert float(hass.states.get("sensor.bathroom_energy_total").state) == 3.75
        assert hass.states.get("switch.bathroom_open_window_detection").state == STATE_ON

        from homeassistant.helpers import device_registry as dr

        device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, thermostat.peer_id)})
        assert device.sw_version == "1.127"
        assert device.serial_number == "10175249"

        await hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": "climate.bathroom", "temperature": 23},
            blocking=True,
        )
        await asyncio.wait_for(thermostat.got_data.wait(), 5)

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    await grid.stop()

    from custom_components.devireg import dominion

    assert thermostat.received[0] == dominion.write_decimal(Code.SCHEDULER_SETPOINT_MANUAL, 23)

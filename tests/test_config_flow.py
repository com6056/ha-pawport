"""Tests for the Pawport config flow."""

from __future__ import annotations

from typing import Any

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.pawport.api import API_URL, GRAPHQL_URL
from custom_components.pawport.const import CONF_AUTH_TOKEN, CONF_CODE, CONF_REFRESH_TOKEN, DOMAIN

from .conftest import CODE, EMAIL, NEW_TOKEN, PASSWORD, USER_ID, FakePawport, setup_entry


async def start(hass: HomeAssistant, email: str = EMAIL) -> dict[str, Any]:
    """Start a user flow and submit the email, which sends the code."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: f" {email} "}
    )


async def configure(hass: HomeAssistant, flow_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return await hass.config_entries.flow.async_configure(flow_id, data)


async def choose(hass: HomeAssistant, flow_id: str, option: str) -> dict[str, Any]:
    return await configure(hass, flow_id, {"next_step_id": option})


async def to_password(hass: HomeAssistant, result: dict[str, Any]) -> str:
    """From the menu a password account sees, pick the password."""
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "method"
    result = await choose(hass, result["flow_id"], "password")
    assert result["step_id"] == "password"
    return str(result["flow_id"])


async def test_code_flow(hass: HomeAssistant, pawport: FakePawport) -> None:
    """An account without a password goes straight to the code, no menu."""
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "code"
    assert pawport.codes_sent == [EMAIL]
    flow_id = result["flow_id"]

    result = await configure(hass, flow_id, {CONF_CODE: "999999"})
    assert result["errors"] == {"base": "invalid_code"}

    result = await configure(hass, flow_id, {CONF_CODE: CODE})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["result"].unique_id == USER_ID
    assert result["data"] == {
        CONF_EMAIL: EMAIL,
        CONF_AUTH_TOKEN: NEW_TOKEN,
        CONF_REFRESH_TOKEN: None,
    }


async def test_password_account_can_still_use_the_code(
    hass: HomeAssistant, pawport: FakePawport
) -> None:
    pawport.password_supported = True
    result = await start(hass)
    assert result["type"] is FlowResultType.MENU
    result = await choose(hass, result["flow_id"], "code")
    assert result["step_id"] == "code"
    result = await configure(hass, result["flow_id"], {CONF_CODE: CODE})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_PASSWORD not in result["data"]


async def test_password_flow_stores_password(hass: HomeAssistant, pawport: FakePawport) -> None:
    pawport.password_supported = True
    flow_id = await to_password(hass, await start(hass))

    result = await configure(hass, flow_id, {CONF_PASSWORD: "nope"})
    assert result["errors"] == {"base": "invalid_auth"}

    result = await configure(hass, flow_id, {CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PASSWORD] == PASSWORD


async def test_password_flow_errors(hass: HomeAssistant, pawport: FakePawport) -> None:
    pawport.password_supported = True
    flow_id = await to_password(hass, await start(hass))
    pawport.overrides["/user/password"] = aiohttp.ClientError("down")
    result = await configure(hass, flow_id, {CONF_PASSWORD: PASSWORD})
    assert result["errors"] == {"base": "cannot_connect"}

    pawport.overrides["/user/password"] = AiohttpClientMockResponse("post", API_URL, status=404)
    result = await configure(hass, flow_id, {CONF_PASSWORD: PASSWORD})
    assert result["errors"] == {"base": "unknown"}


async def test_code_errors(hass: HomeAssistant, pawport: FakePawport) -> None:
    flow_id = (await start(hass))["flow_id"]
    for override, error in (
        (aiohttp.ClientError("down"), "cannot_connect"),
        (AiohttpClientMockResponse("post", API_URL, status=404), "unknown"),
        (
            AiohttpClientMockResponse(
                "post", API_URL, status=422, json={"errors": {"emailAddress": ["unknown"]}}
            ),
            "invalid_auth",
        ),
    ):
        pawport.overrides["/user/verify"] = override
        result = await configure(hass, flow_id, {CONF_CODE: CODE})
        assert result["errors"] == {"base": error}


async def test_send_code_failures_abort(hass: HomeAssistant, pawport: FakePawport) -> None:
    for override, reason in (
        (aiohttp.ClientError("down"), "cannot_connect"),
        (
            AiohttpClientMockResponse("post", API_URL, status=422, json={"message": "bad"}),
            "invalid_email",
        ),
        (AiohttpClientMockResponse("post", API_URL, status=404), "unknown"),
    ):
        pawport.overrides["/user"] = override
        result = await start(hass)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == reason


async def test_unexpected_send_response_means_no_password(
    hass: HomeAssistant, pawport: FakePawport
) -> None:
    """Anything but an explicit true is treated as a code-only account."""
    pawport.overrides["/user"] = AiohttpClientMockResponse(
        "post", API_URL, status=200, json={"passwordSupported": "yes"}
    )
    result = await start(hass)
    assert result["step_id"] == "code"


async def test_account_read_failure_aborts(hass: HomeAssistant, pawport: FakePawport) -> None:
    flow_id = (await start(hass))["flow_id"]
    pawport.overrides["authDataGet"] = AiohttpClientMockResponse("post", GRAPHQL_URL, status=500)
    result = await configure(hass, flow_id, {CONF_CODE: CODE})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_duplicate_email_aborts_before_sending(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert pawport.codes_sent == []


async def test_duplicate_account_by_user_id(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    """A second email alias for the same account still collides on user ID."""
    config_entry.add_to_hass(hass)
    flow_id = (await start(hass, "alias@example.com"))["flow_id"]
    result = await configure(hass, flow_id, {CONF_CODE: CODE})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_with_code(
    hass: HomeAssistant, pawport: FakePawport, password_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, password_entry)
    result = await password_entry.start_reauth_flow(hass)
    assert result["step_id"] == "code"
    assert pawport.codes_sent == [EMAIL]
    result = await configure(hass, result["flow_id"], {CONF_CODE: CODE})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert password_entry.data[CONF_AUTH_TOKEN] == NEW_TOKEN
    # Signing in with a code drops the old password: it may be why reauth was needed.
    assert CONF_PASSWORD not in password_entry.data


async def test_reauth_wrong_account(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    pawport.context["userID"] = "someone-else"
    pawport.valid_token = pawport.issue_token
    result = await config_entry.start_reauth_flow(hass)
    result = await configure(hass, result["flow_id"], {CONF_CODE: CODE})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


async def test_reconfigure_switches_to_password(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    pawport.password_supported = True
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await configure(hass, result["flow_id"], {CONF_EMAIL: EMAIL})
    flow_id = await to_password(hass, result)
    result = await configure(hass, flow_id, {CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_PASSWORD] == PASSWORD
    assert config_entry.data[CONF_AUTH_TOKEN] == NEW_TOKEN


async def test_reconfigure_follows_email_change(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    """A new address for the same account updates the entry and its title."""
    await setup_entry(hass, config_entry)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await configure(hass, result["flow_id"], {CONF_EMAIL: "new@example.com"})
    assert result["step_id"] == "code"
    result = await configure(hass, result["flow_id"], {CONF_CODE: CODE})
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_EMAIL] == "new@example.com"
    assert config_entry.title == "new@example.com"
    assert pawport.codes_sent == ["new@example.com"]


async def test_reconfigure_refuses_another_account(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await configure(hass, result["flow_id"], {CONF_EMAIL: "other@example.com"})
    pawport.context["userID"] = "someone-else"
    pawport.valid_token = pawport.issue_token
    result = await configure(hass, result["flow_id"], {CONF_CODE: CODE})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data[CONF_EMAIL] == EMAIL

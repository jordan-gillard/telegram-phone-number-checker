import asyncio
import json
from collections.abc import Iterable

import click
from dotenv import load_dotenv
from telethon import types
from telethon.sync import TelegramClient, functions
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import (
    TypeUserStatus,
    UserStatusEmpty,
    UserStatusLastMonth,
    UserStatusLastWeek,
    UserStatusOffline,
    UserStatusOnline,
    UserStatusRecently,
)
from telethon.tl.types.contacts import ImportedContacts

load_dotenv()


def get_human_readable_status(status: TypeUserStatus):
    match status:
        case UserStatusEmpty():
            return "Unknown"
        case UserStatusOnline():
            return "Currently online"
        case UserStatusOffline():
            return status.was_online.strftime("%Y-%m-%d %H:%M:%S %Z")
        case UserStatusRecently():
            return "Last seen recently"
        case UserStatusLastWeek():
            return "Last seen last week"
        case UserStatusLastMonth():
            return "Last seen last month"
        case _:
            return "Unknown status returned"


async def get_user_info(client: TelegramClient, phone_number: str) -> dict:
    """Take in a phone number and returns the associated user information if the user exists."""
    print(f"Checking: {phone_number=} ...", end="", flush=True)
    try:
        peer_id = await client.get_peer_id(phone_number)
    except ValueError:
        print(f"Could not find a Telegram account associated with {phone_number=}")
        return {}
    user = (await client(GetFullUserRequest(peer_id))).users[0]
    return {
        "id": peer_id,
        "username": user.username,
        "usernames": user.usernames,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "fake": user.fake,
        "verified": user.verified,
        "premium": user.premium,
        "mutual_contact": user.mutual_contact,
        "bot": user.bot,
        "bot_chat_history": user.bot_chat_history,
        "restricted": user.restricted,
        "restriction_reason": user.restriction_reason,
        "user_was_online": get_human_readable_status(user.status),
        "deleted": user.deleted,
        "phone": user.phone,
    }


async def _is_phone_number_a_contact(client, phone_number: str) -> bool:
    normalized_target_number = phone_number.replace("+", "").replace(" ", "")
    contacts = await client(functions.contacts.GetContactsRequest(hash=0))
    for contact in contacts.users:
        normalized_contact_number = (
            contact.phone.replace(" ", "") if contact.phone else None
        )
        if normalized_target_number == normalized_contact_number:
            return True
    return False


async def _create_temp_contacts(
    client: TelegramClient, numbers: Iterable[str]
) -> ImportedContacts:
    print(f"Temporarily adding {", ".join(numbers)} to contact list.")
    temp_contacts = [
        types.InputPhoneContact(client_id=0, phone=number, first_name="", last_name="")
        for number in numbers
    ]
    just_added_contacts: ImportedContacts = await client(
        functions.contacts.ImportContactsRequest(temp_contacts)
    )
    just_added_numbers = [user.phone for user in just_added_contacts.users]
    print(f"Successfully added {", ".join(just_added_numbers)} to contact list.")
    return just_added_contacts


async def _get_numbers_not_in_contacts(client: TelegramClient, numbers: Iterable[str]):
    return {
        number
        for number in numbers
        if not await _is_phone_number_a_contact(client, number)
    }


async def validate_users(client: TelegramClient, phone_numbers: str) -> dict:
    """
    Take in a string of comma separated phone numbers and try to get the user information associated with each phone number.
    """
    if not phone_numbers or not len(phone_numbers):
        phone_numbers = input("Enter the phone numbers to check, separated by commas: ")
    cleaned_numbers: set[str] = set(phone_numbers.replace(" ", "").split(","))
    numbers_not_in_contacts = await _get_numbers_not_in_contacts(
        client, cleaned_numbers
    )
    temp_contacts = None
    if numbers_not_in_contacts:
        temp_contacts = await _create_temp_contacts(client, numbers_not_in_contacts)
    try:
        return {phone: await get_user_info(client, phone) for phone in cleaned_numbers}
    finally:
        if temp_contacts:
            print(f"Removing users temporarily added to contact list.")
            to_delete = [
                types.InputUser(user_id=user.id, access_hash=user.access_hash)
                for user in temp_contacts.users
            ]
            await client(functions.contacts.DeleteContactsRequest(to_delete))


def show_results(output: str, res: dict) -> None:
    print(json.dumps(res, indent=4))
    with open(output, "w") as f:
        json.dump(res, f, indent=4)
        print(f"Results saved to {output}")


@click.command(
    epilog="Check out the docs at github.com/bellingcat/telegram-phone-number-checker for more information."
)
@click.option(
    "--phone-numbers",
    "-p",
    help="List of phone numbers to check, separated by commas",
    type=str,
)
@click.option(
    "--api-id",
    help="Your Telegram app api_id",
    type=int,
    prompt="Enter your Telegram App app_id",
    envvar="API_ID",
    show_envvar=True,
)
@click.option(
    "--api-hash",
    help="Your Telegram app api_hash",
    type=str,
    prompt="Enter your Telegram App api_hash",
    hide_input=True,
    envvar="API_HASH",
    show_envvar=True,
)
@click.option(
    "--api-phone-number",
    help="Your phone number",
    type=str,
    prompt="Enter the number associated with your Telegram account",
    envvar="PHONE_NUMBER",
    show_envvar=True,
)
@click.option(
    "--api-phone-password",
    help="The password for your Telegram account",
    type=str,
    prompt="Enter the password associated with your Telegram account",
    hide_input=True,
    envvar="PASSWORD",
    show_envvar=True,
)
@click.option(
    "--output",
    help="Filename to store results",
    default="results.json",
    show_default=True,
    type=str,
)
def main_entrypoint(
    phone_numbers: str,
    api_id: int,
    api_hash: str,
    api_phone_number: str,
    api_phone_password: str,
    output: str,
) -> None:
    """
    Check to see if one or more phone numbers belong to a valid Telegram account.

    \b
    Prerequisites:
    1. A Telegram account with an active phone number
    2. A Telegram App api_id and App api_hash, which you can get by creating
       a Telegram App @ https://my.telegram.org/apps

    \b
    Note:
    If you do not want to enter the API ID, API hash, phone number, or password
    associated with your Telegram account on the command line, you can store these
    values in a `.env` file located within the same directory you run this command from.

    \b
    // .env file example:
    API_ID=12345678
    API_HASH=1234abcd5678efgh1234abcd567
    PHONE_NUMBER=+15555555555
    PASSWORD=mmyy_+ppaasssswwoorrdd$

    See the official Telegram docs at https://core.telegram.org/api/obtaining_api_id
    for more information on obtaining an API ID.

    \b
    Recommendations:
    Telegram recommends entering phone numbers in international format
    +(country code)(city or carrier code)(your number)
    i.e. +491234567891

    """
    asyncio.run(
        run_program(
            api_phone_number,
            api_phone_password,
            api_id,
            api_hash,
            phone_numbers,
            output,
        )
    )


async def run_program(
    api_phone_number, api_phone_password, api_id, api_hash, phone_numbers, output
):
    async with TelegramClient(
        "Telegram Phone Number Checker", api_id, api_hash
    ) as client:
        await client.start(phone=api_phone_number, password=api_phone_password)
        res = await validate_users(client, phone_numbers)
        show_results(output, res)


if __name__ == "__main__":
    main_entrypoint()

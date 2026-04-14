import asyncio
import datetime
import os
import shutil
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
import subprocess
from typing import Union, List, Optional
import re

from rich.text import Text
from rich.prompt import IntPrompt
from rich.console import Console
from rich.table import Table

from icloud import HideMyEmail

MAX_CONCURRENT_TASKS = 10

class RichHideMyEmail(HideMyEmail):
    _cookie_file = "cookie.txt"

    def __init__(self):
        super().__init__()
        self.console = Console()
        self.table = Table()

        if os.path.exists(self._cookie_file):
            with open(self._cookie_file, "r") as f:
                self.cookies = [line for line in f if not line.startswith("//")][0]
        else:
            self.console.log(
                '[bold yellow][WARN][/] No "cookie.txt" file found! Generation might not work due to unauthorized access.'
            )

    async def _generate_one(self) -> Union[str, None]:
        gen_res = await self.generate_email()

        if not gen_res:
            return
        elif "success" not in gen_res or not gen_res["success"]:
            error = gen_res["error"] if "error" in gen_res else {}
            err_msg = "Unknown"
            if isinstance(error, int) and "reason" in gen_res:
                err_msg = gen_res["reason"]
            elif isinstance(error, dict) and "errorMessage" in error:
                err_msg = error["errorMessage"]
            self.console.log(
                f"[bold red][ERR][/] - Failed to generate email. Reason: {err_msg}"
            )
            return

        email = gen_res["result"]["hme"]
        self.console.log(f'[50%] "{email}" - Successfully generated')

        reserve_res = await self.reserve_email(email)

        if not reserve_res:
            return
        elif "success" not in reserve_res or not reserve_res["success"]:
            error = reserve_res["error"] if "error" in reserve_res else {}
            err_msg = "Unknown"
            if isinstance(error, int) and "reason" in reserve_res:
                err_msg = reserve_res["reason"]
            elif isinstance(error, dict) and "errorMessage" in error:
                err_msg = error["errorMessage"]
            self.console.log(
                f'[bold red][ERR][/] "{email}" - Failed to reserve email. Reason: {err_msg}'
            )
            return

        self.console.log(f'[100%] "{email}" - Successfully reserved')
        return email

    async def _generate(self, num: int) -> List[str]:
        tasks = [self._generate_one() for _ in range(num)]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def generate(self, count: Optional[int]) -> List[str]:
        try:
            emails = []
            self.console.rule()
            if count is None:
                s = IntPrompt.ask(
                    Text.assemble(("How many iCloud emails you want to generate?")),
                    console=self.console,
                )
                count = int(s)

            self.console.log(f"Generating {count} email(s)...")
            self.console.rule()

            with self.console.status(f"[bold green]Generating iCloud email(s)..."):
                while count > 0:
                    batch_size = min(count, MAX_CONCURRENT_TASKS)
                    batch = await self._generate(batch_size)
                    count -= batch_size
                    emails += batch

            if emails:
                emails_path = os.path.join(BASE_DIR, "emails.txt")
                with open(emails_path, "a+") as f:
                    f.write(os.linesep.join(emails) + os.linesep)

                self.console.rule()
                self.console.log(
                    f':star: Emails have been saved into the "emails.txt" file'
                )
                self.console.log(
                    f"[bold green]All done![/] Successfully generated [bold green]{len(emails)}[/] email(s)"
                )

            return emails
        except KeyboardInterrupt:
            return []

    async def list(self, active: bool, search: str) -> None:
        gen_res = await self.list_email()
        if not gen_res:
            return

        if "success" not in gen_res or not gen_res["success"]:
            error = gen_res["error"] if "error" in gen_res else {}
            err_msg = "Unknown"
            if isinstance(error, int) and "reason" in gen_res:
                err_msg = gen_res["reason"]
            elif isinstance(error, dict) and "errorMessage" in error:
                err_msg = error["errorMessage"]
            self.console.log(
                f"[bold red][ERR][/] - Failed to generate email. Reason: {err_msg}"
            )
            return

        self.table.add_column("Label")
        self.table.add_column("Hide my email")
        self.table.add_column("Created Date Time")
        self.table.add_column("IsActive")

        for row in gen_res["result"]["hmeEmails"]:
            if row["isActive"] == active:
                if search and re.search(search, row["label"]):
                    self.table.add_row(
                        row["label"],
                        row["hme"],
                        str(datetime.datetime.fromtimestamp(row["createTimestamp"] / 1000)),
                        str(row["isActive"]),
                    )
                elif not search:
                    self.table.add_row(
                        row["label"],
                        row["hme"],
                        str(datetime.datetime.fromtimestamp(row["createTimestamp"] / 1000)),
                        str(row["isActive"]),
                    )

        self.console.print(self.table)


async def generate(count: Optional[int]) -> None:
    async with RichHideMyEmail() as hme:
        await hme.generate(count)


async def list(active: bool, search: str = "") -> None:
    async with RichHideMyEmail() as hme:
        await hme.list(active, search)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def looped_generation():
        while True:
            try:
                # ⚙️ Mettre à jour les cookies avant chaque génération
                subprocess.run(["python", "auto_cookie_from_chrome.py"], check=True)

                await generate(25)  # Apple limite à 5 alias/heure
                print(f"[{datetime.datetime.now()}] - Waiting 1 hour before next batch...")
                await asyncio.sleep(3600)  # Pause de 1 heure
            except Exception as e:
                print(f"[ERROR] {e}")
                await asyncio.sleep(300)  # Attendre 5 min avant retry si erreur

    try:
        loop.run_until_complete(looped_generation())
    except KeyboardInterrupt:
        print("⛔ Interrompu manuellement")

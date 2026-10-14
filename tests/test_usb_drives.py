"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (docs/sketches/first-run-guide.md, Q68): the first-run
guide's dialogs open on the USB drive plugged in last. `aoi.hal.drives` lists the removable drives the system mounts, in
the order the app saw them, so the one plugged in while the app runs is the last; with none, each dialog opens where it
did."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.hal import drives
from tests.test_dataset_stores import as_admin
from tests.test_first_board_model_store import shell
from tests.test_first_run_guide import guide_of, typed
from tests.test_guide_images import BM, boards

REMOVABLE = drives.removable  # the system's own listing: tests/conftest.py lists no drive in every test


def plugged(monkeypatch: pytest.MonkeyPatch, *now: Path) -> list[Path]:
    """The system listing `now` as its removable drives, in its order, and the app's order forgotten; a drive appended
    to the list returned is plugged in, one removed from it taken out."""
    listed = list(now)
    monkeypatch.setattr(drives, "_seen", [])
    monkeypatch.setattr(drives, "removable", lambda: list(listed))
    return listed


def block(sys_root: Path, number: str, place: str, removable: str | None = None) -> None:
    """`number` (major:minor) under sys_root/dev/block linking to sys_root/devices/`place`, a partition of the disk
    above it, with that disk's removable mark when given, as Linux's /sys has them."""
    device = sys_root / "devices" / place
    device.mkdir(parents=True)
    (device / "partition").write_text(device.name[-1] + "\n", encoding="ascii")
    if removable is not None:
        (device.parent / "removable").write_text(f"{removable}\n", encoding="ascii")
    (sys_root / "dev" / "block").mkdir(parents=True, exist_ok=True)
    os.symlink(device, sys_root / "dev" / "block" / number)


@pytest.mark.skipif(sys.platform == "win32", reason="Linux's /sys: symbolic links, and names with a colon")
def test_req_trn_021_linux_lists_removable_drives_in_the_order_they_were_mounted(tmp_path: Path) -> None:
    """A partition mounted whole, of a disk on a USB bus or marked removable, is a drive, by its mount point, spaces and
    all; a fixed disk, a folder of a drive mounted again elsewhere, a filesystem with no block device and the USB drive
    the system started from, its other partitions included, are not. The order is mountinfo's, the order of the
    mounts."""
    sys_root = tmp_path / "sys"
    block(sys_root, "8:1", "pci0000:00/0000:00:17.0/ata1/host0/block/sda/sda1", "0")
    block(sys_root, "8:17", "pci0000:00/0000:00:14.0/usb2/2-1/2-1:1.0/host6/block/sdb/sdb1")
    block(sys_root, "8:49", "pci0000:00/0000:00:17.0/ata2/host1/block/sdd/sdd1", "1")  # a removable disk, not on USB
    block(sys_root, "8:33", "pci0000:00/0000:00:14.0/usb2/2-2/2-2:1.0/host7/block/sdc/sdc1")
    block(sys_root, "8:34", "pci0000:00/0000:00:14.0/usb2/2-2/2-2:1.0/host7/block/sdc/sdc2")
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "\n".join(
            (
                "22 1 8:33 / / rw,relatime shared:1 - ext4 /dev/sdc1 rw",  # started from a USB drive
                "23 22 8:1 / /home rw,relatime shared:2 - ext4 /dev/sda1 rw",
                "24 22 0:21 / /run rw,nosuid shared:3 - tmpfs tmpfs rw",
                "25 22 8:34 / /boot/efi rw,relatime shared:4 - vfat /dev/sdc2 rw",  # the system's USB drive too
                "40 24 8:17 / /media/jay/KEY\\040DRIVE rw,nosuid shared:9 - vfat /dev/sdb1 rw",
                "41 22 8:17 /backup /mnt/backup rw shared:9 - vfat /dev/sdb1 rw",  # a folder of the same drive
                "38 24 8:49 / /media/jay/IMAGES rw,nosuid shared:10 - exfat /dev/sdd1 rw",  # an id reused
            )
        )
        + "\n",
        encoding="utf-8",
    )
    found = drives._linux(mountinfo, sys_root / "dev" / "block")
    assert found == [Path("/media/jay/KEY DRIVE"), Path("/media/jay/IMAGES")]


class Kernel32:
    """Windows' drive letters as kernel32 gives them, by root: each one's type, those holding a volume, and this
    thread's error mode, each mode set noted."""

    def __init__(self, types: dict[str, int], volumes: set[str]) -> None:
        self.types, self.volumes, self.gone, self.mode, self.modes = types, volumes, set[str](), 0x8000, list[int]()

    def mounted(self) -> int:
        return sum(1 << (ord(root[0]) - ord("A")) for root in self.types)

    def drive_type(self, root: str) -> int:
        return self.types[root]

    def holds_volume(self, root: str) -> bool:
        if root in self.gone:
            raise OSError("the drive was taken out")
        return root in self.volumes

    def error_mode(self, mode: int) -> int:
        before, self.mode = self.mode, mode
        self.modes.append(mode)
        return before


def test_req_trn_021_windows_lists_removable_letters_holding_a_volume() -> None:
    """Windows lists each drive letter of the removable type holding a volume, A to Z, by its root: not a fixed drive,
    a CD drive or a card reader with no card. No box asks for a disk meanwhile, and this thread's error mode is put
    back after, a failed call included."""
    types = {"C:\\": 3, "D:\\": 5, "E:\\": drives.DRIVE_REMOVABLE, "F:\\": drives.DRIVE_REMOVABLE, "G:\\": 2}
    kernel32 = Kernel32(types, {"C:\\", "D:\\", "E:\\", "G:\\"})
    assert drives._windows(kernel32) == [Path("E:\\"), Path("G:\\")]
    assert kernel32.modes == [drives.SEM_FAILCRITICALERRORS, 0x8000]
    kernel32.gone = {"E:\\"}
    with pytest.raises(OSError):
        drives._windows(kernel32)
    assert kernel32.mode == 0x8000


def test_req_trn_021_a_listing_that_fails_lists_no_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    """A system that will not list its drives, however it fails, lists none: each dialog opens where it did, and the
    window still opens."""

    def fails(*_: object) -> list[Path]:
        raise RuntimeError("the system answered something else")

    monkeypatch.setattr(drives, "_linux", fails)
    monkeypatch.setattr(drives, "_windows", fails)
    assert REMOVABLE() == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' kernel32 is the only system with drive letters")
def test_req_trn_021_windows_lists_no_fixed_drive() -> None:
    """On the Windows running the test, the listing names each drive by its letter's root, and never the system's own
    fixed drive."""
    found = REMOVABLE()
    assert all(str(d) == f"{d.drive}\\" for d in found) and Path(os.environ["SystemDrive"] + "\\") not in found


def test_req_trn_021_the_drive_plugged_in_last_is_the_one_the_app_saw_last(monkeypatch: pytest.MonkeyPatch) -> None:
    """The drives there at the app's first look come in the system's order; one plugged in after is the last, ahead of
    one the system lists after it; one taken out is gone, and plugged in again it is the last once more."""
    key, images, other = Path("E:/"), Path("F:/"), Path("D:/")
    now = plugged(monkeypatch)
    assert drives.last_plugged() is None
    now.append(key)
    assert drives.last_plugged() == key
    now[:] = [other, key]  # D: plugged in after E:, listed first by its letter
    assert drives.last_plugged() == other
    now.append(images)
    assert drives.last_plugged() == images
    now.remove(images)
    assert drives.last_plugged() == other
    now.append(images)
    assert drives.last_plugged() == images


def test_req_trn_021_with_no_usb_drive_the_dialogs_open_where_they_did(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no USB drive, the key's save dialog opens on the home folder and Pick Folder… where the system opens it;
    with one plugged in, both open on it."""
    usb = tmp_path / "usb"
    usb.mkdir()
    now = plugged(monkeypatch)
    win = shell(qtbot, ctx)
    win.navigate("Home")
    guide = guide_of(win)
    typed(qtbot, guide, "TBOX-A1", "Acme")
    guide.btn_create.click()
    asked: list[str] = []

    def save(parent: object, title: str, path: str, kinds: str) -> tuple[str, str]:
        asked.append(path)
        return "", kinds  # cancelled

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(save))
    guide.recovery.btn_save.click()
    now.append(usb)
    guide.recovery.btn_save.click()
    home = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation))
    assert asked == [str(home / "recovery-key-Acme.txt"), str(usb / "recovery-key-Acme.txt")]


def test_req_trn_021_pick_folder_opens_on_the_usb_drive_plugged_in_last(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pick Folder… opens where the system opens it with no USB drive, then on the one plugged in last."""
    key, images = tmp_path / "key", tmp_path / "images"
    now = plugged(monkeypatch)
    as_admin(ctx, ctx.create_customer_board_model, BM, "Acme")
    win = shell(qtbot, ctx)
    win.select_board_model(BM)
    win.navigate("Home")
    screen = guide_of(win).images
    asked: list[str] = []
    folder = boards(images / BM, 4, {})

    def pick(parent: object, title: str, start: str = "") -> str:
        asked.append(start)
        return "" if len(asked) < 3 else str(folder)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(pick))
    screen.btn_pick.click()
    now.append(key)
    screen.btn_pick.click()
    now.append(images)
    screen.btn_pick.click()
    qtbot.waitUntil(lambda: screen.copying is None, timeout=20000)
    assert asked == ["", str(key), str(images)] and screen.folder == str(folder)

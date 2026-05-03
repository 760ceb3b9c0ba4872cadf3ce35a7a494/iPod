"""
iPod management command line utility
"""

import io
import os
import platform
import subprocess
import typing
from contextlib import contextmanager
from enum import Enum
from math import ceil
from pathlib import Path
from typing import BinaryIO

import click

import ipod.definitions
import ipod.device
import ipod.ipsw
import ipod.mse
import ipod.serial_number
from ipod.definitions import iPodMode
from ipod.device import iPodUpdateKind
from ipod.serial_number import calculate_week_start_and_end_dates
from ipod.utils import numeric_build_id_to_string

ipod_provider = ipod.device.iPodProvider()

NON_BOOTABLE_IMAGES = {"appl", "lbat", "bdsw", "bdhw", "chrg", "rsrc"}


@contextmanager
def error_wrapper():
	try:
		yield
	except PermissionError as error:
		lines = [click.style(f"\nPermission error.", fg="red", bold=True)]
		if platform.system() == "Darwin":
			lines.append("Try running with sudo.")
		elif platform.system() == "Windows":
			lines.append("Try running as administrator.")
		elif platform.system() == "Linux":
			lines.append("Try running with sudo, or change permissions so you can access /dev/sg* devices.")
			lines.append("For example, you can add yourself to the disk group:")
			lines.append(click.style(f"	sudo usermod -a -G disk {os.environ.get('USER')}; logout", italic=True))
			lines.append("(How you do this depends on your Linux distribution.)")
		lines.append(
			click.style(f"\nOriginal exception: ", dim=True)
			+ click.style(f"{type(error).__name__}: {str(error)}", italic=True)
		)
		raise click.ClickException("\n".join(lines)) from None


@click.group(no_args_is_help=True)
@click.pass_context
def cli(ctx: click.Context):
	"""
	iPod management command line utility
	by https://760ceb3b9c0ba4872cadf3ce35a7a494.neocities.org/
	"""
	ctx.obj = ctx.with_resource(error_wrapper())


@cli.command(name="list")
def list_connected():
	"""List connected iPods"""
	connected_devices = list(ipod_provider.list_devices())
	if not len(connected_devices):
		click.echo("No connected iPods found. You may need to run with sudo/as administrator.")
		return

	for connected_device in connected_devices:
		click.echo(
			click.style(f"Device {connected_device.id}: ", dim=True) + f"{connected_device.target.get_pretty_name()}")


def ensure_device_ready(device: ipod.device.iPodDeviceDiskMode):
	"""make sure the iPod device is ready for access and the operating system has let go of it"""
	if not isinstance(device, ipod.device.iPodDeviceDiskMode):
		# this only applies to disk mode. there is no kernel driver for DFU modes.
		return

	if device.is_kernel_driver_active():
		if platform.system() == "Darwin":
			# if macOS:
			click.echo(click.style("macOS is still connected to the iPod, disconnecting...", fg="cyan", bold=True))

			mount_point = device.get_mount_point()
			if mount_point:
				click.echo(f"\tUnmounting {mount_point}... ", nl=False)
				subprocess.run(["diskutil", "unmount", mount_point], stdout=subprocess.DEVNULL).check_returncode()
				click.echo("done")

			click.echo("\tDetaching kernel driver... ", nl=False)
			device.detach_kernel_driver()
			click.echo("done\n")
		else:
			# TODO
			raise click.ClickException("Unsupported")


class iPodParameterType(click.ParamType):
	"""Click parameter that returns an iPodDevice"""
	name = "device"

	def __init__(self, mode: iPodMode | set[iPodMode] = None):
		self._modes = (
			mode if isinstance(mode, set)
			else {mode} if isinstance(mode, iPodMode)
			else None
		)

	def convert(self, value, param, ctx):
		device = ipod_provider.get_device(value)
		if not device:
			raise click.ClickException(
				f"iPod with ID {value} not found. Try running `list`. You may need to run with sudo/as administrator.")
		target = device.target
		if self._modes and (target.mode not in self._modes):
			raise click.ClickException(
				f"This iPod is in the wrong mode to use this command.\n"
				f"Your iPod is in {target.mode.pretty_name} mode, when you need to be in "
				f"{' or '.join(sorted(mode.pretty_name for mode in self._modes))} mode."
			)
		ensure_device_ready(device)
		return device


@cli.command()
@click.option('--device', "-d", type=iPodParameterType(), required=True)
def information(device: ipod.device.iPodDeviceDiskMode | ipod.device.iPodDeviceDFU):
	"""Present information about a connected iPod"""
	click.echo(click.style(device.target.get_pretty_name(), bold=True, italic=True, fg="magenta"))

	def print_row(key: str, value: str):
		# just a helper to make the rows prettier
		click.echo(" ".join((
			click.style(key + ":", bold=True),
			value
		)))

	# only info for disk mode for now
	if isinstance(device, ipod.device.iPodDeviceDiskMode):
		info = device.get_device_information()
		if info.get("ForcedDiskMode"):
			click.echo(click.style("(in recovery mode/forced disk mode)", bold=True, fg="yellow"))

		print_row("	Firmware", f"{info['VisibleBuildID']} (build {info.get('BuildVersion') or info['BuildID']})")

		format_name = {
			"HFSPLUS": "Mac (HFS+)",
			"FAT32": "Windows (FAT32)",
			"Unknown": "Unknown"
		}.get(info["VolumeFormat"], "???")
		print_row("	Format", format_name)
		print_row("	Serial number", info["SerialNumber"])
		serial_number = ipod.serial_number.SerialNumber.from_serial(info["SerialNumber"])

		# Manufacturing date stuff
		start_day_date, end_day_date = calculate_week_start_and_end_dates(
			year=serial_number.manufacturing_year, week=serial_number.manufacturing_week
		)
		strftime_pattern = (
			"%b %-e, %Y" if start_day_date.year != end_day_date.year else
			"%b %-e"
		)
		if platform.system() == "Windows":
			# yes there are platform incompatibilities with strftime its great
			strftime_pattern = strftime_pattern.replace("-", "#")

		print_row(
			"		Manufactured",
			f"week {serial_number.manufacturing_week} of {serial_number.manufacturing_year} "
			f"({start_day_date.strftime(strftime_pattern)} - {end_day_date.strftime(strftime_pattern)})"
		)

		# ok, all done

		if "MLBN" in info:
			print_row("	MLBN", info["MLBN"])
		print_row("	FireWire GUID", info["FireWireGUID"])


@cli.group()
def dfu():
	"""Commands for iPods in DFU and WTF mode"""
	pass


class FirmwareFileType(Enum):
	IPSW = "ipsw"
	IMG1 = "img1"
	UNKNOWN = "unknown"


def peek_determine_filetype(stream: typing.BinaryIO):
	"""Peek at the first 4 bytes from a stream to determine what file it is"""
	magic = stream.read(4)
	stream.seek(-len(magic), io.SEEK_CUR)  # its like we were never here
	if magic == b"PK\x03\x04":
		# ZIP file IPSW
		return FirmwareFileType.IPSW
	elif magic == b"8723":
		return FirmwareFileType.IMG1
	else:
		return FirmwareFileType.UNKNOWN


@contextmanager
def unwrap_ipsw_file(stream: typing.BinaryIO, target: ipod.device.iPodTarget):
	"""unwrap an IPSW file, removing the crunchy outside to reveal the gooey IMG1 core.
	yields the IMG1 file and its length, separate because the stream has no intrinsic length and we need it
	for chunking logic and progress bars and stuff"""

	ipsw_kind = ipod.ipsw.get_ipsw_kind(stream)
	if ipsw_kind == ipod.ipsw.IPSWKind.RECOVERY:
		# e.g. IPSWs like `x####0000_Recovery.ipsw`
		click.echo(click.style("Found recovery IPSW file", fg="cyan"))
		with ipod.ipsw.RecoveryIPSWFile(stream) as ipsw_file:
			if not ipsw_file.is_compatible_with(target):
				raise click.ClickException("IPSW file incompatible with your device.")

			img1_length = ipsw_file.get_img1_length()
			with ipsw_file.open_img1_file() as img1_file:
				yield img1_file, img1_length

	elif ipsw_kind == ipod.ipsw.IPSWKind.PAYLOAD:
		# e.g. IPSWs like `iPod_1.0_ABCDEF.ipsw`
		with ipod.ipsw.PayloadIPSWFile(stream) as ipsw_file:
			click.echo(click.style("Found payload IPSW file", fg="cyan"))
			manifest = ipsw_file.get_manifest()
			if not manifest.is_compatible_with(target):
				raise click.ClickException("IPSW file incompatible with your device.")

			if target.mode == iPodMode.DFU:
				# if the iPod is in DFU mode, it needs a bootloader. all we can send it at this stage from the IPSW file
				# is the bootloader. for weirder arrangements like tetherbooting into osos, we need to get it into WTF
				# mode separately first.
				img1_data = ipsw_file.get_bootloader_img1_data()
				if not img1_data:
					raise click.ClickException("IPSW file incompatible with your device.")

				click.echo(click.style(
					"Not in DFU mode, sending bootloader. To send another image, like osos, enter WTF mode first.",
					fg="yellow"
				))
				yield io.BytesIO(img1_data), len(img1_data)
				return

			elif target.mode == iPodMode.WTF:
				# if the iPod is in WTF mode, we can send it any partition from the file
				with ipsw_file.open_firmware_mse_file() as mse_stream:
					header = ipod.mse.read_mse_header(mse_stream)
					click.echo("\nImages in this file:")
					bootable_images = {
						image_metadata.name: image_metadata for image_metadata in header
						if image_metadata.name not in NON_BOOTABLE_IMAGES
					}
					for image_metadata in header:
						if image_metadata.name in NON_BOOTABLE_IMAGES:
							click.echo(click.style(
								f"- {image_metadata.name} ({image_metadata.length:,} bytes) (not bootable)",
								dim=True
							))
						else:
							click.echo(
								f"- {click.style(image_metadata.name, bold=True)} ({image_metadata.length:,} bytes)")

					selection = click.prompt("Image file to send", type=click.Choice(bootable_images.keys()))
					image_metadata = bootable_images[selection]

					img1_data = ipod.mse.read_mse_image(mse_stream, image_metadata)
					yield io.BytesIO(img1_data), len(img1_data)


@dfu.command()
@click.option('--device', "-d", type=iPodParameterType(mode={iPodMode.DFU, iPodMode.WTF}), required=True)
@click.argument("firmware_file", type=click.Path(
	file_okay=True,
	dir_okay=False,
	readable=True,
	path_type=Path,
))
def send_firmware(device: ipod.device.iPodDeviceDFU, firmware_file: Path):
	"""Send firmware to an iPod in DFU or WTF mode."""

	def start_sending(stream: typing.BinaryIO, length: int):
		block_size = 0x800
		block_count = ceil(length / block_size)

		with click.progressbar(length=block_count, label="Sending firmware...") as bar:
			device.send_firmware(
				stream=stream,
				length=length,
				block_size=block_size,
				on_progress=lambda state: bar.update(1)
			)

	with firmware_file.open("rb") as firmware_stream:
		file_type = peek_determine_filetype(firmware_stream)

		if file_type == FirmwareFileType.IPSW:
			with unwrap_ipsw_file(firmware_stream, target=device.target) as (img1_stream, img1_length):
				start_sending(img1_stream, length=img1_length)
		elif file_type == FirmwareFileType.IMG1:
			img1_stream = firmware_stream
			start_sending(img1_stream, length=firmware_file.lstat().st_size)


@cli.command()
@click.option('--device', "-d", type=iPodParameterType(mode=iPodMode.DISK), required=True)
@click.argument("ipsw_stream", metavar="IPSW_FILE", type=click.File("rb"))
def update_firmware(device: ipod.device.iPodDeviceDiskMode, ipsw_stream: BinaryIO):
	"""Update the firmware on an iPod."""
	info = device.get_device_information()
	old_version = info["VisibleBuildID"]

	with ipsw_stream:
		file_type = peek_determine_filetype(ipsw_stream)

		if file_type != FirmwareFileType.IPSW:
			raise click.ClickException("Must be an IPSW file.")

		with ipod.ipsw.PayloadIPSWFile(ipsw_stream) as ipsw_file:
			manifest = ipsw_file.get_manifest()

			if info["UpdaterFamilyID"] != manifest.updater_family_id:
				raise click.ClickException("Firmware incompatible.")

			new_version = manifest.product_version or numeric_build_id_to_string(manifest.visible_build_id)

			if old_version == new_version:
				text = (f"Are you sure you want to reinstall firmware version {new_version} "
						f"on this {device.target.get_pretty_model_name()}?")
			else:
				text = (f"Are you sure you want to update this {device.target.get_pretty_model_name()} "
						f"from version {old_version} to version {new_version}?")

			click.confirm(text=click.style(text, fg="bright_magenta"), abort=True)

			block_size = 0x8000

			# TODO: bootloader updates. for some reason it crashes my n6g.

			if manifest.firmware_name:
				mse_length = ipsw_file.get_firmware_mse_length()
				block_count = ceil(mse_length / block_size)
				with click.progressbar(label="Updating firmware...", length=block_count) as bar:
					with ipsw_file.open_firmware_mse_file() as mse_stream:
						device.update(
							kind=iPodUpdateKind.FIRMWARE,
							stream=mse_stream,
							length=mse_length,
							on_progress=lambda _: bar.update(1),
							block_size=block_size
						)

	click.echo("Finalizing updates...")
	device.finalize_updates()
	click.echo("Rebooting...")
	device.eject()
	click.echo(click.style("Update complete! ^-^", fg="green", bold=True))


if __name__ == "__main__":
	cli()

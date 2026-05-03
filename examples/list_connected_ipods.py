from ipod.device import iPodProvider

provider = iPodProvider()
devices = provider.list_devices()
print(f"Found {len(devices)} device{'' if len(devices) == 1 else 's'}")
for device in devices:
	print("-", device.target.get_pretty_name())

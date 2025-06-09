from ipod.device import find_devices

devices = find_devices()
print(f"Found {len(devices)} device{'' if len(devices) == 1 else 's'}")
for device in devices:
	print(f"- {device.target.get_pretty_name()}")

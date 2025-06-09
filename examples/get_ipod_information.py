# NOTE: this example must be run as root or with permission to detach USB kernel drivers
# on macOS try running this in a normal terminal window if you are having an issue

import json
from ipod.device import find_devices, iPodDeviceDiskMode

devices = find_devices()
for device in devices:
	if not isinstance(device, iPodDeviceDiskMode):
		continue

	device.detach_kernel_driver()
	print(device.target.get_pretty_name())
	data = device.get_device_information()
	print(json.dumps(data, indent=2))
	break

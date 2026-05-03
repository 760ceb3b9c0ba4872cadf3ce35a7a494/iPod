# NOTE: this example must be run as root or with permission to detach USB kernel drivers
# on macOS try running this in a normal terminal window if you are having an issue

import json

from ipod.definitions import iPodMode
from ipod.device import iPodProvider, iPodDeviceDiskMode

provider = iPodProvider()
for connected_device in provider.list_devices():
	if connected_device.target.mode == iPodMode.DISK:
		device: iPodDeviceDiskMode = provider.get_device(connected_device)

		device.detach_kernel_driver()  # Required on macOS
		print(device.target.get_pretty_name())
		data = device.get_device_information()
		print(json.dumps(data, indent=2))
		break

# iPod
Python library for talking to iPod devices. [Documentation](https://760ceb3b9c0ba4872cadf3ce35a7a494.github.io/iPod/)

## CLI
This library comes with a CLI! Install it:
```
git clone https://github.com/760ceb3b9c0ba4872cadf3ce35a7a494/iPod
cd iPod
pip3 install .
```
Next, run `ipod --help` for syntax.

## Support
### Model support
All Samsung-based iPods should be supported, other than the iPod shuffle. PortalPlayer-based iPods are out of scope for this library.  

| Model                         | Supported |
|-------------------------------|:---------:|
| iPod nano (1st generation)    | ❌ No      |
| iPod nano (2nd generation)    | ❌ No      |
| iPod nano (3rd generation)    | ✅ Yes     |
| iPod nano (4th generation)    | ✅ Yes     |
| iPod nano (5th generation)    | ✅ Yes     |
| iPod nano (6th generation)    | ✅ Yes     |
| iPod nano (7th generation)    | ✅ Yes     |
| iPod classic (6th generation) | ✅ Yes     |
| All other iPods               | ❌ No      |

### Operating system support
| Operating system | Recovery, DFU images | Device information, software updates | Notes                                                            |
|-----------------:|:--------------------:|:------------------------------------:|------------------------------------------------------------------|
| Windows          | ❌ No                 | ✅ Yes                                |                                                                  |
| macOS            | ✅ Yes                | ✅ Yes                                | libusb backend used for all modes. requires root                 |
| Linux            | ✅ Yes                | ✅ Yes                                | sg_io backend used for normal modes, libusb backend used for DFU |

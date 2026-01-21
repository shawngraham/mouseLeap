# mouseLeap
Python script for controlling the mouse using [ultra leap](https://www.ultraleap.com/) Leap 2 controller.

## Leap Motion Mouse Controller Requirements
## ==========================================

## Mouse control library
pynput>=1.7.0

## Screen info for multi-monitor support (optional but recommended)
screeninfo>=0.8.0

Note: The 'leap' module (leapc-python-api) must be installed separately from the official Ultraleap repository:
[https://github.com/ultraleap/leapc-python-bindings]

## Installation of the leap bit:

```bash
git clone https://github.com/ultraleap/leapc-python-bindings
cd leapc-python-bindings
pip install -e leapc-python-api
pip install cffi
pip install numpy
```
Directories should be arranged like this:

```
|
|-your project
  |- mouseLeap
  |- leapc-python-api
```

Python 3.12.

```bash
python mouseLeap/leap_mouse.py
```
Then move your hand over the controller: you're controlling the mouse!

+ Click: Quick dip down and back up
+ Double-click: Two quick dips in succession
+ Drag: Dip down and hold low for ~0.2 seconds → drag starts → move while holding low → raise hand to release

### tuning

```
# If dip is triggering too easily, require a deeper dip
python leap_mouse.py --dip-distance 50

# If drag starts too quickly (accidental drags), increase hold time
python leap_mouse.py --drag-hold 0.3

# Combine as needed
python leap_mouse.py --dip-distance 45 --drag-hold 0.25
```

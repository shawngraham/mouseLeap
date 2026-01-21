# mouseLeap
Python script for controlling the mouse using [ultra leap](https://www.ultraleap.com/) Leap 2 controller.


## Mouse control library
pynput>=1.7.0

## Screen info for multi-monitor support (optional)
screeninfo>=0.8.0

The 'leap' module (leapc-python-api) must be installed separately from the official Ultraleap repository:
[https://github.com/ultraleap/leapc-python-bindings]

## Installation of the leap bit:

```bash
git clone https://github.com/ultraleap/leapc-python-bindings
cd leapc-python-bindings
pip install -e leapc-python-api
pip install cffi
pip install numpy
```

Then clone or download this repository: 

```
git clone https://shawngraham/mouseLeap
```

Directories should be arranged like this:

```
|
|-your_project
  |- mouseLeap
  |- leapc-python-api
```

We wrote this in a Python 3.12 environment, via conda.

## Give it a whirl

```bash
python mouseLeap/leap_mouse.py
```
Then move your hand over the controller: you're controlling the mouse!

+ Quick pinch → Click
+ Double-pinch → Double-click
+ Pinch and hold → Drag (release pinch to drop)
+ Make a fist → Pause tracking
+ Press Ctrl+C to exit


### tuning

```
# More smoothing on pinch detection (default 0.5, try higher)
python leap_mouse.py --pinch-smoothing 0.7

# Even stickier - require pinch to drop very low to release
python leap_mouse.py --pinch-release 0.2

# Require stronger pinch to start (if accidental triggers)
python leap_mouse.py --pinch-engage 0.8

# Longer hold before drag starts (if accidental drags)
python leap_mouse.py --drag-delay 0.25

# Combine them
python leap_mouse.py --pinch-smoothing 0.7 --pinch-release 0.2 --drag-delay 0.2
```

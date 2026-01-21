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
## Leap Motion Mouse Controller - Controls

### Right Hand Only

| Gesture | Action |
|---------|--------|
| Move hand | Move cursor |
| Quick pinch | Click |
| Double-pinch | Double-click |
| Pinch and hold | Drag |

### Two Hands

| Left Hand | Right Hand | Action |
|-----------|------------|--------|
| Fist | Open | **Scroll** – move right hand up/down to scroll |
| Open | Open | **Pan** – move both hands together (middle-click drag) |
| Pinch | Pinch | **Zoom** – spread hands apart or bring together |
| Fist | Fist (hold 1s) | **Exit program** |


### Command Line Options
```bash
# Cursor movement
--sensitivity, -s     Movement multiplier (default: 1.5)
--smoothing, -m       Cursor smoothing 0-1 (default: 0.3)

# Pinch/click tuning
--pinch-engage        Strength to start click/drag (default: 0.7)
--pinch-release       Strength to release (default: 0.3, lower = stickier)
--pinch-smoothing     Smoothing to reduce tremor (default: 0.5)
--drag-delay          Seconds before drag starts (default: 0.15)

# Two-hand gestures
--scroll-sensitivity  Scroll speed (default: 0.05)
--zoom-sensitivity    Zoom speed (default: 0.02)
```

### tuning

```
# Scroll/zoom too fast or slow?
python leap_mouse.py --scroll-sensitivity 0.08 --zoom-sensitivity 0.03

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

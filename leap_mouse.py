#!/usr/bin/env python3
"""
Leap Motion Mouse Controller
============================
Controls the desktop mouse using hand tracking from an Ultraleap Leap Motion Controller 2.

Features:
- Hand position controls mouse cursor
- Sticky pinch gesture for click (with hysteresis to handle tremor)
- Pinch and hold for click-and-drag
- Fist gesture to pause/resume tracking

Requirements:
- Ultraleap Tracking Service 6.x running
- leapc-python-api (from ultraleap/leapc-python-bindings)
- pynput
- screeninfo (optional, for multi-monitor support)

Usage:
    python leap_mouse.py [--sensitivity 1.5] [--smoothing 0.3]
"""

import argparse
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple, Deque

try:
    import leap
except ImportError:
    print("Error: Could not import 'leap' module.")
    print("\nTo install the Ultraleap Python bindings:")
    print("1. Clone: git clone https://github.com/ultraleap/leapc-python-bindings")
    print("2. Install: pip install -e leapc-python-bindings/leapc-python-api")
    print("\nMake sure Ultraleap Tracking Service is installed and running.")
    sys.exit(1)

try:
    from pynput.mouse import Button, Controller as MouseController
except ImportError:
    print("Error: Could not import 'pynput' module.")
    print("Install with: pip install pynput")
    sys.exit(1)

# Try to get screen dimensions
try:
    from screeninfo import get_monitors
    monitors = get_monitors()
    PRIMARY_MONITOR = monitors[0]
    SCREEN_WIDTH = PRIMARY_MONITOR.width
    SCREEN_HEIGHT = PRIMARY_MONITOR.height
except ImportError:
    print("Note: 'screeninfo' not installed. Using default 1920x1080 resolution.")
    print("Install with: pip install screeninfo")
    SCREEN_WIDTH = 1920
    SCREEN_HEIGHT = 1080


@dataclass
class Config:
    """Configuration for the mouse controller."""
    sensitivity: float = 1.5
    smoothing: float = 0.3
    
    # Sticky pinch settings (hysteresis)
    pinch_engage: float = 0.7      # Pinch strength to START click/drag
    pinch_release: float = 0.3     # Pinch strength to RELEASE (much lower = sticky)
    pinch_smoothing: float = 0.5   # Smoothing for pinch strength (reduces tremor)
    
    # Drag timing
    drag_delay: float = 0.15       # Seconds of pinch before drag starts (vs click)
    
    # Click timing
    double_click_window: float = 0.4
    
    # Leap Motion interaction box bounds (in mm from device center)
    leap_x_range: Tuple[float, float] = (-150, 150)
    leap_y_range: Tuple[float, float] = (100, 350)
    
    # Grab strength threshold to pause tracking
    pause_threshold: float = 0.9
    
    screen_width: int = SCREEN_WIDTH
    screen_height: int = SCREEN_HEIGHT


class LeapMouseListener(leap.Listener):
    """
    Listener that receives tracking events and controls the mouse.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.mouse = MouseController()
        
        # State tracking
        self.is_paused = False
        self.smoothed_position: Optional[Tuple[float, float]] = None
        
        # Smoothed pinch value
        self.smoothed_pinch: float = 0.0
        
        # Pinch/click/drag state
        self.is_pinched = False           # Currently in pinched state
        self.pinch_start_time: Optional[float] = None
        self.is_dragging = False          # Mouse button is held down
        self.did_drag = False             # Was this pinch a drag? (to suppress click on release)
        
        # Click timing
        self.last_click_time = 0.0
        
    def map_to_screen(self, palm) -> Tuple[int, int]:
        """Map Leap Motion palm coordinates to screen coordinates."""
        x_min, x_max = self.config.leap_x_range
        y_min, y_max = self.config.leap_y_range
        
        leap_x = palm.position.x
        leap_y = palm.position.y
        
        # Normalize to 0-1 range
        norm_x = (leap_x - x_min) / (x_max - x_min)
        norm_y = (leap_y - y_min) / (y_max - y_min)
        
        # Clamp to valid range
        norm_x = max(0, min(1, norm_x))
        norm_y = max(0, min(1, norm_y))
        
        # Apply sensitivity (expand from center)
        center = 0.5
        norm_x = center + (norm_x - center) * self.config.sensitivity
        norm_y = center + (norm_y - center) * self.config.sensitivity
        
        # Clamp again
        norm_x = max(0, min(1, norm_x))
        norm_y = max(0, min(1, norm_y))
        
        # Map to screen (Y is inverted - higher leap Y = lower screen Y)
        screen_x = int(norm_x * self.config.screen_width)
        screen_y = int((1 - norm_y) * self.config.screen_height)
        
        return screen_x, screen_y
    
    def smooth_position(self, new_pos: Tuple[int, int]) -> Tuple[int, int]:
        """Apply exponential smoothing to cursor position."""
        if self.smoothed_position is None:
            self.smoothed_position = new_pos
            return new_pos
        
        alpha = 1 - self.config.smoothing
        smooth_x = int(alpha * new_pos[0] + self.config.smoothing * self.smoothed_position[0])
        smooth_y = int(alpha * new_pos[1] + self.config.smoothing * self.smoothed_position[1])
        
        self.smoothed_position = (smooth_x, smooth_y)
        return self.smoothed_position
    
    def smooth_pinch(self, raw_pinch: float) -> float:
        """Apply smoothing to pinch strength to reduce tremor effects."""
        alpha = 1 - self.config.pinch_smoothing
        self.smoothed_pinch = alpha * raw_pinch + self.config.pinch_smoothing * self.smoothed_pinch
        return self.smoothed_pinch
    
    def handle_pinch(self, raw_pinch: float):
        """Handle sticky pinch for click and drag with hysteresis."""
        current_time = time.time()
        pinch = self.smooth_pinch(raw_pinch)
        
        # STATE: Not pinched - check if we should engage
        if not self.is_pinched:
            if pinch >= self.config.pinch_engage:
                self.is_pinched = True
                self.pinch_start_time = current_time
                self.did_drag = False
                # Don't click yet - wait to see if it's click or drag
        
        # STATE: Pinched - check for drag start or release
        else:
            pinch_duration = current_time - self.pinch_start_time
            
            # Check if we should start dragging
            if not self.is_dragging and pinch_duration >= self.config.drag_delay:
                self.is_dragging = True
                self.did_drag = True
                self.mouse.press(Button.left)
                print("  [Drag Start]")
            
            # Check if pinch released (using lower threshold = sticky)
            if pinch < self.config.pinch_release:
                if self.is_dragging:
                    # End drag
                    self.mouse.release(Button.left)
                    print("  [Drag End]")
                    self.is_dragging = False
                elif not self.did_drag:
                    # It was a quick pinch = click
                    time_since_last = current_time - self.last_click_time
                    
                    if time_since_last <= self.config.double_click_window:
                        self.mouse.click(Button.left, 2)
                        print("  [Double Click]")
                    else:
                        self.mouse.click(Button.left, 1)
                        print("  [Click]")
                    self.last_click_time = current_time
                
                # Reset pinch state
                self.is_pinched = False
                self.pinch_start_time = None
                self.did_drag = False
    
    def process_hand(self, hand):
        """Process a single hand's tracking data."""
        # Check for pause gesture (fist)
        if hand.grab_strength >= self.config.pause_threshold:
            if not self.is_paused:
                # Release drag if pausing
                if self.is_dragging:
                    self.mouse.release(Button.left)
                    print("  [Drag Cancelled]")
                    self.is_dragging = False
                    self.is_pinched = False
                
                self.is_paused = True
                print("\n[Paused - Open hand to resume]")
            return
        else:
            if self.is_paused:
                self.is_paused = False
                print("\n[Resumed]")
        
        # Map palm position to screen
        screen_pos = self.map_to_screen(hand.palm)
        
        # Apply smoothing
        smooth_pos = self.smooth_position(screen_pos)
        
        # Move mouse
        self.mouse.position = smooth_pos
        
        # Handle pinch gesture
        self.handle_pinch(hand.pinch_strength)
    
    def on_tracking_event(self, event):
        """Called when a tracking event is received."""
        if not event.hands:
            # Hand lost - release any drag
            if self.is_dragging:
                self.mouse.release(Button.left)
                print("  [Drag Cancelled - Hand Lost]")
                self.is_dragging = False
                self.is_pinched = False
            return
        
        # Prefer right hand if multiple hands detected
        hand = None
        for h in event.hands:
            if h.type == leap.HandType.Right:
                hand = h
                break
        
        if hand is None:
            hand = event.hands[0]
        
        self.process_hand(hand)
    
    def on_connection_event(self, event):
        print("[Connected to Leap Motion service]")
    
    def on_device_event(self, event):
        print("[Device connected]")


def main():
    parser = argparse.ArgumentParser(
        description="Control your mouse with Leap Motion hand tracking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python leap_mouse.py                        # Run with defaults
  python leap_mouse.py --sensitivity 2.0      # More sensitive cursor movement
  python leap_mouse.py --smoothing 0.5        # Smoother but laggier cursor
  python leap_mouse.py --pinch-engage 0.8     # Require stronger pinch to start
  python leap_mouse.py --pinch-release 0.2    # More sticky (lower = stickier)
  python leap_mouse.py --pinch-smoothing 0.7  # More smoothing on pinch (reduces tremor)
        """
    )
    
    parser.add_argument("--sensitivity", "-s", type=float, default=1.5,
                        help="Movement sensitivity multiplier (default: 1.5)")
    parser.add_argument("--smoothing", "-m", type=float, default=0.3,
                        help="Cursor smoothing factor 0-1 (default: 0.3)")
    parser.add_argument("--pinch-engage", type=float, default=0.7,
                        help="Pinch strength to engage click/drag (default: 0.7)")
    parser.add_argument("--pinch-release", type=float, default=0.3,
                        help="Pinch strength to release - lower=stickier (default: 0.3)")
    parser.add_argument("--pinch-smoothing", type=float, default=0.5,
                        help="Pinch smoothing to reduce tremor 0-1 (default: 0.5)")
    parser.add_argument("--drag-delay", type=float, default=0.15,
                        help="Seconds before pinch becomes drag (default: 0.15)")
    parser.add_argument("--screen-width", type=int, default=SCREEN_WIDTH,
                        help=f"Screen width in pixels (default: {SCREEN_WIDTH})")
    parser.add_argument("--screen-height", type=int, default=SCREEN_HEIGHT,
                        help=f"Screen height in pixels (default: {SCREEN_HEIGHT})")
    
    args = parser.parse_args()
    
    config = Config(
        sensitivity=args.sensitivity,
        smoothing=args.smoothing,
        pinch_engage=args.pinch_engage,
        pinch_release=args.pinch_release,
        pinch_smoothing=args.pinch_smoothing,
        drag_delay=args.drag_delay,
        screen_width=args.screen_width,
        screen_height=args.screen_height,
    )
    
    print("\n" + "=" * 50)
    print("Leap Motion Mouse Controller")
    print("=" * 50)
    print(f"\nScreen: {config.screen_width}x{config.screen_height}")
    print(f"Sensitivity: {config.sensitivity}")
    print(f"Smoothing: {config.smoothing}")
    print(f"Pinch engage/release: {config.pinch_engage}/{config.pinch_release}")
    print(f"Pinch smoothing: {config.pinch_smoothing}")
    print(f"Drag delay: {config.drag_delay}s")
    print("\nControls:")
    print("  - Move hand to move cursor")
    print("  - Quick pinch → Click")
    print("  - Double-pinch → Double-click") 
    print("  - Pinch and hold → Drag (release pinch to drop)")
    print("  - Make a fist → Pause tracking")
    print("  - Press Ctrl+C to exit")
    print("\n" + "=" * 50)
    
    listener = LeapMouseListener(config)
    connection = leap.Connection()
    connection.add_listener(listener)
    
    print("\nWaiting for hand tracking...")
    print("(Place your hand above the Leap Motion device)\n")
    
    try:
        with connection.open():
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n[Shutting down...]")
        if listener.is_dragging:
            listener.mouse.release(Button.left)
    except Exception as e:
        print(f"\nError: {e}")
        print("\nMake sure:")
        print("  1. Ultraleap Tracking Service is running")
        print("  2. Leap Motion Controller is connected")
    finally:
        print("[Goodbye!]")


if __name__ == "__main__":
    main()
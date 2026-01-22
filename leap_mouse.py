#!/usr/bin/env python3
"""
Leap Motion Mouse Controller
============================
Controls the desktop mouse using hand tracking from an Ultraleap Leap Motion Controller 2.

Features:
- Right hand controls cursor + sticky pinch for click/drag
- Two-hand gestures:
  - Both fists (hold) → Exit program
  - Left fist + right open → Scroll mode
  - Both hands open → Pan mode (middle-click drag)
  - Both hands pinch together/apart → Zoom
- Optional window targeting (only active when specified window is focused)

Requirements:
- Ultraleap Tracking Service 6.x running
- leapc-python-api (from ultraleap/leapc-python-bindings)
- pynput
- screeninfo (optional, for multi-monitor support)

Usage:
    python leap_mouse.py [--sensitivity 1.5] [--smoothing 0.3]
    python leap_mouse.py --window "MeshLab"  # Only active when MeshLab is focused
"""

import argparse
import sys
import time
import math
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple


def get_running_apps() -> list[dict]:
    """Get list of running GUI applications using pywinctl."""
    try:
        import pywinctl as pwc
        
        # Get all windows
        windows = pwc.getAllWindows()
        
        # Extract unique app names
        apps = []
        seen = set()
        
        for win in windows:
            title = win.title
            # Get app name - on macOS this is usually the app, on others use window title
            try:
                app_name = win.getAppName()
            except:
                app_name = title.split(' - ')[-1] if ' - ' in title else title
            
            if app_name and app_name not in seen and app_name.strip():
                seen.add(app_name)
                apps.append({'name': app_name, 'title': title})
        
        return sorted(apps, key=lambda x: x['name'].lower())
    
    except ImportError:
        print("pywinctl not installed. Install with: pip install pywinctl")
        return []
    except Exception as e:
        print(f"Error getting windows: {e}")
        return []


# Cache pywinctl module to avoid repeated imports during tracking
_pwc = None
def _get_pwc():
    global _pwc
    if _pwc is None:
        try:
            import pywinctl as pwc
            _pwc = pwc
        except ImportError:
            pass
    return _pwc


def get_frontmost_app() -> Optional[str]:
    """Get the name of the currently focused application using pywinctl."""
    pwc = _get_pwc()
    if pwc is None:
        return None
    
    try:
        win = pwc.getActiveWindow()
        if win:
            try:
                return win.getAppName()
            except:
                return win.title
    except Exception:
        pass
    
    return None


def select_target_window() -> Optional[str]:
    """Interactive window selection. Returns app name or None for all windows."""
    apps = get_running_apps()
    
    if not apps:
        print("Could not detect running applications.")
        print("Install pywinctl: pip install pywinctl")
        print("Tracking will be active for all windows.\n")
        return None
    
    print("\n" + "=" * 50)
    print("SELECT TARGET WINDOW")
    print("=" * 50)
    print("\n  0. [All windows - no filtering]\n")
    
    for i, app in enumerate(apps, 1):
        print(f"  {i}. {app['name']}")
    
    print()
    
    while True:
        try:
            choice = input("Enter number (or press Enter for all): ").strip()
            
            if choice == "":
                print("\nTracking: All windows")
                return None
            
            idx = int(choice)
            
            if idx == 0:
                print("\nTracking: All windows")
                return None
            elif 1 <= idx <= len(apps):
                selected = apps[idx - 1]['name']
                print(f"\nTracking: {selected}")
                return selected
            else:
                print(f"Please enter 0-{len(apps)}")
        
        except ValueError:
            print("Please enter a number")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled")
            sys.exit(0)

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


class Mode(Enum):
    """Current interaction mode based on hand gestures."""
    CURSOR = auto()      # Right hand only - normal cursor control
    SCROLL = auto()      # Left fist + right open - scroll mode
    PAN = auto()         # Both hands open - pan mode
    ZOOM = auto()        # Both hands pinching - zoom mode
    EXIT_PENDING = auto() # Both fists - waiting to confirm exit


@dataclass
class Config:
    """Configuration for the mouse controller."""
    sensitivity: float = 1.5
    smoothing: float = 0.3
    
    # Sticky pinch settings (hysteresis)
    pinch_engage: float = 0.7
    pinch_release: float = 0.3
    pinch_smoothing: float = 0.5
    
    # Gesture thresholds
    fist_threshold: float = 0.8       # Grab strength to count as fist
    open_threshold: float = 0.4       # Below this grab strength = open hand
    pinch_threshold: float = 0.6      # Pinch strength for zoom gesture
    
    # Drag timing
    drag_delay: float = 0.15
    
    # Exit gesture timing
    exit_hold_time: float = 1.0       # Seconds to hold both fists to exit
    
    # Scroll settings
    scroll_sensitivity: float = 0.05  # Scroll amount per mm of hand movement
    
    # Zoom settings  
    zoom_sensitivity: float = 0.02    # Scroll amount per mm of distance change
    
    # Click timing
    double_click_window: float = 0.4
    
    # Leap Motion interaction box bounds (in mm)
    leap_x_range: Tuple[float, float] = (-150, 150)
    leap_y_range: Tuple[float, float] = (100, 350)
    
    screen_width: int = SCREEN_WIDTH
    screen_height: int = SCREEN_HEIGHT
    
    # Window targeting (None = all windows)
    target_window: Optional[str] = None


class LeapMouseListener(leap.Listener):
    """
    Listener that receives tracking events and controls the mouse.
    """
    
    def __init__(self, config: Config, exit_callback):
        self.config = config
        self.mouse = MouseController()
        self.exit_callback = exit_callback
        
        # Current mode
        self.mode = Mode.CURSOR
        self.prev_mode = Mode.CURSOR
        
        # Cursor state
        self.smoothed_position: Optional[Tuple[float, float]] = None
        
        # Pinch state (for cursor mode)
        self.smoothed_pinch: float = 0.0
        self.is_pinched = False
        self.pinch_start_time: Optional[float] = None
        self.is_dragging = False
        self.did_drag = False
        self.last_click_time = 0.0
        
        # Pan state
        self.is_panning = False
        self.last_pan_pos: Optional[Tuple[float, float]] = None
        
        # Scroll state
        self.last_scroll_y: Optional[float] = None
        
        # Zoom state
        self.last_hand_distance: Optional[float] = None
        
        # Exit state
        self.exit_start_time: Optional[float] = None
        
        # Window targeting state
        self._window_active = (config.target_window is None)  # Start inactive if targeting a window
        self._window_lock = threading.Lock()
        self._stop_window_monitor = threading.Event()
        
        # Start background window monitor if targeting a window
        if config.target_window is not None:
            self._window_thread = threading.Thread(target=self._monitor_window, daemon=True)
            self._window_thread.start()
        else:
            self._window_thread = None
    
    def _monitor_window(self):
        """Background thread that monitors window focus."""
        while not self._stop_window_monitor.is_set():
            active_app = get_frontmost_app()
            
            if active_app is not None:
                is_active = self.config.target_window.lower() == active_app.lower()
                
                with self._window_lock:
                    was_active = self._window_active
                    self._window_active = is_active
                
                # Notify on state change (outside lock)
                if is_active != was_active:
                    if is_active:
                        print(f"\n  [Window Active: {active_app}]")
                    else:
                        self.release_all_buttons()
                        print(f"\n  [Window Inactive: {active_app} - tracking paused]")
            
            # Check every 100ms
            time.sleep(0.1)
    
    def is_target_window_active(self) -> bool:
        """Check if the target window is currently focused."""
        if self.config.target_window is None:
            return True
        with self._window_lock:
            return self._window_active
    
    def stop_window_monitor(self):
        """Stop the background window monitor thread."""
        if self._window_thread is not None:
            self._stop_window_monitor.set()
            self._window_thread.join(timeout=1.0)
        
    def get_hand_state(self, hand) -> str:
        """Determine if hand is 'fist', 'open', or 'pinch'."""
        if hand.grab_strength >= self.config.fist_threshold:
            return 'fist'
        elif hand.pinch_strength >= self.config.pinch_threshold:
            return 'pinch'
        elif hand.grab_strength < self.config.open_threshold:
            return 'open'
        else:
            return 'neutral'
    
    def determine_mode(self, left_hand, right_hand) -> Mode:
        """Determine interaction mode based on hand states."""
        # No hands
        if left_hand is None and right_hand is None:
            return Mode.CURSOR
        
        # Right hand only
        if left_hand is None and right_hand is not None:
            return Mode.CURSOR
        
        # Left hand only - ignore (could be reaching for keyboard)
        if left_hand is not None and right_hand is None:
            return self.mode  # Keep current mode
        
        # Both hands present
        left_state = self.get_hand_state(left_hand)
        right_state = self.get_hand_state(right_hand)
        
        # Both fists = exit
        if left_state == 'fist' and right_state == 'fist':
            return Mode.EXIT_PENDING
        
        # Left fist + right open = scroll
        if left_state == 'fist' and right_state in ('open', 'neutral'):
            return Mode.SCROLL
        
        # Both hands pinching = zoom
        if left_state == 'pinch' and right_state == 'pinch':
            return Mode.ZOOM
        
        # Both hands open = pan
        if left_state in ('open', 'neutral') and right_state in ('open', 'neutral'):
            return Mode.PAN
        
        # Default to cursor mode
        return Mode.CURSOR
    
    def map_to_screen(self, palm) -> Tuple[int, int]:
        """Map Leap Motion palm coordinates to screen coordinates."""
        x_min, x_max = self.config.leap_x_range
        y_min, y_max = self.config.leap_y_range
        
        leap_x = palm.position.x
        leap_y = palm.position.y
        
        norm_x = (leap_x - x_min) / (x_max - x_min)
        norm_y = (leap_y - y_min) / (y_max - y_min)
        
        norm_x = max(0, min(1, norm_x))
        norm_y = max(0, min(1, norm_y))
        
        center = 0.5
        norm_x = center + (norm_x - center) * self.config.sensitivity
        norm_y = center + (norm_y - center) * self.config.sensitivity
        
        norm_x = max(0, min(1, norm_x))
        norm_y = max(0, min(1, norm_y))
        
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
        """Apply smoothing to pinch strength."""
        alpha = 1 - self.config.pinch_smoothing
        self.smoothed_pinch = alpha * raw_pinch + self.config.pinch_smoothing * self.smoothed_pinch
        return self.smoothed_pinch
    
    def release_all_buttons(self):
        """Release any held mouse buttons."""
        if self.is_dragging:
            self.mouse.release(Button.left)
            self.is_dragging = False
            self.is_pinched = False
        if self.is_panning:
            self.mouse.release(Button.middle)
            self.is_panning = False
    
    def handle_mode_change(self, new_mode: Mode):
        """Handle transition between modes."""
        if new_mode != self.mode:
            # Release any held buttons from previous mode
            self.release_all_buttons()
            
            # Reset mode-specific state
            self.last_scroll_y = None
            self.last_hand_distance = None
            self.last_pan_pos = None
            
            if new_mode != Mode.EXIT_PENDING:
                self.exit_start_time = None
            
            # Announce mode change
            mode_names = {
                Mode.CURSOR: "Cursor",
                Mode.SCROLL: "Scroll",
                Mode.PAN: "Pan",
                Mode.ZOOM: "Zoom",
                Mode.EXIT_PENDING: "Exit (hold fists)"
            }
            if self.mode != new_mode:
                print(f"  [{mode_names.get(new_mode, 'Unknown')} Mode]")
            
            self.prev_mode = self.mode
            self.mode = new_mode
    
    def handle_cursor_mode(self, right_hand):
        """Handle normal cursor control with sticky pinch."""
        # Move cursor
        screen_pos = self.map_to_screen(right_hand.palm)
        smooth_pos = self.smooth_position(screen_pos)
        self.mouse.position = smooth_pos
        
        # Handle pinch
        current_time = time.time()
        pinch = self.smooth_pinch(right_hand.pinch_strength)
        
        if not self.is_pinched:
            if pinch >= self.config.pinch_engage:
                self.is_pinched = True
                self.pinch_start_time = current_time
                self.did_drag = False
        else:
            pinch_duration = current_time - self.pinch_start_time
            
            if not self.is_dragging and pinch_duration >= self.config.drag_delay:
                self.is_dragging = True
                self.did_drag = True
                self.mouse.press(Button.left)
                print("  [Drag Start]")
            
            if pinch < self.config.pinch_release:
                if self.is_dragging:
                    self.mouse.release(Button.left)
                    print("  [Drag End]")
                    self.is_dragging = False
                elif not self.did_drag:
                    time_since_last = current_time - self.last_click_time
                    if time_since_last <= self.config.double_click_window:
                        self.mouse.click(Button.left, 2)
                        print("  [Double Click]")
                    else:
                        self.mouse.click(Button.left, 1)
                        print("  [Click]")
                    self.last_click_time = current_time
                
                self.is_pinched = False
                self.pinch_start_time = None
                self.did_drag = False
    
    def handle_scroll_mode(self, right_hand):
        """Handle scroll mode - right hand Y movement scrolls."""
        current_y = right_hand.palm.position.y
        
        if self.last_scroll_y is not None:
            delta_y = current_y - self.last_scroll_y
            scroll_amount = int(delta_y * self.config.scroll_sensitivity)
            
            if scroll_amount != 0:
                self.mouse.scroll(0, scroll_amount)
        
        self.last_scroll_y = current_y
    
    def handle_pan_mode(self, left_hand, right_hand):
        """Handle pan mode - average hand position controls middle-click drag."""
        # Calculate average position of both hands
        avg_x = (left_hand.palm.position.x + right_hand.palm.position.x) / 2
        avg_y = (left_hand.palm.position.y + right_hand.palm.position.y) / 2
        
        # Start panning if not already
        if not self.is_panning:
            self.mouse.press(Button.middle)
            self.is_panning = True
            self.last_pan_pos = (avg_x, avg_y)
            print("  [Pan Start]")
            return
        
        if self.last_pan_pos is not None:
            # Calculate delta and move cursor
            delta_x = (avg_x - self.last_pan_pos[0]) * self.config.sensitivity
            delta_y = -(avg_y - self.last_pan_pos[1]) * self.config.sensitivity  # Invert Y
            
            self.mouse.move(int(delta_x), int(delta_y))
        
        self.last_pan_pos = (avg_x, avg_y)
    
    def handle_zoom_mode(self, left_hand, right_hand):
        """Handle zoom mode - distance between hands controls zoom."""
        # Calculate distance between hands
        dx = right_hand.palm.position.x - left_hand.palm.position.x
        dy = right_hand.palm.position.y - left_hand.palm.position.y
        dz = right_hand.palm.position.z - left_hand.palm.position.z
        distance = math.sqrt(dx*dx + dy*dy + dz*dz)
        
        if self.last_hand_distance is not None:
            delta = distance - self.last_hand_distance
            scroll_amount = int(delta * self.config.zoom_sensitivity)
            
            if scroll_amount != 0:
                self.mouse.scroll(0, scroll_amount)
        
        self.last_hand_distance = distance
    
    def handle_exit_pending(self):
        """Handle exit gesture - both fists held."""
        current_time = time.time()
        
        if self.exit_start_time is None:
            self.exit_start_time = current_time
            print(f"  [Hold fists for {self.config.exit_hold_time}s to exit...]")
        
        elapsed = current_time - self.exit_start_time
        
        if elapsed >= self.config.exit_hold_time:
            print("\n  [EXIT GESTURE DETECTED]")
            self.exit_callback()
    
    def on_tracking_event(self, event):
        """Called when a tracking event is received."""
        # Check if target window is active
        if not self.is_target_window_active():
            return  # Skip processing when target window is not focused
        
        # Separate hands
        left_hand = None
        right_hand = None
        
        for hand in event.hands:
            if hand.type == leap.HandType.Left:
                left_hand = hand
            elif hand.type == leap.HandType.Right:
                right_hand = hand
        
        # Handle no hands
        if not event.hands:
            if self.is_dragging or self.is_panning:
                self.release_all_buttons()
                print("  [Released - Hands Lost]")
            return
        
        # Determine and handle mode
        new_mode = self.determine_mode(left_hand, right_hand)
        self.handle_mode_change(new_mode)
        
        # Execute mode-specific behavior
        if self.mode == Mode.CURSOR and right_hand:
            self.handle_cursor_mode(right_hand)
        
        elif self.mode == Mode.SCROLL and right_hand:
            self.handle_scroll_mode(right_hand)
        
        elif self.mode == Mode.PAN and left_hand and right_hand:
            self.handle_pan_mode(left_hand, right_hand)
        
        elif self.mode == Mode.ZOOM and left_hand and right_hand:
            self.handle_zoom_mode(left_hand, right_hand)
        
        elif self.mode == Mode.EXIT_PENDING:
            self.handle_exit_pending()
    
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
  python leap_mouse.py                        # Interactive window selection
  python leap_mouse.py --all-windows          # Track in all windows (no prompt)
  python leap_mouse.py --window "MeshLab"     # Direct window specification
  python leap_mouse.py --sensitivity 2.0      # More sensitive cursor movement
        """
    )
    
    parser.add_argument("--sensitivity", "-s", type=float, default=1.5,
                        help="Movement sensitivity multiplier (default: 1.5)")
    parser.add_argument("--smoothing", "-m", type=float, default=0.3,
                        help="Cursor smoothing factor 0-1 (default: 0.3)")
    parser.add_argument("--pinch-engage", type=float, default=0.7,
                        help="Pinch strength to engage click/drag (default: 0.7)")
    parser.add_argument("--pinch-release", type=float, default=0.3,
                        help="Pinch strength to release (default: 0.3)")
    parser.add_argument("--pinch-smoothing", type=float, default=0.5,
                        help="Pinch smoothing to reduce tremor (default: 0.5)")
    parser.add_argument("--drag-delay", type=float, default=0.15,
                        help="Seconds before pinch becomes drag (default: 0.15)")
    parser.add_argument("--scroll-sensitivity", type=float, default=0.05,
                        help="Scroll sensitivity (default: 0.05)")
    parser.add_argument("--zoom-sensitivity", type=float, default=0.02,
                        help="Zoom sensitivity (default: 0.02)")
    parser.add_argument("--screen-width", type=int, default=SCREEN_WIDTH,
                        help=f"Screen width in pixels (default: {SCREEN_WIDTH})")
    parser.add_argument("--screen-height", type=int, default=SCREEN_HEIGHT,
                        help=f"Screen height in pixels (default: {SCREEN_HEIGHT})")
    parser.add_argument("--window", "-w", type=str, default=None,
                        help="Target window name. Only track when this window is focused.")
    parser.add_argument("--all-windows", "-a", action="store_true",
                        help="Track in all windows (skip interactive selection)")
    
    args = parser.parse_args()
    
    # Determine target window
    if args.window:
        target_window = args.window
    elif args.all_windows:
        target_window = None
    else:
        # Interactive selection
        target_window = select_target_window()
    
    config = Config(
        sensitivity=args.sensitivity,
        smoothing=args.smoothing,
        pinch_engage=args.pinch_engage,
        pinch_release=args.pinch_release,
        pinch_smoothing=args.pinch_smoothing,
        drag_delay=args.drag_delay,
        scroll_sensitivity=args.scroll_sensitivity,
        zoom_sensitivity=args.zoom_sensitivity,
        screen_width=args.screen_width,
        screen_height=args.screen_height,
        target_window=target_window,
    )
    
    print("\n" + "=" * 60)
    print("Leap Motion Mouse Controller")
    print("=" * 60)
    print(f"\nScreen: {config.screen_width}x{config.screen_height}")
    if config.target_window:
        print(f"Target window: {config.target_window}")
    else:
        print("Target window: All windows")
    print(f"Sensitivity: {config.sensitivity}")
    print(f"Smoothing: {config.smoothing}")
    print(f"Pinch engage/release: {config.pinch_engage}/{config.pinch_release}")
    
    print("\n" + "-" * 60)
    print("CONTROLS:")
    print("-" * 60)
    print("  RIGHT HAND ONLY:")
    print("    Move hand         → Move cursor")
    print("    Quick pinch       → Click")
    print("    Double-pinch      → Double-click")
    print("    Pinch and hold    → Drag")
    print()
    print("  TWO HANDS:")
    print("    Left fist + Right open    → Scroll (move right hand up/down)")
    print("    Both hands open           → Pan (move both hands)")
    print("    Both hands pinch          → Zoom (spread/pinch hands)")
    print("    Both fists (hold 1s)      → EXIT PROGRAM")
    print("-" * 60)
    
    # Exit flag
    should_exit = False
    
    def request_exit():
        nonlocal should_exit
        should_exit = True
    
    listener = LeapMouseListener(config, request_exit)
    connection = leap.Connection()
    connection.add_listener(listener)
    
    print("\nWaiting for hand tracking...")
    print("(Place your hand above the Leap Motion device)\n")
    
    try:
        with connection.open():
            while not should_exit:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n[Ctrl+C - Shutting down...]")
    except Exception as e:
        print(f"\nError: {e}")
        print("\nMake sure:")
        print("  1. Ultraleap Tracking Service is running")
        print("  2. Leap Motion Controller is connected")
    finally:
        listener.stop_window_monitor()
        listener.release_all_buttons()
        print("[Goodbye!]")


if __name__ == "__main__":
    main()

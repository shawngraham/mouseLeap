#!/usr/bin/env python3
"""
Leap Motion Mouse Controller (WebSocket Version)
=================================================
Alternative implementation using Ultraleap's WebSocket server.

This version connects to the Ultraleap Tracking WebSocket server instead of
using the native LeapC bindings. It may be easier to get working if you have
issues with the native Python bindings.

Requirements:
1. Enable the WebSocket server in Ultraleap Tracking Service:
   - Open Ultraleap Control Panel
   - Go to Settings > General
   - Enable "Allow Web Apps"
   
   Or use the UltraleapTrackingWebSocket server:
   https://github.com/ultraleap/UltraleapTrackingWebSocket

2. Install dependencies:
   pip install websocket-client pynput screeninfo

Usage:
    python leap_mouse_websocket.py
"""

import json
import sys
import time
import threading
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

try:
    import websocket
except ImportError:
    print("Error: websocket-client not installed")
    print("Install with: pip install websocket-client")
    sys.exit(1)

try:
    from pynput.mouse import Button, Controller as MouseController
except ImportError:
    print("Error: pynput not installed")
    print("Install with: pip install pynput")
    sys.exit(1)

try:
    from screeninfo import get_monitors
    monitors = get_monitors()
    SCREEN_WIDTH = monitors[0].width
    SCREEN_HEIGHT = monitors[0].height
except ImportError:
    SCREEN_WIDTH = 1920
    SCREEN_HEIGHT = 1080


@dataclass
class Config:
    """Configuration settings."""
    websocket_url: str = "ws://127.0.0.1:6437/v7.json"
    sensitivity: float = 1.5
    smoothing: float = 0.3
    click_threshold: float = 0.7
    double_click_window: float = 0.4
    click_cooldown: float = 0.15
    screen_width: int = SCREEN_WIDTH
    screen_height: int = SCREEN_HEIGHT
    # Interaction box (mm from device center)
    leap_x_range: Tuple[float, float] = (-150, 150)
    leap_y_range: Tuple[float, float] = (100, 350)


class LeapWebSocketController:
    """
    Mouse controller using Leap Motion WebSocket API.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.mouse = MouseController()
        
        # State
        self.is_running = False
        self.smoothed_pos: Optional[Tuple[float, float]] = None
        self.is_pinching = False
        self.last_click_time = 0.0
        
        # WebSocket
        self.ws: Optional[websocket.WebSocketApp] = None
        
    def map_to_screen(self, x: float, y: float) -> Tuple[int, int]:
        """Map Leap coordinates to screen coordinates."""
        x_min, x_max = self.config.leap_x_range
        y_min, y_max = self.config.leap_y_range
        
        # Normalize
        norm_x = (x - x_min) / (x_max - x_min)
        norm_y = (y - y_min) / (y_max - y_min)
        
        # Clamp
        norm_x = max(0, min(1, norm_x))
        norm_y = max(0, min(1, norm_y))
        
        # Apply sensitivity
        norm_x = 0.5 + (norm_x - 0.5) * self.config.sensitivity
        norm_y = 0.5 + (norm_y - 0.5) * self.config.sensitivity
        norm_x = max(0, min(1, norm_x))
        norm_y = max(0, min(1, norm_y))
        
        # Map to screen
        screen_x = int(norm_x * self.config.screen_width)
        screen_y = int((1 - norm_y) * self.config.screen_height)
        
        return screen_x, screen_y
    
    def smooth_position(self, pos: Tuple[int, int]) -> Tuple[int, int]:
        """Apply smoothing."""
        if self.smoothed_pos is None:
            self.smoothed_pos = pos
            return pos
        
        alpha = 1 - self.config.smoothing
        smooth_x = int(alpha * pos[0] + self.config.smoothing * self.smoothed_pos[0])
        smooth_y = int(alpha * pos[1] + self.config.smoothing * self.smoothed_pos[1])
        self.smoothed_pos = (smooth_x, smooth_y)
        return self.smoothed_pos
    
    def calculate_pinch_strength(self, hand: Dict[str, Any]) -> float:
        """
        Calculate pinch strength from hand data.
        WebSocket API may not provide pinch_strength directly,
        so we calculate it from thumb and index finger distance.
        """
        # Try to get pinch strength directly
        if 'pinchStrength' in hand:
            return hand['pinchStrength']
        
        # Otherwise calculate from finger positions
        try:
            pointables = hand.get('pointables', [])
            thumb_tip = None
            index_tip = None
            
            for p in pointables:
                if p.get('type') == 0:  # Thumb
                    thumb_tip = p.get('tipPosition')
                elif p.get('type') == 1:  # Index
                    index_tip = p.get('tipPosition')
            
            if thumb_tip and index_tip:
                # Calculate distance
                dist = ((thumb_tip[0] - index_tip[0])**2 + 
                        (thumb_tip[1] - index_tip[1])**2 + 
                        (thumb_tip[2] - index_tip[2])**2) ** 0.5
                
                # Map distance to strength (closer = stronger)
                # Typical pinch distance: ~20mm when closed, ~80mm when open
                strength = max(0, min(1, 1 - (dist - 20) / 60))
                return strength
        except (KeyError, TypeError):
            pass
        
        return 0.0
    
    def handle_frame(self, data: Dict[str, Any]):
        """Process a frame of tracking data."""
        hands = data.get('hands', [])
        
        if not hands:
            return
        
        # Use first hand (prefer right)
        hand = hands[0]
        for h in hands:
            if h.get('type') == 'right':
                hand = h
                break
        
        # Get palm position
        palm_pos = hand.get('palmPosition', [0, 0, 0])
        x, y, z = palm_pos
        
        # Map to screen
        screen_pos = self.map_to_screen(x, y)
        smooth_pos = self.smooth_position(screen_pos)
        
        # Move mouse
        self.mouse.position = smooth_pos
        
        # Handle click
        pinch_strength = self.calculate_pinch_strength(hand)
        current_time = time.time()
        is_pinching_now = pinch_strength >= self.config.click_threshold
        
        if is_pinching_now and not self.is_pinching:
            time_since_last = current_time - self.last_click_time
            
            if time_since_last >= self.config.click_cooldown:
                if time_since_last <= self.config.double_click_window:
                    self.mouse.click(Button.left, 2)
                    print("  [Double Click]")
                else:
                    self.mouse.click(Button.left, 1)
                    print("  [Click]")
                
                self.last_click_time = current_time
        
        self.is_pinching = is_pinching_now
    
    def on_message(self, ws, message):
        """WebSocket message handler."""
        try:
            data = json.loads(message)
            
            # Handle version message
            if 'serviceVersion' in data:
                print(f"[Connected to Leap Service v{data['serviceVersion']}]")
                return
            
            # Handle tracking frame
            if 'hands' in data:
                self.handle_frame(data)
                
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"Error processing frame: {e}")
    
    def on_error(self, ws, error):
        """WebSocket error handler."""
        print(f"WebSocket error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        """WebSocket close handler."""
        print("[Disconnected from Leap Service]")
        self.is_running = False
    
    def on_open(self, ws):
        """WebSocket open handler."""
        print("[WebSocket connected]")
        
        # Request tracking data
        # The exact format depends on the WebSocket server version
        ws.send(json.dumps({
            "enableGestures": True,
            "background": True
        }))
    
    def run(self):
        """Main run loop."""
        print("\n" + "=" * 50)
        print("Leap Motion Mouse Controller (WebSocket)")
        print("=" * 50)
        print(f"\nConnecting to: {self.config.websocket_url}")
        print(f"Screen: {self.config.screen_width}x{self.config.screen_height}")
        print("\nControls:")
        print("  - Move hand to move cursor")
        print("  - Pinch to click")
        print("  - Press Ctrl+C to exit")
        print("\n" + "=" * 50 + "\n")
        
        self.is_running = True
        
        # WebSocket connection
        websocket.enableTrace(False)
        
        self.ws = websocket.WebSocketApp(
            self.config.websocket_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        try:
            self.ws.run_forever()
        except KeyboardInterrupt:
            print("\n[Shutting down...]")
        finally:
            self.is_running = False
            print("[Goodbye!]")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Leap Motion mouse control via WebSocket"
    )
    parser.add_argument("--url", default="ws://127.0.0.1:6437/v7.json",
                        help="WebSocket server URL")
    parser.add_argument("--sensitivity", "-s", type=float, default=1.5)
    parser.add_argument("--smoothing", "-m", type=float, default=0.3)
    parser.add_argument("--click-threshold", "-c", type=float, default=0.7)
    
    args = parser.parse_args()
    
    config = Config(
        websocket_url=args.url,
        sensitivity=args.sensitivity,
        smoothing=args.smoothing,
        click_threshold=args.click_threshold
    )
    
    controller = LeapWebSocketController(config)
    controller.run()


if __name__ == "__main__":
    main()

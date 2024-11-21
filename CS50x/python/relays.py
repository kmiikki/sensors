#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Aug 16 13:02:36 2024

@author: Kim Miikki

BME280 modes
------------
NC, LED off, GPIO.HIGH (Default without current)
NO, LED on,  GPIO.LOW

Normal oparation:
    - All relays in NC mode
    - All LEDS off
    - All GPIOs HIGH
    
Raspberry Pi 5:
sudo apt remove python3-rpi.gpio
pip3 install rpi-lgpio
"""
import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

class Relay:
    """Relay object class"""
    _global_pins = []

    
    def __init__(self, relay_pins: list[int], nc_high = True):
        # BME280 nc_high = True
        if isinstance(relay_pins, list):
            for pin in relay_pins:
                if pin in self._global_pins:
                    raise ValueError(f"Pin {pin} already in the relay list. Unable to create a new relay object.")
        
        # Set relay mode
        self._nc_high = nc_high
        
        # Add pins to global list of pins
        for pin in relay_pins:
            self._global_pins.append(pin)
                
        self._pins = relay_pins
        
        GPIO.setup(self._pins, GPIO.OUT)
        # NC mode: HIGH (Waveshare BME280 RPi Relay Board)
        GPIO.output(self._pins, self._nc_high and 1)


    # Destructor
    def __del__(self):
        GPIO.cleanup(self._pins)
        for pin in self._pins:
            self._global_pins.remove(pin)


    @property
    def pins_count(self) -> int:
        return len(self._pins)


    @property
    def pins(self) -> list[int]:
        return self._pins


    def ch_state(self, relay_ch) -> int:
        if (relay_ch > 0) and (relay_ch < len(self._pins) + 1):
            return GPIO.input(self._pins[relay_ch - 1])
        else:
            return -1 # Channel out of range


    @property
    def ch_states(self) -> list[int]:
        return [self.ch_state(num + 1) for num in range(len(self._pins))]

    
    def all_toggle(self):
        pins = self._pins
        if isinstance(pins, int):
            pins = [pins]
        for pin in pins:
            state = GPIO.input(pin)
            state = not state
            GPIO.output(pin, state)


    def all_low(self):
        GPIO.output(self._pins, GPIO.LOW)


    def all_high(self):
        GPIO.output(self._pins, GPIO.HIGH)

    
    # All relays: NC path
    def all_close(self):
        GPIO.output(self._pins, GPIO.LOW ^ self._nc_high)

    
    # All relays: NO path
    def all_open(self):
        GPIO.output(self._pins, GPIO.HIGH ^ self._nc_high)


    def ch_toggle(self, relay_ch: int):
        if (relay_ch > 0) and (relay_ch < len(self._pins) + 1):
            state = not self.ch_state(relay_ch)
            GPIO.output(self._pins[relay_ch - 1], state)

    
    def ch_high(self, relay_ch: int):
        if (relay_ch > 0) and (relay_ch < len(self._pins) + 1):
            GPIO.output(self._pins[relay_ch - 1], GPIO.HIGH)


    def ch_low(self, relay_ch: int):
        if (relay_ch > 0) and (relay_ch < len(self._pins) + 1):
            GPIO.output(self._pins[relay_ch - 1], GPIO.LOW)

            
    def ch_open(self, relay_ch: int):
        if self._nc_high:
            self.ch_low(relay_ch)
        else:
            self.ch_high(relay_ch)


    def ch_close(self, relay_ch: int):
        if not self._nc_high:
            self.ch_low(relay_ch)
        else:
            self.ch_high(relay_ch)

        
if __name__ == "__main__":
    ...


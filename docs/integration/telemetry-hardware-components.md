# QBox Hardware Components

Stable component keys:

```text
camera.csi
camera.usb
led.red
led.green
locker.solenoid
buzzer
```

Component status values:

```text
UNKNOWN
INITIALIZING
AVAILABLE
HEALTHY
DEGRADED
FAULT
DISCONNECTED
DISABLED
```

GPIO numbers are metadata, not component identity. LEDs, buzzer, and solenoid do
not claim physical state unless hardware readback exists. The solenoid uses
safe checks only during diagnostics and is not actuated by telemetry.
